"""Exam builder for teachers/admins.

Builds a DRAFT exam from a blueprint (knowledge domain, Bloom mix, question
formats, difficulty anchor) using the question bank first and LLM generation
for what the bank cannot supply. Every generated item passes through the
quality-control pipeline (self-validation + optional Gemini cross-check) and
ships with a per-item validation report so the teacher can keep / discard /
regenerate before the exam is saved as a preset.

Generated items are persisted with is_archived=True (quarantined); saving the
exam un-archives the kept ones.
"""
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial

import anyio
from anyio import to_thread
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.llm_client import (
    generate_question_with_llm,
    validate_generated_mcq_with_llm,
    cross_validate_with_gemini,
)
from app.models.question import Question, PresetExam, PresetExamQuestion
from app.models.knowledge import Topic, MajorTopic
from app.models.cat_knowledge import UserAbility
from app.services.adaptive_shared import (
    normalize_question_type,
    build_topic_context,
    question_signature_from_model,
    normalize_text,
)
from app.services.question_format import (
    SUPPORTED_FORMATS,
    normalize_format_fields,
    parse_matching_pairs,
)

MAX_LLM_ITEMS_PER_BUILD = 10
# Số câu sinh song song (mỗi câu là 1-3 lệnh gọi HTTP chặn, chạy trong thread).
LLM_CONCURRENCY = 4
# Trần thời gian cho pha sinh LLM: quá hạn thì trả đề nháp một phần kèm cảnh
# báo, thay vì để request treo cho tới khi proxy ngắt kết nối.
# Tệ nhất = BUDGET + CALL_TIMEOUT_CAP (~140s), phải nhỏ hơn experimental
# .proxyTimeout của Next (180s, xem frontend/next.config.js) để backend luôn là
# bên trả lời thay vì proxy ngắt kết nối.
LLM_PHASE_BUDGET_SECONDS = 100.0
# Trần timeout mỗi lệnh gọi LLM khi dựng đề (cấu hình admin cho phép tới 300s —
# quá dài cho một request đồng bộ).
LLM_CALL_TIMEOUT_CAP_SECONDS = 40

BLOOM_BY_B = [(-0.5, "Nhận biết"), (0.7, "Thông hiểu"), (99.0, "Vận dụng")]


def _bloom_for_b(b: float) -> str:
    for threshold, label in BLOOM_BY_B:
        if b < threshold:
            return label
    return "Vận dụng"


async def _learner_anchor_b(db: AsyncSession, subject_id: int) -> float | None:
    """Anchor difficulty at the average ability of learners of this subject."""
    row = await db.execute(
        select(func.avg(UserAbility.theta_estimate)).where(
            UserAbility.subject_id == subject_id,
            UserAbility.answered_count > 0,
        )
    )
    avg = row.scalar()
    return round(float(avg), 2) if avg is not None else None


def _question_admin_view(q: Question, source: str, validation: dict | None) -> dict:
    fmt = (q.question_format or "mcq").lower()
    pairs = parse_matching_pairs(q.matching_pairs) if fmt == "matching" else []
    return {
        "id": q.id,
        "external_id": q.external_id,
        "stem": q.stem,
        "question_format": fmt,
        "question_type": q.question_type,
        "topic_id": q.topic_id,
        "topic_name": q.topic.name if q.topic else "",
        "option_a": q.option_a,
        "option_b": q.option_b,
        "option_c": q.option_c,
        "option_d": q.option_d,
        "correct_answer": q.correct_answer,
        "answer_text": q.answer_text,
        "matching_pairs": pairs,
        "difficulty_b": float(q.difficulty_b),
        "discrimination_a": float(q.discrimination_a),
        "source": source,
        "validation": validation,
    }


async def _persist_generated(
    db: AsyncSession,
    *,
    topic_id: int,
    payload: dict,
    fmt: str,
    bloom: str,
) -> Question:
    ts = int(datetime.now(timezone.utc).timestamp())
    base = f"BQ{topic_id}{ts}"[-16:]
    external_id = base
    for suffix in range(100):
        candidate = f"{base}{suffix:02d}"[:20]
        exists = await db.execute(select(Question).where(Question.external_id == candidate))
        if not exists.scalar_one_or_none():
            external_id = candidate
            break

    b = max(-3.0, min(3.0, float(payload.get("difficulty_b", 0.0) or 0.0)))
    a = max(0.5, min(2.5, float(payload.get("discrimination_a", 1.2) or 1.2)))

    fields = normalize_format_fields(fmt, payload)

    stem = str(payload.get("stem", "")).strip()
    if not stem:
        raise ValueError("Thiếu stem")

    question = Question(
        external_id=external_id,
        topic_id=topic_id,
        stem=stem,
        question_type=bloom,
        difficulty_b=round(b, 2),
        discrimination_a=round(a, 2),
        time_limit_seconds=90 if bloom == "Vận dụng" else 60,
        time_display="01:30" if bloom == "Vận dụng" else "01:00",
        is_archived=True,  # quarantined until the teacher approves
        **fields,
    )
    db.add(question)
    await db.flush()

    loaded = await db.execute(
        select(Question)
        .where(Question.id == question.id)
        .options(*_topic_load_options())
    )
    return loaded.scalar_one()


