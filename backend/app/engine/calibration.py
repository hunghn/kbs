"""Item difficulty calibration from real response logs.

The bank ships with pre-labeled IRT parameters (Excel / LLM estimates).
Once an item accumulates enough real responses, its difficulty b is
re-estimated by 1-D maximum likelihood under the 3PL model, using each
responder's session ability estimate as their theta. The update is blended
conservatively: new items keep their prior label, well-observed items
converge to the empirical estimate.

This closes the knowledge-refinement loop: the system corrects its own
knowledge base from evidence.
"""
import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.engine.irt import probability_3pl
from app.models.question import Question
from app.models.knowledge import Topic, MajorTopic
from app.models.user import QuizResponse, QuizSession

B_GRID_LO, B_GRID_HI, B_GRID_STEP = -3.0, 3.0, 0.05


def estimate_b_mle(
    observations: list[tuple[float, bool]], a: float, c: float
) -> float:
    """Grid-search MLE for b given (theta_user, is_correct) observations."""
    best_b, best_ll = 0.0, float("-inf")
    b = B_GRID_LO
    while b <= B_GRID_HI + 1e-9:
        ll = 0.0
        for theta, correct in observations:
            p = probability_3pl(theta, a, b, c)
            p = min(max(p, 1e-6), 1 - 1e-6)
            ll += math.log(p) if correct else math.log(1 - p)
        if ll > best_ll:
            best_ll, best_b = ll, b
        b += B_GRID_STEP
    return round(best_b, 2)


async def run_calibration(
    db: AsyncSession,
    subject_id: int | None = None,
    min_responses: int | None = None,
    apply: bool = True,
) -> dict:
    """Re-estimate b for every item with enough real responses.

    Returns a report; when apply=True the blended values are written back
    to the question bank.
    """
    settings = get_settings()
    min_n = int(min_responses or settings.CALIBRATION_MIN_RESPONSES)
    full_weight_at = int(settings.CALIBRATION_FULL_WEIGHT_AT)

    query = (
        select(
            QuizResponse.question_id,
            QuizResponse.is_correct,
            QuizSession.theta_estimate,
        )
        .join(QuizSession, QuizSession.id == QuizResponse.session_id)
        .where(QuizResponse.user_answer.isnot(None))
        .where(QuizSession.theta_estimate.isnot(None))
    )
    if subject_id is not None:
        query = query.where(QuizSession.subject_id == subject_id)

    rows = (await db.execute(query)).all()

    by_question: dict[int, list[tuple[float, bool]]] = {}
    for qid, correct, theta in rows:
        by_question.setdefault(qid, []).append((float(theta), bool(correct)))

    eligible_ids = [qid for qid, obs in by_question.items() if len(obs) >= min_n]
    report_items = []

    if eligible_ids:
        q_query = select(Question).where(Question.id.in_(eligible_ids))
        if subject_id is not None:
            q_query = (
                q_query.join(Topic, Topic.id == Question.topic_id)
                .join(MajorTopic, MajorTopic.id == Topic.major_topic_id)
                .where(MajorTopic.subject_id == subject_id)
            )
        questions = (await db.execute(q_query)).scalars().all()

        for q in questions:
            obs = by_question[q.id]
            a = float(q.discrimination_a)
            c = float(q.guessing_c)
            b_old = float(q.difficulty_b)
            b_hat = estimate_b_mle(obs, a, c)

            # Conservative blend: weight grows with evidence
            weight = min(1.0, len(obs) / float(full_weight_at))
            b_new = round((1 - weight) * b_old + weight * b_hat, 2)
            b_new = min(max(b_new, -3.0), 3.0)

            observed_acc = sum(1 for _t, ok in obs if ok) / len(obs)
            report_items.append(
                {
                    "question_id": q.id,
                    "external_id": q.external_id,
                    "n_responses": len(obs),
                    "observed_accuracy": round(observed_acc, 3),
                    "b_old": b_old,
                    "b_mle": b_hat,
                    "blend_weight": round(weight, 2),
                    "b_new": b_new,
                    "shift": round(b_new - b_old, 2),
                }
            )
            if apply and abs(b_new - b_old) >= 0.01:
                q.difficulty_b = b_new

        if apply:
            await db.commit()

    report_items.sort(key=lambda r: -abs(r["shift"]))
    total_items_with_data = len(by_question)
    return {
        "subject_id": subject_id,
        "min_responses": min_n,
        "applied": apply,
        "items_with_responses": total_items_with_data,
        "items_calibrated": len(report_items),
        "items_below_threshold": total_items_with_data - len(report_items),
        "mean_abs_shift": round(
            sum(abs(r["shift"]) for r in report_items) / len(report_items), 3
        )
        if report_items
        else None,
        "items": report_items[:50],
    }
