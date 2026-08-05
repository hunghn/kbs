"""Test harness: in-memory SQLite + a minimal app carrying only the router
under test, so the suite runs without PostgreSQL or the startup migrations.
"""
import asyncio
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base, get_db  # noqa: E402
from app.api.auth import get_current_user  # noqa: E402
from app.api import questions as questions_api  # noqa: E402
from app.models.knowledge import MajorTopic, Subject, Topic  # noqa: E402
from app.models.question import Question  # noqa: E402
from app.models.user import QuizResponse, QuizSession, User  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def seeded(session_factory):
    """One subject -> one major topic -> two topics, plus a user."""
    async with session_factory() as session:
        subject = Subject(name="Toán rời rạc")
        session.add(subject)
        await session.flush()

        major = MajorTopic(subject_id=subject.id, code="1", name="Logic", order_index=0)
        session.add(major)
        await session.flush()

        topic_a = Topic(major_topic_id=major.id, code="1.1", name="Logic mệnh đề", order_index=0)
        topic_b = Topic(major_topic_id=major.id, code="1.2", name="Tập hợp", order_index=1)
        user = User(username="teacher", email="t@example.com", password_hash="x")
        session.add_all([topic_a, topic_b, user])
        await session.commit()

        return {
            "subject_id": subject.id,
            "topic_a": topic_a.id,
            "topic_b": topic_b.id,
            "user_id": user.id,
        }


@pytest_asyncio.fixture
async def client(session_factory, seeded):
    app = FastAPI()
    app.include_router(questions_api.router)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    async def override_get_current_user():
        async with session_factory() as session:
            return await session.get(User, seeded["user_id"])

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


@pytest_asyncio.fixture
async def answered_question(session_factory, seeded):
    """A question that already has a graded response attached."""
    async with session_factory() as session:
        question = Question(
            external_id="HIST01",
            topic_id=seeded["topic_a"],
            stem="Câu đã có lịch sử",
            question_format="mcq",
            option_a="A",
            option_b="B",
            option_c="C",
            option_d="D",
            correct_answer="A",
            difficulty_b=0.0,
            discrimination_a=1.0,
            guessing_c=0.25,
            question_type="Thông hiểu",
            time_limit_seconds=60,
            time_display="01:00",
        )
        quiz = QuizSession(user_id=seeded["user_id"], subject_id=seeded["subject_id"])
        session.add_all([question, quiz])
        await session.flush()
        session.add(
            QuizResponse(
                session_id=quiz.id,
                question_id=question.id,
                user_answer="A",
                is_correct=True,
            )
        )
        await session.commit()
        return question.id
