"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { MathContent } from "@/components/common/math-content";
import { cn } from "@/lib/utils";
import { Clock, Send, FileText, GripVertical, X } from "lucide-react";
import type { AdaptiveExamInfo, AnswerSubmit, QuestionInfo } from "@/lib/api";

/** Kéo-thả ghép đôi: kéo (hoặc bấm chọn) mục bên phải thả vào ô bên trái. */
function MatchingQuestion({
  question,
  value,
  onChange,
}: {
  question: QuestionInfo;
  value: string;
  onChange: (json: string) => void;
}) {
  const left = question.matching_left || [];
  const right = question.matching_right || [];
  let mapping: Record<string, string> = {};
  try {
    mapping = value ? JSON.parse(value) : {};
  } catch {
    mapping = {};
  }
  const used = new Set(Object.values(mapping));
  const [picked, setPicked] = useState<string | null>(null);

  const assign = (l: string, r: string) => {
    const next = { ...mapping };
    // Remove r from any other slot first
    for (const key of Object.keys(next)) {
      if (next[key] === r) delete next[key];
    }
    next[l] = r;
    setPicked(null);
    onChange(JSON.stringify(next));
  };

  const unassign = (l: string) => {
    const next = { ...mapping };
    delete next[l];
    onChange(JSON.stringify(next));
  };

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {/* Left slots */}
      <div className="space-y-2">
        {left.map((l) => (
          <div
            key={l}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const r = e.dataTransfer.getData("text/plain");
              if (r) assign(l, r);
            }}
            onClick={() => picked && assign(l, picked)}
            className={cn(
              "flex items-center gap-2 rounded-lg border-2 border-dashed p-2.5 text-sm min-h-11",
              mapping[l] ? "border-primary/60 bg-primary/5" : "border-muted-foreground/30",
              picked ? "cursor-pointer hover:border-primary" : ""
            )}
          >
            <span className="font-medium shrink-0"><MathContent content={l} inline /></span>
            <span className="text-muted-foreground shrink-0">→</span>
            {mapping[l] ? (
              <span className="flex items-center gap-1 rounded bg-primary/10 px-2 py-0.5 text-primary">
                <MathContent content={mapping[l]} inline />
                <button type="button" onClick={(e) => { e.stopPropagation(); unassign(l); }}>
                  <X className="h-3 w-3" />
                </button>
              </span>
            ) : (
              <span className="text-xs text-muted-foreground italic">thả vào đây</span>
            )}
          </div>
        ))}
      </div>
      {/* Right pool */}
      <div className="flex flex-wrap content-start gap-2">
        {right.map((r) => {
          const isUsed = used.has(r);
          return (
            <button
              key={r}
              type="button"
              draggable={!isUsed}
              onDragStart={(e) => e.dataTransfer.setData("text/plain", r)}
              onClick={() => !isUsed && setPicked(picked === r ? null : r)}
              disabled={isUsed}
              className={cn(
                "flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-sm transition-colors",
                isUsed
                  ? "opacity-35 line-through cursor-default"
                  : picked === r
                    ? "border-primary bg-primary/15 ring-1 ring-primary"
                    : "hover:bg-accent cursor-grab"
              )}
            >
              <GripVertical className="h-3.5 w-3.5 text-muted-foreground" />
              <MathContent content={r} inline />
            </button>
          );
        })}
        <p className="w-full text-xs text-muted-foreground mt-1">
          Kéo thẻ (hoặc bấm chọn thẻ rồi bấm ô trống) để ghép đôi.
        </p>
      </div>
    </div>
  );
}

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

  const isAnswered = (q: QuestionInfo): boolean => {
    const v = answers[q.id];
    if (!v) return false;
    if ((q.question_format || "mcq") === "matching") {
      try {
        const map = JSON.parse(v);
        return (q.matching_left || []).every((l) => map[l]);
      } catch {
        return false;
      }
    }
    return v.trim().length > 0;
  };

  const answeredCount = exam.questions.filter((q) => isAnswered(q)).length;

  const buildPayload = (current: Record<number, string>): AnswerSubmit[] =>
    exam.questions
      .filter((q) => (current[q.id] || "").trim().length > 0)
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
    if (!answers[questionId]) {
      const now = Date.now();
      timeSpent.current[questionId] = Math.max(
        1,
        Math.round((now - lastInteractionAt.current) / 1000)
      );
      lastInteractionAt.current = now;
    }
    const next = { ...answers, [questionId]: option };
    setAnswers(next);
    onDraftChange?.(next);
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
              {(q.question_format || "mcq") === "short_answer" ? (
                <div className="space-y-1">
                  <Input
                    placeholder="Nhập câu trả lời ngắn..."
                    value={answers[q.id] || ""}
                    onChange={(e) => selectAnswer(q.id, e.target.value)}
                    className="max-w-xl"
                  />
                  <p className="text-xs text-muted-foreground">
                    Trả lời ngắn gọn — hệ thống chấm theo đáp án chuẩn hóa.
                  </p>
                </div>
              ) : (q.question_format || "mcq") === "matching" ? (
                <MatchingQuestion
                  question={q}
                  value={answers[q.id] || ""}
                  onChange={(json) => selectAnswer(q.id, json)}
                />
              ) : (
              <div className="grid gap-2 md:grid-cols-2">
                {((q.question_format === "true_false" ? ["A", "B"] : ["A", "B", "C", "D"]) as ("A" | "B" | "C" | "D")[]).map((opt) => {
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
              )}
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
