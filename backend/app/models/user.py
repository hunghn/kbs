from sqlalchemy import Column, Integer, String, Text, Numeric, Boolean, ForeignKey, DateTime, UniqueConstraint
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


class ExamChain(Base):
    """Chuỗi đề thi thích ứng: mỗi lần thi gồm nhiều đề (QuizSession) nối tiếp."""
    __tablename__ = "exam_chains"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    questions_per_exam = Column(Integer, nullable=False, default=20)
    max_exams = Column(Integer, nullable=False, default=5)
    recognition_pct = Column(Numeric(4, 3), nullable=False, default=0.3)
    comprehension_pct = Column(Numeric(4, 3), nullable=False, default=0.5)
    application_pct = Column(Numeric(4, 3), nullable=False, default=0.2)
    status = Column(String(20), nullable=False, default="active")  # active | completed
    stop_reason = Column(String(100))
    strategy = Column(String(10), nullable=False, default="rules")  # rules | rl
    rl_state = Column(String(40))   # pending bandit decision awaiting reward
    rl_action = Column(Integer)
    # Warm-start: informative EAP prior from UserAbility + DKT (NULL = cold start)
    prior_theta = Column(Numeric(6, 3))
    current_theta = Column(Numeric(6, 3), default=0)
    current_sem = Column(Numeric(6, 3), default=999)
    exams_generated = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))

    user = relationship("User")
    subject = relationship("Subject")
    sessions = relationship("QuizSession", back_populates="chain")


class QuizSession(Base):
    __tablename__ = "quiz_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    chain_id = Column(Integer, ForeignKey("exam_chains.id"), nullable=True)
    exam_index = Column(Integer, nullable=True)  # 1-based within the chain
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    total_score = Column(Numeric(5, 2))
    theta_estimate = Column(Numeric(5, 2))
    total_questions = Column(Integer, default=0)
    correct_answers = Column(Integer, default=0)

    user = relationship("User", back_populates="quiz_sessions")
    subject = relationship("Subject")
    chain = relationship("ExamChain", back_populates="sessions")
    responses = relationship("QuizResponse", back_populates="session", cascade="all, delete-orphan")


class QuizResponse(Base):
    __tablename__ = "quiz_responses"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("quiz_sessions.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    user_answer = Column(String(1))
    # Full answer for non-MCQ formats (short answer text / matching JSON)
    answer_text = Column(Text)
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
