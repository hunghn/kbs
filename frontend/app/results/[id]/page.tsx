"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { authAPI, quizAPI, type QuizResultInfo, type InferenceRuleLogInfo, type ExplanationInfo } from "@/lib/api";
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
  const [explanation, setExplanation] = useState<ExplanationInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    try {
      const me = await authAPI.me();
      setUser(me);
      const res = await quizAPI.getResults(Number(id));
      setResult(res);
      const logs = await quizAPI.getRuleLogs(Number(id));
      setRuleLogs(logs);
      try {
        setExplanation(await quizAPI.getExplanation(Number(id)));
      } catch {
        setExplanation(null);
      }
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
  const normalizedAccuracy = result.accuracy > 0 ? result.accuracy : (accuracy / 100);
  const sem = typeof result.sem === "number" ? result.sem : 999;
  const answeredCount = result.answered_count ?? results.length;
  const theta = typeof session.theta_estimate === "number" ? session.theta_estimate : null;
  const hasApplicationQuestions = results.some((r) => {
    const qType = (r.question.question_type || "").toLowerCase();
    return qType.includes("vận") || qType.includes("van");
  });

  const overallEvaluationLabel = (() => {
    if (theta == null) {
      return "N/A";
    }

    const bloomGate = !hasApplicationQuestions || Boolean(result.bloom_classification);

    if (
      theta >= 1.5
      && normalizedAccuracy >= 0.75
      && sem <= 0.6
      && answeredCount >= 15
      && bloomGate
    ) {
      return "Xuất sắc";
    }

    if (
      theta >= 1.1
      && normalizedAccuracy >= 0.7
      && sem <= 0.75
      && answeredCount >= 12
    ) {
      return "Giỏi";
    }

    if (
      theta >= 0.6
      && normalizedAccuracy >= 0.6
      && sem <= 0.9
      && answeredCount >= 10
    ) {
      return "Khá";
    }

    if (
      theta >= -0.2
      && normalizedAccuracy >= 0.45
      && answeredCount >= 8
    ) {
      return "Trung bình";
    }

    return "Cần cải thiện";
  })();

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

  return (
    <div className="min-h-screen">
      <Navbar user={user} onLogout={() => { localStorage.removeItem("kbs_token"); router.push("/"); }} />
      <main className="container py-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Kết quả Bài thi</h1>
            <p className="text-muted-foreground mt-1">
              {session.subject_name} · {session.exam_index ? `Đề ${session.exam_index}` : `Bài thi #${session.id}`}
              {session.chain_id ? ` · Chuỗi đề #${session.chain_id}` : ""}
            </p>
          </div>
          <div className="flex gap-2">
            {session.chain_id && (
              <Link href={`/results/chain/${session.chain_id}`}>
                <Button variant="outline">
                  <ArrowLeft className="h-4 w-4 mr-1" /> Tổng kết chuỗi đề
                </Button>
              </Link>
            )}
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
                {overallEvaluationLabel}
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

        {/* Explainable AI */}
        {explanation && (
          <Card>
            <CardHeader>
              <CardTitle>Giải thích đánh giá (Explainable AI)</CardTitle>
              <CardDescription>
                Phân rã cách hệ thống ước lượng năng lực θ từ từng câu trả lời
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              {/* Narrative */}
              <ul className="space-y-2 text-sm">
                {explanation.narrative.map((line, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-primary mt-0.5">▸</span>
                    <span>{line}</span>
                  </li>
                ))}
              </ul>

              {/* Per-question delta theta bars */}
              <div>
                <p className="text-sm font-medium mb-2">Ảnh hưởng của từng câu lên θ (Δθ)</p>
                <div className="space-y-1.5">
                  {explanation.questions.map((q) => {
                    const maxAbs = Math.max(
                      ...explanation.questions.map((x) => Math.abs(x.delta_theta)),
                      0.001
                    );
                    const pct = Math.min(Math.abs(q.delta_theta) / maxAbs, 1) * 50;
                    return (
                      <div key={q.question_id} className="flex items-center gap-2 text-xs">
                        <span className="w-14 shrink-0 text-muted-foreground">Câu {q.order}</span>
                        <span className="w-16 shrink-0 font-mono">{q.external_id}</span>
                        <div className="relative h-4 flex-1 rounded bg-muted overflow-hidden">
                          <div className="absolute left-1/2 top-0 bottom-0 w-px bg-border" />
                          <div
                            className={q.delta_theta >= 0 ? "absolute top-0 bottom-0 bg-green-500/80" : "absolute top-0 bottom-0 bg-red-500/80"}
                            style={
                              q.delta_theta >= 0
                                ? { left: "50%", width: `${pct}%` }
                                : { right: "50%", width: `${pct}%` }
                            }
                          />
                        </div>
                        <span className={`w-16 shrink-0 text-right font-mono ${q.delta_theta >= 0 ? "text-green-700" : "text-red-700"}`}>
                          {q.delta_theta >= 0 ? "+" : ""}{q.delta_theta.toFixed(3)}
                        </span>
                        <span className="w-20 shrink-0 text-right text-muted-foreground">
                          FI {Math.round(q.information_share * 100)}%
                          {q.guessing_flag ? " ⚠R7" : ""}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Skill layer */}
              {explanation.skill_stats && explanation.skill_stats.length > 0 && (
                <div>
                  <p className="text-sm font-medium mb-2">Kỹ năng đo được (tầng Kỹ năng của ontology)</p>
                  <div className="space-y-1.5">
                    {explanation.skill_stats.map((s) => (
                      <div key={s.skill_id} className="flex items-center gap-2 text-xs">
                        <span
                          className={
                            s.kind === "application"
                              ? "w-2 h-2 shrink-0 rounded-full bg-purple-500"
                              : "w-2 h-2 shrink-0 rounded-full bg-sky-500"
                          }
                        />
                        <span className="flex-1 truncate" title={s.skill_name}>{s.skill_name}</span>
                        <Progress value={s.accuracy * 100} className="h-2 w-32 shrink-0" />
                        <span className="w-16 shrink-0 text-right text-muted-foreground">
                          {s.correct}/{s.total} đúng
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Misconception detection */}
              {explanation.misconceptions && explanation.misconceptions.length > 0 && (
                <div>
                  <p className="text-sm font-medium mb-2">⚠️ Ngộ nhận phổ biến được phát hiện</p>
                  <div className="space-y-2">
                    {explanation.misconceptions.map((m) => (
                      <div key={m.question_id} className="rounded-lg border border-orange-300 bg-orange-50/60 p-3 text-xs">
                        <p>
                          <span className="font-mono font-semibold">{m.external_id}</span>
                          <span className="text-muted-foreground"> · {m.topic_name}</span>
                        </p>
                        <p className="mt-1">
                          Bạn chọn <b>{m.chosen_option}</b> — giống{" "}
                          <b>{Math.round(m.share_of_wrong * 100)}%</b> người làm sai câu này
                          ({m.n_wrong} lượt sai). Đây là phương án gây nhầm lẫn điển hình,
                          không phải lỗi ngẫu nhiên — nên xem lại khái niệm liên quan.
                        </p>
                        {m.chosen_text && (
                          <p className="mt-1 text-muted-foreground line-clamp-2">
                            Phương án đã chọn: “{m.chosen_text}”
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Bloom + difficulty tables */}
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <p className="text-sm font-medium mb-2">Kỹ năng đo được (thang Bloom)</p>
                  <div className="space-y-1.5">
                    {Object.entries(explanation.bloom_stats).map(([label, s]) => (
                      <div key={label} className="flex items-center gap-2 text-xs">
                        <span className="w-24 shrink-0">{label}</span>
                        <Progress value={s.accuracy * 100} className="h-2 flex-1" />
                        <span className="w-16 shrink-0 text-right text-muted-foreground">
                          {s.correct}/{s.total} đúng
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="text-sm font-medium mb-2">Theo mức độ khó (tham số b)</p>
                  <div className="space-y-1.5">
                    {Object.entries(explanation.difficulty_stats).map(([label, s]) => (
                      <div key={label} className="flex items-center gap-2 text-xs">
                        <span className="w-24 shrink-0">{label}</span>
                        <Progress value={s.accuracy * 100} className="h-2 flex-1" />
                        <span className="w-16 shrink-0 text-right text-muted-foreground">
                          {s.correct}/{s.total} đúng
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

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
