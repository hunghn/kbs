"""DKT training/prediction service.

Builds training sequences from real quiz logs, augments with synthetic
students simulated through the IRT 3PL model on the actual question bank
(so DKT learns the bank's per-topic difficulty structure even when real
logs are still sparse), and persists one model per subject.
"""
import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.irt import probability_3pl
from app.engine.dkt import DKTModel, train_dkt, model_path
from app.models.user import QuizSession, QuizResponse
from app.models.question import Question
from app.models.knowledge import Topic, MajorTopic
from app.services.exam_generation import _load_candidate_pool, _ordered_topic_ids


async def _topic_index(db: AsyncSession, subject_id: int) -> dict[int, int]:
    topic_ids = await _ordered_topic_ids(db, subject_id)
    return {tid: i for i, tid in enumerate(topic_ids)}


async def build_real_sequences(
    db: AsyncSession, subject_id: int, topic_index: dict[int, int]
) -> list[list[tuple[int, int]]]:
    rows = await db.execute(
        select(QuizSession.user_id, Question.topic_id, QuizResponse.is_correct)
        .select_from(QuizResponse)
        .join(QuizSession, QuizSession.id == QuizResponse.session_id)
        .join(Question, Question.id == QuizResponse.question_id)
        .where(QuizSession.subject_id == subject_id)
        .where(QuizResponse.user_answer.isnot(None))
        .order_by(QuizSession.user_id.asc(), QuizResponse.answered_at.asc(), QuizResponse.id.asc())
    )
    sequences: dict[int, list[tuple[int, int]]] = {}
    for user_id, topic_id, is_correct in rows:
        if topic_id not in topic_index:
            continue
        sequences.setdefault(user_id, []).append((topic_index[topic_id], int(bool(is_correct))))
    return [s for s in sequences.values() if len(s) >= 2]


async def build_synthetic_sequences(
    db: AsyncSession,
    subject_id: int,
    topic_index: dict[int, int],
    *,
    n_students: int = 200,
    seed: int = 42,
) -> list[list[tuple[int, int]]]:
    pool = await _load_candidate_pool(db, subject_id)
    pool = [q for q in pool if q["topic_id"] in topic_index]
    if not pool:
        return []

    rng = random.Random(seed)
    sequences = []
    for _ in range(n_students):
        theta = rng.gauss(0.0, 1.0)
        length = rng.randint(15, min(40, len(pool)))
        picked = rng.sample(pool, length)
        seq = []
        for q in picked:
            p = probability_3pl(
                theta,
                float(q["discrimination_a"]),
                float(q["difficulty_b"]),
                float(q["guessing_c"]),
            )
            seq.append((topic_index[q["topic_id"]], int(rng.random() < p)))
        sequences.append(seq)
    return sequences


async def train_subject_dkt(
    db: AsyncSession,
    subject_id: int,
    *,
    synthetic_students: int = 200,
    epochs: int = 25,
    seed: int = 42,
) -> dict:
    topic_index = await _topic_index(db, subject_id)
    if not topic_index:
        raise ValueError("Subject has no topics")

    real = await build_real_sequences(db, subject_id, topic_index)
    synthetic = await build_synthetic_sequences(
        db, subject_id, topic_index, n_students=synthetic_students, seed=seed
    )
    sequences = real + synthetic
    if not sequences:
        raise ValueError("No training sequences available")

    model, metrics = train_dkt(sequences, n_skills=len(topic_index), epochs=epochs, seed=seed)

    ordered_topic_ids = sorted(topic_index, key=topic_index.get)
    model.save(model_path(subject_id), ordered_topic_ids, meta={"subject_id": subject_id})

    metrics.update(
        {
            "subject_id": subject_id,
            "n_skills": len(topic_index),
            "n_real_sequences": len(real),
            "n_synthetic_sequences": len(synthetic),
            "model_path": str(model_path(subject_id)),
        }
    )
    # Don't ship the full per-epoch list to keep payload small
    metrics["loss_history"] = metrics["loss_history"][:: max(1, len(metrics["loss_history"]) // 10)]
    return metrics


async def predict_user_mastery(db: AsyncSession, subject_id: int, user_id: int) -> dict:
    path = model_path(subject_id)
    if not path.exists():
        raise FileNotFoundError("DKT model not trained for this subject")

    model, topic_ids = DKTModel.load(path)
    topic_index = {tid: i for i, tid in enumerate(topic_ids)}

    rows = await db.execute(
        select(Question.topic_id, QuizResponse.is_correct)
        .select_from(QuizResponse)
        .join(QuizSession, QuizSession.id == QuizResponse.session_id)
        .join(Question, Question.id == QuizResponse.question_id)
        .where(QuizSession.subject_id == subject_id)
        .where(QuizSession.user_id == user_id)
        .where(QuizResponse.user_answer.isnot(None))
        .order_by(QuizResponse.answered_at.asc(), QuizResponse.id.asc())
    )
    seq = [
        (topic_index[topic_id], int(bool(is_correct)))
        for topic_id, is_correct in rows
        if topic_id in topic_index
    ]

    probs = model.predict_next(seq)

    names_result = await db.execute(
        select(Topic.id, Topic.code, Topic.name, MajorTopic.name.label("major_topic_name"))
        .join(MajorTopic, MajorTopic.id == Topic.major_topic_id)
        .where(Topic.id.in_(topic_ids))
    )
    name_map = {row.id: row for row in names_result}

    per_topic_counts: dict[int, dict] = {}
    for skill_idx, correct in seq:
        agg = per_topic_counts.setdefault(skill_idx, {"attempted": 0, "correct": 0})
        agg["attempted"] += 1
        agg["correct"] += correct

    predictions = []
    for tid in topic_ids:
        idx = topic_index[tid]
        info = name_map.get(tid)
        counts = per_topic_counts.get(idx, {"attempted": 0, "correct": 0})
        predictions.append(
            {
                "topic_id": tid,
                "code": info.code if info else None,
                "topic_name": info.name if info else str(tid),
                "major_topic_name": info.major_topic_name if info else "",
                "p_correct_next": round(float(probs[idx]), 4),
                "attempted": counts["attempted"],
                "correct": counts["correct"],
            }
        )
    predictions.sort(key=lambda x: -x["p_correct_next"])

    return {
        "subject_id": subject_id,
        "history_length": len(seq),
        "predictions": predictions,
    }
