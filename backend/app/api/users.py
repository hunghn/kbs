"""User API: Registration, login, dashboard."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.api.auth import hash_password, verify_password, create_access_token, get_current_user
from app.models.user import User, QuizSession, UserTopicProgress
from app.models.knowledge import Topic, MajorTopic
from app.schemas.user import UserCreate, UserLogin, UserOut, Token, UserDashboard, TopicProgressOut

router = APIRouter(prefix="/api/auth", tags=["auth"])
user_router = APIRouter(prefix="/api/users", tags=["users"])


@router.post("/register", response_model=UserOut)
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user."""
    existing = await db.execute(select(User).where(User.username == data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")

    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserOut(id=user.id, username=user.username, email=user.email)


@router.post("/login", response_model=Token)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    """Login and get access token."""
    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": user.id})
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user)):
    return UserOut(id=user.id, username=user.username, email=user.email)


@user_router.get("/dashboard", response_model=UserDashboard)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get user dashboard with progress data."""
    # Recent sessions
    sessions_result = await db.execute(
        select(QuizSession)
        .where(QuizSession.user_id == user.id)
        .order_by(QuizSession.started_at.desc())
        .limit(10)
    )
    sessions = sessions_result.scalars().all()

    # Topic progress
    progress_result = await db.execute(
        select(UserTopicProgress)
        .where(UserTopicProgress.user_id == user.id)
        .options(
            selectinload(UserTopicProgress.topic)
            .selectinload(Topic.major_topic)
        )
    )
    progress_list = progress_result.scalars().all()

    total_attempted = sum(p.questions_attempted or 0 for p in progress_list)
    total_correct = sum(p.questions_correct or 0 for p in progress_list)

    topic_progress = [
        TopicProgressOut(
            topic_id=p.topic_id,
            topic_name=p.topic.name if p.topic else "",
            major_topic_name=p.topic.major_topic.name if p.topic and p.topic.major_topic else "",
            theta_estimate=float(p.theta_estimate) if p.theta_estimate else 0,
            questions_attempted=p.questions_attempted or 0,
            questions_correct=p.questions_correct or 0,
            mastery_level=p.mastery_level or "beginner",
        )
        for p in progress_list
    ]

    recent = [
        {
            "id": s.id,
            "subject_id": s.subject_id,
            "total_questions": s.total_questions or 0,
            "correct_answers": s.correct_answers or 0,
            "total_score": float(s.total_score) if s.total_score else None,
            "theta_estimate": float(s.theta_estimate) if s.theta_estimate else None,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "completed_at": s.completed_at.isoformat() if s.completed_at else None,
        }
        for s in sessions
    ]

    return UserDashboard(
        user=UserOut(id=user.id, username=user.username, email=user.email),
        total_quizzes=len(sessions),
        total_questions_attempted=total_attempted,
        overall_accuracy=total_correct / total_attempted if total_attempted > 0 else 0,
        topic_progress=topic_progress,
        recent_sessions=recent,
    )


@user_router.get("/learning-path")
async def get_learning_path(
    subject_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lộ trình học đề xuất: sắp xếp topo trên đồ thị tiên quyết, ưu tiên
    củng cố kiến thức nền của các topic yếu trước khi học topic phụ thuộc."""
    from app.models.knowledge import TopicPrerequisite
    from app.models.cat_knowledge import KnowledgeGraph

    topics_result = await db.execute(
        select(Topic, MajorTopic)
        .join(MajorTopic, MajorTopic.id == Topic.major_topic_id)
        .where(MajorTopic.subject_id == subject_id)
        .order_by(MajorTopic.order_index.asc(), Topic.order_index.asc(), Topic.id.asc())
    )
    rows = topics_result.all()
    if not rows:
        raise HTTPException(status_code=404, detail="Subject has no topics")

    topic_info = {t.id: (t, mt) for t, mt in rows}
    ontology_order = {t.id: i for i, (t, _mt) in enumerate(rows)}
    topic_ids = set(topic_info)

    # Prerequisite edges: prereq -> dependent (learn prereq first)
    edges: set[tuple[int, int]] = set()
    prereq_rows = await db.execute(
        select(TopicPrerequisite).where(TopicPrerequisite.topic_id.in_(topic_ids))
    )
    for link in prereq_rows.scalars().all():
        if link.prerequisite_topic_id in topic_ids:
            edges.add((link.prerequisite_topic_id, link.topic_id))
    kg_rows = await db.execute(
        select(KnowledgeGraph)
        .where(KnowledgeGraph.subject_id == subject_id)
        .where(KnowledgeGraph.source_type == "topic")
        .where(KnowledgeGraph.target_type == "topic")
        .where(KnowledgeGraph.relation_type == "prerequisite")
    )
    for e in kg_rows.scalars().all():
        # source requires target (R12 semantics) -> learn target first
        if e.target_id in topic_ids and e.source_id in topic_ids:
            edges.add((int(e.target_id), int(e.source_id)))

    progress_rows = await db.execute(
        select(UserTopicProgress).where(
            UserTopicProgress.user_id == user.id,
            UserTopicProgress.topic_id.in_(topic_ids),
        )
    )
    progress = {p.topic_id: p for p in progress_rows.scalars().all()}

    def status_of(tid: int) -> str:
        p = progress.get(tid)
        if not p or not (p.questions_attempted or 0):
            return "not_started"
        level = (p.mastery_level or "").lower()
        if level in ("proficient", "master"):
            return "mastered"
        if level == "developing":
            return "in_progress"
        return "weak"

    status = {tid: status_of(tid) for tid in topic_ids}
    weak_topics = {tid for tid, s in status.items() if s == "weak"}
    prereq_of_weak = {a for a, b in edges if b in weak_topics and status[a] != "mastered"}

    # Kahn topological sort over non-mastered topics; ready nodes are picked
    # by priority (foundations of weak topics -> weak -> in-progress -> new)
    # then by ontology order.
    pending = {tid for tid, s in status.items() if s != "mastered"}
    graph_edges = [(a, b) for a, b in edges if a in pending and b in pending]
    indegree = {tid: 0 for tid in pending}
    for _a, b in graph_edges:
        indegree[b] += 1

    def priority(tid: int) -> int:
        if tid in prereq_of_weak:
            return 0
        if status[tid] == "weak":
            return 1
        if status[tid] == "in_progress":
            return 2
        return 3

    steps = []
    ready = [tid for tid in pending if indegree[tid] == 0]
    while ready:
        ready.sort(key=lambda t: (priority(t), ontology_order[t]))
        current = ready.pop(0)
        t, mt = topic_info[current]
        p = progress.get(current)
        prereq_names = [
            topic_info[a][0].name for a, b in edges if b == current and a in topic_ids
        ]

        s = status[current]
        if s == "weak":
            reason = "Tỷ lệ đúng thấp ở các bài thi gần đây — cần củng cố lại"
        elif current in prereq_of_weak:
            dependents = [topic_info[b][0].name for a, b in edges if a == current and b in weak_topics]
            reason = "Kiến thức nền của: " + ", ".join(dependents[:3])
        elif s == "in_progress":
            reason = "Đang tiến bộ — luyện thêm để đạt mức thành thạo"
        else:
            reason = "Chưa được đánh giá — học sau khi vững kiến thức nền"

        steps.append(
            {
                "order": len(steps) + 1,
                "topic_id": current,
                "code": t.code,
                "name": t.name,
                "major_topic_name": mt.name,
                "status": s,
                "theta": float(p.theta_estimate) if p and p.theta_estimate is not None else None,
                "mastery": p.mastery_level if p else None,
                "attempted": int(p.questions_attempted or 0) if p else 0,
                "correct": int(p.questions_correct or 0) if p else 0,
                "reason": reason,
                "prerequisite_names": prereq_names,
            }
        )
        for a, b in graph_edges:
            if a == current:
                indegree[b] -= 1
                if indegree[b] == 0:
                    ready.append(b)

    # Defensive: if the prerequisite graph has a cycle, append leftovers in
    # ontology order so no topic is silently dropped from the path.
    placed = {s["topic_id"] for s in steps}
    for tid in sorted(pending - placed, key=lambda t: ontology_order[t]):
        t, mt = topic_info[tid]
        p = progress.get(tid)
        steps.append(
            {
                "order": len(steps) + 1,
                "topic_id": tid,
                "code": t.code,
                "name": t.name,
                "major_topic_name": mt.name,
                "status": status[tid],
                "theta": float(p.theta_estimate) if p and p.theta_estimate is not None else None,
                "mastery": p.mastery_level if p else None,
                "attempted": int(p.questions_attempted or 0) if p else 0,
                "correct": int(p.questions_correct or 0) if p else 0,
                "reason": "Theo thứ tự chương trình học",
                "prerequisite_names": [],
            }
        )

    return {
        "subject_id": subject_id,
        "total_topics": len(topic_ids),
        "mastered_count": sum(1 for s in status.values() if s == "mastered"),
        "steps": steps,
    }


@user_router.get("/ability-prediction")
async def get_ability_prediction(
    subject_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """DKT prediction: P(correct next) per topic for the current user."""
    from app.services.dkt_service import predict_user_mastery

    try:
        return await predict_user_mastery(db, subject_id, user.id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="DKT model chưa được huấn luyện cho môn này. Gọi POST /api/quiz/dkt/train trước.",
        )
