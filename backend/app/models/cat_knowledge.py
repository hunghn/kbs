from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, UniqueConstraint, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class KnowledgeGraph(Base):
    """Generic knowledge graph edge: parent-child or prerequisite."""

    __tablename__ = "knowledge_graph"

    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    source_type = Column(String(30), nullable=False)
    source_id = Column(Integer, nullable=False)
    target_type = Column(String(30), nullable=False)
    target_id = Column(Integer, nullable=False)
    relation_type = Column(String(30), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "subject_id",
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relation_type",
            name="uq_knowledge_graph_edge",
        ),
    )


class UserAbility(Base):
    """User theta tracking at subject level."""

    __tablename__ = "user_ability"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    theta_estimate = Column(Numeric(6, 3), default=0)
    sem = Column(Numeric(6, 3), default=999)
    answered_count = Column(Integer, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    subject = relationship("Subject")

    __table_args__ = (
        UniqueConstraint("user_id", "subject_id", name="uq_user_subject_ability"),
    )
