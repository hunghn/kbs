from pydantic import BaseModel
from typing import Optional


class TopicBase(BaseModel):
    code: Optional[str] = None
    name: str
    order_index: int = 0


class TopicOut(TopicBase):
    id: int
    major_topic_id: int
    question_count: int = 0

    class Config:
        from_attributes = True


class MajorTopicBase(BaseModel):
    code: Optional[str] = None
    name: str
    order_index: int = 0


class MajorTopicOut(MajorTopicBase):
    id: int
    subject_id: int
    topics: list[TopicOut] = []

    class Config:
        from_attributes = True


class SubjectBase(BaseModel):
    name: str
    description: Optional[str] = None


class SubjectOut(SubjectBase):
    id: int
    major_topics: list[MajorTopicOut] = []

    class Config:
        from_attributes = True


class SubjectSummary(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    total_questions: int = 0
    total_topics: int = 0

    class Config:
        from_attributes = True


class KnowledgeTreeOut(BaseModel):
    """Full ontology tree for a subject"""
    subject: SubjectOut
