from sqlalchemy import Column, Integer, String, Text, Numeric, Boolean, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class LearnerProfile(Base):
    """Hồ sơ cá nhân hóa: lịch rảnh trong tuần của người học."""
    __tablename__ = "learner_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    # JSON: [{"day": 0-6 (0=Thứ 2), "slot": "sang"|"chieu"|"toi"}, ...]
    availability = Column(Text, nullable=False, default="[]")
    onboarded = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")


class StudyPlan(Base):
    """Lộ trình học một môn: mục tiêu + dự phóng validate + trạng thái."""
    __tablename__ = "study_plans"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    goal_theta = Column(Numeric(5, 2), nullable=False)          # θ mục tiêu
    goal_label = Column(String(30), nullable=False)              # Khá/Giỏi/Xuất sắc
    target_weeks = Column(Integer, nullable=False, default=8)
    start_theta = Column(Numeric(5, 2))                          # θ đầu vào (placement)
    status = Column(String(20), nullable=False, default="active")  # active | replaced | done
    # JSON dự phóng: {"feasible": bool, "projected_weekly": [...], "notes": ...}
    projection = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")
    subject = relationship("Subject")
    items = relationship(
        "StudyPlanItem",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="StudyPlanItem.week_index, StudyPlanItem.order_in_week",
    )


class StudyPlanItem(Base):
    """Một buổi học trong lộ trình: tuần + thứ + buổi + hoạt động."""
    __tablename__ = "study_plan_items"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("study_plans.id"), nullable=False)
    week_index = Column(Integer, nullable=False)                 # 1-based
    order_in_week = Column(Integer, nullable=False, default=0)
    day_of_week = Column(Integer, nullable=False)                # 0=Thứ 2 ... 6=CN
    slot = Column(String(10), nullable=False)                    # sang | chieu | toi
    activity = Column(String(20), nullable=False, default="practice")  # practice | review | mock_exam
    topic_id = Column(Integer, ForeignKey("topics.id"))          # NULL với mock_exam
    status = Column(String(20), nullable=False, default="pending")  # pending | done | skipped
    session_id = Column(Integer, ForeignKey("quiz_sessions.id"))
    result_score = Column(Integer)
    result_total = Column(Integer)
    completed_at = Column(DateTime(timezone=True))

    plan = relationship("StudyPlan", back_populates="items")
    topic = relationship("Topic")

    __table_args__ = (
        UniqueConstraint("plan_id", "week_index", "order_in_week", name="uq_plan_item_slot"),
    )
