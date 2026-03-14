from pydantic import BaseModel
from typing import Optional


class UserCreate(BaseModel):
    username: str
    email: Optional[str] = None
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[str] = None

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TopicProgressOut(BaseModel):
    topic_id: int
    topic_name: str
    major_topic_name: str
    theta_estimate: float = 0
    questions_attempted: int = 0
    questions_correct: int = 0
    mastery_level: str = "beginner"

    class Config:
        from_attributes = True


class UserDashboard(BaseModel):
    user: UserOut
    total_quizzes: int = 0
    total_questions_attempted: int = 0
    overall_accuracy: float = 0
    topic_progress: list[TopicProgressOut] = []
    recent_sessions: list = []
