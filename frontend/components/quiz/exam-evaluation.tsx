"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import {
  Trophy, Target, Brain, Activity, ArrowRight, Flag, Lightbulb,
} from "lucide-react";
import type { ExamEvaluationInfo } from "@/lib/api";

interface ExamEvaluationProps {
  evaluation: ExamEvaluationInfo;
  onNextExam: () => Promise<void> | void;
  onFinish: () => Promise<void> | void;
}

const masteryLabel: Record<string, string> = {
  master: "Xuất sắc",
  proficient: "Giỏi",
  developing: "Khá",
  beginner: "Trung bình",
  novice: "Cần cải thiện",
};

const masteryColor: Record<string, string> = {
  master: "text-green-600",
  proficient: "text-blue-600",
  developing: "text-yellow-600",
  beginner: "text-orange-600",
  novice: "text-red-600",
};

function ThetaSparkline({ history }: { history: number[] }) {
  if (history.length < 2) return null;
  const min = Math.min(...history);
  const max = Math.max(...history);
  const range = max - min || 1;
  const width = 280;
  const height = 60;
  const points = history
    .map((v, i) => {
      const x = (i / (history.length - 1)) * width;
      const y = height - ((v - min) / range) * (height - 8) - 4;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-16">
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        className="text-primary"
      />
    </svg>
  );
}

export function ExamEvaluation({ evaluation, onNextExam, onFinish }: ExamEvaluationProps) {
  const [loadingNext, setLoadingNext] = useState(false);
  const [loadingFinish, setLoadingFinish] = useState(false);

  const accuracyPct = Math.round(evaluation.accuracy * 100);
  const canContinue = !evaluation.chain_completed;

  const handleNext = async () => {
    setLoadingNext(true);
    try {
      await onNextExam();
    } finally {
      setLoadingNext(false);
    }
  };

  const handleFinish = async () => {
    setLoadingFinish(true);
    try {
      await onFinish();
    } finally {
      setLoadingFinish(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="text-center">
        <h1 className="text-2xl font-bold tracking-tight">
          Đánh giá Đề {evaluation.exam_index}/{evaluation.max_exams}
        </h1>
        {evaluation.chain_completed && (
          <p className="mt-1 text-sm font-medium text-primary">
            Bài kiểm tra đã kết thúc{evaluation.stop_reason ? ` — ${evaluation.stop_reason}` : ""}
          </p>
        )}
      </div>

      {/* Summary tiles */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Điểm đề này</CardTitle>
            <Trophy className="h-4 w-4 text-yellow-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{evaluation.score}/{evaluation.total}</div>
            <Progress value={accuracyPct} className="mt-2" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Độ chính xác</CardTitle>
            <Target className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{accuracyPct}%</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Năng lực (θ)</CardTitle>
            <Brain className="h-4 w-4 text-purple-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{evaluation.theta.toFixed(2)}</div>
            <p className="text-xs text-muted-foreground mt-1">tích lũy toàn bài</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Độ bất định (SEM)</CardTitle>
            <Activity className="h-4 w-4 text-green-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {evaluation.sem >= 999 ? "—" : evaluation.sem.toFixed(3)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">dừng khi &lt; 0.3</p>
          </CardContent>
        </Card>
      </div>

      {/* Theta history */}
      {evaluation.theta_history.length > 1 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Tiến trình năng lực θ</CardTitle>
          </CardHeader>
          <CardContent>
            <ThetaSparkline history={evaluation.theta_history} />
          </CardContent>
        </Card>
      )}

      {/* Applied rules */}
      {evaluation.applied_rules.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Luật suy diễn đã áp dụng</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {evaluation.applied_rules.map((r) => (
              <span key={r} className="rounded bg-primary/10 px-2 py-1 text-xs font-semibold text-primary">
                {r}
              </span>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Bloom */}
      {evaluation.bloom_classification && (
        <Card className="border-green-500/50 bg-green-50/50">
          <CardContent className="pt-4 text-sm font-medium text-green-700">
            🏆 {evaluation.bloom_classification}
          </CardContent>
        </Card>
      )}

      {/* Topic breakdown of this exam */}
      <Card>
        <CardHeader>
          <CardTitle>Kết quả theo Chủ đề (đề này)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {Object.entries(evaluation.topic_scores).map(([name, score]) => {
              const pct = score.total > 0 ? Math.round((score.correct / score.total) * 100) : 0;
              return (
                <div key={name} className="flex items-center justify-between p-3 rounded-lg border">
                  <div className="flex-1">
                    <p className="font-medium">{name}</p>
                    <div className="flex items-center gap-3 mt-1 text-sm">
                      <span className="text-muted-foreground">{score.correct}/{score.total} đúng</span>
                      <span className={cn("font-medium", masteryColor[score.mastery] || "")}>
                        {masteryLabel[score.mastery] || score.mastery}
                      </span>
                    </div>
                  </div>
                  <div className="w-24">
                    <div className="text-right text-sm font-bold">{pct}%</div>
                    <Progress value={pct} className="mt-1" />
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Recommendations */}
      {evaluation.recommendations.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Lightbulb className="h-4 w-4 text-yellow-500" />
              Gợi ý học tập
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2 text-sm">
              {evaluation.recommendations.map((rec, idx) => (
                <li key={idx} className="rounded-lg border p-2">
                  <span className="font-medium">{rec.topic_name}</span>
                  {rec.prerequisite_topic_name && (
                    <span className="text-muted-foreground"> — ôn lại: {rec.prerequisite_topic_name}</span>
                  )}
                  <p className="text-xs text-muted-foreground mt-0.5">{rec.reason}</p>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* Actions */}
      <div className="flex justify-center gap-3 pb-8">
        {canContinue && (
          <Button size="lg" onClick={handleNext} disabled={loadingNext || loadingFinish}>
            {loadingNext ? "Đang sinh đề..." : (
              <>
                Làm đề tiếp theo
                <ArrowRight className="h-5 w-5 ml-2" />
              </>
            )}
          </Button>
        )}
        <Button
          size="lg"
          variant={canContinue ? "outline" : "default"}
          onClick={handleFinish}
          disabled={loadingNext || loadingFinish}
        >
          <Flag className="h-5 w-5 mr-2" />
          {loadingFinish ? "Đang tổng kết..." : canContinue ? "Kết thúc" : "Xem báo cáo cuối"}
        </Button>
      </div>
    </div>
  );
}
