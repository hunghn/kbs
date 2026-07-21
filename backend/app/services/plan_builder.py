"""Personal study-plan builder.

Sinh lộ trình học theo tuần từ: kết quả test đầu vào (θ từng topic), mục tiêu
(θ đích + số tuần), lịch rảnh của người học, thứ tự tiên quyết trong ontology
và đường cong quên. Lộ trình được VALIDATE bằng mô hình dự phóng học tập
(learning-gain giảm dần theo số buổi luyện) — trả về đường cong θ dự kiến theo
tuần; nếu không chạm mục tiêu trong thời gian đặt ra, báo rõ và gợi ý điều chỉnh.
"""
import json
import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.irt import classify_mastery
from app.models.knowledge import Topic, MajorTopic, TopicPrerequisite
from app.models.cat_knowledge import KnowledgeGraph
from app.models.user import UserTopicProgress
from app.models.personal import StudyPlan, StudyPlanItem
from app.services.adaptive_shared import apply_forgetting

GOAL_LEVELS = {
    "kha": (0.5, "Khá"),
    "gioi": (1.0, "Giỏi"),
    "xuat_sac": (1.5, "Xuất sắc"),
}

SLOT_ORDER = {"sang": 0, "chieu": 1, "toi": 2}
MAX_WEEKS = 16

# Learning-gain model: buổi luyện thứ k của một topic tăng θ_topic thêm
# GAIN_BASE * exp(-GAIN_DECAY * k) — lợi ích giảm dần, dùng cho dự phóng.
GAIN_BASE = 0.30
GAIN_DECAY = 0.40


async def _topics_with_status(
    db: AsyncSession, user_id: int, subject_id: int
) -> list[dict]:
    """Topics của môn theo thứ tự topo tiên quyết, kèm θ hiệu dụng + trạng thái."""
    rows = (
        await db.execute(
            select(Topic, MajorTopic)
            .join(MajorTopic, MajorTopic.id == Topic.major_topic_id)
            .where(MajorTopic.subject_id == subject_id)
            .order_by(MajorTopic.order_index.asc(), Topic.order_index.asc(), Topic.id.asc())
        )
    ).all()
    topic_ids = [t.id for t, _mt in rows]
    if not topic_ids:
        return []

    edges: set[tuple[int, int]] = set()
    for link in (
        await db.execute(
            select(TopicPrerequisite).where(TopicPrerequisite.topic_id.in_(topic_ids))
        )
    ).scalars().all():
        if link.prerequisite_topic_id in set(topic_ids):
            edges.add((link.prerequisite_topic_id, link.topic_id))
    for e in (
        await db.execute(
            select(KnowledgeGraph)
            .where(KnowledgeGraph.subject_id == subject_id)
            .where(KnowledgeGraph.source_type == "topic")
            .where(KnowledgeGraph.target_type == "topic")
            .where(KnowledgeGraph.relation_type == "prerequisite")
        )
    ).scalars().all():
        if e.target_id in set(topic_ids) and e.source_id in set(topic_ids):
            edges.add((int(e.target_id), int(e.source_id)))

    progress = {
        p.topic_id: p
        for p in (
            await db.execute(
                select(UserTopicProgress).where(
                    UserTopicProgress.user_id == user_id,
                    UserTopicProgress.topic_id.in_(topic_ids),
                )
            )
        ).scalars().all()
    }

    info: dict[int, dict] = {}
    for t, mt in rows:
        p = progress.get(t.id)
        if p and (p.questions_attempted or 0) > 0:
            theta_eff, _days = apply_forgetting(float(p.theta_estimate or 0.0), p.updated_at)
        else:
            theta_eff = -1.2  # chưa học: giả định dưới trung bình
        level = classify_mastery(theta_eff) if p and (p.questions_attempted or 0) > 0 else None
        if level in ("proficient", "master"):
            status = "mastered"
        elif level == "developing":
            status = "in_progress"
        elif level is not None:
            status = "weak"
        else:
            status = "not_started"
        info[t.id] = {
            "topic_id": t.id,
            "code": t.code,
            "name": t.name,
            "major_topic_name": mt.name,
            "theta": round(theta_eff, 2),
            "status": status,
        }

    # Kahn topo sort (ontology order tie-break)
    base_order = {tid: i for i, tid in enumerate(topic_ids)}
    indegree = {tid: 0 for tid in topic_ids}
    for _a, b in edges:
        indegree[b] += 1
    ordered: list[int] = []
    ready = sorted([t for t in topic_ids if indegree[t] == 0], key=base_order.get)
    while ready:
        cur = ready.pop(0)
        ordered.append(cur)
        for a, b in edges:
            if a == cur:
                indegree[b] -= 1
                if indegree[b] == 0:
                    ready.append(b)
        ready.sort(key=base_order.get)
    for tid in topic_ids:  # cycle fallback
        if tid not in ordered:
            ordered.append(tid)

    return [info[tid] for tid in ordered]


def _build_activity_queue(topics: list[dict]) -> list[dict]:
    """Hàng đợi buổi học: topic yếu 2 buổi (luyện + ôn lại cách xa — spaced
    repetition), đang tiến bộ/chưa học 1 buổi, đã thành thạo bỏ qua."""
    first_pass, review_pass = [], []
    for t in topics:
        if t["status"] == "mastered":
            continue
        first_pass.append({"activity": "practice", "topic_id": t["topic_id"], "name": t["name"]})
        if t["status"] == "weak":
            review_pass.append({"activity": "review", "topic_id": t["topic_id"], "name": t["name"]})
    return first_pass + review_pass