def _topic_load_options():
    from sqlalchemy.orm import selectinload

    return [selectinload(Question.topic).selectinload(Topic.major_topic)]


def _generate_and_validate_blocking(
    *,
    topic_name: str,
    context: str,
    fmt: str,
    bloom: str,
    target_b: float | None,
    runtime_settings: dict,
    deadline: float | None = None,
) -> tuple[dict, dict]:
    """Sinh câu + kiểm soát chất lượng. Toàn bộ lệnh gọi LLM ở đây đều CHẶN
    (urllib), nên hàm này phải chạy trong worker thread — không gọi thẳng từ
    coroutine, nếu không event loop bị khoá suốt vài phút.

    ``deadline`` (time.monotonic) là mốc dừng mềm: quá hạn thì bỏ qua các bước
    thẩm định phụ và trả về câu vừa sinh.
    """
    payload = generate_question_with_llm(
        topic_name=topic_name,
        knowledge_context=context,
        target_level=bloom,
        question_format=fmt,
        target_b=target_b,
        runtime_settings=runtime_settings,
    )

    validation: dict = {"self_check": None, "gemini": None}
    out_of_time = deadline is not None and time.monotonic() >= deadline

    if fmt == "mcq" and not out_of_time:
        try:
            self_check = validate_generated_mcq_with_llm(
                payload, target_b=float(target_b or 0.0), runtime_settings=runtime_settings
            )
            validation["self_check"] = {
                "is_valid": self_check["is_valid"],
                "solved_answer": self_check["solved_answer"],
                "estimated_b": self_check["estimated_b"],
                "confidence": self_check["confidence"],
                "agrees": self_check["solved_answer"] == str(payload.get("correct_answer", "")).upper()[:1],
            }
        except Exception as exc:  # noqa: BLE001 — report, don't fail the draft
            validation["self_check"] = {"error": str(exc)[:200]}
    elif fmt == "mcq":
        validation["self_check"] = {"error": "Bỏ qua tự thẩm định: hết thời gian dựng đề"}

    payload["question_format"] = fmt
    if deadline is not None and time.monotonic() >= deadline:
        validation["gemini"] = {
            "enabled": False,
            "agree": None,
            "gemini_answer": None,
            "notes": "Bỏ qua Gemini: hết thời gian dựng đề",
        }
    else:
        validation["gemini"] = cross_validate_with_gemini(payload, runtime_settings=runtime_settings)

    return payload, validation


async def generate_one_item(
    db: AsyncSession,
    *,
    subject_id: int,
    topic_id: int,
    fmt: str,
    bloom: str,
    target_b: float | None,
    runtime_settings: dict,
) -> dict:
    """Generate + validate + persist (quarantined) one item; returns admin view."""
    if not runtime_settings.get("llm_enabled"):
        raise ValueError("LLM đang tắt — bật trong trang Cấu hình để sinh câu hỏi")

    topic = await db.get(Topic, topic_id)
    if not topic:
        raise ValueError("Topic không tồn tại")

    context = await build_topic_context(db, topic_id)
    payload, validation = await to_thread.run_sync(
        partial(
            _generate_and_validate_blocking,
            topic_name=topic.name,
            context=context,
            fmt=fmt,
            bloom=bloom,
            target_b=target_b,
            runtime_settings=runtime_settings,
        )
    )

    question = await _persist_generated(db, topic_id=topic_id, payload=payload, fmt=fmt, bloom=bloom)
    return _question_admin_view(question, source="llm", validation=validation)


@dataclass(frozen=True)
class _LlmGap:
    """Một câu ngân hàng không đáp ứng được, cần LLM sinh bù."""
    topic_id: int
    fmt: str
    bloom: str


