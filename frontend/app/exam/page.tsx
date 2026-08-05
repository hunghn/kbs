"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  authAPI,
  examAPI,
  knowledgeAPI,
  type CATStepInfo,
  type ExamGradeOut,
  type ExamStartOut,
  type SubjectSummary,
} from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { QuizSetup, type ExamType, type DifficultyProfile } from "@/components/quiz/quiz-setup";
import { CATExamInterface, FixedExamInterface } from "@/components/quiz/exam-interface";

type Phase = "setup" | "fixed_exam" | "cat_exam" | "submitting" | "done";

const EXAM_SESSION_KEY = "kbs_active_exam_session_v1";

type PersistedExam = {
  user_id: number;
  phase: "fixed_exam" | "cat_exam";
  exam_type: ExamType;
  exam_data?: ExamStartOut;
  cat_step?: CATStepInfo;
  updated_at: number;
};

export default function ExamPage() {
  const router = useRouter();
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [phase, setPhase] = useState<Phase>("setup");
  const [examData, setExamData] = useState<ExamStartOut | null>(null);
  const [catStep, setCatStep] = useState<CATStepInfo | null>(null);

  const clearSession = useCallback(() => {
    if (typeof window !== "undefined") localStorage.removeItem(EXAM_SESSION_KEY);
  }, []);

  // Auth + subjects
  useEffect(() => {
    (async () => {
      try {
        const me = await authAPI.me();
        setUser(me);
        const subs = await knowledgeAPI.getSubjects();
        setSubjects(subs);
      } catch {
        router.push("/");
      }
    })();
  }, [router]);

  // Restore persisted session
  useEffect(() => {
    if (!user || typeof window === "undefined") return;
    const raw = localStorage.getItem(EXAM_SESSION_KEY);
    if (!raw) return;
    try {
      const saved = JSON.parse(raw) as PersistedExam;
      if (saved.user_id !== user.id) return;
      if (saved.phase === "fixed_exam" && saved.exam_data) {
        setExamData(saved.exam_data);
        setPhase("fixed_exam");
      } else if (saved.phase === "cat_exam" && saved.cat_step && !saved.cat_step.is_completed) {
        setCatStep(saved.cat_step);
        setPhase("cat_exam");
      } else {
        clearSession();
      }
    } catch {
      clearSession();
    }
  }, [user, clearSession]);

  const handleStartExam = async (config: {
    subject_id: number;
    num_questions: number;
    exam_type: ExamType;
    difficulty_profile: DifficultyProfile;
    recognition_pct: number;
    comprehension_pct: number;
    application_pct: number;
    time_limit_override?: number;
  }) => {
    if (config.exam_type === "fixed") {
      const data = await examAPI.generate(config);
      setExamData(data);
      setPhase("fixed_exam");
      if (user) {
        localStorage.setItem(EXAM_SESSION_KEY, JSON.stringify({
          user_id: user.id,
          phase: "fixed_exam",
          exam_type: "fixed",
          exam_data: data,
          updated_at: Date.now(),
        } as PersistedExam));
      }
    } else {
      const step = await examAPI.startCAT(config);
      setCatStep(step);
      setPhase("cat_exam");
      if (user) {
        localStorage.setItem(EXAM_SESSION_KEY, JSON.stringify({
          user_id: user.id,
          phase: "cat_exam",
          exam_type: "cat_exam",
          cat_step: step,
          updated_at: Date.now(),
        } as PersistedExam));
      }
    }
  };

  const handleFixedSubmit = (grade: ExamGradeOut) => {
    clearSession();
    router.push(`/exam/results/${grade.session_id}`);
  };

  const handleCATComplete = (sessionId: number) => {
    clearSession();
    router.push(`/exam/results/${sessionId}`);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-orange-50/40 via-white to-slate-50">
      <Navbar user={user} />
      <main className="container mx-auto px-4 py-8">
        {phase === "setup" && (
          <QuizSetup
            subjects={subjects}
            onStart={() => {
              /* practice mode — redirect to quiz page */
              router.push("/quiz");
            }}
            onStartExam={handleStartExam}
          />
        )}

        {phase === "fixed_exam" && examData && (
          <FixedExamInterface examData={examData} onSubmit={handleFixedSubmit} />
        )}

        {phase === "cat_exam" && catStep && (
          <CATExamInterface initialStep={catStep} onComplete={handleCATComplete} />
        )}

        {phase === "submitting" && (
          <div className="flex items-center justify-center min-h-64">
            <p className="text-muted-foreground">Đang nộp bài...</p>
          </div>
        )}
      </main>
    </div>
  );
}
