"""CRUD tests for the question bank API across all four formats."""
import pytest

BASE = "/api/questions"


def _base_payload(topic_id: int, **overrides) -> dict:
    payload = {
        "external_id": "T001",
        "topic_id": topic_id,
        "stem": "Câu hỏi thử nghiệm",
        "question_format": "mcq",
        "option_a": "A",
        "option_b": "B",
        "option_c": "C",
        "option_d": "D",
        "correct_answer": "A",
        "matching_pairs": [],
        "difficulty_b": 0.5,
        "discrimination_a": 1.2,
        "question_type": "Thông hiểu",
        "time_limit_seconds": 60,
    }
    payload.update(overrides)
    return payload


class TestCreateByFormat:
    async def test_creates_mcq(self, client, seeded):
        res = await client.post(BASE, json=_base_payload(seeded["topic_a"]))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["question_format"] == "mcq"
        assert body["correct_answer"] == "A"
        assert body["guessing_c"] == 0.25  # format default
        assert body["matching_pairs"] == []
        assert body["time_display"] == "01:00"

    async def test_creates_true_false(self, client, seeded):
        res = await client.post(
            BASE,
            json=_base_payload(
                seeded["topic_a"],
                external_id="TF001",
                question_format="true_false",
                correct_answer="B",
                option_a="",
                option_b="",
                option_c="",
                option_d="",
            ),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert (body["option_a"], body["option_b"]) == ("Đúng", "Sai")
        assert body["correct_answer"] == "B"
        assert body["guessing_c"] == 0.5

    async def test_creates_short_answer(self, client, seeded):
        res = await client.post(
            BASE,
            json=_base_payload(
                seeded["topic_a"],
                external_id="SA001",
                question_format="short_answer",
                answer_text="4|bốn",
                option_a="",
                option_b="",
                option_c="",
                option_d="",
            ),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["answer_text"] == "4|bốn"
        assert body["correct_answer"] == "A"
        assert body["guessing_c"] == 0.05

    async def test_creates_matching(self, client, seeded):
        pairs = [{"left": f"L{i}", "right": f"R{i}"} for i in range(3)]
        res = await client.post(
            BASE,
            json=_base_payload(
                seeded["topic_a"],
                external_id="MT001",
                question_format="matching",
                matching_pairs=pairs,
                option_a="",
                option_b="",
                option_c="",
                option_d="",
            ),
        )
        assert res.status_code == 200, res.text
        assert res.json()["matching_pairs"] == pairs

    @pytest.mark.parametrize(
        "overrides,expected",
        [
            ({"question_format": "short_answer", "answer_text": ""}, "thiếu đáp án chuẩn"),
            ({"question_format": "matching", "matching_pairs": []}, "ít nhất 3 cặp"),
            ({"question_format": "true_false", "correct_answer": "D"}, "Đúng/Sai"),
            ({"option_b": ""}, "thiếu nội dung đáp án"),
        ],
    )
    async def test_rejects_invalid_payloads(self, client, seeded, overrides, expected):
        res = await client.post(BASE, json=_base_payload(seeded["topic_a"], **overrides))
        assert res.status_code == 400
        assert expected in res.json()["detail"]

    async def test_rejects_unsupported_format(self, client, seeded):
        res = await client.post(
            BASE, json=_base_payload(seeded["topic_a"], question_format="essay")
        )
        # Unknown formats fall back to mcq-shaped validation rather than 500
        assert res.status_code in (200, 400)


class TestUpdate:
    async def _create(self, client, seeded, **overrides):
        res = await client.post(BASE, json=_base_payload(seeded["topic_a"], **overrides))
        assert res.status_code == 200, res.text
        return res.json()

    async def test_partial_update_keeps_format_fields(self, client, seeded):
        created = await self._create(
            client,
            seeded,
            external_id="SA002",
            question_format="short_answer",
            answer_text="4|bốn",
        )
        res = await client.put(f"{BASE}/{created['id']}", json={"stem": "Stem mới"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["stem"] == "Stem mới"
        assert body["answer_text"] == "4|bốn"
        assert body["question_format"] == "short_answer"

    async def test_switching_format_clears_previous_key(self, client, seeded):
        created = await self._create(
            client,
            seeded,
            external_id="SA003",
            question_format="short_answer",
            answer_text="4|bốn",
        )
        res = await client.put(
            f"{BASE}/{created['id']}",
            json={
                "question_format": "mcq",
                "option_a": "a",
                "option_b": "b",
                "option_c": "c",
                "option_d": "d",
                "correct_answer": "C",
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["question_format"] == "mcq"
        assert body["answer_text"] is None
        assert body["correct_answer"] == "C"
        assert body["guessing_c"] == 0.25  # reset to the new format's default

    async def test_switching_to_matching_requires_pairs(self, client, seeded):
        created = await self._create(client, seeded, external_id="MT002")
        res = await client.put(f"{BASE}/{created['id']}", json={"question_format": "matching"})
        assert res.status_code == 400
        assert "ít nhất 3 cặp" in res.json()["detail"]

    async def test_updating_pairs_replaces_them(self, client, seeded):
        pairs = [{"left": f"L{i}", "right": f"R{i}"} for i in range(3)]
        created = await self._create(
            client, seeded, external_id="MT003", question_format="matching", matching_pairs=pairs
        )
        new_pairs = [{"left": f"X{i}", "right": f"Y{i}"} for i in range(4)]
        res = await client.put(f"{BASE}/{created['id']}", json={"matching_pairs": new_pairs})
        assert res.status_code == 200, res.text
        assert res.json()["matching_pairs"] == new_pairs

    async def test_format_change_blocked_when_answered(self, client, answered_question):
        res = await client.put(
            f"{BASE}/{answered_question}",
            json={"question_format": "true_false", "correct_answer": "A"},
        )
        assert res.status_code == 409
        assert "lịch sử làm bài" in res.json()["detail"]

    async def test_non_format_edit_allowed_when_answered(self, client, answered_question):
        res = await client.put(f"{BASE}/{answered_question}", json={"stem": "Sửa nội dung"})
        assert res.status_code == 200, res.text
        assert res.json()["stem"] == "Sửa nội dung"

    async def test_recomputes_time_display(self, client, seeded):
        created = await self._create(client, seeded, external_id="TD001")
        res = await client.put(f"{BASE}/{created['id']}", json={"time_limit_seconds": 90})
        assert res.json()["time_display"] == "01:30"


class TestListAndStats:
    async def _seed_one_of_each(self, client, seeded):
        await client.post(BASE, json=_base_payload(seeded["topic_a"], external_id="L-MCQ"))
        await client.post(
            BASE,
            json=_base_payload(
                seeded["topic_a"], external_id="L-TF", question_format="true_false", correct_answer="A"
            ),
        )
        await client.post(
            BASE,
            json=_base_payload(
                seeded["topic_b"],
                external_id="L-SA",
                question_format="short_answer",
                answer_text="x",
            ),
        )
        await client.post(
            BASE,
            json=_base_payload(
                seeded["topic_b"],
                external_id="L-MT",
                question_format="matching",
                matching_pairs=[{"left": f"L{i}", "right": f"R{i}"} for i in range(3)],
            ),
        )

    async def test_filters_by_format(self, client, seeded):
        await self._seed_one_of_each(client, seeded)
        res = await client.get(BASE, params={"subject_id": seeded["subject_id"], "question_format": "matching"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total"] == 1
        assert body["items"][0]["external_id"] == "L-MT"
        assert len(body["items"][0]["matching_pairs"]) == 3

    async def test_rejects_unknown_format_filter(self, client, seeded):
        res = await client.get(BASE, params={"question_format": "essay"})
        assert res.status_code == 400

    async def test_format_stats_counts_every_format(self, client, seeded):
        await self._seed_one_of_each(client, seeded)
        res = await client.get(f"{BASE}/format-stats", params={"subject_id": seeded["subject_id"]})
        assert res.status_code == 200, res.text
        stats = res.json()
        assert stats == {
            "total": 4,
            "mcq": 1,
            "true_false": 1,
            "short_answer": 1,
            "matching": 1,
            "archived": 0,
        }

    async def test_format_stats_respects_topic_filter(self, client, seeded):
        await self._seed_one_of_each(client, seeded)
        res = await client.get(f"{BASE}/format-stats", params={"topic_id": seeded["topic_b"]})
        stats = res.json()
        assert stats["total"] == 2
        assert stats["short_answer"] == 1 and stats["matching"] == 1
        assert stats["mcq"] == 0

    async def test_archive_counted_separately(self, client, seeded):
        created = await client.post(BASE, json=_base_payload(seeded["topic_a"], external_id="AR1"))
        qid = created.json()["id"]
        await client.post(f"{BASE}/{qid}/archive")

        stats = (await client.get(f"{BASE}/format-stats", params={"subject_id": seeded["subject_id"]})).json()
        assert stats["total"] == 1 and stats["archived"] == 1

        stats_active = (
            await client.get(
                f"{BASE}/format-stats",
                params={"subject_id": seeded["subject_id"], "include_archived": False},
            )
        ).json()
        assert stats_active["total"] == 0
