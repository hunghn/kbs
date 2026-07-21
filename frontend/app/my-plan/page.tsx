"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  authAPI, knowledgeAPI, personalAPI, quizAPI,
  type SubjectSummary, type StudyPlanInfo, type StudyPlanItemInfo,
  type MonthlyReportInfo, type AdaptiveExamInfo, type AnswerSubmit,
} from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { ExamInterface } from "@/components/quiz/exam-interface";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import { Play, CheckCircle2, Target, CalendarDays, TrendingUp, RefreshCw } from "lucide-react";

const ACTIVITY_LABEL: Record<string, string> = {
  practice: "Luyện topic",
  review: "Ôn lại (spaced repetition)",
  mock_exam: "Thi thử tổng hợp",
};

function ProjectionChart({ plan }: { plan: StudyPlanInfo }) {
  const proj = plan.projection?.projected_weekly || [];
  const actual = plan.actual_weekly || [];
  if (proj.length < 2) return null;

  const W = 620, H = 200, PAD = 36;
  const maxWeek = Math.max(proj[proj.length - 1].week, ...(actual.map((a) => a.week)), 1);
  const all = [...proj.map((p) => p.theta), ...actual.map((a) => a.theta), plan.goal_theta];
  const minY = Math.min(...all) - 0.2;
  const maxY = Math.max(...all) + 0.2;
  const x = (w: number) => PAD + (w / maxWeek) * (W - PAD * 2);
  const y = (v: number) => H - PAD - ((v - minY) / (maxY - minY)) * (H - PAD * 2);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
      <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="currentColor" strokeOpacity="0.25" />
      {/* Goal line */}
      <line x1={PAD} y1={y(plan.goal_theta)} x2={W - PAD} y2={y(plan.goal_theta)}
        stroke="#16a34a" strokeDasharray="6 4" strokeWidth="1.5" />
      <text x={W - PAD + 2} y={y(plan.goal_theta) + 4} fontSize="10" fill="#16a34a">
        mục tiêu {plan.goal_theta}
      </text>
      {/* Projection */}
      <polyline fill="none" stroke="#0284c7" strokeWidth="2" strokeDasharray="4 3"
        points={proj.map((p) => `${x(p.week)},${y(p.theta)}`).join(" ")} />
      {/* Actual */}
      {actual.length > 0 && (
        <polyline fill="none" stroke="#9333ea" strokeWidth="2.5"
          points={[`${x(0)},${y(plan.start_theta ?? actual[0].theta)}`,
            ...actual.map((a) => `${x(a.week)},${y(a.theta)}`)].join(" ")} />
      )}
      {actual.map((a, i) => (
        <circle key={i} cx={x(a.week)} cy={y(a.theta)} r="3.5" fill="#9333ea" />
      ))}
      {/* X labels */}
      {proj.filter((_p, i) => i % Math.ceil(proj.length / 8) === 0).map((p) => (
        <text key={p.week} x={x(p.week)} y={H - PAD + 14} fontSize="9" textAnchor="middle"
          fill="currentColor" fillOpacity="0.6">T{p.week}</text>
      ))}
      <text x={10} y={16} fontSize="10" fill="#0284c7">- - dự phóng</text>
      <text x={110} y={16} fontSize="10" fill="#9333ea">— thực tế</text>
    </svg>
  );
}

