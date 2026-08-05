"""Per-format rules for question items.

Single source of truth for the four supported formats (mcq | true_false |
short_answer | matching). Both the exam builder (LLM-generated items) and the
question-bank CRUD API normalize through here so the two cannot drift.

Column conventions kept for backwards compatibility with `grade_answer`:
- true_false : option_a = "Đúng", option_b = "Sai", correct_answer in A/B
- short_answer / matching : options are placeholders, correct_answer = "A";
  the real key lives in `answer_text` / `matching_pairs`
"""
import json

SUPPORTED_FORMATS = ("mcq", "true_false", "short_answer", "matching")

FORMAT_LABELS = {
    "mcq": "Trắc nghiệm",
    "true_false": "Đúng/Sai",
    "short_answer": "Trả lời ngắn",
    "matching": "Ghép đôi",
}

# Guessing parameter c: a 4-option MCQ guesses at ~0.25, Đúng/Sai at 0.5, while
# a constructed response is near-impossible to guess.
DEFAULT_GUESSING_C = {
    "mcq": 0.25,
    "true_false": 0.5,
    "short_answer": 0.05,
    "matching": 0.05,
}

GUESSING_C_BOUNDS = {
    "mcq": (0.0, 0.35),
    "true_false": (0.0, 0.6),
    "short_answer": (0.0, 0.2),
    "matching": (0.0, 0.2),
}

PLACEHOLDER_OPTION = "—"
MATCHING_MIN_PAIRS = 3
MATCHING_MAX_PAIRS = 6


def normalize_format(value: str | None) -> str:
    fmt = str(value or "mcq").strip().lower()
    return fmt if fmt in SUPPORTED_FORMATS else "mcq"


def parse_matching_pairs(raw) -> list[dict]:
    """Accept a JSON string or an iterable of {left, right}; drop incomplete rows."""
    if not raw:
        return []

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []

    if not isinstance(raw, (list, tuple)):
        return []

    pairs: list[dict] = []
    for item in raw:
        if isinstance(item, dict):
            left, right = item.get("left", ""), item.get("right", "")
        else:
            left, right = getattr(item, "left", ""), getattr(item, "right", "")
        left, right = str(left).strip(), str(right).strip()
        if left and right:
            pairs.append({"left": left, "right": right})
    return pairs


def _resolve_guessing_c(fmt: str, payload: dict, strict: bool) -> float:
    raw = payload.get("guessing_c")
    if raw is None or raw == "":
        return DEFAULT_GUESSING_C[fmt]

    try:
        value = float(raw)
    except (ValueError, TypeError):
        if strict:
            raise ValueError("Tham số đoán mò c không hợp lệ")
        return DEFAULT_GUESSING_C[fmt]

    low, high = GUESSING_C_BOUNDS[fmt]
    if low <= value <= high:
        return value
    if strict:
        raise ValueError(
            f"Dạng {FORMAT_LABELS[fmt]}: tham số c phải trong [{low}, {high}]"
        )
    return min(max(value, low), high)


def normalize_format_fields(fmt: str, payload: dict, *, strict: bool = False) -> dict:
    """Map a format-specific payload onto the `questions` columns.

    Returns every format-owned column so switching a question's format clears
    the fields the previous format owned.

    strict=True (teacher input via CRUD) reports out-of-range values as errors;
    strict=False (LLM output) clamps them silently.

    Raises ValueError with a user-facing Vietnamese message on invalid input.
    """
    fmt = str(fmt or "").strip().lower()
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"Dạng câu hỏi không hỗ trợ: {fmt}")

    fields = {
        "question_format": fmt,
        "option_a": PLACEHOLDER_OPTION,
        "option_b": PLACEHOLDER_OPTION,
        "option_c": PLACEHOLDER_OPTION,
        "option_d": PLACEHOLDER_OPTION,
        "correct_answer": "A",
        "guessing_c": _resolve_guessing_c(fmt, payload, strict),
        "answer_text": None,
        "matching_pairs": None,
    }

    if fmt == "mcq":
        options = {
            key: str(payload.get(key, "") or "").strip()
            for key in ("option_a", "option_b", "option_c", "option_d")
        }
        missing = [key[-1].upper() for key, value in sorted(options.items()) if not value]
        if missing:
            raise ValueError(f"Trắc nghiệm: thiếu nội dung đáp án {', '.join(missing)}")
        correct = str(payload.get("correct_answer", "") or "").strip().upper()[:1]
        if correct not in ("A", "B", "C", "D"):
            raise ValueError("Trắc nghiệm: đáp án đúng phải thuộc A/B/C/D")
        fields.update(options)
        fields["correct_answer"] = correct

    elif fmt == "true_false":
        correct = str(payload.get("correct_answer", "") or "").strip().upper()[:1]
        if correct not in ("A", "B"):
            raise ValueError("Đúng/Sai: đáp án đúng phải là A (Đúng) hoặc B (Sai)")
        fields.update({"option_a": "Đúng", "option_b": "Sai", "correct_answer": correct})

    elif fmt == "short_answer":
        aliases = [
            part.strip()
            for part in str(payload.get("answer_text", "") or "").split("|")
            if part.strip()
        ]
        if not aliases:
            raise ValueError("Trả lời ngắn: thiếu đáp án chuẩn (answer_text)")
        fields["answer_text"] = "|".join(aliases)

    else:  # matching
        pairs = parse_matching_pairs(
            payload.get("matching_pairs") if payload.get("matching_pairs") else payload.get("pairs")
        )
        if len(pairs) < MATCHING_MIN_PAIRS:
            raise ValueError(f"Ghép đôi: cần ít nhất {MATCHING_MIN_PAIRS} cặp hợp lệ")
        if len(pairs) > MATCHING_MAX_PAIRS:
            if strict:
                raise ValueError(f"Ghép đôi: tối đa {MATCHING_MAX_PAIRS} cặp")
            pairs = pairs[:MATCHING_MAX_PAIRS]
        rights = [p["right"] for p in pairs]
        if len(set(rights)) != len(rights):
            raise ValueError("Ghép đôi: các vế phải phải khác nhau")
        fields["matching_pairs"] = json.dumps(pairs, ensure_ascii=False)

    return fields
