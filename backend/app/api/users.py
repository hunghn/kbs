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
