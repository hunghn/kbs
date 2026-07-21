"""Personalized learning API: onboarding, placement test, weekly study plan,
progress tracking and monthly report."""
import json
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.api.auth import get_current_user
from app.models.user import User, QuizSession, QuizResponse, UserTopicProgress
from app.models.question import Question
from app.models.knowledge import Subject, MajorTopic, Topic
from app.models.personal import LearnerProfile, StudyPlan, StudyPlanItem
from app.services.adaptive_shared import apply_forgetting, question_to_out
from app.services.plan_builder import generate_plan, GOAL_LEVELS

router = APIRouter(prefix="/api/personal", tags=["personal"])

DAY_NAMES = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
SLOT_NAMES = {"sang": "Sáng", "chieu": "Chiều", "toi": "Tối"}


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on DateTime(timezone=True); Postgres keeps it.
    Normalize to aware-UTC so callers can safely compare across backends."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class ProfileIn(BaseModel):
    availability: list[dict] = Field(default_factory=list)
    onboarded: bool | None = None


class GeneratePlanIn(BaseModel):
    subject_id: int
    goal: str = "gioi"           # kha | gioi | xuat_sac
    target_weeks: int = 8


class CompleteItemIn(BaseModel):
    session_id: int


async def _get_profile(db: AsyncSession, user_id: int) -> LearnerProfile | None:
    return (
        await db.execute(select(LearnerProfile).where(LearnerProfile.user_id == user_id))
    ).scalar_one_or_none()


