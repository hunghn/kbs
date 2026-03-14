from sqlalchemy import Column, Integer, String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base


class Subject(Base):
    """Môn học (e.g., Toán rời rạc, Cơ sở dữ liệu SQL)"""
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text)

    major_topics = relationship("MajorTopic", back_populates="subject", cascade="all, delete-orphan")


class MajorTopic(Base):
    """Chủ đề lớn (e.g., 1. Logic & Lý thuyết Tập hợp)"""
    __tablename__ = "major_topics"

    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    code = Column(String(10))
    name = Column(String(200), nullable=False)
    order_index = Column(Integer, default=0)

    subject = relationship("Subject", back_populates="major_topics")
    topics = relationship("Topic", back_populates="major_topic", cascade="all, delete-orphan")


class Topic(Base):
    """Kiến thức liên quan / Chủ đề con (e.g., 1.1 Logic mệnh đề & Vị từ)"""
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, index=True)
    major_topic_id = Column(Integer, ForeignKey("major_topics.id"), nullable=False)
    code = Column(String(20))
    name = Column(String(200), nullable=False)
    order_index = Column(Integer, default=0)

    major_topic = relationship("MajorTopic", back_populates="topics")
    questions = relationship("Question", back_populates="topic", cascade="all, delete-orphan")
    prerequisites = relationship(
        "TopicPrerequisite",
        foreign_keys="TopicPrerequisite.topic_id",
        back_populates="topic",
        cascade="all, delete-orphan",
    )


class TopicPrerequisite(Base):
    """Quan hệ tiên quyết giữa các Topic"""
    __tablename__ = "topic_prerequisites"

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=False)
    prerequisite_topic_id = Column(Integer, ForeignKey("topics.id"), nullable=False)

    topic = relationship("Topic", foreign_keys=[topic_id], back_populates="prerequisites")
    prerequisite = relationship("Topic", foreign_keys=[prerequisite_topic_id])

    __table_args__ = (
        UniqueConstraint("topic_id", "prerequisite_topic_id", name="uq_topic_prerequisite"),
    )
