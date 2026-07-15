"""Minimal OpenAI-compatible LLM client.

Uses stdlib urllib to avoid extra dependencies.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any


def _extract_json_object(text: str) -> dict[str, Any]:
    """Try parsing direct JSON, then fenced JSON code block."""
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Handle ```json ... ``` blocks
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data

    raise ValueError("LLM response is not valid JSON object")


def _chat_completion(
    messages: list[dict[str, str]],
    temperature: float | None = None,
    runtime_settings: dict[str, Any] | None = None,
) -> str:
    """Call OpenAI-compatible chat completion API and return assistant content."""
    if runtime_settings is None:
        raise RuntimeError("LLM runtime settings are required")

    effective = runtime_settings

    if not effective["llm_enabled"]:
        raise RuntimeError("LLM is disabled")
    api_key = str(effective.get("llm_api_key") or "").strip()
    if not api_key:
        raise RuntimeError("LLM_API_KEY is empty")

    payload = {
        "model": effective["llm_model"],
        "temperature": effective["llm_temperature"] if temperature is None else temperature,
        "messages": messages,
    }

    url = str(effective["llm_base_url"]).rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=int(effective["llm_timeout_seconds"])) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        raise RuntimeError(f"LLM HTTP error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM connection error: {exc}") from exc

    data = json.loads(raw)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected LLM response format: {data}") from exc
    return str(content)


def generate_mcq_with_llm(
    topic_name: str,
    knowledge_context: str,
    target_level: str,
    target_b: float | None = None,
    target_a: float | None = None,
    target_c: float | None = None,
    runtime_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call OpenAI-compatible chat completion API and return parsed JSON question."""
    if runtime_settings is None:
        raise RuntimeError("LLM runtime settings are required")

    system_prompt = str(runtime_settings.get("llm_system_prompt") or "").strip()
    if not system_prompt:
        raise RuntimeError("LLM system prompt is empty")

    irt_hint = ""
    if target_b is not None or target_a is not None or target_c is not None:
        irt_hint = (
            "\\nMục tiêu tham số IRT cụ thể:"
            f" b={target_b if target_b is not None else 'N/A'},"
            f" a={target_a if target_a is not None else 'N/A'},"
            f" c={target_c if target_c is not None else 'N/A'}."
            " Ưu tiên bám gần các giá trị này."
        )

    user_prompt = (
        "Tạo 1 câu hỏi trắc nghiệm 4 lựa chọn bằng tiếng Việt.\\n"
        f"Topic: {topic_name}\\n"
        f"Ngữ cảnh kiến thức: {knowledge_context}\\n"
        f"Mức độ mục tiêu: {target_level}\\n"
        f"{irt_hint}\\n"
        "Yêu cầu trả về DUY NHẤT JSON object hợp lệ, không thêm text ngoài JSON.\\n"
        "Ràng buộc: correct_answer chỉ một trong A/B/C/D; b trong [-3,3], a trong [0.5,2.5], c trong [0,0.35]."
    )

    content = _chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        runtime_settings=runtime_settings,
    )
    return _extract_json_object(content)


FORMAT_PROMPTS = {
    "mcq": (
        "Tạo 1 câu hỏi trắc nghiệm 4 lựa chọn bằng tiếng Việt.",
        "JSON gồm: stem, option_a, option_b, option_c, option_d, correct_answer (A/B/C/D), "
        "difficulty_b, discrimination_a, guessing_c, explanation.",
    ),
    "true_false": (
        "Tạo 1 câu hỏi Đúng/Sai bằng tiếng Việt (một khẳng định, người học chọn Đúng hoặc Sai).",
        "JSON gồm: stem (khẳng định), correct_answer ('A' nếu Đúng, 'B' nếu Sai), "
        "difficulty_b, discrimination_a, explanation. KHÔNG cần các option.",
    ),
    "short_answer": (
        "Tạo 1 câu hỏi trả lời ngắn bằng tiếng Việt (đáp án là một từ/cụm từ/giá trị ngắn, xác định duy nhất).",
        "JSON gồm: stem, answer_text (đáp án chuẩn, kèm các cách viết chấp nhận được ngăn cách "
        "bằng ký tự '|', ví dụ '3|ba'), difficulty_b, discrimination_a, explanation.",
    ),
    "matching": (
        "Tạo 1 câu hỏi ghép đôi bằng tiếng Việt: 3-5 cặp khái niệm bên trái ghép với mô tả/giá trị bên phải.",
        "JSON gồm: stem (câu lệnh yêu cầu ghép đôi), pairs (mảng object {left, right}, 3-5 phần tử, "
        "các right phải khác nhau), difficulty_b, discrimination_a, explanation.",
    ),
}


