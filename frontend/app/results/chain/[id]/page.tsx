"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { authAPI, adaptiveAPI, userAPI, type ChainSummaryInfo, type LearningPathInfo } from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import {
  Trophy, Brain, Activity, Target, ArrowLeft, Lightbulb, FileText,
} from "lucide-react";

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

function ThetaChart({ history }: { history: number[] }) {
  if (history.length < 2) return null;
  const min = Math.min(...history);
  const max = Math.max(...history);
  const range = max - min || 1;
  const width = 600;
  const height = 120;
  const points = history
    .map((v, i) => {
      const x = (i / (history.length - 1)) * width;
      const y = height - ((v - min) / range) * (height - 16) - 8;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-28">
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        className="text-primary"
      />
      {history.map((v, i) => {
        const x = (i / (history.length - 1)) * width;
        const y = height - ((v - min) / range) * (height - 16) - 8;
        return <circle key={i} cx={x} cy={y} r="2.5" className="fill-primary" />;
      })}
    </svg>
  );
}

export default function ChainSummaryPage() {
  const { id } = useParams();
  const router = useRouter();
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);
  const [summary, setSummary] = useState<ChainSummaryInfo | null>(null);
  const [learningPath, setLearningPath] = useState<LearningPathInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    try {
      const me = await authAPI.me();
      setUser(me);
      const data = await adaptiveAPI.getSummary(Number(id));
      setSummary(data);
      try {
        setLearningPath(await userAPI.getLearningPath(data.subject_id));
      } catch {
        setLearningPath(null);
      }
    } catch {
      router.push("/");
    }
    setLoading(false);
  }, [id, router]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading || !user || !summary) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary" />
      </div>
    );
  }

  const overallAccuracy = summary.total_questions > 0
    ? Math.round((summary.total_correct / summary.total_questions) * 100)
    : 0;

  return (
    <div className="min-h-screen">
      <Navbar
        user={user}
        onLogout={() => {
          localStorage.removeItem("kbs_token");
          router.push("/");
        }}
      />
      <main className="container py-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Tổng kết Bài kiểm tra</h1>
            <p className="text-muted-foreground mt-1">
              {summary.subject_name} · Chuỗi đề #{summary.chain_id}
              {summary.stop_reason ? ` · ${summary.stop_reason}` : ""}
            </p>
          </div>
          <div className="flex gap-2">
            <Link href="/quiz">
              <Button variant="outline">Làm bài mới</Button>
            </Link>
            <Link href="/">
              <Button variant="ghost">
                <ArrowLeft className="h-4 w-4 mr-1" /> Dashboard
              </Button>
            </Link>
          </div>
        </div>

        {/* Summary cards */}
        <div className="grid gap-4 md:grid-cols-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Tổng điểm</CardTitle>
              <Trophy className="h-4 w-4 text-yellow-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {summary.total_correct}/{summary.total_questions}
              </div>
              <Progress value={overallAccuracy} className="mt-2" />
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Độ chính xác</CardTitle>
              <Target className="h-4 w-4 text-primary" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{overallAccuracy}%</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Năng lực (θ)</CardTitle>
              <Brain className="h-4 w-4 text-purple-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{summary.theta.toFixed(2)}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Độ bất định (SEM)</CardTitle>
              <Activity className="h-4 w-4 text-green-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {summary.sem >= 999 ? "—" : summary.sem.toFixed(3)}
              </div>
            </CardContent>
          </Card>
        </div>

        {summary.bloom_classification && (
          <Card className="border-green-500/50 bg-green-50/50">
            <CardContent className="pt-4 text-sm font-medium text-green-700">
              🏆 {summary.bloom_classification}
            </CardContent>
          </Card>
        )}

        {/* Theta progression */}
        {summary.theta_history.length > 1 && (
          <Card>
            <CardHeader>
              <CardTitle>Tiến trình năng lực θ toàn chuỗi</CardTitle>
              <CardDescription>
                Cập nhật sau từng câu trả lời trên tất cả các đề
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ThetaChart history={summary.theta_history} />
            </CardContent>
          </Card>
        )}

        {/* Per-exam table */}
        <Card>
          <CardHeader>
            <CardTitle>Các đề đã làm</CardTitle>
            <CardDescription>Bấm vào từng đề để xem chi tiết câu hỏi và audit luật suy diễn</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {summary.exams.map((exam) => {
                const pct = Math.round(exam.accuracy * 100);
                return (
                  <Link
                    key={exam.session_id}
                    href={`/results/${exam.session_id}`}
                    className="flex items-center justify-between rounded-lg border p-3 transition-colors hover:bg-accent"
                  >
                    <div className="flex items-center gap-3">
                      <FileText className="h-5 w-5 text-primary" />
                      <div>
                        <p className="font-medium">Đề {exam.exam_index}</p>
                        <p className="text-sm text-muted-foreground">
                          {exam.score}/{exam.total} đúng
                          {exam.theta_after != null && ` · θ sau đề: ${exam.theta_after.toFixed(2)}`}
                          {!exam.completed && " · chưa nộp"}
                        </p>
                      </div>
                    </div>
                    <div className="w-24">
                      <div className="text-right text-sm font-bold">{pct}%</div>
                      <Progress value={pct} className="mt-1" />
                    </div>
                  </Link>
                );
              })}
            </div>
          </CardContent>
        </Card>

        {/* Topic breakdown */}
        <Card>
          <CardHeader>
            <CardTitle>Kết quả theo Chủ đề (toàn chuỗi)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {Object.entries(summary.topic_scores).map(([name, score]) => {
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

        {/* Learning path */}
        {learningPath && learningPath.steps.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Lộ trình học đề xuất</CardTitle>
              <CardDescription>
                Sắp xếp theo quan hệ tiên quyết trong ontology — học kiến thức nền trước, chủ đề phụ thuộc sau
                ({learningPath.mastered_count}/{learningPath.total_topics} chủ đề đã thành thạo, không cần ôn lại)
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ol className="relative space-y-0 border-l-2 border-muted ml-3">
                {learningPath.steps.map((step) => {
                  const statusColor =
                    step.status === "weak" ? "bg-red-500" :
                    step.status === "in_progress" ? "bg-yellow-500" : "bg-slate-400";
                  const statusLabel =
                    step.status === "weak" ? "Cần củng cố" :
                    step.status === "in_progress" ? "Đang tiến bộ" : "Chưa học";
                  return (
                    <li key={step.topic_id} className="relative pl-6 pb-4">
                      <span className={`absolute -left-[9px] top-1 h-4 w-4 rounded-full border-2 border-background ${statusColor}`} />
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-bold text-muted-foreground">Bước {step.order}</span>
                        <span className="font-medium">
                          {step.code && !step.name.startsWith(step.code) ? `${step.code} ` : ""}{step.name}
                        </span>
                        <span className={`rounded-full px-2 py-0.5 text-xs text-white ${statusColor}`}>
                          {statusLabel}
                        </span>
                        {step.attempted > 0 && (
                          <span className="text-xs text-muted-foreground">
                            {step.correct}/{step.attempted} đúng{step.theta != null ? ` · θ ${step.theta.toFixed(2)}` : ""}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5">{step.reason}</p>
                      {step.prerequisite_names.length > 0 && (
                        <p className="text-xs text-muted-foreground">
                          Tiên quyết: {step.prerequisite_names.join(", ")}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ol>
            </CardContent>
          </Card>
        )}

        {/* Recommendations */}
        {summary.recommendations.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Lightbulb className="h-5 w-5 text-yellow-500" />
                Gợi ý học lại kiến thức nền
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2 text-sm">
                {summary.recommendations.map((rec, idx) => (
                  <li key={idx} className="rounded-lg border p-3">
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
      </main>
    </div>
  );
}
