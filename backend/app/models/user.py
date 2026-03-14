from sqlalchemy import Column, Integer, String, Numeric, Boolean, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(200))
    password_hash = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    quiz_sessions = relationship("QuizSession", back_populates="user", cascade="all, delete-orphan")
    topic_progress = relationship("UserTopicProgress", back_populates="user", cascade="all, delete-orphan")


class QuizSession(Base):
    __tablename__ = "quiz_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    total_score = Column(Numeric(5, 2))
    theta_estimate = Column(Numeric(5, 2))
    total_questions = Column(Integer, default=0)
    correct_answers = Column(Integer, default=0)

    user = relationship("User", back_populates="quiz_sessions")
    subject = relationship("Subject")
    responses = relationship("QuizResponse", back_populates="session", cascade="all, delete-orphan")


class QuizResponse(Base):
    __tablename__ = "quiz_responses"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("quiz_sessions.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    user_answer = Column(String(1))
    is_correct = Column(Boolean, nullable=False)
    guessing_flag = Column(Boolean, nullable=False, default=False)
    time_spent_seconds = Column(Integer)
    answered_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("QuizSession", back_populates="responses")
    question = relationship("Question", back_populates="responses")


class UserTopicProgress(Base):
    __tablename__ = "user_topic_progress"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=False)
    theta_estimate = Column(Numeric(5, 2), default=0)
    questions_attempted = Column(Integer, default=0)
    questions_correct = Column(Integer, default=0)
    mastery_level = Column(String(20), default="beginner")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="topic_progress")
    topic = relationship("Topic")

    __table_args__ = (
        UniqueConstraint("user_id", "topic_id", name="uq_user_topic"),
    )


class InferenceRuleLog(Base):
    __tablename__ = "inference_rule_logs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("quiz_sessions.id"), nullable=False)
    response_id = Column(Integer, ForeignKey("quiz_responses.id"))
    question_id = Column(Integer, ForeignKey("questions.id"))
    rule_code = Column(String(20), nullable=False)
    reason = Column(String(500), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