def generate_question_with_llm(
    topic_name: str,
    knowledge_context: str,
    target_level: str,
    question_format: str = "mcq",
    target_b: float | None = None,
    runtime_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a question of any supported format; returns parsed JSON payload."""
    if runtime_settings is None:
        raise RuntimeError("LLM runtime settings are required")

    fmt = question_format if question_format in FORMAT_PROMPTS else "mcq"
    if fmt == "mcq":
        return generate_mcq_with_llm(
            topic_name=topic_name,
            knowledge_context=knowledge_context,
            target_level=target_level,
            target_b=target_b,
            runtime_settings=runtime_settings,
        )

    intro, schema = FORMAT_PROMPTS[fmt]
    system_prompt = str(runtime_settings.get("llm_system_prompt") or "").strip() or (
        "Bạn là trợ lý tạo câu hỏi kiểm tra theo IRT. Luôn trả JSON hợp lệ."
    )
    b_hint = f"\nĐộ khó mục tiêu b ≈ {target_b:.2f} (thang [-3,3])." if target_b is not None else ""
    user_prompt = (
        f"{intro}\n"
        f"Topic: {topic_name}\n"
        f"Ngữ cảnh kiến thức: {knowledge_context}\n"
        f"Mức Bloom mục tiêu: {target_level}{b_hint}\n"
        f"Trả về DUY NHẤT JSON object hợp lệ. {schema}\n"
        "Ràng buộc: difficulty_b trong [-3,3], discrimination_a trong [0.5,2.5]."
    )
    content = _chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        runtime_settings=runtime_settings,
    )
    payload = _extract_json_object(content)
    payload["question_format"] = fmt
    return payload


def _gemini_generate(prompt: str, runtime_settings: dict[str, Any]) -> str:
    """Call Google Generative Language API (Gemini) and return text."""
    api_key = str(runtime_settings.get("gemini_api_key") or "").strip()
    if not runtime_settings.get("gemini_enabled") or not api_key:
        raise RuntimeError("Gemini validator is disabled")

    model = str(runtime_settings.get("gemini_model") or "gemini-2.0-flash")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(runtime_settings.get("llm_timeout_seconds", 30))) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        raise RuntimeError(f"Gemini HTTP error {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Gemini connection error: {exc}") from exc

    data = json.loads(raw)
    try:
        return str(data["candidates"][0]["content"]["parts"][0]["text"])
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected Gemini response: {str(data)[:300]}") from exc


def cross_validate_with_gemini(
    question_payload: dict[str, Any],
    runtime_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Second-opinion check: Gemini solves the question independently; the item
    passes when Gemini's answer agrees with the intended key.

    Returns {enabled, agree, gemini_answer, notes}. Never raises when Gemini is
    disabled — returns enabled=False so callers can treat it as skipped.
    """
    if runtime_settings is None or not runtime_settings.get("gemini_enabled") or not str(
        runtime_settings.get("gemini_api_key") or ""
    ).strip():
        return {"enabled": False, "agree": None, "gemini_answer": None, "notes": "Gemini tắt"}

    fmt = str(question_payload.get("question_format") or "mcq")
    q_json = json.dumps(
        {k: v for k, v in question_payload.items() if k not in ("correct_answer", "answer_text", "pairs", "matching_pairs", "explanation")},
        ensure_ascii=False,
    )

    if fmt in ("mcq", "true_false"):
        expected = str(question_payload.get("correct_answer", "")).upper()[:1]
        options = "A/B/C/D" if fmt == "mcq" else "A (Đúng) / B (Sai)"
        prompt = (
            f"Giải câu hỏi sau và trả về DUY NHẤT JSON {{\"answer\": \"...\"}} với answer thuộc {options}.\n"
            f"{q_json}"
        )
        try:
            text = _gemini_generate(prompt, runtime_settings)
            parsed = _extract_json_object(text)
            got = str(parsed.get("answer", "")).upper()[:1]
            return {
                "enabled": True,
                "agree": got == expected,
                "gemini_answer": got,
                "notes": "" if got == expected else f"Gemini chọn {got}, đáp án dự kiến {expected}",
            }
        except Exception as exc:  # noqa: BLE001 — validator must not break generation
            return {"enabled": True, "agree": None, "gemini_answer": None, "notes": f"Lỗi Gemini: {exc}"}

    if fmt == "short_answer":
        expected_aliases = [
            a.strip().lower() for a in str(question_payload.get("answer_text", "")).split("|") if a.strip()
        ]
        prompt = (
            "Trả lời ngắn gọn câu hỏi sau, trả về DUY NHẤT JSON {\"answer\": \"...\"}.\n"
            f"{q_json}"
        )
        try:
            text = _gemini_generate(prompt, runtime_settings)
            parsed = _extract_json_object(text)
            got = " ".join(str(parsed.get("answer", "")).strip().lower().split())
            agree = got in expected_aliases
            return {
                "enabled": True,
                "agree": agree,
                "gemini_answer": got,
                "notes": "" if agree else f"Gemini trả lời '{got}'",
            }
        except Exception as exc:  # noqa: BLE001
            return {"enabled": True, "agree": None, "gemini_answer": None, "notes": f"Lỗi Gemini: {exc}"}

    if fmt == "matching":
        pairs = question_payload.get("pairs") or question_payload.get("matching_pairs") or []
        lefts = [str(p.get("left", "")) for p in pairs]
        rights = sorted(str(p.get("right", "")) for p in pairs)
        expected = {str(p.get("left", "")): str(p.get("right", "")) for p in pairs}
        prompt = (
            "Ghép mỗi mục bên trái với đúng một mục bên phải. Trả về DUY NHẤT JSON "
            "{\"mapping\": {left: right, ...}}.\n"
            f"Câu hỏi: {question_payload.get('stem', '')}\n"
            f"Trái: {json.dumps(lefts, ensure_ascii=False)}\n"
            f"Phải: {json.dumps(rights, ensure_ascii=False)}"
        )
        try:
            text = _gemini_generate(prompt, runtime_settings)
            parsed = _extract_json_object(text)
            mapping = parsed.get("mapping") or {}
            agree = bool(expected) and all(
                str(mapping.get(l, "")).strip() == r for l, r in expected.items()
            )
            return {
                "enabled": True,
                "agree": agree,
                "gemini_answer": json.dumps(mapping, ensure_ascii=False)[:300],
                "notes": "" if agree else "Gemini ghép khác đáp án dự kiến",
            }
        except Exception as exc:  # noqa: BLE001
            return {"enabled": True, "agree": None, "gemini_answer": None, "notes": f"Lỗi Gemini: {exc}"}

    return {"enabled": True, "agree": None, "gemini_answer": None, "notes": f"Format {fmt} chưa hỗ trợ"}


def validate_generated_mcq_with_llm(
    question_payload: dict[str, Any],
    target_b: float,
    runtime_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Zero-shot validation: ask LLM to solve and estimate calibrated difficulty."""
    validation_system = (
        "Bạn là agent thẩm định chất lượng câu hỏi trắc nghiệm theo IRT 3PL. "
        "Nhiệm vụ: tự giải, kiểm tra tính nhất quán đáp án, ước lượng lại độ khó b. "
        "Trả DUY NHẤT JSON với các khóa: "
        "is_valid, solved_answer, estimated_b, reasoning_steps, confidence, notes."
    )
    validation_user = (
        "Thẩm định câu hỏi sau và trả JSON.\\n"
        f"Target b mong muốn: {round(float(target_b), 2)}\\n"
        f"Question JSON: {json.dumps(question_payload, ensure_ascii=False)}\\n"
        "Ràng buộc: is_valid là boolean; solved_answer thuộc A/B/C/D; estimated_b trong [-3,3]; "
        "reasoning_steps là số nguyên >= 1; confidence trong [0,1]."
    )

    content = _chat_completion(
        messages=[
            {"role": "system", "content": validation_system},
            {"role": "user", "content": validation_user},
        ],
        temperature=0.0,
        runtime_settings=runtime_settings,
    )
    parsed = _extract_json_object(content)

    solved = str(parsed.get("solved_answer", "")).upper()[:1]
    if solved not in {"A", "B", "C", "D"}:
        raise ValueError("Validation failed: solved_answer invalid")

    estimated_b = float(parsed.get("estimated_b"))
    reasoning_steps = int(parsed.get("reasoning_steps"))
    confidence = float(parsed.get("confidence"))
    is_valid = bool(parsed.get("is_valid"))

    return {
        "is_valid": is_valid,
        "solved_answer": solved,
        "estimated_b": max(-3.0, min(3.0, estimated_b)),
        "reasoning_steps": max(1, reasoning_steps),
        "confidence": max(0.0, min(1.0, confidence)),
        "notes": str(parsed.get("notes", "")).strip(),
    }