def _project(
    topics: list[dict],
    schedule: list[dict],
    weeks: int,
    goal_theta: float,
) -> dict:
    """Mô phỏng dự phóng: θ từng topic tăng theo learning-gain giảm dần khi
    được luyện; θ môn = trung bình các topic. Trả đường cong theo tuần."""
    theta = {t["topic_id"]: float(t["theta"]) for t in topics}
    practiced: dict[int, int] = {}

    def subject_theta() -> float:
        return sum(theta.values()) / len(theta) if theta else 0.0

    weekly = [{"week": 0, "theta": round(subject_theta(), 3)}]
    by_week: dict[int, list[dict]] = {}
    for it in schedule:
        by_week.setdefault(it["week_index"], []).append(it)

    for w in range(1, weeks + 1):
        for it in by_week.get(w, []):
            tid = it.get("topic_id")
            if tid is None or tid not in theta:
                continue
            k = practiced.get(tid, 0)
            theta[tid] = min(3.0, theta[tid] + GAIN_BASE * math.exp(-GAIN_DECAY * k))
            practiced[tid] = k + 1
        weekly.append({"week": w, "theta": round(subject_theta(), 3)})

    final_theta = weekly[-1]["theta"]
    feasible = final_theta >= goal_theta
    reach_week = next((p["week"] for p in weekly if p["theta"] >= goal_theta), None)

    notes: list[str] = []
    if feasible and reach_week is not None:
        notes.append(f"Dự kiến chạm mục tiêu θ ≥ {goal_theta} ở tuần {reach_week}.")
    else:
        gap = round(goal_theta - final_theta, 2)
        notes.append(
            f"Với lịch hiện tại, θ dự phóng cuối kỳ = {final_theta} — còn thiếu {gap} so với mục tiêu."
        )
        notes.append("Gợi ý: thêm buổi rảnh mỗi tuần, tăng số tuần, hoặc hạ mức mục tiêu.")

    return {
        "feasible": feasible,
        "goal_theta": goal_theta,
        "final_theta": final_theta,
        "reach_week": reach_week,
        "projected_weekly": weekly,
        "notes": notes,
    }


async def generate_plan(
    db: AsyncSession,
    *,
    user_id: int,
    subject_id: int,
    goal_key: str,
    target_weeks: int,
    availability: list[dict],
) -> StudyPlan:
    """Sinh lộ trình mới (đánh dấu 'replaced' cho lộ trình active cũ)."""
    if goal_key not in GOAL_LEVELS:
        raise ValueError("Mục tiêu không hợp lệ (kha / gioi / xuat_sac)")
    goal_theta, goal_label = GOAL_LEVELS[goal_key]

    slots = sorted(
        {(int(s["day"]), str(s["slot"])) for s in availability if str(s.get("slot")) in SLOT_ORDER},
        key=lambda x: (x[0], SLOT_ORDER[x[1]]),
    )
    if not slots:
        raise ValueError("Chưa chọn buổi rảnh nào trong tuần")

    topics = await _topics_with_status(db, user_id, subject_id)
    if not topics:
        raise ValueError("Môn học chưa có topic")

    queue = _build_activity_queue(topics)
    if not queue:
        raise ValueError("Bạn đã thành thạo mọi topic — không cần lộ trình mới")

    target_weeks = max(2, min(int(target_weeks), MAX_WEEKS))
    slots_per_week = len(slots)

    # Xếp hàng đợi vào các buổi rảnh; cuối mỗi tuần chẵn chèn 1 buổi thi thử
    schedule: list[dict] = []
    week, cursor = 1, 0
    qi = 0
    while qi < len(queue) and week <= MAX_WEEKS:
        day, slot = slots[cursor]
        is_last_slot_of_week = cursor == slots_per_week - 1
        if is_last_slot_of_week and week % 2 == 0:
            schedule.append({
                "week_index": week, "order_in_week": cursor, "day_of_week": day,
                "slot": slot, "activity": "mock_exam", "topic_id": None,
            })
        else:
            item = queue[qi]
            qi += 1
            schedule.append({
                "week_index": week, "order_in_week": cursor, "day_of_week": day,
                "slot": slot, "activity": item["activity"], "topic_id": item["topic_id"],
            })
        cursor += 1
        if cursor >= slots_per_week:
            cursor = 0
            week += 1

    weeks_used = max(it["week_index"] for it in schedule)
    projection = _project(topics, schedule, max(weeks_used, target_weeks), goal_theta)
    projection["weeks_used"] = weeks_used
    projection["target_weeks"] = target_weeks
    projection["slots_per_week"] = slots_per_week
    projection["sessions_total"] = len(schedule)
    if weeks_used > target_weeks:
        projection["notes"].append(
            f"Cần {weeks_used} tuần để phủ hết nội dung với {slots_per_week} buổi/tuần "
            f"(mục tiêu đặt {target_weeks} tuần)."
        )

    # Replace old active plan
    for old in (
        await db.execute(
            select(StudyPlan).where(
                StudyPlan.user_id == user_id,
                StudyPlan.subject_id == subject_id,
                StudyPlan.status == "active",
            )
        )
    ).scalars().all():
        old.status = "replaced"

    start_theta = sum(t["theta"] for t in topics) / len(topics)
    plan = StudyPlan(
        user_id=user_id,
        subject_id=subject_id,
        goal_theta=goal_theta,
        goal_label=goal_label,
        target_weeks=target_weeks,
        start_theta=round(start_theta, 2),
        status="active",
        projection=json.dumps(projection, ensure_ascii=False),
    )
    db.add(plan)
    await db.flush()

    for it in schedule:
        db.add(StudyPlanItem(plan_id=plan.id, **it))

    await db.commit()
    await db.refresh(plan)
    return plan