@router.get("/profile")
async def get_profile(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    profile = await _get_profile(db, user.id)
    plans = (
        await db.execute(
            select(StudyPlan, Subject.name)
            .join(Subject, Subject.id == StudyPlan.subject_id)
            .where(StudyPlan.user_id == user.id, StudyPlan.status == "active")
        )
    ).all()
    return {
        "has_profile": profile is not None,
        "onboarded": bool(profile.onboarded) if profile else False,
        "availability": json.loads(profile.availability) if profile else [],
        "active_plans": [
            {
                "plan_id": p.id,
                "subject_id": p.subject_id,
                "subject_name": sname,
                "goal_label": p.goal_label,
                "goal_theta": float(p.goal_theta),
                "target_weeks": p.target_weeks,
            }
            for p, sname in plans
        ],
    }


@router.post("/profile")
async def save_profile(
    payload: ProfileIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    profile = await _get_profile(db, user.id)
    if not profile:
        profile = LearnerProfile(user_id=user.id)
        db.add(profile)
    profile.availability = json.dumps(payload.availability, ensure_ascii=False)
    if payload.onboarded is not None:
        profile.onboarded = payload.onboarded
    await db.commit()
    return {"ok": True, "availability": payload.availability}


@router.post("/placement/start")
async def start_placement(
    subject_id: int,
    num_questions: int = 12,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bài test đầu vào: trải đều độ khó + phủ tối đa topic của môn."""
    pool = (
        await db.execute(
            select(Question)
            .join(Topic, Topic.id == Question.topic_id)
            .join(MajorTopic, MajorTopic.id == Topic.major_topic_id)
            .where(MajorTopic.subject_id == subject_id)
            .where(Question.is_archived.is_(False))
            .options(selectinload(Question.topic).selectinload(Topic.major_topic))
        )
    ).scalars().unique().all()
    if not pool:
        raise HTTPException(status_code=404, detail="Môn học chưa có câu hỏi")

    n = max(6, min(int(num_questions), 20))
    # Round-robin topic, trong mỗi topic chọn trải theo b
    by_topic: dict[int, list[Question]] = {}
    for q in pool:
        by_topic.setdefault(q.topic_id, []).append(q)
    for qs in by_topic.values():
        qs.sort(key=lambda q: float(q.difficulty_b))

    picked: list[Question] = []
    topic_lists = list(by_topic.values())
    step_idx = {id(qs): 0 for qs in topic_lists}
    while len(picked) < n and any(step_idx[id(qs)] < len(qs) for qs in topic_lists):
        for qs in topic_lists:
            if len(picked) >= n:
                break
            i = step_idx[id(qs)]
            if i < len(qs):
                # trải độ khó: lấy phần tử cách đều trong dải b của topic
                pos = min(len(qs) - 1, round(i * (len(qs) - 1) / max(1, (n // len(topic_lists)) or 1)))
                picked.append(qs[pos])
                step_idx[id(qs)] = i + 1

    session = QuizSession(user_id=user.id, subject_id=subject_id, total_questions=len(picked))
    db.add(session)
    await db.flush()
    for q in picked:
        db.add(QuizResponse(session_id=session.id, question_id=q.id, is_correct=False))
    await db.commit()

    return {
        "session_id": session.id,
        "subject_id": subject_id,
        "questions": [question_to_out(q) for q in picked],
    }


def _plan_detail(plan: StudyPlan, items: list[StudyPlanItem], topic_names: dict[int, str]) -> dict:
    weeks: dict[int, list[dict]] = {}
    done = 0
    for it in items:
        if it.status == "done":
            done += 1
        weeks.setdefault(it.week_index, []).append(
            {
                "item_id": it.id,
                "day_of_week": it.day_of_week,
                "day_name": DAY_NAMES[it.day_of_week % 7],
                "slot": it.slot,
                "slot_name": SLOT_NAMES.get(it.slot, it.slot),
                "activity": it.activity,
                "topic_id": it.topic_id,
                "topic_name": topic_names.get(it.topic_id, "") if it.topic_id else "Thi thử tổng hợp",
                "status": it.status,
                "result_score": it.result_score,
                "result_total": it.result_total,
                "session_id": it.session_id,
            }
        )
    return {
        "plan_id": plan.id,
        "subject_id": plan.subject_id,
        "goal_label": plan.goal_label,
        "goal_theta": float(plan.goal_theta),
        "target_weeks": plan.target_weeks,
        "start_theta": float(plan.start_theta) if plan.start_theta is not None else None,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "projection": json.loads(plan.projection) if plan.projection else None,
        "progress": {"done": done, "total": len(items)},
        "weeks": [
            {"week_index": w, "items": its} for w, its in sorted(weeks.items())
        ],
    }


async def _load_plan_detail(db: AsyncSession, plan: StudyPlan) -> dict:
    items = (
        await db.execute(
            select(StudyPlanItem)
            .where(StudyPlanItem.plan_id == plan.id)
            .order_by(StudyPlanItem.week_index.asc(), StudyPlanItem.order_in_week.asc())
        )
    ).scalars().all()
    topic_ids = {it.topic_id for it in items if it.topic_id}
    names = {}
    if topic_ids:
        for t in (await db.execute(select(Topic).where(Topic.id.in_(topic_ids)))).scalars():
            names[t.id] = t.name
    return _plan_detail(plan, list(items), names)


@router.post("/plan/generate")
async def generate_study_plan(
    payload: GeneratePlanIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    profile = await _get_profile(db, user.id)
    if not profile:
        raise HTTPException(status_code=400, detail="Chưa có hồ sơ — hãy hoàn thành onboarding")
    availability = json.loads(profile.availability or "[]")

    try:
        plan = await generate_plan(
            db,
            user_id=user.id,
            subject_id=payload.subject_id,
            goal_key=payload.goal,
            target_weeks=payload.target_weeks,
            availability=availability,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return await _load_plan_detail(db, plan)


@router.get("/plan")
async def get_study_plan(
    subject_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plan = (
        await db.execute(
            select(StudyPlan).where(
                StudyPlan.user_id == user.id,
                StudyPlan.subject_id == subject_id,
                StudyPlan.status == "active",
            )
        )
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Chưa có lộ trình cho môn này")

    detail = await _load_plan_detail(db, plan)

    # θ thực tế theo tuần kể từ khi lập lộ trình (từ các phiên đã hoàn thành)
    sessions = (
        await db.execute(
            select(QuizSession)
            .where(
                QuizSession.user_id == user.id,
                QuizSession.subject_id == subject_id,
                QuizSession.completed_at.isnot(None),
                QuizSession.theta_estimate.isnot(None),
            )
            .order_by(QuizSession.completed_at.asc())
        )
    ).scalars().all()
    actual_weekly: list[dict] = []
    if plan.created_at:
        start = _aware(plan.created_at)
        for s in sessions:
            completed = _aware(s.completed_at)
            if completed and completed >= start:
                week = int((completed - start).days // 7) + 1
                actual_weekly.append({"week": week, "theta": float(s.theta_estimate)})
        # giữ giá trị cuối của mỗi tuần
        last_by_week: dict[int, float] = {}
        for p in actual_weekly:
            last_by_week[p["week"]] = p["theta"]
        actual_weekly = [{"week": w, "theta": t} for w, t in sorted(last_by_week.items())]
    detail["actual_weekly"] = actual_weekly
    return detail


@router.post("/plan/item/{item_id}/start")
async def start_plan_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bắt đầu một buổi học: practice/review = 5 câu topic quanh θ hiệu dụng;
    thi thử tổng hợp = 10 câu trải đều môn."""
    item = await db.get(StudyPlanItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy buổi học")
    plan = await db.get(StudyPlan, item.plan_id)
    if not plan or plan.user_id != user.id:
        raise HTTPException(status_code=404, detail="Không tìm thấy buổi học")

    if item.activity in ("practice", "review") and item.topic_id:
        prog = (
            await db.execute(
                select(UserTopicProgress).where(
                    UserTopicProgress.user_id == user.id,
                    UserTopicProgress.topic_id == item.topic_id,
                )
            )
        ).scalar_one_or_none()
        theta_eff = 0.0
        if prog and (prog.questions_attempted or 0) > 0:
            theta_eff, _d = apply_forgetting(float(prog.theta_estimate or 0.0), prog.updated_at)
        pool = (
            await db.execute(
                select(Question)
                .where(Question.topic_id == item.topic_id, Question.is_archived.is_(False))
                .options(selectinload(Question.topic).selectinload(Topic.major_topic))
            )
        ).scalars().all()
        if not pool:
            raise HTTPException(status_code=400, detail="Topic chưa có câu hỏi")
        picked = sorted(pool, key=lambda q: abs(float(q.difficulty_b) - theta_eff))[:5]
    else:
        pool = (
            await db.execute(
                select(Question)
                .join(Topic, Topic.id == Question.topic_id)
                .join(MajorTopic, MajorTopic.id == Topic.major_topic_id)
                .where(MajorTopic.subject_id == plan.subject_id)
                .where(Question.is_archived.is_(False))
                .options(selectinload(Question.topic).selectinload(Topic.major_topic))
            )
        ).scalars().unique().all()
        pool.sort(key=lambda q: float(q.difficulty_b))
        step = max(1, len(pool) // 10)
        picked = pool[::step][:10]

    session = QuizSession(user_id=user.id, subject_id=plan.subject_id, total_questions=len(picked))
    db.add(session)
    await db.flush()
    for q in picked:
        db.add(QuizResponse(session_id=session.id, question_id=q.id, is_correct=False))
    item.session_id = session.id
    await db.commit()

    return {
        "session_id": session.id,
        "item_id": item.id,
        "activity": item.activity,
        "questions": [question_to_out(q) for q in picked],
    }


@router.post("/plan/item/{item_id}/complete")
async def complete_plan_item(
    item_id: int,
    payload: CompleteItemIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = await db.get(StudyPlanItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy buổi học")
    plan = await db.get(StudyPlan, item.plan_id)
    if not plan or plan.user_id != user.id:
        raise HTTPException(status_code=404, detail="Không tìm thấy buổi học")

    session = await db.get(QuizSession, payload.session_id)
    if not session or session.user_id != user.id or not session.completed_at:
        raise HTTPException(status_code=400, detail="Phiên làm bài chưa hoàn thành")

    item.status = "done"
    item.session_id = session.id
    item.result_score = int(session.correct_answers or 0)
    item.result_total = int(session.total_questions or 0)
    item.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "item_id": item.id, "score": item.result_score, "total": item.result_total}


@router.get("/monthly-report")
async def monthly_report(
    subject_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Báo cáo 30 ngày: tiến độ lộ trình, θ đầu–cuối kỳ, phần yếu cần cải
    thiện và phần đã tiến bộ."""
    since = datetime.now(timezone.utc) - timedelta(days=30)

    sessions = (
        await db.execute(
            select(QuizSession)
            .where(
                QuizSession.user_id == user.id,
                QuizSession.subject_id == subject_id,
                QuizSession.completed_at.isnot(None),
                QuizSession.completed_at >= since,
            )
            .order_by(QuizSession.completed_at.asc())
        )
    ).scalars().all()

    theta_start = float(sessions[0].theta_estimate) if sessions and sessions[0].theta_estimate is not None else None
    theta_now = float(sessions[-1].theta_estimate) if sessions and sessions[-1].theta_estimate is not None else None

    # Accuracy theo topic trong 30 ngày
    rows = (
        await db.execute(
            select(Question.topic_id, Topic.name, QuizResponse.is_correct)
            .select_from(QuizResponse)
            .join(QuizSession, QuizSession.id == QuizResponse.session_id)
            .join(Question, Question.id == QuizResponse.question_id)
            .join(Topic, Topic.id == Question.topic_id)
            .where(
                QuizSession.user_id == user.id,
                QuizSession.subject_id == subject_id,
                QuizSession.completed_at.isnot(None),
                QuizSession.completed_at >= since,
                QuizResponse.user_answer.isnot(None),
            )
        )
    ).all()
    agg: dict[int, dict] = {}
    for tid, tname, ok in rows:
        a = agg.setdefault(tid, {"topic_id": tid, "topic_name": tname, "total": 0, "correct": 0})
        a["total"] += 1
        a["correct"] += int(bool(ok))
    topic_stats = [
        {**a, "accuracy": round(a["correct"] / a["total"], 3)}
        for a in agg.values()
        if a["total"] >= 2
    ]
    weak = sorted(topic_stats, key=lambda x: x["accuracy"])[:3]
    strong = sorted(topic_stats, key=lambda x: -x["accuracy"])[:3]

    # Tiến độ lộ trình trong 30 ngày
    plan = (
        await db.execute(
            select(StudyPlan).where(
                StudyPlan.user_id == user.id,
                StudyPlan.subject_id == subject_id,
                StudyPlan.status == "active",
            )
        )
    ).scalar_one_or_none()
    plan_progress = None
    if plan:
        items = (
            await db.execute(select(StudyPlanItem).where(StudyPlanItem.plan_id == plan.id))
        ).scalars().all()
        done_month = sum(
            1 for it in items
            if it.status == "done" and _aware(it.completed_at) and _aware(it.completed_at) >= since
        )
        plan_progress = {
            "done_this_month": done_month,
            "done_total": sum(1 for it in items if it.status == "done"),
            "total": len(items),
        }

    return {
        "subject_id": subject_id,
        "period_days": 30,
        "sessions_completed": len(sessions),
        "theta_start": theta_start,
        "theta_now": theta_now,
        "theta_delta": round(theta_now - theta_start, 2) if theta_start is not None and theta_now is not None else None,
        "weak_topics": weak,
        "improved_topics": strong,
        "plan_progress": plan_progress,
        "goals": {k: {"theta": v[0], "label": v[1]} for k, v in GOAL_LEVELS.items()},
    }
