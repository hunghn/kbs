"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  authAPI,
  knowledgeAPI,
  adaptiveAPI,
  presetAPI,
  quizAPI,
  type SubjectSummary,
  type AdaptiveExamInfo,
  type ExamEvaluationInfo,
  type AnswerSubmit,
} from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { QuizSetup } from "@/components/quiz/quiz-setup";
import { ExamInterface } from "@/components/quiz/exam-interface";
import { ExamEvaluation } from "@/components/quiz/exam-evaluation";
import { PresetList } from "@/components/quiz/preset-list";
import { Button } from "@/components/ui/button";
import { Sparkles, FileText } from "lucide-react";

const CHAIN_STORAGE_KEY = "kbs_active_exam_chain_v1";

type PersistedChain = {
  user_id: number;
  chain_id: number;
  session_id: number;
  exam_index: number;
  draft_answers: Record<number, string>;
  updated_at: number;
};

function QuizContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [phase, setPhase] = useState<"setup" | "exam" | "grading" | "evaluation" | "preset-exam">("setup");
  const [mode, setMode] = useState<"adaptive" | "preset">("adaptive");
  const [exam, setExam] = useState<AdaptiveExamInfo | null>(null);
  const [presetExam, setPresetExam] = useState<AdaptiveExamInfo | null>(null);
  const [evaluation, setEvaluation] = useState<ExamEvaluationInfo | null>(null);
  const [draftAnswers, setDraftAnswers] = useState<Record<number, string>>({});

  const clearPersisted = useCallback(() => {
    if (typeof window === "undefined") return;
    localStorage.removeItem(CHAIN_STORAGE_KEY);
  }, []);

  const persistChain = useCallback(
    (currentExam: AdaptiveExamInfo, answers: Record<number, string>) => {
      if (typeof window === "undefined" || !user) return;
      const payload: PersistedChain = {
        user_id: user.id,
        chain_id: currentExam.chain_id,
        session_id: currentExam.session_id,
        exam_index: currentExam.exam_index,
        draft_answers: answers,
        updated_at: Date.now(),
      };
      localStorage.setItem(CHAIN_STORAGE_KEY, JSON.stringify(payload));
    },
    [user]
  );

  const checkAuth = useCallback(async () => {
    try {
      const me = await authAPI.me();
      setUser(me);
      const subs = await knowledgeAPI.getSubjects();
      setSubjects(subs);
    } catch {
      router.push("/");
    }
  }, [router]);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  // Resume an unfinished chain from localStorage.
  useEffect(() => {
    if (!user || typeof window === "undefined") return;
    const raw = localStorage.getItem(CHAIN_STORAGE_KEY);
    if (!raw) return;

    (async () => {
      try {
        const parsed = JSON.parse(raw) as PersistedChain;
        if (parsed.user_id !== user.id || !parsed.chain_id) {
          return;
        }
        const state = await adaptiveAPI.getState(parsed.chain_id);
        if (state.status === "active" && state.active_exam) {
          setExam(state.active_exam);
          setDraftAnswers(
            state.active_exam.session_id === parsed.session_id ? parsed.draft_answers ?? {} : {}
          );
          setPhase("exam");
        } else {
          clearPersisted();
        }
      } catch {
        clearPersisted();
      }
    })();
  }, [user, clearPersisted]);

  const handleStartQuiz = async (config: {
    subject_id: number;
    questions_per_exam: number;
    max_exams: number;
    recognition_pct: number;
    comprehension_pct: number;
    application_pct: number;
    strategy: "rules" | "rl";
  }) => {
    if (!config.subject_id || config.subject_id <= 0) {
      throw new Error("Bạn phải chọn môn học trước khi bắt đầu");
    }
    const firstExam = await adaptiveAPI.start(config);
    setExam(firstExam);
    setDraftAnswers({});
    setEvaluation(null);
    setPhase("exam");
    persistChain(firstExam, {});
  };

  const handleSubmitExam = async (answers: AnswerSubmit[]) => {
    if (!exam) return;
    setPhase("grading");
    try {
      const result = await adaptiveAPI.submit(exam.chain_id, {
        session_id: exam.session_id,
        answers,
      });
      setEvaluation(result);
      setDraftAnswers({});
      setPhase("evaluation");
    } catch (err) {
      setPhase("exam");
      throw err;
    }
  };

  const handleNextExam = async () => {
    if (!evaluation) return;
    const state = await adaptiveAPI.next(evaluation.chain_id);
    if (state.status === "active" && state.active_exam) {
      setExam(state.active_exam);
      setDraftAnswers({});
      setEvaluation(null);
      setPhase("exam");
      persistChain(state.active_exam, {});
    } else {
      // Chain ended (out of questions / max exams reached).
      clearPersisted();
      router.push(`/results/chain/${evaluation.chain_id}`);
    }
  };

  const handleFinish = async () => {
    if (!evaluation) return;
    clearPersisted();
    if (!evaluation.chain_completed) {
      await adaptiveAPI.finish(evaluation.chain_id);
    }
    router.push(`/results/chain/${evaluation.chain_id}`);
  };

  const handleDraftChange = (answers: Record<number, string>) => {
    setDraftAnswers(answers);
    if (exam) persistChain(exam, answers);
  };

  const handleStartPreset = async (presetId: number) => {
    const started = await presetAPI.start(presetId);
    // Wrap the fixed exam into the shape ExamInterface renders
    setPresetExam({
      chain_id: 0,
      session_id: started.session_id,
      exam_index: 1,
      max_exams: 1,
      questions_per_exam: started.questions.length,
      questions: started.questions,
      theta: 0,
      sem: 999,
      applied_rules: [],
      strategy: "preset",
    });
    setPhase("preset-exam");
  };

  const handleSubmitPreset = async (answers: AnswerSubmit[]) => {
    if (!presetExam) return;
    setPhase("grading");
    try {
      await quizAPI.submit(presetExam.session_id, answers);
      router.push(`/results/${presetExam.session_id}`);
    } catch (err) {
      setPhase("preset-exam");
      throw err;
    }
  };

  if (!user) return null;

  const defaultSubject = searchParams.get("subject")
    ? parseInt(searchParams.get("subject")!)
    : undefined;

  return (
    <div className="min-h-screen">
      <Navbar
        user={user}
        onLogout={() => {
          localStorage.removeItem("kbs_token");
          clearPersisted();
          router.push("/");
        }}
      />
      <main className="container py-6">
        {phase === "setup" && (
          <div className="max-w-3xl mx-auto space-y-4">
            <div className="flex gap-2">
              <Button
                variant={mode === "adaptive" ? "default" : "outline"}
                size="sm"
                onClick={() => setMode("adaptive")}
              >
                <Sparkles className="h-4 w-4 mr-1" />
                Thi thích ứng (chuỗi đề)
              </Button>
              <Button
                variant={mode === "preset" ? "default" : "outline"}
                size="sm"
                onClick={() => setMode("preset")}
              >
                <FileText className="h-4 w-4 mr-1" />
                Đề có sẵn
              </Button>
            </div>
            {mode === "adaptive" ? (
              <QuizSetup
                subjects={subjects}
                defaultSubjectId={defaultSubject}
                onStart={handleStartQuiz}
              />
            ) : (
              <PresetList subjects={subjects} onStart={handleStartPreset} />
            )}
          </div>
        )}
        {phase === "preset-exam" && presetExam && (
          <ExamInterface
            exam={presetExam}
            onSubmit={handleSubmitPreset}
          />
        )}
        {phase === "exam" && exam && (
          <ExamInterface
            exam={exam}
            initialAnswers={draftAnswers}
            onDraftChange={handleDraftChange}
            onSubmit={handleSubmitExam}
          />
        )}
        {phase === "grading" && (
          <div className="flex flex-col items-center justify-center py-20">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mb-4" />
            <p className="text-muted-foreground">Đang chấm bài và đánh giá năng lực...</p>
          </div>
        )}
        {phase === "evaluation" && evaluation && (
          <ExamEvaluation
            evaluation={evaluation}
            onNextExam={handleNextExam}
            onFinish={handleFinish}
          />
        )}
      </main>
    </div>
  );
}

export default function QuizPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-screen">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary" />
        </div>
      }
    >
      <QuizContent />
    </Suspense>
  );
}
