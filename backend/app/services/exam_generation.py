"""Exam-batch generation engine for multi-stage adaptive testing.

Applies the R1-R12 inference rules at exam level: instead of picking one
question after every answer, the whole previous exam is evaluated and the
rules shape the blueprint (difficulty target, topic coverage, exclusions,
LLM fill) of the next exam.
"""
from itertools import cycle
import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.question import Question
from app.models.knowledge import Topic, MajorTopic, TopicPrerequisite
from app.models.user import ExamChain
from app.engine.question_selector import (
    prioritize_high_discrimination,
    select_best_by_fisher,
)
from app.engine.rules import topic_error_rates
from app.services.adaptive_shared import (
    append_rule,
    count_consecutive_correct_on_topic,
    count_consecutive_fail_on_topic,
    normalize_question_type,
    pick_min_b_gap,
    pick_r12_computation_target_topic,
    question_signature_from_model,
    recent_answered_question_ids,
    generate_and_persist_cat_question,
)

# Difficulty offsets rotated around b_target so one exam spreads items
# across a band instead of stacking N near-identical difficulties.
B_SPREAD = [0.0, 0.3, -0.3, 0.6, -0.6]

# Cap LLM generations per exam: each call is slow (generation + validation).
MAX_LLM_FILL_PER_EXAM = 3


async def _load_candidate_pool(db: AsyncSession, subject_id: int) -> list[dict]:
    rows = await db.execute(
        select(
            Question.id,
            Question.topic_id,
            Question.question_type,
            Question.discrimination_a,
            Question.difficulty_b,
            Question.guessing_c,
            Topic.name.label("topic_name"),
            MajorTopic.name.label("major_topic_name"),
        )
        .select_from(Question)
        .join(Topic, Topic.id == Question.topic_id)
        .join(MajorTopic, MajorTopic.id == Topic.major_topic_id)
        .where(MajorTopic.subject_id == subject_id)
        .where(Question.is_archived.is_(False))
    )
    return [
        {
            "id": row.id,
            "topic_id": row.topic_id,
            "question_type": row.question_type,
            "discrimination_a": float(row.discrimination_a),
            "difficulty_b": float(row.difficulty_b),
            "guessing_c": float(row.guessing_c),
            "topic_name": row.topic_name,
            "major_topic_name": row.major_topic_name,
        }
        for row in rows
    ]


async def _ordered_topic_ids(db: AsyncSession, subject_id: int) -> list[int]:
    rows = await db.execute(
        select(Topic.id)
        .join(MajorTopic, MajorTopic.id == Topic.major_topic_id)
        .where(MajorTopic.subject_id == subject_id)
        .order_by(MajorTopic.order_index.asc(), Topic.order_index.asc(), Topic.id.asc())
    )
    return [row.id for row in rows]


def _bloom_quotas(n: int, chain: ExamChain) -> dict[str, int]:
    n_rec = round(n * float(chain.recognition_pct or 0.3))
    n_com = round(n * float(chain.comprehension_pct or 0.5))
    n_app = max(n - n_rec - n_com, 0)
    return {"nhan_biet": n_rec, "thong_hieu": n_com, "van_dung": n_app}