async def _generate_gaps(
    db: AsyncSession,
    *,
    gaps: list[_LlmGap],
    target_b: float | None,
    runtime_settings: dict,
) -> tuple[list[dict], list[str]]:
    """Sinh các câu còn thiếu song song trong thread pool, rồi ghi DB tuần tự.

    Lệnh gọi LLM chạy ngoài event loop và cả pha bị chặn bởi
    ``LLM_PHASE_BUDGET_SECONDS``, nên request luôn trả về (có thể là đề nháp
    một phần) thay vì treo tới lúc proxy ngắt kết nối.
    """
    topic_names: dict[int, str] = {}
    contexts: dict[int, str] = {}
    for topic_id in {g.topic_id for g in gaps}:
        topic = await db.get(Topic, topic_id)
        if not topic:
            continue
        topic_names[topic_id] = topic.name
        contexts[topic_id] = await build_topic_context(db, topic_id)

    call_settings = {
        **runtime_settings,
        "llm_timeout_seconds": min(
            int(runtime_settings.get("llm_timeout_seconds") or 30),
            LLM_CALL_TIMEOUT_CAP_SECONDS,
        ),
    }

    deadline = time.monotonic() + LLM_PHASE_BUDGET_SECONDS
    limiter = anyio.CapacityLimiter(LLM_CONCURRENCY)
    results: list[tuple[_LlmGap, tuple[dict, dict] | None, str | None]] = [
        (gap, None, None) for gap in gaps
    ]

    async def run_one(index: int, gap: _LlmGap) -> None:
        async with limiter:
            if gap.topic_id not in topic_names:
                results[index] = (gap, None, "topic không tồn tại")
                return
            if time.monotonic() >= deadline:
                results[index] = (gap, None, "hết thời gian dựng đề")
                return
            try:
                payload, validation = await to_thread.run_sync(
                    partial(
                        _generate_and_validate_blocking,
                        topic_name=topic_names[gap.topic_id],
                        context=contexts.get(gap.topic_id, ""),
                        fmt=gap.fmt,
                        bloom=gap.bloom,
                        target_b=target_b,
                        runtime_settings=call_settings,
                        deadline=deadline,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — một câu hỏng không làm hỏng cả đề
                results[index] = (gap, None, str(exc)[:150])
                return
            results[index] = (gap, (payload, validation), None)

    async with anyio.create_task_group() as tg:
        for index, gap in enumerate(gaps):
            tg.start_soon(run_one, index, gap)

    items: list[dict] = []
    warnings: list[str] = []
    for gap, outcome, error in results:
        if outcome is None:
            warnings.append(f"Sinh câu {gap.fmt}/{gap.bloom} thất bại: {error}")
            continue
        payload, validation = outcome
        try:
            question = await _persist_generated(
                db, topic_id=gap.topic_id, payload=payload, fmt=gap.fmt, bloom=gap.bloom
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Lưu câu {gap.fmt}/{gap.bloom} thất bại: {str(exc)[:150]}")
            continue
        items.append(_question_admin_view(question, source="llm", validation=validation))

    return items, warnings


async def build_draft(
    db: AsyncSession,
    *,
    subject_id: int,
    topic_ids: list[int] | None,
    format_counts: dict[str, int],
    bloom_pcts: dict[str, float],
    anchor_mode: str,          # "manual" | "learners"
    target_b: float | None,
    use_llm: bool,
    runtime_settings: dict,
) -> dict:
    """Build a draft exam: bank items first, LLM fills the gaps."""
    total = sum(max(0, int(n)) for n in format_counts.values())
    if total <= 0:
        raise ValueError("Tổng số câu phải > 0")

    if anchor_mode == "learners":
        target_b = await _learner_anchor_b(db, subject_id)

    # ---- Bank pool ----
    query = (
        select(Question)
        .join(Topic, Topic.id == Question.topic_id)
        .join(MajorTopic, MajorTopic.id == Topic.major_topic_id)
        .where(MajorTopic.subject_id == subject_id)
        .where(Question.is_archived.is_(False))
        .options(*_topic_load_options())
    )
    if topic_ids:
        query = query.where(Question.topic_id.in_(topic_ids))
    bank = list((await db.execute(query)).scalars().unique().all())

    rng = random.Random()
    items: list[dict] = []
    warnings: list[str] = []
    llm_budget = MAX_LLM_ITEMS_PER_BUILD

    # Ordered topic list for LLM topic rotation
    topics_rows = await db.execute(
        select(Topic.id)
        .join(MajorTopic, MajorTopic.id == Topic.major_topic_id)
        .where(MajorTopic.subject_id == subject_id)
        .order_by(MajorTopic.order_index.asc(), Topic.order_index.asc())
    )
    llm_topics = [r.id for r in topics_rows if not topic_ids or r.id in set(topic_ids)]

    bloom_labels = [("Nhận biết", bloom_pcts.get("recognition", 0.3)),
                    ("Thông hiểu", bloom_pcts.get("comprehension", 0.5)),
                    ("Vận dụng", bloom_pcts.get("application", 0.2))]

    used_ids: set[int] = set()
    topic_cursor = 0
    gaps: list[_LlmGap] = []

    for fmt in SUPPORTED_FORMATS:
        need = max(0, int(format_counts.get(fmt, 0)))
        if need == 0:
            continue

        # Bloom split within this format
        quota = {label: round(need * pct) for label, pct in bloom_labels}
        # Fix rounding drift
        drift = need - sum(quota.values())
        quota["Thông hiểu"] = quota.get("Thông hiểu", 0) + drift

        for bloom, q_need in quota.items():
            for _ in range(max(0, q_need)):
                # 1) Try the bank
                candidates = [
                    q for q in bank
                    if q.id not in used_ids
                    and (q.question_format or "mcq") == fmt
                    and normalize_question_type(q.question_type) == normalize_question_type(bloom)
                ]
                if not candidates:
                    candidates = [
                        q for q in bank
                        if q.id not in used_ids and (q.question_format or "mcq") == fmt
                    ]
                pick = None
                if candidates:
                    if target_b is not None:
                        pick = min(candidates, key=lambda q: abs(float(q.difficulty_b) - target_b))
                    else:
                        pick = rng.choice(candidates)

                if pick is not None:
                    used_ids.add(pick.id)
                    items.append(_question_admin_view(pick, source="bank", validation=None))
                    continue

                # 2) LLM fills the gap — gom lại, sinh song song ở pha sau
                if not use_llm or not runtime_settings.get("llm_enabled"):
                    warnings.append(f"Thiếu câu {fmt}/{bloom} — ngân hàng không đủ và LLM tắt")
                    continue
                if llm_budget <= 0:
                    warnings.append(
                        f"Đã chạm trần {MAX_LLM_ITEMS_PER_BUILD} câu sinh LLM mỗi lần dựng đề"
                    )
                    continue
                if not llm_topics:
                    warnings.append("Không có topic để sinh câu LLM")
                    continue

                topic_id = llm_topics[topic_cursor % len(llm_topics)]
                topic_cursor += 1
                llm_budget -= 1
                gaps.append(_LlmGap(topic_id=topic_id, fmt=fmt, bloom=bloom))

    if gaps:
        generated, llm_warnings = await _generate_gaps(
            db, gaps=gaps, target_b=target_b, runtime_settings=runtime_settings
        )
        items.extend(generated)
        warnings.extend(llm_warnings)

    rng.shuffle(items)
    return {
        "subject_id": subject_id,
        "requested": total,
        "built": len(items),
        "anchor_b": target_b,
        "items": items,
        "warnings": warnings,
        "sources": {
            "bank": sum(1 for i in items if i["source"] == "bank"),
            "llm": sum(1 for i in items if i["source"] == "llm"),
        },
    }


async def save_preset(
    db: AsyncSession,
    *,
    subject_id: int,
    name: str,
    description: str | None,
    question_ids: list[int],
    discarded_generated_ids: list[int],
) -> dict:
    """Approve the draft: un-archive kept generated items, save as preset."""
    if not question_ids:
        raise ValueError("Đề phải có ít nhất 1 câu")

    kept = (
        await db.execute(select(Question).where(Question.id.in_(question_ids)))
    ).scalars().all()
    kept_map = {q.id: q for q in kept}
    missing = [qid for qid in question_ids if qid not in kept_map]
    if missing:
        raise ValueError(f"Không tìm thấy câu hỏi: {missing}")

    for q in kept:
        if q.is_archived:
            q.is_archived = False  # approved into the bank

    preset = PresetExam(
        subject_id=subject_id,
        name=name.strip()[:100],
        description=(description or "").strip() or None,
        question_count=len(question_ids),
    )
    db.add(preset)
    await db.flush()
    for pos, qid in enumerate(question_ids):
        db.add(PresetExamQuestion(preset_id=preset.id, question_id=qid, position=pos))

    # Discarded generated items stay archived (they were quarantined already);
    # nothing to do beyond ignoring them.
    _ = discarded_generated_ids

    await db.commit()
    return {"preset_id": preset.id, "name": preset.name, "question_count": preset.question_count}
