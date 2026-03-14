"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { authAPI, quizAPI, type QuizResultInfo, type InferenceRuleLogInfo } from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { MathContent } from "@/components/common/math-content";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  CheckCircle2, XCircle, Trophy, Brain, Target,
  ArrowLeft, BarChart3,
} from "lucide-react";
import { cn } from "@/lib/utils";
import Link from "next/link";

export default function ResultsPage() {
  const { id } = useParams();
  const router = useRouter();
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);
  const [result, setResult] = useState<QuizResultInfo | null>(null);
  const [ruleLogs, setRuleLogs] = useState<InferenceRuleLogInfo[]>([]);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    try {
      const me = await authAPI.me();
      setUser(me);
      const res = await quizAPI.getResults(Number(id));
      setResult(res);
      const logs = await quizAPI.getRuleLogs(Number(id));
      setRuleLogs(logs);
    } catch {
      router.push("/");
    }
    setLoading(false);
  }, [id, router]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading || !user || !result) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary" />
      </div>
    );
  }

  const { session, results, topic_scores } = result;
  const accuracy = session.total_questions > 0
    ? Math.round((session.correct_answers / session.total_questions) * 100)
    : 0;

  const masteryLabel: Record<string, string> = {
    master: "Xuất sắc",
    proficient: "Thành thạo",
    developing: "Đang phát triển",
    beginner: "Mới bắt đầu",
    novice: "Cần cải thiện",
  };

  const masteryColor: Record<string, string> = {
    master: "text-green-600",
    proficient: "text-blue-600",
    developing: "text-yellow-600",
    beginner: "text-orange-600",
    novice: "text-red-600",
  };

  return (
    <div className="min-h-screen">
      <Navbar user={user} onLogout={() => { localStorage.removeItem("kbs_token"); router.push("/"); }} />
      <main className="container py-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Kết quả Bài thi</h1>
            <p className="text-muted-foreground mt-1">
              {session.subject_name} · Bài thi #{session.id}
            </p>
          </div>
          <div className="flex gap-2">
            <Link href="/quiz">
              <Button variant="outline">
                Làm bài mới
              </Button>
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
              <CardTitle className="text-sm font-medium">Điểm số</CardTitle>
              <Trophy className="h-4 w-4 text-yellow-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{session.correct_answers}/{session.total_questions}</div>
              <Progress value={accuracy} className="mt-2" />
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Độ chính xác</CardTitle>
              <Target className="h-4 w-4 text-primary" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{accuracy}%</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Năng lực (θ)</CardTitle>
              <Brain className="h-4 w-4 text-purple-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{session.theta_estimate ?? "N/A"}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Đánh giá</CardTitle>
              <BarChart3 className="h-4 w-4 text-green-500" />
            </CardHeader>
            <CardContent>
              <div className="text-lg font-bold">
                {session.theta_estimate != null
                  ? masteryLabel[
                      session.theta_estimate >= 1.5 ? "master"
                      : session.theta_estimate >= 0.5 ? "proficient"
                      : session.theta_estimate >= -0.5 ? "developing"
                      : session.theta_estimate >= -1.5 ? "beginner"
                      : "novice"
                    ] ?? "N/A"
                  : "N/A"}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Topic breakdown */}
        <Card>
          <CardHeader>
            <CardTitle>Kết quả theo Chủ đề</CardTitle>
            <CardDescription>Phân tích năng lực từng lĩnh vực kiến thức</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {Object.entries(topic_scores).map(([name, score]) => {
                const topicAcc = score.total > 0 ? Math.round((score.correct / score.total) * 100) : 0;
                return (
                  <div key={name} className="flex items-center justify-between p-3 rounded-lg border">
                    <div className="flex-1">
                      <p className="font-medium">{name}</p>
                      <div className="flex items-center gap-3 mt-1">
                        <span className="text-sm text-muted-foreground">
                          {score.correct}/{score.total} đúng
                        </span>
                        <span className={cn("text-sm font-medium", masteryColor[score.mastery] || "")}>
                          {masteryLabel[score.mastery] || score.mastery}
                        </span>
                      </div>
                    </div>
                    <div className="w-24">
                      <div className="text-right text-sm font-bold">{topicAcc}%</div>
                      <Progress value={topicAcc} className="mt-1" />
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Lịch sử Rule Logs Theo Session</CardTitle>
            <CardDescription>Audit các luật suy diễn đã kích hoạt trong phiên CAT</CardDescription>
          </CardHeader>
          <CardContent>
            {ruleLogs.length === 0 ? (
              <p className="text-sm text-muted-foreground">Phiên này chưa có rule logs.</p>
            ) : (
              <div className="space-y-2">
                {[...ruleLogs].reverse().map((log) => (
                  <div key={log.id} className="rounded-lg border p-3">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="rounded bg-primary/10 px-2 py-0.5 font-semibold text-primary">{log.rule_code}</span>
                      <span className="text-muted-foreground">Step {log.step_index ?? "-"}</span>
                      <span className="text-muted-foreground">#{log.question_external_id || log.question_id || "N/A"}</span>
                      <span className="text-muted-foreground">
                        {log.answered_at ? new Date(log.answered_at).toLocaleString() : "-"}
                      </span>
                    </div>
                    <p className="mt-1 text-sm">{log.reason}</p>
                    {log.question_stem && (
                      <div className="mt-1 text-xs text-muted-foreground line-clamp-2">
                        <MathContent content={log.question_stem} inline />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Detailed question results */}
        <Card>
          <CardHeader>
            <CardTitle>Chi tiết Câu hỏi</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {results.map((r, idx) => (
                <div
                  key={idx}
                  className={cn(
                    "p-4 rounded-lg border-l-4",
                    r.is_correct ? "border-l-green-500 bg-green-50/50" : "border-l-red-500 bg-red-50/50"
                  )}
                >
                  <div className="flex items-start gap-3">
                    {r.is_correct ? (
                      <CheckCircle2 className="h-5 w-5 text-green-500 mt-0.5" />
                    ) : (
                      <XCircle className="h-5 w-5 text-red-500 mt-0.5" />
                    )}
                    <div className="flex-1">
                      <p className="font-medium">
                        <span className="text-primary">{r.question.external_id}</span>
                        {" "}<MathContent content={r.question.stem} inline />
                      </p>
                      <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
                        {["A", "B", "C", "D"].map((opt) => {
                          const text = r.question[`option_${opt.toLowerCase()}` as keyof typeof r.question] as string;
                          const isCorrect = opt === r.question.correct_answer;
                          const isUserAnswer = r.user_answer === opt;
                          return (
                            <div
                              key={opt}
                              className={cn(
                                "p-2 rounded",
                                isCorrect && "bg-green-100 font-medium text-green-800",
                                isUserAnswer && !isCorrect && "bg-red-100 text-red-800 line-through",
                              )}
                            >
                              <span className="font-bold mr-1">{opt}.</span> <MathContent content={text} inline />
                            </div>
                          );
                        })}
                      </div>
                      <p className="text-xs text-muted-foreground mt-2">
                        {r.question.topic_name} · {r.question.question_type} · 
                        Độ khó: {r.question.difficulty_b} · Thời gian: {r.time_spent_seconds}s
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
