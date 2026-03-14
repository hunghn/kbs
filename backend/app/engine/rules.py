"""Rule engine for Rela-model inference rules."""

from collections import defaultdict


def classify_difficulty_level(b_value: float) -> str:
    """IF b > 0.8 => hard; IF b < -0.8 => easy; else medium."""
    if b_value > 0.8:
        return "Mức khó"
    if b_value < -0.8:
        return "Mức dễ"
    return "Mức trung bình"


def topic_error_rates(responses: list[dict]) -> dict[int, float]:
    """Compute per-topic error rate from answer history."""
    agg = defaultdict(lambda: {"total": 0, "wrong": 0})
    for r in responses:
        tid = int(r["topic_id"])
        agg[tid]["total"] += 1
        if not r.get("is_correct", False):
            agg[tid]["wrong"] += 1

    rates = {}
    for tid, item in agg.items():
        if item["total"] > 0:
            rates[tid] = item["wrong"] / item["total"]
    return rates
