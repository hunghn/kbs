"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { authAPI, examAPI, type ExamGradeOut } from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { MathContent } from "@/components/common/math-content";
import { cn } from "@/lib/utils";
import { CheckCircle, XCircle, ChevronDown, ChevronUp, Trophy } from "lucide-react";

const GRADE_COLOR: Record<string, string> = {
  "Xuất sắc": "text-emerald-700 bg-emerald-50 border-emerald-200",
  "Giỏi": "text-sky-700 bg-sky-50 border-sky-200",
  "Khá": "text-blue-700 bg-blue-50 border-blue-200",
  "Trung bình": "text-amber-700 bg-amber-50 border-amber-200",
  "Yếu": "text-red-700 bg-red-50 border-red-200",
};

function ScoreCard({
  title,
  score,
  subtitle,
  accent,
}: {
  title: string;
  score: number | string;
  subtitle?: string;
  accent?: string;
}) {
  return (
    <div className={cn("rounded-xl border p-5 text-center", accent ?? "bg-white border-border")}>
      <p className="text-sm text-muted-foreground mb-1">{title}</p>
      <p className="text-5xl font-bold tabular-nums">{score}</p>
      {subtitle && <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>}
    </div>
  );
}

export default function ExamResultsPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = Number(params.id);
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);
  const [grade, setGrade] = useState<ExamGradeOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showExplainer, setShowExplainer] = useState(false);
  const [expandedQ, setExpandedQ] = useState<Set<number>>(new Set());

  useEffect(() => {
    (async () => {
      try {
        const me = await authAPI.me();
        setUser(me);
        const result = await examAPI.getResults(sessionId);
        setGrade(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Không thể tải kết quả");
      } finally {
        setLoading(false);
      }
    })();
  }, [sessionId, router]);

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-orange-50/40 via-white to-slate-50">
        <Navbar user={user} />
        <div className="flex items-center justify-center min-h-64">
          <p className="text-muted-foreground">Đang tải kết quả...</p>
        </div>
      </div>
    );
  }

  if (error || !grade) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-orange-50/40 via-white to-slate-50">
        <Navbar user={null} />
        <div className="container mx-auto px-4 py-8 text-center space-y-4">
          <p className="text-destructive">{error || "Không tìm thấy kết quả"}</p>
          <Button variant="outline" onClick={() => router.push("/exam")}>Về trang thi</Button>
        </div>
      </div>
    );
  }

  const gradeColor = GRADE_COLOR[grade.grade_label] ?? "text-slate-700 bg-slate-50 border-slate-200";

  return (
    <div className="min-h-screen bg-gradient-to-br from-orange-50/40 via-white to-slate-50">
      <Navbar user={user} />
      <main className="container mx-auto px-4 py-8 max-w-4xl space-y-6">
        {/* Grade Banner */}
        <div className={cn("rounded-2xl border p-6 text-center", gradeColor)}>
          <Trophy className="h-8 w-8 mx-auto mb-2" />
          <h1 className="text-2xl font-bold">{grade.grade_label}</h1>
          <p className="text-sm opacity-75 mt-0.5">
            {grade.correct_count}/{grade.total_count} câu đúng
          </p>
        </div>

        {/* Score cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <ScoreCard
            title="Điểm thô"
            score={grade.raw_score_10.toFixed(1)}
            subtitle={`${grade.correct_count}/${grade.total_count} câu đúng`}
            accent="bg-white border-border"
          />
          <ScoreCard
            title="Điểm IRT (10-pt)"
            score={grade.irt_score_10.toFixed(1)}
            subtitle={`θ = ${grade.theta.toFixed(2)}, SD = ${grade.posterior_sd.toFixed(2)}`}
            accent="bg-orange-50 border-orange-200"
          />
          <ScoreCard
            title="Tỷ lệ đúng"
            score={`${Math.round(grade.accuracy * 100)}%`}
            accent="bg-white border-border"
          />
          <ScoreCard
            title="Năng lực θ"
            score={grade.theta.toFixed(2)}
            subtitle="Thang IRT chuẩn hóa"
            accent="bg-white border-border"
          />
        </div>

        {/* IRT Explainer */}
        <Card>
          <button
            className="w-full flex items-center justify-between px-5 py-3 text-sm font-medium hover:bg-muted/30 transition-colors rounded-xl"
            onClick={() => setShowExplainer((v) => !v)}
          >
            <span>Tại sao điểm IRT khác điểm thô?</span>
            {showExplainer ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
          {showExplainer && (
            <CardContent className="pt-0 text-sm text-muted-foreground space-y-2">
              <p>
                <strong>Điểm thô</strong> tính đơn giản: số câu đúng / tổng câu × 10.
                Nó không phân biệt câu khó hay dễ.
              </p>
              <p>
                <strong>Điểm IRT</strong> dùng Mô hình 3-tham số (3PL) để ước lượng năng lực thực
                sự (θ) của bạn. Trả lời đúng câu khó sẽ được đánh giá cao hơn trả lời đúng câu
                dễ. Sau đó θ được quy đổi về thang 10 điểm theo công thức:{" "}
                <code className="bg-muted px-1 rounded">5.0 + 1.667 × θ</code>.
              </p>
              <p className="text-xs">
                θ ≈ 0 tương đương mức trung bình → điểm 5.0. θ = +1.5 → 7.5 điểm (giỏi).
                θ = −1.5 → 2.5 điểm (yếu).
              </p>
            </CardContent>
          )}
        </Card>

        {/* Topic breakdown */}
        {Object.keys(grade.topic_scores).length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Kết quả theo chủ đề</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {Object.entries(grade.topic_scores).map(([topicName, ts]) => (
                  <div key={topicName} className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground truncate max-w-xs">{topicName}</span>
                    <div className="flex items-center gap-2 shrink-0">
                      <span>{ts.correct}/{ts.total} câu</span>
                      <span
                        className={cn("text-xs font-medium",
                          ts.accuracy >= 0.7 ? "text-green-600" :
                            ts.accuracy >= 0.5 ? "text-amber-600" : "text-red-600"
                        )}>
                        {Math.round(ts.accuracy * 100)}%
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Per-question detail */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Chi tiết từng câu</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {grade.per_question_detail.map((q, i) => {
              const expanded = expandedQ.has(q.question_id);
              return (
                <div key={q.question_id}
                  className={cn("rounded-lg border text-sm overflow-hidden",
                    q.is_correct ? "border-green-200" : "border-red-200")}>
                  <button
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-muted/20 transition-colors"
                    onClick={() => setExpandedQ((prev) => {
                      const next = new Set(prev);
                      next.has(q.question_id) ? next.delete(q.question_id) : next.add(q.question_id);
                      return next;
                    })}>
                    {q.is_correct ? (
                      <CheckCircle className="h-4 w-4 text-green-600 shrink-0" />
                    ) : (
                      <XCircle className="h-4 w-4 text-red-500 shrink-0" />
                    )}
                    <span className="font-medium text-xs text-muted-foreground shrink-0">
                      Câu {i + 1}
                    </span>
                    <span className="truncate text-sm"><MathContent content={q.stem} /></span>
                    <span className={cn("ml-auto shrink-0 text-xs",
                      q.is_correct ? "text-green-600" : "text-red-500")}>
                      {q.is_correct ? "Đúng" : "Sai"}
                    </span>
                    {expanded ? <ChevronUp className="h-3 w-3 shrink-0" /> : <ChevronDown className="h-3 w-3 shrink-0" />}
                  </button>
                  {expanded && (
                    <div className="px-4 pb-3 space-y-1.5 border-t bg-muted/10">
                      <p className="text-xs text-muted-foreground pt-2">
                        Chủ đề: {q.topic_name} &mdash; b = {q.difficulty_b.toFixed(2)}
                      </p>
                      <p>
                        <span className="text-muted-foreground">Bạn chọn:</span>{" "}
                        <span className={q.is_correct ? "text-green-700 font-semibold" : "text-red-600 font-semibold"}>
                          {q.user_answer ?? "(Không trả lời)"}
                        </span>
                      </p>
                      <p>
                        <span className="text-muted-foreground">Đáp án đúng:</span>{" "}
                        <span className="text-green-700 font-semibold">{q.correct_answer}</span>
                      </p>
                    </div>
                  )}
                </div>
              );
            })}
          </CardContent>
        </Card>

        <div className="flex gap-3 justify-center pb-8">
          <Button variant="outline" onClick={() => router.push("/exam")}>
            Thi lại
          </Button>
          <Button variant="outline" onClick={() => router.push("/knowledge")}>
            Bản đồ tri thức
          </Button>
          <Button onClick={() => router.push("/")}>
            Dashboard
          </Button>
        </div>
      </main>
    </div>
  );
}
