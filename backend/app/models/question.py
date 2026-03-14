from sqlalchemy import Column, Integer, String, Text, Numeric, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.database import Base


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
    time_limit_seconds = Column(Integer, nullable=False)
    time_display = Column(String(10))
    is_archived = Column(Boolean, nullable=False, default=False)

    topic = relationship("Topic", back_populates="questions")
    responses = relationship("QuizResponse", back_populates="question")
