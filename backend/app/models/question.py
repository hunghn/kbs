from sqlalchemy import Column, Integer, String, Text, Numeric, ForeignKey, Boolean, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class PresetExam(Base):
    """Đề thi có sẵn: bộ câu hỏi cố định, phân bổ đủ mức Bloom và phủ topic."""
    __tablename__ = "preset_exams"

    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    question_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    subject = relationship("Subject")
    items = relationship(
        "PresetExamQuestion",
        back_populates="preset",
        cascade="all, delete-orphan",
        order_by="PresetExamQuestion.position",
    )


class PresetExamQuestion(Base):
    __tablename__ = "preset_exam_questions"

    id = Column(Integer, primary_key=True, index=True)
    preset_id = Column(Integer, ForeignKey("preset_exams.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    position = Column(Integer, nullable=False, default=0)

    preset = relationship("PresetExam", back_populates="items")
    question = relationship("Question")

    __table_args__ = (
        UniqueConstraint("preset_id", "question_id", name="uq_preset_question"),
    )


class Question(Base):
    """Ngân hàng câu hỏi với tham số IRT"""
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(20), unique=True, nullable=False, index=True)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=False)
    stem = Column(Text, nullable=False)
    option_a = Column(Text, nullable=False)
    option_b = Column(Text, nullable=False)
    option_c = Column(Text, nullable=False)
    option_d = Column(Text, nullable=False)
    correct_answer = Column(String(1), nullable=False)
    difficulty_b = Column(Numeric(4, 2), nullable=False)
    discrimination_a = Column(Numeric(4, 2), nullable=False)
    guessing_c = Column(Numeric(4, 2), nullable=False)
    question_type = Column(String(50), nullable=False)  # Nhận biết, Thông hiểu, Vận dụng
    # mcq | true_false | short_answer | matching
    question_format = Column(String(20), nullable=False, default="mcq")
    # short_answer: reference answer, aliases separated by "|"
    answer_text = Column(Text)
    # matching: JSON list [{"left": ..., "right": ...}, ...]
    matching_pairs = Column(Text)
    time_limit_seconds = Column(Integer, nullable=False)
    time_display = Column(String(10))
    is_archived = Column(Boolean, nullable=False, default=False)

    topic = relationship("Topic", back_populates="questions")
    responses = relationship("QuizResponse", back_populates="question")