export default function MyPlanPage() {
  const router = useRouter();
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [subjectId, setSubjectId] = useState<number>(0);
  const [plan, setPlan] = useState<StudyPlanInfo | null>(null);
  const [planMissing, setPlanMissing] = useState(false);
  const [report, setReport] = useState<MonthlyReportInfo | null>(null);
  const [playing, setPlaying] = useState<{ item: StudyPlanItemInfo; exam: AdaptiveExamInfo } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const checkAuth = useCallback(async () => {
    try {
      const me = await authAPI.me();
      setUser(me);
      const subs = await knowledgeAPI.getSubjects();
      setSubjects(subs);
      const profile = await personalAPI.getProfile();
      if (!profile.onboarded && profile.active_plans.length === 0) {
        router.push("/onboarding");
        return;
      }
      const first = profile.active_plans[0]?.subject_id || subs[0]?.id || 0;
      setSubjectId(first);
    } catch {
      router.push("/");
    }
  }, [router]);

  useEffect(() => { checkAuth(); }, [checkAuth]);

  const loadPlan = useCallback(async (sid: number) => {
    setPlan(null);
    setReport(null);
    setPlanMissing(false);
    try {
      setPlan(await personalAPI.getPlan(sid));
    } catch {
      setPlanMissing(true);
    }
    try {
      setReport(await personalAPI.monthlyReport(sid));
    } catch {
      setReport(null);
    }
  }, []);

  useEffect(() => {
    if (subjectId) loadPlan(subjectId);
  }, [subjectId, loadPlan]);

  const startItem = async (item: StudyPlanItemInfo) => {
    setBusy(true);
    setError("");
    try {
      const started = await personalAPI.startItem(item.item_id);
      setPlaying({
        item,
        exam: {
          chain_id: 0,
          session_id: started.session_id,
          exam_index: 1,
          max_exams: 1,
          questions_per_exam: started.questions.length,
          questions: started.questions,
          theta: 0,
          sem: 999,
          applied_rules: [],
          strategy: "plan",
        },
      });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Không bắt đầu được buổi học");
    }
    setBusy(false);
  };

  const submitItem = async (answers: AnswerSubmit[]) => {
    if (!playing) return;
    await quizAPI.submit(playing.exam.session_id, answers);
    await personalAPI.completeItem(playing.item.item_id, playing.exam.session_id);
    const sessionId = playing.exam.session_id;
    setPlaying(null);
    await loadPlan(subjectId);
    router.push(`/results/${sessionId}`);
  };

  if (!user) return null;

  // Playing a plan session
  if (playing) {
    return (
      <div className="min-h-screen">
        <Navbar user={user} onLogout={() => { localStorage.removeItem("kbs_token"); router.push("/"); }} />
        <main className="container py-6 space-y-4">
          <div className="max-w-4xl mx-auto rounded-lg border bg-sky-50 p-3 text-sm">
            🎯 <b>{ACTIVITY_LABEL[playing.item.activity]}</b>
            {playing.item.topic_id ? ` — ${playing.item.topic_name}` : ""} · Tuần buổi {playing.item.day_name} ({playing.item.slot_name})
          </div>
          <ExamInterface exam={playing.exam} onSubmit={submitItem} />
        </main>
      </div>
    );
  }

  const currentWeek = (() => {
    if (!plan?.created_at) return 1;
    const days = Math.floor((Date.now() - new Date(plan.created_at).getTime()) / 86400000);
    return Math.max(1, Math.floor(days / 7) + 1);
  })();

  return (
    <div className="min-h-screen">
      <Navbar user={user} onLogout={() => { localStorage.removeItem("kbs_token"); router.push("/"); }} />
      <main className="container py-6 space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Lộ trình của tôi</h1>
            <p className="text-muted-foreground mt-1">
              Lộ trình tuần cá nhân hóa theo mục tiêu, lịch rảnh và kết quả test đầu vào
            </p>
          </div>
          <div className="flex gap-2">
            {subjects.map((s) => (
              <Button key={s.id} size="sm"
                variant={subjectId === s.id ? "default" : "outline"}
                onClick={() => setSubjectId(s.id)}>
                {s.name}
              </Button>
            ))}
          </div>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        {planMissing && (
          <Card>
            <CardContent className="py-10 text-center space-y-3">
              <p className="text-muted-foreground">Môn này chưa có lộ trình.</p>
              <Link href="/onboarding">
                <Button>Làm test đầu vào & dựng lộ trình</Button>
              </Link>
            </CardContent>
          </Card>
        )}

        {plan && (
          <>
            {/* Goal + progress + validation */}
            <div className="grid gap-4 md:grid-cols-3">
              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">Mục tiêu</CardTitle>
                  <Target className="h-4 w-4 text-primary" />
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{plan.goal_label}</div>
                  <p className="text-xs text-muted-foreground mt-1">
                    θ ≥ {plan.goal_theta} trong {plan.target_weeks} tuần
                    {plan.start_theta != null && ` · xuất phát θ = ${plan.start_theta}`}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">Tiến độ</CardTitle>
                  <CalendarDays className="h-4 w-4 text-green-600" />
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    {plan.progress.done}/{plan.progress.total} buổi
                  </div>
                  <Progress
                    value={plan.progress.total ? (plan.progress.done / plan.progress.total) * 100 : 0}
                    className="mt-2"
                  />
                </CardContent>
              </Card>
              <Card className={plan.projection?.feasible ? "border-green-300" : "border-orange-300"}>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">Kiểm chứng lộ trình</CardTitle>
                  <TrendingUp className="h-4 w-4 text-purple-500" />
                </CardHeader>
                <CardContent>
                  <div className={cn("text-lg font-bold", plan.projection?.feasible ? "text-green-700" : "text-orange-600")}>
                    {plan.projection?.feasible ? "✓ Khả thi" : "⚠ Cần điều chỉnh"}
                  </div>
                  {(plan.projection?.notes || []).map((n, i) => (
                    <p key={i} className="text-xs text-muted-foreground mt-0.5">{n}</p>
                  ))}
                </CardContent>
              </Card>
            </div>

            {/* Projection vs actual */}
            <Card>
              <CardHeader>
                <CardTitle>Đường tiến bộ: dự phóng vs thực tế</CardTitle>
                <CardDescription>
                  Đường đứt xanh: θ dự phóng theo mô hình learning-gain · đường tím: θ thực tế từ các bài đã làm · đường xanh lá: mục tiêu
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ProjectionChart plan={plan} />
              </CardContent>
            </Card>

            {/* Weekly schedule */}
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle>Lịch học theo tuần</CardTitle>
                  <CardDescription>
                    {plan.projection?.slots_per_week} buổi/tuần theo lịch rảnh của bạn · đang ở tuần {currentWeek}
                  </CardDescription>
                </div>
                <Button size="sm" variant="outline" disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await personalAPI.generatePlan({ subject_id: subjectId, goal: "gioi", target_weeks: plan.target_weeks });
                      await loadPlan(subjectId);
                    } finally { setBusy(false); }
                  }}>
                  <RefreshCw className="h-4 w-4 mr-1" /> Dựng lại theo trình độ mới
                </Button>
              </CardHeader>
              <CardContent className="space-y-4">
                {plan.weeks.map((w) => (
                  <div key={w.week_index} className={cn(
                    "rounded-lg border p-3",
                    w.week_index === currentWeek && "border-sky-400 bg-sky-50/50"
                  )}>
                    <p className="mb-2 text-sm font-semibold">
                      Tuần {w.week_index}
                      {w.week_index === currentWeek && <span className="ml-2 rounded bg-sky-600 px-1.5 py-0.5 text-xs text-white">tuần này</span>}
                    </p>
                    <div className="grid gap-2 md:grid-cols-2">
                      {w.items.map((it) => (
                        <div key={it.item_id} className={cn(
                          "flex items-center justify-between gap-2 rounded-md border p-2.5 text-sm",
                          it.status === "done" && "bg-green-50 border-green-200"
                        )}>
                          <div className="min-w-0">
                            <p className="font-medium truncate">
                              {it.day_name} · {it.slot_name} — {it.topic_name}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              {ACTIVITY_LABEL[it.activity]}
                              {it.status === "done" && it.result_total
                                ? ` · ${it.result_score}/${it.result_total} đúng`
                                : ""}
                            </p>
                          </div>
                          {it.status === "done" ? (
                            <CheckCircle2 className="h-5 w-5 shrink-0 text-green-600" />
                          ) : (
                            <Button size="sm" className="h-8 shrink-0" disabled={busy}
                              onClick={() => startItem(it)}>
                              <Play className="h-3.5 w-3.5 mr-1" /> Học ngay
                            </Button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          </>
        )}

        {/* Monthly report */}
        {report && report.sessions_completed > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Tổng kết 30 ngày</CardTitle>
              <CardDescription>
                {report.sessions_completed} bài đã hoàn thành
                {report.plan_progress && ` · ${report.plan_progress.done_this_month} buổi lộ trình trong tháng`}
                {report.theta_delta != null && (
                  <> · θ thay đổi <b className={report.theta_delta >= 0 ? "text-green-700" : "text-red-600"}>
                    {report.theta_delta >= 0 ? "+" : ""}{report.theta_delta}
                  </b> ({report.theta_start} → {report.theta_now})</>
                )}
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2">
              <div>
                <p className="mb-2 text-sm font-medium text-red-700">Cần cải thiện</p>
                <div className="space-y-1.5">
                  {report.weak_topics.length === 0 && <p className="text-xs text-muted-foreground">Chưa đủ dữ liệu</p>}
                  {report.weak_topics.map((t) => (
                    <div key={t.topic_id} className="flex items-center gap-2 text-xs">
                      <span className="flex-1 truncate">{t.topic_name}</span>
                      <Progress value={t.accuracy * 100} className="h-2 w-28" />
                      <span className="w-14 text-right text-muted-foreground">{t.correct}/{t.total} đúng</span>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <p className="mb-2 text-sm font-medium text-green-700">Đang làm tốt</p>
                <div className="space-y-1.5">
                  {report.improved_topics.length === 0 && <p className="text-xs text-muted-foreground">Chưa đủ dữ liệu</p>}
                  {report.improved_topics.map((t) => (
                    <div key={t.topic_id} className="flex items-center gap-2 text-xs">
                      <span className="flex-1 truncate">{t.topic_name}</span>
                      <Progress value={t.accuracy * 100} className="h-2 w-28" />
                      <span className="w-14 text-right text-muted-foreground">{t.correct}/{t.total} đúng</span>
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </main>
    </div>
  );
}
