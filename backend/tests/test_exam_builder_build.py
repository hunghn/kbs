"""Dựng đề nháp không được khoá event loop và luôn phải trả về đúng hạn.

Trước đây các lệnh gọi LLM (urllib, chặn) chạy thẳng trong coroutine và tuần
tự, nên một lần dựng đề 10 câu có thể chiếm event loop vài phút — proxy của
Next ngắt kết nối và client nhận `socket hang up`.
"""
import time

import pytest

from app.services import exam_builder


RUNTIME = {
    "llm_enabled": True,
    "llm_api_key": "k",
    "llm_model": "m",
    "llm_base_url": "http://llm.invalid/v1",
    "llm_temperature": 0.7,
    "llm_timeout_seconds": 300,
    "llm_system_prompt": "sys",
    "gemini_enabled": False,
    "gemini_api_key": "",
}

CALL_SECONDS = 0.3


@pytest.fixture
def slow_llm(monkeypatch):
    """LLM giả lập: chặn thread thật sự (như urllib) trong CALL_SECONDS."""
    calls: list[dict] = []

    def fake_generate(**kwargs):
        calls.append(kwargs)
        time.sleep(CALL_SECONDS)
        return {
            "stem": f"Câu về {kwargs['topic_name']}",
            "option_a": "a", "option_b": "b", "option_c": "c", "option_d": "d",
            "correct_answer": "A",
            "difficulty_b": 0.2,
            "discrimination_a": 1.1,
            "guessing_c": 0.25,
        }

    def fake_self_check(payload, target_b, runtime_settings):
        return {
            "is_valid": True,
            "solved_answer": "A",
            "estimated_b": 0.2,
            "reasoning_steps": 2,
            "confidence": 0.9,
            "notes": "",
        }

    monkeypatch.setattr(exam_builder, "generate_question_with_llm", fake_generate)
    monkeypatch.setattr(exam_builder, "validate_generated_mcq_with_llm", fake_self_check)
    monkeypatch.setattr(
        exam_builder,
        "cross_validate_with_gemini",
        lambda payload, runtime_settings: {"enabled": False, "agree": None,
                                           "gemini_answer": None, "notes": "Gemini tắt"},
    )
    return calls


async def _build(session_factory, seeded, **overrides):
    kwargs = dict(
        subject_id=seeded["subject_id"],
        topic_ids=None,
        format_counts={"mcq": 8, "true_false": 0, "short_answer": 0, "matching": 0},
        bloom_pcts={"recognition": 0.3, "comprehension": 0.5, "application": 0.2},
        anchor_mode="manual",
        target_b=0.0,
        use_llm=True,
        runtime_settings=RUNTIME,
    )
    kwargs.update(overrides)
    async with session_factory() as session:
        draft = await exam_builder.build_draft(session, **kwargs)
        await session.commit()
        return draft


class TestBuildDraftLlmPhase:
    async def test_generates_missing_items_concurrently(self, session_factory, seeded, slow_llm):
        """8 câu × 0.3s tuần tự = 2.4s; song song 4 luồng phải nhanh hơn nhiều."""
        started = time.monotonic()
        draft = await _build(session_factory, seeded)
        elapsed = time.monotonic() - started

        assert draft["built"] == 8
        assert draft["sources"]["llm"] == 8
        assert not draft["warnings"]
        # 2 đợt sinh + 2 đợt tự thẩm định ≈ 1.2s; ngưỡng nới rộng cho CI chậm.
        assert elapsed < 8 * CALL_SECONDS

    async def test_event_loop_stays_responsive(self, session_factory, seeded, slow_llm):
        """Trong lúc dựng đề, event loop vẫn phục vụ được request khác."""
        import asyncio

        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        tick_task = asyncio.ensure_future(ticker())
        try:
            await _build(session_factory, seeded)
        finally:
            tick_task.cancel()

        assert ticks > 10, "event loop bị lệnh gọi LLM chặn"

    async def test_budget_exhausted_returns_partial_draft(
        self, session_factory, seeded, slow_llm, monkeypatch
    ):
        """Hết hạn giờ thì trả đề một phần kèm cảnh báo, không treo request."""
        monkeypatch.setattr(exam_builder, "LLM_PHASE_BUDGET_SECONDS", 0.0)

        draft = await _build(session_factory, seeded)

        assert draft["built"] == 0
        assert len(draft["warnings"]) == 8
        assert all("hết thời gian" in w for w in draft["warnings"])

    async def test_llm_disabled_reports_gaps(self, session_factory, seeded, slow_llm):
        draft = await _build(session_factory, seeded, use_llm=False)

        assert draft["built"] == 0
        assert len(draft["warnings"]) == 8
        assert not slow_llm, "không được gọi LLM khi use_llm=False"

    async def test_per_call_timeout_capped(self, session_factory, seeded, slow_llm):
        """Timeout 300s của admin bị hạ trần trước khi tới lớp HTTP."""
        await _build(session_factory, seeded)

        caps = {c["runtime_settings"]["llm_timeout_seconds"] for c in slow_llm}
        assert caps == {exam_builder.LLM_CALL_TIMEOUT_CAP_SECONDS}

    async def test_one_failing_item_does_not_break_the_draft(
        self, session_factory, seeded, monkeypatch
    ):
        seq = {"n": 0}

        def flaky(**kwargs):
            seq["n"] += 1
            if seq["n"] % 2 == 0:
                raise RuntimeError("LLM HTTP error 429: rate limited")
            return {
                "stem": f"Câu {seq['n']}",
                "option_a": "a", "option_b": "b", "option_c": "c", "option_d": "d",
                "correct_answer": "B", "difficulty_b": 0.0, "discrimination_a": 1.0,
            }

        monkeypatch.setattr(exam_builder, "generate_question_with_llm", flaky)
        monkeypatch.setattr(
            exam_builder,
            "validate_generated_mcq_with_llm",
            lambda payload, target_b, runtime_settings: {
                "is_valid": True, "solved_answer": "B", "estimated_b": 0.0,
                "reasoning_steps": 1, "confidence": 0.8, "notes": "",
            },
        )
        monkeypatch.setattr(
            exam_builder,
            "cross_validate_with_gemini",
            lambda payload, runtime_settings: {"enabled": False, "agree": None,
                                               "gemini_answer": None, "notes": ""},
        )

        draft = await _build(session_factory, seeded)

        assert draft["built"] == 4
        assert len(draft["warnings"]) == 4
        assert all("429" in w for w in draft["warnings"])
