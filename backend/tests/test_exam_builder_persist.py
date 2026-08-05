"""Persisting an LLM-generated item still writes the right columns per format
after the format rules moved into services/question_format.py.
"""
import json

import pytest

from app.services.exam_builder import _persist_generated, _question_admin_view


async def _persist(session_factory, topic_id, fmt, payload, bloom="Thông hiểu"):
    async with session_factory() as session:
        question = await _persist_generated(
            session, topic_id=topic_id, payload=payload, fmt=fmt, bloom=bloom
        )
        await session.commit()
        return question


class TestPersistGenerated:
    async def test_mcq_columns(self, session_factory, seeded):
        q = await _persist(
            session_factory,
            seeded["topic_a"],
            "mcq",
            {
                "stem": "Stem MCQ",
                "option_a": "a", "option_b": "b", "option_c": "c", "option_d": "d",
                "correct_answer": "d",
                "difficulty_b": 0.4,
                "discrimination_a": 1.3,
                "guessing_c": 0.25,
            },
        )
        assert q.question_format == "mcq"
        assert q.correct_answer == "D"
        assert q.is_archived is True  # quarantined until a teacher approves

    async def test_true_false_columns(self, session_factory, seeded):
        q = await _persist(
            session_factory,
            seeded["topic_a"],
            "true_false",
            {"stem": "Khẳng định", "correct_answer": "B", "difficulty_b": 0, "discrimination_a": 1},
        )
        assert q.question_format == "true_false"
        assert (q.option_a, q.option_b) == ("Đúng", "Sai")
        assert float(q.guessing_c) == 0.5

    async def test_short_answer_columns(self, session_factory, seeded):
        q = await _persist(
            session_factory,
            seeded["topic_a"],
            "short_answer",
            {"stem": "Hỏi", "answer_text": "4|bốn", "difficulty_b": 0, "discrimination_a": 1},
        )
        assert q.question_format == "short_answer"
        assert q.answer_text == "4|bốn"
        assert q.correct_answer == "A"

    async def test_matching_columns_serialized(self, session_factory, seeded):
        pairs = [{"left": f"L{i}", "right": f"R{i}"} for i in range(3)]
        q = await _persist(
            session_factory,
            seeded["topic_a"],
            "matching",
            {"stem": "Ghép", "pairs": pairs, "difficulty_b": 0, "discrimination_a": 1},
        )
        assert json.loads(q.matching_pairs) == pairs
        assert _question_admin_view(q, source="llm", validation=None)["matching_pairs"] == pairs

    async def test_bloom_drives_time_budget(self, session_factory, seeded):
        q = await _persist(
            session_factory,
            seeded["topic_a"],
            "true_false",
            {"stem": "S", "correct_answer": "A", "difficulty_b": 0, "discrimination_a": 1},
            bloom="Vận dụng",
        )
        assert (q.time_limit_seconds, q.time_display) == (90, "01:30")

    async def test_irt_params_clamped(self, session_factory, seeded):
        q = await _persist(
            session_factory,
            seeded["topic_a"],
            "true_false",
            {"stem": "S", "correct_answer": "A", "difficulty_b": 42, "discrimination_a": 42},
        )
        assert float(q.difficulty_b) == 3.0
        assert float(q.discrimination_a) == 2.5

    @pytest.mark.parametrize(
        "fmt,payload",
        [
            ("short_answer", {"stem": "S", "answer_text": ""}),
            ("matching", {"stem": "S", "pairs": [{"left": "a", "right": "1"}]}),
            ("mcq", {"stem": "S", "option_a": "a", "option_b": "b", "option_c": "c",
                     "option_d": "d", "correct_answer": "Z"}),
        ],
    )
    async def test_invalid_payload_rejected(self, session_factory, seeded, fmt, payload):
        payload = {"difficulty_b": 0, "discrimination_a": 1, **payload}
        with pytest.raises(ValueError):
            await _persist(session_factory, seeded["topic_a"], fmt, payload)

    async def test_missing_stem_rejected(self, session_factory, seeded):
        with pytest.raises(ValueError, match="Thiếu stem"):
            await _persist(
                session_factory,
                seeded["topic_a"],
                "true_false",
                {"stem": "  ", "correct_answer": "A", "difficulty_b": 0, "discrimination_a": 1},
            )
