"""Unit tests for the shared per-format normalizer."""
import json

import pytest

from app.services.question_format import (
    DEFAULT_GUESSING_C,
    MATCHING_MAX_PAIRS,
    normalize_format,
    normalize_format_fields,
    parse_matching_pairs,
)


class TestNormalizeFormat:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("mcq", "mcq"),
            ("true_false", "true_false"),
            ("SHORT_ANSWER", "short_answer"),
            ("  matching ", "matching"),
            (None, "mcq"),
            ("", "mcq"),
            ("essay", "mcq"),
        ],
    )
    def test_falls_back_to_mcq(self, value, expected):
        assert normalize_format(value) == expected


class TestParseMatchingPairs:
    def test_parses_json_string(self):
        raw = json.dumps([{"left": "A", "right": "1"}], ensure_ascii=False)
        assert parse_matching_pairs(raw) == [{"left": "A", "right": "1"}]

    def test_drops_incomplete_and_trims(self):
        pairs = parse_matching_pairs(
            [{"left": " A ", "right": "1"}, {"left": "", "right": "2"}, {"left": "C", "right": ""}]
        )
        assert pairs == [{"left": "A", "right": "1"}]

    @pytest.mark.parametrize("raw", [None, "", "not json", {"left": "A"}, 42])
    def test_returns_empty_on_garbage(self, raw):
        assert parse_matching_pairs(raw) == []


class TestMcq:
    def test_normalizes_valid_item(self):
        fields = normalize_format_fields(
            "mcq",
            {
                "option_a": " 10 là số lẻ ",
                "option_b": "10 không là số chẵn",
                "option_c": "10 là số nguyên",
                "option_d": "10 là số dương",
                "correct_answer": "b",
                "guessing_c": 0.2,
            },
            strict=True,
        )
        assert fields["question_format"] == "mcq"
        assert fields["option_a"] == "10 là số lẻ"
        assert fields["correct_answer"] == "B"
        assert fields["guessing_c"] == 0.2
        assert fields["answer_text"] is None
        assert fields["matching_pairs"] is None

    def test_rejects_missing_options(self):
        with pytest.raises(ValueError, match="thiếu nội dung đáp án"):
            normalize_format_fields(
                "mcq",
                {"option_a": "x", "option_b": "", "option_c": "z", "option_d": "", "correct_answer": "A"},
                strict=True,
            )

    @pytest.mark.parametrize("correct", ["E", "", "1", None])
    def test_rejects_bad_key(self, correct):
        with pytest.raises(ValueError, match="A/B/C/D"):
            normalize_format_fields(
                "mcq",
                {
                    "option_a": "a", "option_b": "b", "option_c": "c", "option_d": "d",
                    "correct_answer": correct,
                },
                strict=True,
            )

    def test_default_c_when_absent(self):
        fields = normalize_format_fields(
            "mcq",
            {"option_a": "a", "option_b": "b", "option_c": "c", "option_d": "d", "correct_answer": "A"},
        )
        assert fields["guessing_c"] == DEFAULT_GUESSING_C["mcq"]


class TestTrueFalse:
    def test_fills_fixed_options(self):
        fields = normalize_format_fields("true_false", {"correct_answer": "b"}, strict=True)
        assert (fields["option_a"], fields["option_b"]) == ("Đúng", "Sai")
        assert fields["correct_answer"] == "B"
        assert fields["guessing_c"] == 0.5

    @pytest.mark.parametrize("correct", ["C", "D", "", None])
    def test_rejects_keys_outside_ab(self, correct):
        with pytest.raises(ValueError, match="Đúng/Sai"):
            normalize_format_fields("true_false", {"correct_answer": correct}, strict=True)

    def test_ignores_supplied_options(self):
        fields = normalize_format_fields(
            "true_false", {"correct_answer": "A", "option_c": "rác", "option_d": "rác"}
        )
        assert fields["option_c"] == "—" and fields["option_d"] == "—"


class TestShortAnswer:
    def test_joins_aliases(self):
        fields = normalize_format_fields(
            "short_answer", {"answer_text": " 4 | bốn |  four "}, strict=True
        )
        assert fields["answer_text"] == "4|bốn|four"
        assert fields["correct_answer"] == "A"
        assert fields["guessing_c"] == DEFAULT_GUESSING_C["short_answer"]

    @pytest.mark.parametrize("answer", ["", "   ", "|||", None])
    def test_rejects_empty_answer(self, answer):
        with pytest.raises(ValueError, match="thiếu đáp án chuẩn"):
            normalize_format_fields("short_answer", {"answer_text": answer}, strict=True)


class TestMatching:
    def _pairs(self, n):
        return [{"left": f"L{i}", "right": f"R{i}"} for i in range(n)]

    def test_serializes_pairs_as_json(self):
        fields = normalize_format_fields("matching", {"matching_pairs": self._pairs(3)}, strict=True)
        assert json.loads(fields["matching_pairs"]) == self._pairs(3)
        assert fields["correct_answer"] == "A"

    def test_accepts_llm_pairs_key(self):
        fields = normalize_format_fields("matching", {"pairs": self._pairs(4)})
        assert len(json.loads(fields["matching_pairs"])) == 4

    def test_requires_three_pairs(self):
        with pytest.raises(ValueError, match="ít nhất 3 cặp"):
            normalize_format_fields("matching", {"matching_pairs": self._pairs(2)}, strict=True)

    def test_rejects_duplicate_rights(self):
        pairs = [{"left": "A", "right": "1"}, {"left": "B", "right": "1"}, {"left": "C", "right": "2"}]
        with pytest.raises(ValueError, match="vế phải phải khác nhau"):
            normalize_format_fields("matching", {"matching_pairs": pairs}, strict=True)

    def test_strict_rejects_too_many_pairs_but_lenient_truncates(self):
        many = self._pairs(MATCHING_MAX_PAIRS + 2)
        with pytest.raises(ValueError, match="tối đa"):
            normalize_format_fields("matching", {"matching_pairs": many}, strict=True)

        fields = normalize_format_fields("matching", {"matching_pairs": many})
        assert len(json.loads(fields["matching_pairs"])) == MATCHING_MAX_PAIRS


class TestGuessingBounds:
    def test_strict_rejects_out_of_range(self):
        with pytest.raises(ValueError, match="tham số c"):
            normalize_format_fields(
                "mcq",
                {
                    "option_a": "a", "option_b": "b", "option_c": "c", "option_d": "d",
                    "correct_answer": "A", "guessing_c": 0.9,
                },
                strict=True,
            )

    def test_lenient_clamps_llm_output(self):
        fields = normalize_format_fields(
            "mcq",
            {
                "option_a": "a", "option_b": "b", "option_c": "c", "option_d": "d",
                "correct_answer": "A", "guessing_c": 0.9,
            },
        )
        assert fields["guessing_c"] == 0.35


def test_unsupported_format_raises():
    with pytest.raises(ValueError, match="không hỗ trợ"):
        normalize_format_fields("essay", {})
