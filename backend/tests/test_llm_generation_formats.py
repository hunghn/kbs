"""Draft generation must return a well-formed item for each of the four formats,
whether the LLM answers, errors out, or is switched off entirely.
"""
import pytest

from app.engine import llm_generation
from app.services.question_format import DEFAULT_GUESSING_C

LLM_ON = {"llm_enabled": True, "llm_model": "test-model"}
LLM_OFF = {"llm_enabled": False, "llm_model": None}

LLM_PAYLOADS = {
    "true_false": {
        "stem": "Tập rỗng là tập con của mọi tập hợp.",
        "correct_answer": "A",
        "difficulty_b": 0.3,
        "discrimination_a": 1.4,
        "explanation": "Theo định nghĩa tập con.",
    },
    "short_answer": {
        "stem": "Số phần tử của tập lũy thừa của tập 2 phần tử là bao nhiêu?",
        "answer_text": "4|bốn",
        "difficulty_b": 0.1,
        "discrimination_a": 1.1,
        "explanation": "2^2 = 4.",
    },
    "matching": {
        "stem": "Ghép mệnh đề SQL với ý nghĩa.",
        "pairs": [
            {"left": "SELECT", "right": "Chiếu"},
            {"left": "WHERE", "right": "Chọn"},
            {"left": "JOIN", "right": "Kết nối"},
        ],
        "difficulty_b": 0.8,
        "discrimination_a": 1.6,
        "explanation": "Đại số quan hệ.",
    },
}

MCQ_PAYLOAD = {
    "stem": "Mệnh đề phủ định của '10 là số chẵn' là:",
    "option_a": "10 là số lẻ",
    "option_b": "10 không là số chẵn",
    "option_c": "10 là số nguyên",
    "option_d": "10 là số dương",
    "correct_answer": "B",
    "difficulty_b": -1.5,
    "discrimination_a": 1.1,
    "guessing_c": 0.25,
    "explanation": "Phủ định của P là ¬P.",
}


@pytest.fixture
def stub_llm(monkeypatch):
    """Route both generator entry points to canned payloads."""

    def fake_format_call(*, question_format="mcq", **_kwargs):
        return dict(LLM_PAYLOADS[question_format])

    def fake_mcq_call(**_kwargs):
        return dict(MCQ_PAYLOAD)

    monkeypatch.setattr(llm_generation, "generate_question_with_llm", fake_format_call)
    monkeypatch.setattr(llm_generation, "generate_mcq_with_llm", fake_mcq_call)


class TestLlmPath:
    def test_mcq_draft(self, stub_llm):
        draft = llm_generation.generate_question_from_topic(
            "Logic mệnh đề", None, "Thông hiểu", LLM_ON, question_format="mcq"
        )
        assert draft["question_format"] == "mcq"
        assert draft["correct_answer"] == "B"
        assert draft["generation_source"] == "llm"

    def test_true_false_draft_gets_fixed_options(self, stub_llm):
        draft = llm_generation.generate_question_from_topic(
            "Tập hợp", None, "Nhận biết", LLM_ON, question_format="true_false"
        )
        assert draft["question_format"] == "true_false"
        assert (draft["option_a"], draft["option_b"]) == ("Đúng", "Sai")
        assert draft["correct_answer"] == "A"
        assert draft["guessing_c"] == DEFAULT_GUESSING_C["true_false"]
        assert draft["generation_source"] == "llm"

    def test_short_answer_draft_keeps_aliases(self, stub_llm):
        draft = llm_generation.generate_question_from_topic(
            "Tập hợp", None, "Thông hiểu", LLM_ON, question_format="short_answer"
        )
        assert draft["answer_text"] == "4|bốn"
        assert draft["matching_pairs"] == []
        assert draft["guessing_c"] == DEFAULT_GUESSING_C["short_answer"]

    def test_matching_draft_returns_pairs_as_list(self, stub_llm):
        draft = llm_generation.generate_question_from_topic(
            "SQL", None, "Vận dụng", LLM_ON, question_format="matching"
        )
        assert draft["matching_pairs"] == LLM_PAYLOADS["matching"]["pairs"]
        assert draft["answer_text"] is None

    def test_irt_params_are_clamped(self, monkeypatch):
        monkeypatch.setattr(
            llm_generation,
            "generate_question_with_llm",
            lambda **_kw: {
                "stem": "x",
                "correct_answer": "A",
                "difficulty_b": 99,
                "discrimination_a": 99,
                "explanation": "",
            },
        )
        draft = llm_generation.generate_question_from_topic(
            "T", None, "Vận dụng", LLM_ON, question_format="true_false"
        )
        assert draft["difficulty_b"] == 3.0
        assert draft["discrimination_a"] == 2.5


class TestFallbackPath:
    @pytest.mark.parametrize("fmt", ["mcq", "true_false", "short_answer", "matching"])
    def test_llm_disabled_still_yields_a_valid_draft(self, fmt):
        draft = llm_generation.generate_question_from_topic(
            "Logic mệnh đề", "mệnh đề kéo theo", "Thông hiểu", LLM_OFF, question_format=fmt
        )
        assert draft["question_format"] == fmt
        assert draft["stem"]
        assert draft["generation_source"] == "fallback"
        if fmt == "short_answer":
            assert draft["answer_text"]
        if fmt == "matching":
            assert len(draft["matching_pairs"]) >= 3
        if fmt in ("mcq", "true_false"):
            assert draft["correct_answer"] in ("A", "B", "C", "D")

    @pytest.mark.parametrize("fmt", ["true_false", "short_answer", "matching"])
    def test_llm_error_degrades_to_fallback(self, monkeypatch, fmt):
        def boom(**_kwargs):
            raise RuntimeError("LLM timeout")

        monkeypatch.setattr(llm_generation, "generate_question_with_llm", boom)
        draft = llm_generation.generate_question_from_topic(
            "Logic", None, "Thông hiểu", LLM_ON, question_format=fmt
        )
        assert draft["generation_source"] == "fallback"
        assert "LLM timeout" in draft["explanation"]

    def test_unknown_format_falls_back_to_mcq(self):
        draft = llm_generation.generate_question_from_topic(
            "Logic", None, "Thông hiểu", LLM_OFF, question_format="essay"
        )
        assert draft["question_format"] == "mcq"

    def test_runtime_settings_required(self):
        with pytest.raises(ValueError):
            llm_generation.generate_question_from_topic("Logic", None, "Thông hiểu", None)
