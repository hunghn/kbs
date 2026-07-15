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
    # mcq | true_false | short_answer | matching
    question_format: str = "mcq"
    matching_left: list[str] = []
    matching_right: list[str] = []  # shuffled — never reveals the pairing
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
    answer_text: Optional[str] = None       # short_answer reference
    matching_pairs: list[dict] = []          # matching solution


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
    chain_id: Optional[int] = None
    exam_index: Optional[int] = None

    class Config:
        from_attributes = True


# ---------- Exam-batch adaptive testing (multi-stage) ----------

class AdaptiveStartConfig(BaseModel):
    subject_id: int
    questions_per_exam: int = 20
    max_exams: int = 5
    # Distribution: Nhận biết, Thông hiểu, Vận dụng (used by exam #1 blueprint)
    recognition_pct: float = 0.3
    comprehension_pct: float = 0.5
    application_pct: float = 0.2
    # "rules": R2/R3 steer difficulty; "rl": contextual bandit learns the offset
    strategy: str = "rules"


class AdaptiveExamOut(BaseModel):
    chain_id: int
    session_id: int
    exam_index: int
    max_exams: int
    questions_per_exam: int
    questions: list[QuestionOut] = []
    theta: float = 0.0
    sem: float = 999.0
    applied_rules: list[str] = []  # generation-time rules for this exam
    strategy: str = "rules"


class AdaptiveSubmitIn(BaseModel):
    session_id: int
    answers: list[AnswerSubmit] = []


class ExamEvaluationOut(BaseModel):
    chain_id: int
    session_id: int
    exam_index: int
    max_exams: int
    score: int
    total: int
    accuracy: float
    theta: float  # cumulative over the whole chain
    sem: float
    theta_history: list[float] = []
    applied_rules: list[str] = []  # grading-time rules (R7, BLOOM)
    topic_scores: dict[str, dict] = {}
    bloom_classification: Optional[str] = None
    recommendations: list[LearningRecommendation] = []
    chain_completed: bool = False
    stop_reason: Optional[str] = None


class ChainExamRow(BaseModel):
    session_id: int
    exam_index: int
    score: int = 0
    total: int = 0
    accuracy: float = 0.0
    theta_after: Optional[float] = None
    completed: bool = False


class ChainSummaryOut(BaseModel):
    chain_id: int
    subject_id: int
    subject_name: str = ""
    status: str
    stop_reason: Optional[str] = None
    theta: float = 0.0
    sem: float = 999.0
    total_questions: int = 0
    total_correct: int = 0
    theta_history: list[float] = []
    exams: list[ChainExamRow] = []
    topic_scores: dict[str, dict] = {}
    bloom_classification: Optional[str] = None
    recommendations: list[LearningRecommendation] = []


class ChainStateOut(BaseModel):
    chain_id: int
    status: str
    stop_reason: Optional[str] = None
    exam_index: int = 0
    max_exams: int = 5
    theta: float = 0.0
    sem: float = 999.0
    active_exam: Optional[AdaptiveExamOut] = None  # unsubmitted exam, if any


class QuizResultDetail(BaseModel):
    question: QuestionWithAnswer
    user_answer: Optional[str] = None
    user_answer_text: Optional[str] = None  # non-MCQ formats
    is_correct: bool
    time_spent_seconds: int = 0


class QuizResultOut(BaseModel):
    session: QuizSessionOut
    results: list[QuizResultDetail] = []
    topic_scores: dict[str, dict] = {}  # topic_name -> {correct, total, mastery}
    accuracy: float = 0.0
    sem: Optional[float] = None
    answered_count: int = 0
    bloom_classification: Optional[str] = None
