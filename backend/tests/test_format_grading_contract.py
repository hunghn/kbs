"""What the CRUD API stores must be exactly what grade_answer can grade.

These tests build a Question straight from normalize_format_fields (the same
call the API makes) and grade it, so a change to either side breaks here.
"""
import json

import pytest

from app.models.question import Question
from app.services.adaptive_shared import grade_answer, matching_sides
from app.services.question_format import normalize_format_fields


def _question(fmt: str, payload: dict, question_id: int = 1) -> Question:
    fields = normalize_format_fields(fmt, payload, strict=True)
    return Question(
        id=question_id,
        external_id="X1",
        topic_id=1,
        stem="stem",
        difficulty_b=0,
        discrimination_a=1,
        question_type="Thông hiểu",
        time_limit_seconds=60,
        **fields,
    )


class TestMcqGrading:
    def test_correct_letter(self):
        q = _question(
            "mcq",
            {"option_a": "a", "option_b": "b", "option_c": "c", "option_d": "d", "correct_answer": "C"},
        )
        assert grade_answer(q, "C") == (True, "C", None)

    def test_wrong_letter(self):
        q = _question(
            "mcq",
            {"option_a": "a", "option_b": "b", "option_c": "c", "option_d": "d", "correct_answer": "C"},
        )
        is_correct, letter, _ = grade_answer(q, "A")
        assert is_correct is False and letter == "A"


class TestTrueFalseGrading:
    @pytest.mark.parametrize("key,answer,expected", [("A", "A", True), ("A", "B", False), ("B", "B", True)])
    def test_grades_by_letter(self, key, answer, expected):
        q = _question("true_false", {"correct_answer": key})
        assert grade_answer(q, answer)[0] is expected

    def test_options_render_as_dung_sai(self):
        q = _question("true_false", {"correct_answer": "A"})
        assert (q.option_a, q.option_b) == ("Đúng", "Sai")


class TestShortAnswerGrading:
    @pytest.mark.parametrize("submitted", ["4", " 4 ", "bốn", "BỐN", "  four  "])
    def test_accepts_every_alias_case_insensitively(self, submitted):
        q = _question("short_answer", {"answer_text": "4|bốn|four"})
        is_correct, letter, text = grade_answer(q, submitted)
        assert is_correct is True
        assert letter is None
        assert text == submitted.strip()

    def test_rejects_other_answers(self):
        q = _question("short_answer", {"answer_text": "4|bốn"})
        assert grade_answer(q, "5")[0] is False

    def test_form_style_alias_list_round_trips(self):
        """The UI joins primary + aliases with '|'; grading must split them back."""
        q = _question("short_answer", {"answer_text": "|".join(["Kết nối trong", "INNER JOIN"])})
        assert grade_answer(q, "inner join")[0] is True


class TestMatchingGrading:
    PAIRS = [{"left": "SELECT", "right": "Chiếu"}, {"left": "WHERE", "right": "Chọn"},
             {"left": "JOIN", "right": "Kết nối"}]

    def test_full_match_is_correct(self):
        q = _question("matching", {"matching_pairs": self.PAIRS})
        submitted = json.dumps({p["left"]: p["right"] for p in self.PAIRS}, ensure_ascii=False)
        assert grade_answer(q, submitted)[0] is True

    def test_partial_match_is_wrong(self):
        q = _question("matching", {"matching_pairs": self.PAIRS})
        mapping = {p["left"]: p["right"] for p in self.PAIRS}
        mapping["JOIN"] = "Chọn"
        assert grade_answer(q, json.dumps(mapping, ensure_ascii=False))[0] is False

    def test_malformed_submission_is_wrong_not_crash(self):
        q = _question("matching", {"matching_pairs": self.PAIRS})
        assert grade_answer(q, "không phải json")[0] is False

    def test_sides_expose_both_columns_without_the_mapping(self):
        q = _question("matching", {"matching_pairs": self.PAIRS})
        left, right = matching_sides(q)
        assert left == [p["left"] for p in self.PAIRS]
        assert sorted(right) == sorted(p["right"] for p in self.PAIRS)

    def test_shuffle_is_stable_per_question(self):
        """Re-fetching an exam must not reshuffle the right column mid-attempt."""
        q = _question("matching", {"matching_pairs": self.PAIRS})
        assert matching_sides(q) == matching_sides(q)

    def test_shuffle_varies_across_questions(self):
        """Seeded by question id, so different items get different orderings."""
        orderings = {
            tuple(matching_sides(_question("matching", {"matching_pairs": self.PAIRS}, qid))[1])
            for qid in range(1, 12)
        }
        assert len(orderings) > 1
