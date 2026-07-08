"""DB persistence for the exam-difficulty RL bandit."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.rl_policy import QTable, ACTIONS, ALPHA
from app.models.cat_knowledge import RLPolicy


async def load_policy(db: AsyncSession, subject_id: int, seed: int | None = None) -> QTable:
    policy = QTable(seed=seed)
    rows = await db.execute(select(RLPolicy).where(RLPolicy.subject_id == subject_id))
    for row in rows.scalars().all():
        key = (row.state_key, int(row.action_index))
        policy.q[key] = float(row.q_value)
        policy.visits[key] = int(row.visits)
    return policy


async def apply_reward(
    db: AsyncSession, subject_id: int, state: str, action: int, reward: float
) -> float:
    """Bandit update Q += α(r − Q) persisted to DB; returns the new Q."""
    result = await db.execute(
        select(RLPolicy).where(
            RLPolicy.subject_id == subject_id,
            RLPolicy.state_key == state,
            RLPolicy.action_index == action,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        row = RLPolicy(
            subject_id=subject_id, state_key=state, action_index=action, q_value=0, visits=0
        )
        db.add(row)
    new_q = float(row.q_value or 0.0) + ALPHA * (reward - float(row.q_value or 0.0))
    row.q_value = round(new_q, 4)
    row.visits = int(row.visits or 0) + 1
    return new_q


async def policy_snapshot(db: AsyncSession, subject_id: int) -> list[dict]:
    rows = await db.execute(
        select(RLPolicy)
        .where(RLPolicy.subject_id == subject_id)
        .order_by(RLPolicy.state_key.asc(), RLPolicy.action_index.asc())
    )
    return [
        {
            "state": r.state_key,
            "action_index": int(r.action_index),
            "b_offset": ACTIONS[int(r.action_index)],
            "q_value": float(r.q_value),
            "visits": int(r.visits),
        }
        for r in rows.scalars().all()
    ]
