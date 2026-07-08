"""Seed the Skill layer of the ontology.

Each topic gets two measurable skills, bridging topic knowledge with the
Bloom taxonomy used by the question bank:
  - comprehension: đo qua câu Nhận biết / Thông hiểu
  - application  : đo qua câu Vận dụng
Idempotent: only creates skills for topics that don't have them yet, so it
also covers topics imported later.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Topic, Skill


def _strip_code_prefix(name: str) -> str:
    """'1.1 Logic mệnh đề' -> 'Logic mệnh đề'."""
    parts = (name or "").strip().split(" ", 1)
    if len(parts) == 2 and any(ch.isdigit() for ch in parts[0]):
        return parts[1]
    return name


async def seed_skills(db: AsyncSession) -> int:
    """Create missing skills; returns the number of skills created."""
    topics = (await db.execute(select(Topic))).scalars().all()
    existing = (await db.execute(select(Skill.topic_id, Skill.kind))).all()
    existing_pairs = {(t, k) for t, k in existing}

    created = 0
    for topic in topics:
        base = _strip_code_prefix(topic.name)
        for kind, name in (
            ("comprehension", f"Hiểu và trình bày {base}"),
            ("application", f"Vận dụng {base} giải quyết bài toán"),
        ):
            if (topic.id, kind) in existing_pairs:
                continue
            db.add(Skill(topic_id=topic.id, name=name, kind=kind))
            created += 1

    if created:
        await db.commit()
    return created