def _fill_slots_round_robin(
    pool: list[dict],
    topic_order: list[int],
    n: int,
    pick_fn,
    bloom_quotas: dict[str, int] | None = None,
) -> list[dict]:
    """Fill up to *n* slots rotating over topics; pick_fn(candidates, slot_idx) -> dict|None.

    When bloom_quotas is given, each pick first tries candidates of a Bloom type
    still under quota, falling back to any type so slots never stay empty.
    """
    remaining = {q["id"]: q for q in pool}
    by_topic: dict[int, list[dict]] = {}
    for q in pool:
        by_topic.setdefault(q["topic_id"], []).append(q)

    topics = [t for t in topic_order if t in by_topic]
    # Topics unknown to the ontology ordering (defensive) go last.
    topics += [t for t in by_topic if t not in topics]
    if not topics:
        return []

    bloom_used: dict[str, int] = {"nhan_biet": 0, "thong_hieu": 0, "van_dung": 0}
    selected: list[dict] = []
    topic_cycle = cycle(topics)
    misses = 0
    slot_idx = 0

    while len(selected) < n and misses < len(topics):
        topic_id = next(topic_cycle)
        candidates = [q for q in by_topic.get(topic_id, []) if q["id"] in remaining]
        if not candidates:
            misses += 1
            continue

        pick = None
        if bloom_quotas:
            under_quota = [
                q for q in candidates
                if bloom_used.get(normalize_question_type(q.get("question_type")), 0)
                < bloom_quotas.get(normalize_question_type(q.get("question_type")), 0)
            ]
            if under_quota:
                pick = pick_fn(under_quota, slot_idx)
        if pick is None:
            pick = pick_fn(candidates, slot_idx)
        if pick is None:
            misses += 1
            continue

        misses = 0
        slot_idx += 1
        selected.append(pick)
        del remaining[pick["id"]]
        bloom_used[normalize_question_type(pick.get("question_type"))] = (
            bloom_used.get(normalize_question_type(pick.get("question_type")), 0) + 1
        )

    return selected


