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
