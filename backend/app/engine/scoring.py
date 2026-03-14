"""
Scoring module: calculates quiz scores and updates user ability estimates.
"""
from app.engine.irt import estimate_theta_eap, classify_mastery


def score_quiz(responses: list[dict]) -> dict:
    """
    Score a completed quiz.

    Args:
        responses: list of {a, b, c, is_correct, question_type, topic_id}

    Returns:
        Dict with score, theta, topic_scores, etc.
    """
    if not responses:
        return {"score": 0, "theta": 0, "accuracy": 0, "topic_scores": {}}

    total = len(responses)
    correct = sum(1 for r in responses if r["is_correct"])
    accuracy = correct / total if total > 0 else 0

    # Estimate overall theta
    theta = estimate_theta_eap(responses)

    # Per-topic scores
    topic_scores = {}
    topic_responses = {}
    for r in responses:
        tid = r.get("topic_id")
        tname = r.get("topic_name", str(tid))
        if tname not in topic_responses:
            topic_responses[tname] = []
        topic_responses[tname].append(r)

    for tname, t_resps in topic_responses.items():
        t_correct = sum(1 for r in t_resps if r["is_correct"])
        t_total = len(t_resps)
        t_theta = estimate_theta_eap(t_resps)
        topic_scores[tname] = {
            "correct": t_correct,
            "total": t_total,
            "accuracy": t_correct / t_total if t_total > 0 else 0,
            "theta": round(t_theta, 2),
            "mastery": classify_mastery(t_theta),
        }

    return {
        "score": correct,
        "total": total,
        "accuracy": round(accuracy, 4),
        "theta": round(theta, 2),
        "mastery": classify_mastery(theta),
        "topic_scores": topic_scores,
    }
