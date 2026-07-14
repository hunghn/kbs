"""Seed preset exams (đề thi có sẵn).

Each subject gets N fixed exams of M questions with:
  - Bloom distribution ~ 30% Nhận biết / 50% Thông hiểu / 20% Vận dụng
  - topic coverage (round-robin across the subject's topics)
  - difficulty spread (shuffled within topic buckets, deterministic per preset)
Idempotent per subject: subjects that already have presets are skipped.
"""
import random

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Subject, MajorTopic, Topic
from app.models.question import Question, PresetExam, PresetExamQuestion

BLOOM_TARGETS = [("Nhận biết", 0.30), ("Thông hiểu", 0.50), ("Vận dụng", 0.20)]


def _normalize_type(qtype: str | None) -> str:
    text = (qtype or "").strip().lower()
    if "nhận" in text or "nhan" in text:
        return "Nhận biết"
    if "thông" in text or "thong" in text:
        return "Thông hiểu"
    if "vận" in text or "van" in text:
        return "Vận dụng"
    return "Khác"


def _pick_with_topic_coverage(
    candidates: list, target: int, rng: random.Random
) -> list:
    """Round-robin across topics so one preset touches as many topics as possible."""
    by_topic: dict[int, list] = {}
    for q in candidates:
        by_topic.setdefault(q.topic_id, []).append(q)
    for bucket in by_topic.values():
        rng.shuffle(bucket)

    topics = list(by_topic.keys())
    rng.shuffle(topics)
    picked = []
    while len(picked) < target and any(by_topic[t] for t in topics):
        for t in topics:
            if len(picked) >= target:
                break
            if by_topic[t]:
                picked.append(by_topic[t].pop())
    return picked


def _build_preset_questions(
    pool: list, questions_per_exam: int, rng: random.Random
) -> list:
    by_bloom: dict[str, list] = {}
    for q in pool:
        by_bloom.setdefault(_normalize_type(q.question_type), []).append(q)

    selected = []
    selected_ids = set()
    for bloom, pct in BLOOM_TARGETS:
        target = round(questions_per_exam * pct)
        picked = _pick_with_topic_coverage(list(by_bloom.get(bloom, [])), target, rng)
        for q in picked:
            if q.id not in selected_ids:
                selected.append(q)
                selected_ids.add(q.id)

    # Bank may lack some Bloom type: top up from the rest of the pool
    if len(selected) < questions_per_exam:
        rest = [q for q in pool if q.id not in selected_ids]
        rng.shuffle(rest)
        selected.extend(rest[: questions_per_exam - len(selected)])

    rng.shuffle(selected)
    return selected[:questions_per_exam]


async def seed_preset_exams(
    db: AsyncSession,
    per_subject: int = 10,
    questions_per_exam: int = 50,
) -> int:
    """Create presets for subjects that don't have any yet; returns #presets created."""
    subjects = (await db.execute(select(Subject))).scalars().all()
    created = 0

    for subject in subjects:
        existing = await db.execute(
            select(func.count(PresetExam.id)).where(PresetExam.subject_id == subject.id)
        )
        if (existing.scalar() or 0) > 0:
            continue

        pool_rows = await db.execute(
            select(Question)
            .join(Topic, Topic.id == Question.topic_id)
            .join(MajorTopic, MajorTopic.id == Topic.major_topic_id)
            .where(MajorTopic.subject_id == subject.id)
            .where(Question.is_archived.is_(False))
        )
        pool = list(pool_rows.scalars().all())
        if len(pool) < questions_per_exam:
            continue  # bank too small for this subject

        for i in range(1, per_subject + 1):
            rng = random.Random(subject.id * 1000 + i)
            questions = _build_preset_questions(pool, questions_per_exam, rng)
            counts: dict[str, int] = {}
            topics = set()
            for q in questions:
                counts[_normalize_type(q.question_type)] = counts.get(_normalize_type(q.question_type), 0) + 1
                topics.add(q.topic_id)

            preset = PresetExam(
                subject_id=subject.id,
                name=f"Đề số {i}",
                description=(
                    f"{len(questions)} câu · "
                    f"Nhận biết {counts.get('Nhận biết', 0)} · "
                    f"Thông hiểu {counts.get('Thông hiểu', 0)} · "
                    f"Vận dụng {counts.get('Vận dụng', 0)} · "
                    f"phủ {len(topics)} chủ đề"
                ),
                question_count=len(questions),
            )
            db.add(preset)
            await db.flush()
            for pos, q in enumerate(questions):
                db.add(PresetExamQuestion(preset_id=preset.id, question_id=q.id, position=pos))
            created += 1

    if created:
        await db.commit()
    return created
