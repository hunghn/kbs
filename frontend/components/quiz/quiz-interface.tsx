"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import type { QuestionInfo, CATStepInfo } from "@/lib/api";
import { Clock, ChevronRight, Send, AlertCircle, Activity } from "lucide-react";
import { cn } from "@/lib/utils";

interface QuizInterfaceProps {
  currentStep: CATStepInfo;
  onAnswer: (payload: { question_id: number; user_answer: string; time_spent_seconds: number }) => Promise<void>;
  onFinish: (step: CATStepInfo) => void;
}

export function QuizInterface({ currentStep, onAnswer, onFinish }: QuizInterfaceProps) {
  const [selectedAnswer, setSelectedAnswer] = useState<string>("");
  const [questionTimer, setQuestionTimer] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [ruleTimeline, setRuleTimeline] = useState<Array<{
    step: number;
    rules: string[];
    theta: number;
    sem: number;
    createdAt: string;
  }>>([]);
  const [showRuleDetails, setShowRuleDetails] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval>>();
  const questionStartRef = useRef(Date.now());
  const timelineDedupRef = useRef<Set<string>>(new Set());

  const current = currentStep.question as QuestionInfo | undefined;

  useEffect(() => {
    questionStartRef.current = Date.now();
    setQuestionTimer(0);
    setSelectedAnswer("");
    setSubmitError(null);

    timerRef.current = setInterval(() => {
      setQuestionTimer(Math.floor((Date.now() - questionStartRef.current) / 1000));
    }, 1000);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [currentStep.question?.id]);

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  const timeLimit = current?.time_limit_seconds || 60;
  const isOverTime = questionTimer > timeLimit;
  const progressPct = (currentStep.answered_count / Math.max(currentStep.max_questions, 1)) * 100;

  const handleNext = useCallback(async () => {
    if (!current || !selectedAnswer || isSubmitting) return;
    setIsSubmitting(true);
    setSubmitError(null);
    const spent = Math.floor((Date.now() - questionStartRef.current) / 1000);
    try {
      await onAnswer({
        question_id: current.id,
        user_answer: selectedAnswer,
        time_spent_seconds: spent,
      });
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "Không thể gửi câu trả lời. Vui lòng thử lại.");
    } finally {
      setIsSubmitting(false);
    }
  }, [current, selectedAnswer, isSubmitting, onAnswer]);

  useEffect(() => {
    if (currentStep.is_completed) {
      onFinish(currentStep);
    }
  }, [currentStep, onFinish]);

  useEffect(() => {
    const rules = currentStep.applied_rules || [];
    if (rules.length === 0) return;

    const dedupKey = `${currentStep.answered_count}|${rules.join(",")}|${currentStep.theta}|${currentStep.sem}`;
    if (timelineDedupRef.current.has(dedupKey)) return;

    timelineDedupRef.current.add(dedupKey);
    setRuleTimeline((prev) => [
      ...prev,
      {
        step: currentStep.answered_count,
        rules,
        theta: currentStep.theta,
        sem: currentStep.sem,
        createdAt: new Date().toISOString(),
      },
    ]);
  }, [currentStep.applied_rules, currentStep.answered_count, currentStep.theta, currentStep.sem]);

  const ruleStats = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const entry of ruleTimeline) {
      for (const rule of entry.rules) {
        counts[rule] = (counts[rule] || 0) + 1;
      }
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [ruleTimeline]);

  const latestRuleEvents = useMemo(() => {
    return [...ruleTimeline].reverse().slice(0, 3);
  }, [ruleTimeline]);

  if (!current) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-muted-foreground">
          Không còn câu hỏi phù hợp.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">
            CAT · Câu {currentStep.answered_count + 1} / {currentStep.max_questions} · {current.question_type} · {current.topic_name}
          </p>
          <Progress value={progressPct} className="mt-1 w-64" />
        </div>
        <div className={cn(
          "flex items-center gap-2 px-3 py-1 rounded-full text-sm font-mono",
          isOverTime ? "bg-destructive/10 text-destructive" : "bg-muted"
        )}>
          <Clock className="h-4 w-4" />
          {formatTime(questionTimer)}
          <span className="text-muted-foreground">/ {current.time_display || formatTime(timeLimit)}</span>
        </div>
      </div>

      <Card>
        <CardContent className="pt-6">
          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Theta hiện tại</p>
              <p className="text-xl font-semibold">{currentStep.theta.toFixed(3)}</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">SEM</p>
              <p className="text-xl font-semibold">{currentStep.sem.toFixed(3)}</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Điều kiện dừng</p>
              <p className="text-xl font-semibold">SEM &lt; 0.300</p>
            </div>
          </div>
          <div className="mt-4 rounded-lg border p-3">
            <div className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
              <Activity className="h-4 w-4" /> Tiến trình theta theo thời gian thực
            </div>
            <div className="flex h-20 items-end gap-1">
              {currentStep.theta_history.map((value, idx) => {
                const h = Math.max(8, Math.round(((value + 4) / 8) * 64));
                return (
                  <div
                    key={`${idx}-${value}`}
                    className="w-2 rounded-t bg-primary/70"
                    style={{ height: `${h}px` }}
                    title={`Step ${idx}: θ=${value.toFixed(3)}`}
                  />
                );
              })}
            </div>
          </div>

          <div className="mt-4 rounded-lg border p-3">
            <p className="mb-2 text-sm text-muted-foreground">Timeline applied rules</p>
            {ruleTimeline.length === 0 ? (
              <p className="text-sm text-muted-foreground">Chưa có rule nào được ghi nhận.</p>
            ) : (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="text-muted-foreground">{ruleTimeline.length} lần áp dụng</span>
                  {ruleStats.slice(0, 4).map(([rule, count]) => (
                    <span key={rule} className="rounded bg-primary/10 px-2 py-0.5 font-semibold text-primary">
                      {rule} x{count}
                    </span>
                  ))}
                </div>

                <div className="grid gap-2 md:grid-cols-3">
                  {latestRuleEvents.map((entry, idx) => (
                    <div key={`${entry.step}-${idx}`} className="rounded-md border p-2">
                      <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
                        <span>Step {entry.step}</span>
                        <span>{new Date(entry.createdAt).toLocaleTimeString()}</span>
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {entry.rules.map((rule) => (
                          <span key={`${entry.step}-${rule}`} className="rounded bg-muted px-2 py-0.5 text-xs font-medium">
                            {rule}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>

                <Button
                  type="button"
                  variant="ghost"
                  className="h-8 px-2 text-xs"
                  onClick={() => setShowRuleDetails((prev) => !prev)}
                >
                  {showRuleDetails ? "Ẩn chi tiết timeline" : "Xem chi tiết timeline"}
                </Button>

                {showRuleDetails && (
                  <div className="max-h-56 space-y-2 overflow-y-auto pr-1">
                    {[...ruleTimeline].reverse().map((entry, idx) => (
                      <div key={`${entry.step}-detail-${idx}`} className="rounded-md border p-2">
                        <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
                          <span>Step {entry.step}</span>
                          <span>{new Date(entry.createdAt).toLocaleTimeString()}</span>
                        </div>
                        <div className="mb-1 flex flex-wrap gap-1">
                          {entry.rules.map((rule) => (
                            <span key={`${entry.step}-detail-${rule}`} className="rounded bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
                              {rule}
                            </span>
                          ))}
                        </div>
                        <p className="text-xs text-muted-foreground">theta={entry.theta.toFixed(3)} · sem={entry.sem.toFixed(3)}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {submitError && (
        <Card className="border-destructive/60 bg-destructive/5">
          <CardContent className="pt-6 text-sm text-destructive">
            {submitError}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-lg font-medium leading-relaxed">
            <span className="text-primary font-bold mr-2">{current.external_id}</span>
            {current.stem}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {["A", "B", "C", "D"].map((opt) => {
            const text = current[`option_${opt.toLowerCase()}` as keyof QuestionInfo] as string;
            const isSelected = selectedAnswer === opt;
            return (
              <button
                key={opt}
                onClick={() => setSelectedAnswer(opt)}
                className={cn(
                  "w-full text-left p-4 rounded-lg border-2 transition-all hover:border-primary/50",
                  isSelected
                    ? "border-primary bg-primary/5 ring-1 ring-primary"
                    : "border-border hover:bg-accent/50"
                )}
              >
                <span className={cn(
                  "inline-flex items-center justify-center w-8 h-8 rounded-full text-sm font-bold mr-3",
                  isSelected ? "bg-primary text-primary-foreground" : "bg-muted"
                )}>
                  {opt}
                </span>
                {text}
              </button>
            );
          })}
        </CardContent>
      </Card>

      <div className="flex items-center justify-between">
        <div className="text-sm text-muted-foreground">
          Đã trả lời: {currentStep.answered_count}/{currentStep.max_questions}
        </div>

        <Button onClick={handleNext} disabled={!selectedAnswer || isSubmitting}>
          {isSubmitting ? (
            "Đang cập nhật..."
          ) : (
            <>
              Trả lời và tiếp tục <ChevronRight className="h-4 w-4 ml-1" />
            </>
          )}
        </Button>
      </div>

      {currentStep.recommendations.length > 0 && (
        <Card className="border-primary">
          <CardContent className="pt-6">
            <div className="flex items-start gap-3">
              <AlertCircle className="h-5 w-5 text-primary mt-0.5" />
              <div className="flex-1">
                <p className="font-medium">Gợi ý học lại kiến thức tiên quyết</p>
                <div className="mt-2 space-y-2 text-sm text-muted-foreground">
                  {currentStep.recommendations.map((rec, idx) => (
                    <p key={`${rec.topic_id}-${idx}`}>
                      Topic {rec.topic_name}: ôn lại {rec.prerequisite_topic_name || "kiến thức nền"} ({rec.reason}).
                    </p>
                  ))}
                </div>
                <Button className="mt-3" variant="outline" onClick={() => onFinish(currentStep)}>
                  <Send className="h-4 w-4 mr-1" /> Xem kết quả
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
