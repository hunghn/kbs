"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { MathContent } from "@/components/common/math-content";
import { cn } from "@/lib/utils";
import { Clock, Send, FileText } from "lucide-react";
import type { AdaptiveExamInfo, AnswerSubmit } from "@/lib/api";

interface ExamInterfaceProps {
  exam: AdaptiveExamInfo;
  initialAnswers?: Record<number, string>;
  onDraftChange?: (answers: Record<number, string>) => void;
  onSubmit: (answers: AnswerSubmit[]) => Promise<void> | void;
}

function formatSeconds(total: number) {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function ExamInterface({ exam, initialAnswers, onDraftChange, onSubmit }: ExamInterfaceProps) {
  const [answers, setAnswers] = useState<Record<number, string>>(initialAnswers ?? {});
  const [submitting, setSubmitting] = useState(false);

  const totalTimeLimit = useMemo(
    () => exam.questions.reduce((sum, q) => sum + (q.time_limit_seconds || 60), 0),
    [exam.questions]
  );
  const [timeLeft, setTimeLeft] = useState(totalTimeLimit);

  // Per-question time attribution for R7 (guessing detection): the elapsed
  // time since the previous interaction is credited to a question when it
  // receives its FIRST answer.
  const lastInteractionAt = useRef<number>(Date.now());
  const timeSpent = useRef<Record<number, number>>({});
  const submittedRef = useRef(false);

  // Reset state when a new exam arrives.
  useEffect(() => {
    setAnswers(initialAnswers ?? {});
    setTimeLeft(totalTimeLimit);
    timeSpent.current = {};
    lastInteractionAt.current = Date.now();
    submittedRef.current = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exam.session_id]);

  useEffect(() => {
    const timer = setInterval(() => {
      setTimeLeft((t) => (t > 0 ? t - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [exam.session_id]);

  const answeredCount = exam.questions.filter((q) => answers[q.id]).length;

  const buildPayload = (current: Record<number, string>): AnswerSubmit[] =>
    exam.questions
      .filter((q) => current[q.id])
      .map((q) => ({
        question_id: q.id,
        user_answer: current[q.id],
        time_spent_seconds: timeSpent.current[q.id] ?? 0,
      }));

  const handleSubmit = async (skipConfirm = false) => {
    if (submittedRef.current) return;
    const unanswered = exam.questions.length - answeredCount;
    if (!skipConfirm && unanswered > 0) {
      const ok = window.confirm(
        `Còn ${unanswered} câu chưa trả lời (sẽ tính là sai). Bạn chắc chắn muốn nộp bài?`
      );
      if (!ok) return;
    }
    submittedRef.current = true;
    setSubmitting(true);
    try {
      await onSubmit(buildPayload(answers));
    } catch {
      submittedRef.current = false;
      setSubmitting(false);
    }
  };

  // Auto-submit when the global countdown expires.
  useEffect(() => {
    if (timeLeft === 0 && !submittedRef.current && exam.questions.length > 0) {
      handleSubmit(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeLeft]);

  const selectAnswer = (questionId: number, option: string) => {
    setAnswers((prev) => {
      if (!prev[questionId]) {
        const now = Date.now();
        timeSpent.current[questionId] = Math.max(
          1,
          Math.round((now - lastInteractionAt.current) / 1000)
        );
        lastInteractionAt.current = now;
      }
      const next = { ...prev, [questionId]: option };
      onDraftChange?.(next);
      return next;
    });
  };

  const progressPct = exam.questions.length > 0
    ? Math.round((answeredCount / exam.questions.length) * 100)
    : 0;

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      {/* Sticky header */}
      <div className="sticky top-0 z-10 -mx-2 px-2 py-2 bg-background/95 backdrop-blur border-b">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-primary" />
            <span className="font-semibold">
              Đề {exam.exam_index}/{exam.max_exams}
            </span>
            {exam.applied_rules.length > 0 && (
              <span className="hidden md:flex flex-wrap gap-1">
                {exam.applied_rules.map((r) => (
                  <span key={r} className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
                    {r}
                  </span>
                ))}
              </span>
            )}
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm text-muted-foreground">
              {answeredCount}/{exam.questions.length} câu
            </span>
            <span className={cn(
              "flex items-center gap-1 font-mono font-semibold",
              timeLeft <= 60 ? "text-red-600" : "text-foreground"
            )}>
              <Clock className="h-4 w-4" />
              {formatSeconds(timeLeft)}
            </span>
            <Button size="sm" onClick={() => handleSubmit()} disabled={submitting}>
              <Send className="h-4 w-4 mr-1" />
              {submitting ? "Đang nộp..." : "Nộp bài"}
            </Button>
          </div>
        </div>
        <Progress value={progressPct} className="mt-2 h-1.5" />
      </div>

      {/* Question list */}
      <div className="space-y-4">
        {exam.questions.map((q, idx) => (
          <Card key={q.id} id={`question-${q.id}`}>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium leading-relaxed">
                <span className="text-primary font-bold mr-2">Câu {idx + 1}.</span>
                <MathContent content={q.stem} inline />
              </CardTitle>
              <CardDescription className="text-xs">
                {q.topic_name} · {q.question_type}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-2 md:grid-cols-2">
                {(["A", "B", "C", "D"] as const).map((opt) => {
                  const text = q[`option_${opt.toLowerCase()}` as "option_a" | "option_b" | "option_c" | "option_d"];
                  const selected = answers[q.id] === opt;
                  return (
                    <button
                      key={opt}
                      type="button"
                      onClick={() => selectAnswer(q.id, opt)}
                      className={cn(
                        "flex items-start gap-2 rounded-lg border p-3 text-left text-sm transition-colors",
                        selected
                          ? "border-primary bg-primary/10 font-medium"
                          : "hover:bg-accent"
                      )}
                    >
                      <span className={cn(
                        "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-bold",
                        selected ? "border-primary bg-primary text-primary-foreground" : ""
                      )}>
                        {opt}
                      </span>
                      <span className="pt-0.5"><MathContent content={text} inline /></span>
                    </button>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="flex justify-end pb-8">
        <Button size="lg" onClick={() => handleSubmit()} disabled={submitting}>
          <Send className="h-5 w-5 mr-2" />
          {submitting ? "Đang nộp bài..." : "Nộp bài và xem đánh giá"}
        </Button>
      </div>
    </div>
  );
}