async def generate_exam(
    db: AsyncSession,
    *,
    chain: ExamChain,
    user_id: int,
    exam_index: int,
    theta: float,
    sem: float,
    chain_scoring_data: list[dict],
    prev_exam_scoring_data: list[dict],
    used_question_ids: set[int],
    used_signatures: set[str],
    llm_runtime_settings: dict,
    b_target_override: float | None = None,
) -> tuple[list[Question], list[dict]]:
    """Build the next exam of the chain. Returns (questions, rule_events).

    b_target_override bypasses the R2/R3 difficulty steering (used by the RL
    strategy and by simulation studies); every other rule still applies.

    An empty question list means the bank (and LLM fallback) is exhausted;
    the caller should complete the chain with "Hết câu hỏi phù hợp".
    """
    settings = get_settings()
    n = max(1, int(chain.questions_per_exam or 20))
    applied_rules: list[str] = []
    rule_events: list[dict] = []

    pool = await _load_candidate_pool(db, chain.subject_id)
    topic_order = await _ordered_topic_ids(db, chain.subject_id)

    # ---------------------------------------------------------------
    # R8: Ràng buộc lặp – no question repeats within the chain, and
    # avoid cross-session recent questions when a fresh pool remains.
    # ---------------------------------------------------------------
    pool = [q for q in pool if q["id"] not in used_question_ids]
    recent_ids = await recent_answered_question_ids(
        db=db,
        user_id=user_id,
        subject_id=chain.subject_id,
        window_size=int(settings.CAT_RECENT_QUESTION_WINDOW),
    )
    cross_session_ids = recent_ids - used_question_ids
    fresh_pool = [q for q in pool if q["id"] not in cross_session_ids]
    if cross_session_ids and fresh_pool:
        pool = fresh_pool
        append_rule(
            applied_rules,
            rule_events,
            "R8",
            f"Excluded {len(cross_session_ids)} recently answered question(s) from previous sessions",
        )

    selected: list[dict] = []
    b_target = 0.0

    if exam_index <= 1:
        # ---------------------------------------------------------------
        # R1: Khởi tạo – exam #1 blueprint: safe difficulty band relative
        # to the starting theta (0 for cold start, warm-start prior when
        # the learner is already known), high discrimination a > 1.2,
        # Bloom distribution and topic coverage; Fisher picks per slot.
        # ---------------------------------------------------------------
        theta0 = float(theta) if sem < 999 or theta else 0.0
        lo, hi = theta0 - 1.5, theta0 - 0.5
        band = [q for q in pool if lo <= q["difficulty_b"] <= hi and q["discrimination_a"] > 1.2]
        if len(band) < n:
            band = [q for q in pool if lo <= q["difficulty_b"] <= hi]
        if len(band) < n:
            band = pool
        if band:
            append_rule(
                applied_rules,
                rule_events,
                "R1",
                (
                    f"Đề #1: khởi tạo với b ∈ [{lo:.1f}, {hi:.1f}] quanh θ₀={theta0:.2f}, "
                    "ưu tiên a > 1.2, phủ topic, chọn theo Fisher"
                ),
            )
        selected = _fill_slots_round_robin(
            band,
            topic_order,
            n,
            pick_fn=lambda cands, _i: select_best_by_fisher(cands, current_theta=theta0),
            bloom_quotas=_bloom_quotas(n, chain),
        )
    else:
        prev_total = len(prev_exam_scoring_data)
        prev_correct = sum(1 for r in prev_exam_scoring_data if r.get("is_correct"))
        acc = (prev_correct / prev_total) if prev_total else 0.0

        # ---------------------------------------------------------------
        # R2/R3: exam-level difficulty steering from previous exam accuracy.
        # An explicit override (RL strategy / simulation) replaces R2/R3.
        # ---------------------------------------------------------------
        if b_target_override is not None:
            b_target = max(-3.0, min(3.0, float(b_target_override)))
        elif acc >= 0.6:
            b_target = float(theta) + 0.5
            append_rule(
                applied_rules,
                rule_events,
                "R2",
                f"Độ chính xác đề trước {acc:.0%} >= 60% => b_target = θ + 0.5 = {b_target:.2f}",
            )
        elif acc < 0.4:
            b_target = float(theta) - 0.7
            append_rule(
                applied_rules,
                rule_events,
                "R3",
                f"Độ chính xác đề trước {acc:.0%} < 40% => b_target = θ - 0.7 = {b_target:.2f}",
            )
        else:
            b_target = float(theta)
        b_target = max(-3.0, min(3.0, b_target))

        prev_topic_ids = {r["topic_id"] for r in prev_exam_scoring_data if r.get("topic_id") is not None}
        mastered_topics = {
            t for t in prev_topic_ids
            if count_consecutive_correct_on_topic(prev_exam_scoring_data, t) >= 3
        }
        failed_topics = {
            t for t in prev_topic_ids
            if count_consecutive_fail_on_topic(prev_exam_scoring_data, t) >= 2
        }

        # ---------------------------------------------------------------
        # R12: Computation-network inference on cumulative chain evidence.
        # ---------------------------------------------------------------
        r12_topic_id, r12_prereqs = await pick_r12_computation_target_topic(
            db,
            user_id=user_id,
            subject_id=chain.subject_id,
            candidate_topic_ids={q["topic_id"] for q in pool},
            session_scoring_data=chain_scoring_data,
        )
        if r12_topic_id is not None and r12_topic_id in failed_topics:
            r12_topic_id = None
        if r12_topic_id is not None:
            b_target = max(-3.0, min(3.0, b_target + 0.2))
            append_rule(
                applied_rules,
                rule_events,
                "R12",
                (
                    f"Đã mastery các tiên quyết {r12_prereqs} => suy diễn năng lực cho "
                    f"topic_id={r12_topic_id}; dành slot ưu tiên và nâng b_target thêm 0.2"
                ),
            )

        # ---------------------------------------------------------------
        # R11: Prerequisite fallback – reserve easy items (b ≈ -1.0) from
        # prerequisite topics of repeatedly-failed topics.
        # ---------------------------------------------------------------
        reserved: list[dict] = []
        remaining_pool = list(pool)
        for failed_topic_id in sorted(failed_topics)[:2]:
            prereq_result = await db.execute(
                select(TopicPrerequisite).where(TopicPrerequisite.topic_id == failed_topic_id)
            )
            prereq_ids = {p.prerequisite_topic_id for p in prereq_result.scalars().all()}
            if not prereq_ids:
                continue
            prereq_pool = [q for q in remaining_pool if q["topic_id"] in prereq_ids]
            picked_any = False
            for _ in range(2):
                pick = pick_min_b_gap(prereq_pool, target_b=-1.0)
                if not pick or len(reserved) >= n:
                    break
                picked_any = True
                reserved.append(pick)
                remaining_pool = [q for q in remaining_pool if q["id"] != pick["id"]]
                prereq_pool = [q for q in prereq_pool if q["id"] != pick["id"]]
            if picked_any:
                append_rule(
                    applied_rules,
                    rule_events,
                    "R11",
                    (
                        f"Sai liên tiếp >= 2 ở topic_id={failed_topic_id} => củng cố "
                        f"kiến thức tiên quyết với câu dễ (b ≈ -1.0)"
                    ),
                )

        # R12 slot reservation: prefer non-recognition items of the target topic.
        if r12_topic_id is not None:
            r12_quota = max(2, round(0.3 * n))
            r12_pool = [q for q in remaining_pool if q["topic_id"] == r12_topic_id]
            r12_advanced = [
                q for q in r12_pool
                if normalize_question_type(q.get("question_type")) != "nhan_biet"
            ]
            source = r12_advanced or r12_pool
            while source and r12_quota > 0 and len(reserved) < n:
                pick = pick_min_b_gap(source, target_b=b_target)
                if not pick:
                    break
                reserved.append(pick)
                r12_quota -= 1
                remaining_pool = [q for q in remaining_pool if q["id"] != pick["id"]]
                source = [q for q in source if q["id"] != pick["id"]]

        # ---------------------------------------------------------------
        # R5: Topic coverage rotation – mastered topics leave the rotation.
        # ---------------------------------------------------------------
        eligible_topics = [t for t in topic_order if t not in mastered_topics]
        if mastered_topics and eligible_topics:
            append_rule(
                applied_rules,
                rule_events,
                "R5",
                (
                    f"Đúng liên tiếp >= 3 ở topic {sorted(mastered_topics)} => xoay vòng "
                    "sang các topic khác để đảm bảo độ phủ"
                ),
            )
        if not eligible_topics:
            eligible_topics = list(topic_order)

        # ---------------------------------------------------------------
        # R6: High-ability filter – drop recognition-level items.
        # ---------------------------------------------------------------
        if float(theta) > 1.0 and float(sem) < 1.0:
            above_basic = [
                q for q in remaining_pool
                if normalize_question_type(q.get("question_type")) != "nhan_biet"
            ]
            if above_basic:
                remaining_pool = above_basic
                append_rule(
                    applied_rules,
                    rule_events,
                    "R6",
                    f"θ = {float(theta):.2f} > 1.0 và SEM = {float(sem):.3f} < 1.0 => loại câu Nhận biết",
                )

        # ---------------------------------------------------------------
        # R4: Early-phase high-a shortlist for faster theta convergence.
        # ---------------------------------------------------------------
        if exam_index <= 2:
            shortlist = prioritize_high_discrimination(remaining_pool, top_n=max(3 * n, 30))
            if shortlist:
                remaining_pool = shortlist
                append_rule(
                    applied_rules,
                    rule_events,
                    "R4",
                    "Giai đoạn đầu (đề <= 2): ưu tiên shortlist câu có độ phân biệt a cao",
                )

        selected = list(reserved[:n])
        if len(selected) < n:
            spread = B_SPREAD
            filled = _fill_slots_round_robin(
                remaining_pool,
                eligible_topics,
                n - len(selected),
                pick_fn=lambda cands, i: pick_min_b_gap(
                    cands, target_b=b_target + spread[i % len(spread)]
                ),
            )
            selected.extend(filled)

    # ---------------------------------------------------------------
    # R9/R10: LLM hybrid fill – generate items when the bank has no close
    # match around b_target (or slots stayed empty). Exam #1 bootstraps via
    # LLM only when the bank is completely empty, mirroring old /start-cat.
    # ---------------------------------------------------------------
    generated_questions: list[Question] = []
    llm_gap = float(settings.ADAPTIVE_MIN_B_GAP_LLM)
    hybrid_enabled = bool(llm_runtime_settings.get("cat_enable_hybrid_llm_on_answer"))
    bootstrap_needed = exam_index <= 1 and not pool and not selected

    missing = n - len(selected)
    # Picks too far from b_target are replacement candidates (worst gap first).
    far_picks: list[dict] = []
    if exam_index > 1:
        far_picks = sorted(
            (q for q in selected if abs(q["difficulty_b"] - b_target) > llm_gap),
            key=lambda q: -abs(q["difficulty_b"] - b_target),
        )

    if bootstrap_needed or (hybrid_enabled and (missing > 0 or far_picks)):
        gen_target_theta = b_target if exam_index > 1 else 0.0
        error_rates = topic_error_rates(
            [r for r in chain_scoring_data if r.get("topic_id") is not None]
        )
        preferred_topic_id = None
        if error_rates:
            preferred_topic_id = max(error_rates.items(), key=lambda kv: kv[1])[0]
        if preferred_topic_id is None and topic_order:
            preferred_topic_id = topic_order[0]

        to_generate = min(missing + len(far_picks), MAX_LLM_FILL_PER_EXAM)
        if bootstrap_needed:
            to_generate = min(n, MAX_LLM_FILL_PER_EXAM)
        if preferred_topic_id is not None and to_generate > 0:
            append_rule(
                applied_rules,
                rule_events,
                "R9",
                (
                    f"Ngân hàng thiếu câu phù hợp quanh b_target={gen_target_theta:.2f} "
                    f"(thiếu {missing} slot, {len(far_picks)} câu lệch quá {llm_gap}) "
                    f"=> kích hoạt LLM sinh {to_generate} câu"
                ),
            )
            blocked = set(used_signatures)
            for _ in range(to_generate):
                generated_q = await generate_and_persist_cat_question(
                    db=db,
                    user_id=user_id,
                    subject_id=chain.subject_id,
                    topic_id=preferred_topic_id,
                    theta=float(gen_target_theta),
                    blocked_signatures=blocked,
                    llm_runtime_settings=llm_runtime_settings,
                )
                if not generated_q:
                    break
                blocked.add(question_signature_from_model(generated_q))
                generated_questions.append(generated_q)
                append_rule(
                    applied_rules,
                    rule_events,
                    "R10",
                    "Scoring/validation gán b dự kiến cho câu hỏi LLM theo độ phức tạp suy luận",
                    question_id=generated_q.id,
                )
                # Generated items fill empty slots first, then replace the
                # worst-gap bank picks so the exam stays at N questions.
                if missing > 0:
                    missing -= 1
                elif far_picks:
                    dropped = far_picks.pop(0)
                    selected = [q for q in selected if q["id"] != dropped["id"]]

    # ---------------------------------------------------------------
    # Safety fallback: top up remaining slots by pure Fisher information.
    # ---------------------------------------------------------------
    if len(selected) + len(generated_questions) < n:
        chosen_ids = {q["id"] for q in selected}
        leftovers = [q for q in pool if q["id"] not in chosen_ids]
        while leftovers and len(selected) + len(generated_questions) < n:
            pick = select_best_by_fisher(leftovers, current_theta=float(theta))
            if not pick:
                break
            selected.append(pick)
            leftovers = [q for q in leftovers if q["id"] != pick["id"]]

    if not selected and not generated_questions:
        return [], rule_events

    random.shuffle(selected)
    selected_ids = [q["id"] for q in selected]
    questions: list[Question] = []
    if selected_ids:
        loaded = await db.execute(
            select(Question)
            .where(Question.id.in_(selected_ids))
            .options(selectinload(Question.topic).selectinload(Topic.major_topic))
        )
        by_id = {q.id: q for q in loaded.scalars().unique().all()}
        questions = [by_id[qid] for qid in selected_ids if qid in by_id]

    questions.extend(generated_questions)
    return questions, rule_events
