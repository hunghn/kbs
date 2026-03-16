"""
Scoring module: calculates quiz scores and updates user ability estimates.
"""
from app.engine.irt import estimate_ability_3pl, classify_mastery


def score_quiz(responses: list[dict]) -> dict:
    """
    Score a completed quiz using unified Bayesian ability estimation.

    Args:
        responses: list of {a, b, c, is_correct, question_type, topic_id}

    Returns:
        Dict with score, theta, sem, topic_scores, etc.
    """
    if not responses:
        return {
            "score": 0,
            "theta": 0,
            "sem": 999.0,
            "accuracy": 0,
            "topic_scores": {},
        }

    total = len(responses)
    correct = sum(1 for r in responses if r["is_correct"])
    accuracy = correct / total if total > 0 else 0

    # Estimate overall ability using unified Bayesian engine
    ability_result = estimate_ability_3pl(responses)
    theta = ability_result["theta_map"]
    posterior_sd = ability_result["posterior_sd"]

    # Per-topic scores using same unified method
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
        t_ability = estimate_ability_3pl(t_resps)
        t_theta = t_ability["theta_map"]
        topic_scores[tname] = {
            "correct": t_correct,
            "total": t_total,
            "accuracy": round(t_correct / t_total, 4) if t_total > 0 else 0.0,
            "theta": round(t_theta, 2),
            "mastery": classify_mastery(t_theta),
        }

    return {
        "score": correct,
        "total": total,
        "accuracy": round(accuracy, 4),
        "theta": round(theta, 2),
        "sem": round(posterior_sd, 3),
        "mastery": classify_mastery(theta),
        "topic_scores": topic_scores,
    }
