/**
 * API client for KBS backend.
 */

const API_BASE = "/api";

async function fetchAPI<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("kbs_token") : null;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || "API error");
  }

  return res.json();
}

// Auth
export const authAPI = {
  register: (data: { username: string; email?: string; password: string }) =>
    fetchAPI<{ id: number; username: string }>("/auth/register", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  login: (data: { username: string; password: string }) =>
    fetchAPI<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  me: () => fetchAPI<{ id: number; username: string; email?: string }>("/auth/me"),
};

// Knowledge
export const knowledgeAPI = {
  getSubjects: () =>
    fetchAPI<SubjectSummary[]>("/knowledge/subjects"),

  getKnowledgeTree: (subjectId: number) =>
    fetchAPI<{ subject: SubjectTree }>(`/knowledge/subjects/${subjectId}/tree`),

  getTopics: (subjectId?: number) =>
    fetchAPI<TopicInfo[]>(`/knowledge/topics${subjectId ? `?subject_id=${subjectId}` : ""}`),

  getAbilityGraph: (subjectId: number) =>
    fetchAPI<AbilityGraphInfo>(`/knowledge/subjects/${subjectId}/ability-graph`),
};

// Quiz
export const quizAPI = {
  start: (config: QuizConfig) =>
    fetchAPI<QuizSessionInfo>("/quiz/start", {
      method: "POST",
      body: JSON.stringify(config),
    }),

  getQuestions: (sessionId: number) =>
    fetchAPI<QuestionInfo[]>(`/quiz/${sessionId}/questions`),

  submit: (sessionId: number, answers: AnswerSubmit[]) =>
    fetchAPI<QuizSubmitResult>(`/quiz/${sessionId}/submit`, {
      method: "POST",
      body: JSON.stringify(answers),
    }),

  getResults: (sessionId: number) =>
    fetchAPI<QuizResultInfo>(`/quiz/${sessionId}/results`),

  getRuleLogs: (sessionId: number) =>
    fetchAPI<InferenceRuleLogInfo[]>(`/quiz/${sessionId}/rule-logs`),

  getExplanation: (sessionId: number) =>
    fetchAPI<ExplanationInfo>(`/quiz/${sessionId}/explanation`),

  generateQuestion: (payload: {
    topic_id: number;
    knowledge_context?: string;
    target_level: string;
  }) =>
    fetchAPI<GeneratedQuestionInfo>("/quiz/generate-question", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

// Exam-batch adaptive testing (multi-stage)
export const adaptiveAPI = {
  start: (config: AdaptiveStartConfig) =>
    fetchAPI<AdaptiveExamInfo>("/quiz/adaptive/start", {
      method: "POST",
      body: JSON.stringify(config),
    }),

  submit: (chainId: number, payload: { session_id: number; answers: AnswerSubmit[] }) =>
    fetchAPI<ExamEvaluationInfo>(`/quiz/adaptive/${chainId}/submit`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  next: (chainId: number) =>
    fetchAPI<ChainStateInfo>(`/quiz/adaptive/${chainId}/next`, {
      method: "POST",
    }),

  finish: (chainId: number) =>
    fetchAPI<ChainSummaryInfo>(`/quiz/adaptive/${chainId}/finish`, {
      method: "POST",
    }),

  getState: (chainId: number) =>
    fetchAPI<ChainStateInfo>(`/quiz/adaptive/${chainId}`),

  getSummary: (chainId: number) =>
    fetchAPI<ChainSummaryInfo>(`/quiz/adaptive/${chainId}/summary`),
};

// System evaluation (convergence simulation)
export const evaluationAPI = {
  convergence: (params: {
    subject_id: number;
    n_students?: number;
    questions_per_exam?: number;
    max_exams?: number;
    seed?: number;
    include_rl?: boolean;
  }) => {
    const query = new URLSearchParams({ subject_id: String(params.subject_id) });
    if (params.n_students) query.set("n_students", String(params.n_students));
    if (params.questions_per_exam) query.set("questions_per_exam", String(params.questions_per_exam));
    if (params.max_exams) query.set("max_exams", String(params.max_exams));
    if (params.seed) query.set("seed", String(params.seed));
    if (params.include_rl) query.set("include_rl", "true");
    return fetchAPI<ConvergenceReportInfo>(`/quiz/evaluation/convergence?${query.toString()}`);
  },
};

// Users
export const userAPI = {
  getDashboard: () => fetchAPI<DashboardInfo>("/users/dashboard"),

  getAbilityPrediction: (subjectId: number) =>
    fetchAPI<DKTPredictionInfo>(`/users/ability-prediction?subject_id=${subjectId}`),
};

// Admin
export const adminAPI = {
  getLLMSettings: () =>
    fetchAPI<LLMRuntimeConfigInfo>("/admin/settings/llm"),

  updateLLMSettings: (payload: LLMRuntimeConfigUpdatePayload) =>
    fetchAPI<LLMRuntimeConfigInfo>("/admin/settings/llm", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
};

// Questions management
export const questionsAPI = {
  list: (params: {
    subject_id?: number;
    topic_id?: number;
    search?: string;
    include_archived?: boolean;
    skip?: number;
    limit?: number;
  } = {}) => {
    const query = new URLSearchParams();
    if (params.subject_id !== undefined) query.set("subject_id", String(params.subject_id));
    if (params.topic_id !== undefined) query.set("topic_id", String(params.topic_id));
    if (params.search) query.set("search", params.search);
    if (params.include_archived !== undefined) query.set("include_archived", String(params.include_archived));
    if (params.skip !== undefined) query.set("skip", String(params.skip));
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return fetchAPI<QuestionManageListInfo>(`/questions${suffix}`);
  },

  getById: (questionId: number) =>
    fetchAPI<QuestionManageItem>(`/questions/${questionId}`),

  create: (payload: QuestionCreatePayload) =>
    fetchAPI<QuestionManageItem>("/questions", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  update: (questionId: number, payload: QuestionUpdatePayload) =>
    fetchAPI<QuestionManageItem>(`/questions/${questionId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  remove: (questionId: number) =>
    fetchAPI<{ message: string; id: number }>(`/questions/${questionId}`, {
      method: "DELETE",
    }),

  archive: (questionId: number) =>
    fetchAPI<QuestionManageItem>(`/questions/${questionId}/archive`, {
      method: "POST",
    }),

  unarchive: (questionId: number) =>
    fetchAPI<QuestionManageItem>(`/questions/${questionId}/unarchive`, {
      method: "POST",
    }),
};

// Types
export interface SubjectSummary {
  id: number;
  name: string;
  description?: string;
  total_questions: number;
  total_topics: number;
}

export interface TopicInfo {
  id: number;
  major_topic_id: number;
  code?: string;
  name: string;
  order_index: number;
  question_count: number;
}

export interface SubjectTree {
  id: number;
  name: string;
  description?: string;
  major_topics: {
    id: number;
    code?: string;
    name: string;
    topics: TopicInfo[];
  }[];
}

export interface AbilityGraphNode {
  id: number;
  code?: string;
  name: string;
  major_topic_id: number;
  major_topic_name: string;
  major_topic_order: number;
  order_index: number;
  question_count: number;
  theta?: number | null;
  mastery?: string | null;
  attempted: number;
  correct: number;
}

export interface AbilityGraphEdge {
  from: number;
  to: number;
  type: "prerequisite" | "inference";
}

export interface AbilityGraphInfo {
  subject_id: number;
  subject_name: string;
  nodes: AbilityGraphNode[];
  edges: AbilityGraphEdge[];
}

export interface QuizConfig {
  subject_id: number;
  num_questions: number;
  recognition_pct: number;
  comprehension_pct: number;
  application_pct: number;
  topic_ids?: number[];
}

export interface QuizSessionInfo {
  id: number;
  subject_id: number;
  total_questions: number;
}

export interface QuestionInfo {
  id: number;
  external_id: string;
  stem: string;
  option_a: string;
  option_b: string;
  option_c: string;
  option_d: string;
  question_type: string;
  time_limit_seconds: number;
  time_display?: string;
  topic_name: string;
  major_topic_name: string;
}

export interface AnswerSubmit {
  question_id: number;
  user_answer: string;
  time_spent_seconds: number;
}

export interface LearningRecommendation {
  topic_id: number;
  topic_name: string;
  prerequisite_topic_id?: number;
  prerequisite_topic_name?: string;
  reason: string;
}

export interface AdaptiveStartConfig {
  subject_id: number;
  questions_per_exam: number;
  max_exams: number;
  recognition_pct: number;
  comprehension_pct: number;
  application_pct: number;
  strategy?: "rules" | "rl";
}

export interface AdaptiveExamInfo {
  chain_id: number;
  session_id: number;
  exam_index: number;
  max_exams: number;
  questions_per_exam: number;
  questions: QuestionInfo[];
  theta: number;
  sem: number;
  applied_rules: string[];
  strategy?: string;
}

export interface ExamEvaluationInfo {
  chain_id: number;
  session_id: number;
  exam_index: number;
  max_exams: number;
  score: number;
  total: number;
  accuracy: number;
  theta: number;
  sem: number;
  theta_history: number[];
  applied_rules: string[];
  topic_scores: Record<string, { correct: number; total: number; accuracy: number; theta: number; mastery: string }>;
  bloom_classification?: string;
  recommendations: LearningRecommendation[];
  chain_completed: boolean;
  stop_reason?: string;
}

export interface ChainExamRowInfo {
  session_id: number;
  exam_index: number;
  score: number;
  total: number;
  accuracy: number;
  theta_after?: number;
  completed: boolean;
}

export interface ChainSummaryInfo {
  chain_id: number;
  subject_id: number;
  subject_name: string;
  status: string;
  stop_reason?: string;
  theta: number;
  sem: number;
  total_questions: number;
  total_correct: number;
  theta_history: number[];
  exams: ChainExamRowInfo[];
  topic_scores: Record<string, { correct: number; total: number; accuracy: number; theta: number; mastery: string }>;
  bloom_classification?: string;
  recommendations: LearningRecommendation[];
}

export interface DKTPredictionInfo {
  subject_id: number;
  history_length: number;
  predictions: {
    topic_id: number;
    code?: string | null;
    topic_name: string;
    major_topic_name: string;
    p_correct_next: number;
    attempted: number;
    correct: number;
  }[];
}

export interface ExplanationQuestionInfo {
  question_id: number;
  external_id: string;
  order: number;
  topic_name: string;
  question_type: string;
  difficulty_b: number;
  difficulty_level: string;
  is_correct: boolean;
  guessing_flag: boolean;
  delta_theta: number;
  fisher_information: number;
  information_share: number;
}

export interface ExplanationInfo {
  session_id: number;
  theta: number;
  sem: number;
  mastery: string;
  theta_history: number[];
  sem_history: number[];
  questions: ExplanationQuestionInfo[];
  bloom_stats: Record<string, { total: number; correct: number; accuracy: number }>;
  difficulty_stats: Record<string, { total: number; correct: number; accuracy: number }>;
  narrative: string[];
}

export interface ConvergenceStrategyInfo {
  strategy: string;
  n_students: number;
  bias: number;
  rmse: number;
  mae: number;
  correlation: number;
  convergence_rate: number;
  mean_items_used: number;
  mean_items_to_converge?: number | null;
  mean_sem_by_exam: number[];
  students: {
    true_theta: number;
    theta_hat: number;
    error: number;
    items_used: number;
    converged: boolean;
    final_sem: number;
  }[];
}

export interface ConvergenceReportInfo {
  subject_id: number;
  n_students: number;
  questions_per_exam: number;
  max_exams: number;
  sem_stop: number;
  pool_size: number;
  strategies: ConvergenceStrategyInfo[];
}

export interface ChainStateInfo {
  chain_id: number;
  status: string;
  stop_reason?: string;
  exam_index: number;
  max_exams: number;
  theta: number;
  sem: number;
  active_exam?: AdaptiveExamInfo;
}

export interface InferenceRuleLogInfo {
  id: number;
  session_id: number;
  response_id?: number;
  step_index?: number;
  question_id?: number;
  question_external_id?: string;
  question_stem?: string;
  rule_code: string;
  reason: string;
  answered_at?: string;
  created_at?: string;
}

export interface GeneratedQuestionInfo {
  stem: string;
  option_a: string;
  option_b: string;
  option_c: string;
  option_d: string;
  correct_answer: string;
  difficulty_b: number;
  discrimination_a: number;
  guessing_c: number;
  explanation: string;
  generation_source: string;
  llm_model?: string | null;
}

export interface LLMRuntimeConfigInfo {
  llm_enabled: boolean;
  cat_enable_hybrid_llm_on_answer: boolean;
  has_llm_api_key: boolean;
  llm_system_prompt: string;
  llm_base_url: string;
  llm_model: string;
  llm_temperature: number;
  llm_timeout_seconds: number;
}

export interface LLMRuntimeConfigUpdatePayload {
  llm_enabled: boolean;
  cat_enable_hybrid_llm_on_answer: boolean;
  llm_api_key?: string;
  llm_system_prompt: string;
  llm_base_url: string;
  llm_model: string;
  llm_temperature: number;
  llm_timeout_seconds: number;
}

export interface QuestionManageBase {
  topic_id: number;
  stem: string;
  option_a: string;
  option_b: string;
  option_c: string;
  option_d: string;
  correct_answer: string;
  difficulty_b: number;
  discrimination_a: number;
  guessing_c: number;
  question_type: string;
  time_limit_seconds: number;
  time_display?: string;
}

export interface QuestionCreatePayload extends QuestionManageBase {
  external_id: string;
}

export type QuestionUpdatePayload = Partial<QuestionCreatePayload>;

export interface QuestionManageItem {
  id: number;
  external_id: string;
  topic_id: number;
  topic_name: string;
  major_topic_name: string;
  stem: string;
  option_a: string;
  option_b: string;
  option_c: string;
  option_d: string;
  correct_answer: string;
  difficulty_b: number;
  discrimination_a: number;
  guessing_c: number;
  question_type: string;
  time_limit_seconds: number;
  time_display?: string;
  is_archived: boolean;
}

export interface QuestionManageListInfo {
  items: QuestionManageItem[];
  total: number;
  skip: number;
  limit: number;
}

export interface QuizSubmitResult {
  message: string;
  score: number;
  total: number;
  accuracy: number;
  theta: number;
  mastery: string;
}

export interface QuizResultInfo {
  session: {
    id: number;
    subject_id: number;
    subject_name: string;
    total_questions: number;
    correct_answers: number;
    total_score?: number;
    theta_estimate?: number;
    started_at?: string;
    completed_at?: string;
    chain_id?: number;
    exam_index?: number;
  };
  results: {
    question: QuestionInfo & {
      correct_answer: string;
      difficulty_b: number;
      discrimination_a: number;
      guessing_c: number;
    };
    user_answer?: string;
    is_correct: boolean;
    time_spent_seconds: number;
  }[];
  topic_scores: Record<
    string,
    { correct: number; total: number; mastery: string }
  >;
  accuracy: number;
  sem?: number;
  answered_count: number;
  bloom_classification?: string;
}

export interface TopicProgress {
  topic_id: number;
  topic_name: string;
  major_topic_name: string;
  theta_estimate: number;
  questions_attempted: number;
  questions_correct: number;
  mastery_level: string;
}

export interface DashboardInfo {
  user: { id: number; username: string; email?: string };
  total_quizzes: number;
  total_questions_attempted: number;
  overall_accuracy: number;
  topic_progress: TopicProgress[];
  recent_sessions: {
    id: number;
    subject_id: number;
    total_questions: number;
    correct_answers: number;
    total_score?: number;
    theta_estimate?: number;
    started_at?: string;
    completed_at?: string;
  }[];
}
