"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { authAPI, knowledgeAPI, quizAPI, type SubjectSummary, type CATStepInfo } from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { QuizSetup } from "@/components/quiz/quiz-setup";
import { QuizInterface } from "@/components/quiz/quiz-interface";

const CAT_SESSION_STORAGE_KEY = "kbs_active_cat_session_v1";

type PersistedCatSession = {
  user_id: number;
  session_id: number;
  phase: "quiz" | "submitting";
  step: CATStepInfo;
  updated_at: number;
};

function QuizContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [step, setStep] = useState<CATStepInfo | null>(null);
  const [phase, setPhase] = useState<"setup" | "quiz" | "submitting">("setup");

  const clearPersistedSession = useCallback(() => {
    if (typeof window === "undefined") return;
    localStorage.removeItem(CAT_SESSION_STORAGE_KEY);
  }, []);

  const persistSession = useCallback((payload: PersistedCatSession) => {
    if (typeof window === "undefined") return;
    localStorage.setItem(CAT_SESSION_STORAGE_KEY, JSON.stringify(payload));
  }, []);

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

  useEffect(() => {
    if (!user || typeof window === "undefined") return;

    const raw = localStorage.getItem(CAT_SESSION_STORAGE_KEY);
    if (!raw) return;

    try {
      const parsed = JSON.parse(raw) as PersistedCatSession;
      if (parsed.user_id !== user.id) return;
      if (!parsed.session_id || !parsed.step) return;

      if (parsed.phase === "submitting") {
        setSessionId(parsed.session_id);
        setStep(parsed.step);
        setPhase("submitting");
        router.push(`/results/${parsed.session_id}`);
        return;
      }

      if (parsed.step.is_completed) {
        clearPersistedSession();
        return;
      }

      setSessionId(parsed.session_id);
      setStep(parsed.step);
      setPhase("quiz");
    } catch {
      clearPersistedSession();
    }
  }, [user, router, clearPersistedSession]);

  useEffect(() => {
    if (!user || !sessionId || !step) return;
    if (phase !== "quiz" && phase !== "submitting") return;

    persistSession({
      user_id: user.id,
      session_id: sessionId,
      phase,
      step,
      updated_at: Date.now(),
    });
  }, [user, sessionId, step, phase, persistSession]);

  const handleStartQuiz = async (config: {
    subject_id: number;
    num_questions: number;
    recognition_pct: number;
    comprehension_pct: number;
    application_pct: number;
  }) => {
    if (!config.subject_id || config.subject_id <= 0) {
      throw new Error("Bạn phải chọn môn học trước khi bắt đầu");
    }

    const catStart = await quizAPI.startCAT(config);
    setSessionId(catStart.session_id);
    setStep(catStart);
    setPhase("quiz");
    if (user) {
      persistSession({
        user_id: user.id,
        session_id: catStart.session_id,
        phase: "quiz",
        step: catStart,
        updated_at: Date.now(),
      });
    }
  };

  const handleAnswer = async (payload: { question_id: number; user_answer: string; time_spent_seconds: number }) => {
    if (!sessionId) return;
    const nextStep = await quizAPI.answerCAT(sessionId, payload);
    setStep(nextStep);
  };

  const handleFinish = (finalStep: CATStepInfo) => {
    setStep(finalStep);
    if (sessionId) {
      setPhase("submitting");
      clearPersistedSession();
      router.push(`/results/${sessionId}`);
    }
  };

  if (!user) return null;

  const defaultSubject = searchParams.get("subject")
    ? parseInt(searchParams.get("subject")!)
    : undefined;

  return (
    <div className="min-h-screen">
      <Navbar user={user} onLogout={() => { localStorage.removeItem("kbs_token"); clearPersistedSession(); router.push("/"); }} />
      <main className="container py-6">
        {phase === "setup" && (
          <QuizSetup
            subjects={subjects}
            defaultSubjectId={defaultSubject}
            onStart={handleStartQuiz}
          />
        )}
        {phase === "quiz" && (
          sessionId && step ? (
            <QuizInterface
              currentStep={step}
              onAnswer={handleAnswer}
              onFinish={handleFinish}
            />
          ) : null
        )}
        {phase === "submitting" && (
          <div className="flex flex-col items-center justify-center py-20">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mb-4" />
            <p className="text-muted-foreground">Đang chấm bài...</p>
          </div>
        )}
      </main>
    </div>
  );
}

export default function QuizPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center min-h-screen">
      <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary" />
    </div>}>
      <QuizContent />
    </Suspense>
  );
}
