from pydantic import BaseModel
from typing import Optional


class QuestionOut(BaseModel):
    id: int
    external_id: str
    stem: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    question_type: str
    time_limit_seconds: int
    time_display: Optional[str] = None
    is_archived: bool = False
    topic_name: str = ""
    major_topic_name: str = ""

    class Config:
        from_attributes = True


class QuestionManageBase(BaseModel):
    topic_id: int
    stem: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str
    difficulty_b: float
    discrimination_a: float
    guessing_c: float
    question_type: str
    time_limit_seconds: int
    time_display: Optional[str] = None


class QuestionCreate(QuestionManageBase):
    external_id: str


class QuestionUpdate(BaseModel):
    external_id: Optional[str] = None
    topic_id: Optional[int] = None
    stem: Optional[str] = None
    option_a: Optional[str] = None
    option_b: Optional[str] = None
    option_c: Optional[str] = None
    option_d: Optional[str] = None
    correct_answer: Optional[str] = None
    difficulty_b: Optional[float] = None
    discrimination_a: Optional[float] = None
    guessing_c: Optional[float] = None
    question_type: Optional[str] = None
    time_limit_seconds: Optional[int] = None
    time_display: Optional[str] = None
    is_archived: Optional[bool] = None


class QuestionManageOut(BaseModel):
    id: int
    external_id: str
    topic_id: int
    topic_name: str
    major_topic_name: str
    stem: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str
    difficulty_b: float
    discrimination_a: float
    guessing_c: float
    question_type: str
    time_limit_seconds: int
    time_display: Optional[str] = None
    is_archived: bool = False


class QuestionManageListOut(BaseModel):
    items: list[QuestionManageOut]
    total: int
    skip: int
    limit: int


class QuestionWithAnswer(QuestionOut):
    correct_answer: str
    difficulty_b: float
    discrimination_a: float
    guessing_c: float


class AnswerSubmit(BaseModel):
    question_id: int
    user_answer: str
    time_spent_seconds: int = 0


class QuizConfig(BaseModel):
    subject_id: int
    num_questions: int = 20
    # Distribution: Nhận biết, Thông hiểu, Vận dụng
    recognition_pct: float = 0.3
    comprehension_pct: float = 0.5
    application_pct: float = 0.2
    topic_ids: Optional[list[int]] = None  # Filter by specific topics


class CATAnswerSubmit(BaseModel):
    question_id: int
    user_answer: str
    time_spent_seconds: int = 0


class LearningRecommendation(BaseModel):
    topic_id: int
    topic_name: str
    prerequisite_topic_id: Optional[int] = None
    prerequisite_topic_name: Optional[str] = None
    reason: str


class InferenceRuleLogOut(BaseModel):
    id: int
    session_id: int
    response_id: Optional[int] = None
    step_index: Optional[int] = None
    question_id: Optional[int] = None
    question_external_id: Optional[str] = None
    question_stem: Optional[str] = None
    rule_code: str
    reason: str
    answered_at: Optional[str] = None
    created_at: Optional[str] = None


class CATStepOut(BaseModel):
    session_id: int
    question: Optional[QuestionOut] = None
    theta: float
    sem: float
    answered_count: int
    max_questions: int
    is_completed: bool
    stop_reason: Optional[str] = None
    bloom_classification: Optional[str] = None
    applied_rules: list[str] = []
    theta_history: list[float] = []
    recommendations: list[LearningRecommendation] = []


class LLMGenerateRequest(BaseModel):
    topic_id: int
    knowledge_context: Optional[str] = None
    target_level: str = "Thông hiểu"


class GeneratedQuestionOut(BaseModel):
    stem: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str
    difficulty_b: float
    discrimination_a: float
    guessing_c: float
    explanation: str
    generation_source: str = "fallback"
    llm_model: Optional[str] = None


class CalibrationBin(BaseModel):
    bucket: str
    count: int
    avg_b: float
    observed_accuracy: float


class CalibrationReport(BaseModel):
    total_responses: int
    bins: list[CalibrationBin]


class QuizSessionOut(BaseModel):
    id: int
    subject_id: int
    subject_name: str = ""
    total_questions: int = 0
    correct_answers: int = 0
    total_score: Optional[float] = None
    theta_estimate: Optional[float] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    class Config:
        from_attributes = True


class QuizResultDetail(BaseModel):
    question: QuestionWithAnswer
    user_answer: Optional[str] = None
    is_correct: bool
    time_spent_seconds: int = 0


class QuizResultOut(BaseModel):
    session: QuizSessionOut
    results: list[QuizResultDetail] = []
    topic_scores: dict[str, dict] = {}  # topic_name -> {correct, total, mastery}
