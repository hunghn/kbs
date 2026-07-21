"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import {
  personalAPI, knowledgeAPI,
  type PersonalProfileInfo, type StudyPlanInfo, type SubjectSummary, type StudyPlanItemInfo,
} from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  Play, Sparkles, FileText, Map as MapIcon, BarChart3, Rocket,
  CheckCircle2, Flame, ChevronRight,
} from "lucide-react";

interface LearnerHomeProps {
  user: { id: number; username: string };
}

/** Vòng tiến độ tới mục tiêu (θ hiện tại giữa θ xuất phát và θ đích). */
function GoalRing({ plan, subjectName }: { plan: StudyPlanInfo; subjectName: string }) {
  const actual = plan.actual_weekly || [];
  const now = actual.length > 0 ? actual[actual.length - 1].theta : plan.start_theta ?? 0;
  const start = plan.start_theta ?? 0;
  const span = Math.max(0.05, plan.goal_theta - start);
  const pct = Math.max(0, Math.min(1, (now - start) / span));
  const R = 34, C = 2 * Math.PI * R;
  return (
    <div className="flex items-center gap-3">
      <div className="relative h-20 w-20 shrink-0">
        <svg viewBox="0 0 80 80" className="h-20 w-20 -rotate-90">
          <circle cx="40" cy="40" r={R} fill="none" stroke="white" strokeOpacity="0.25" strokeWidth="8" />
          <circle cx="40" cy="40" r={R} fill="none" stroke="white" strokeWidth="8"
            strokeLinecap="round" strokeDasharray={C} strokeDashoffset={C * (1 - pct)} />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-sm font-bold text-white">
          {Math.round(pct * 100)}%
        </span>
      </div>
      <div className="text-white">
        <p className="text-sm font-semibold leading-tight">{subjectName}</p>
        <p className="text-xs opacity-85">
          θ {now.toFixed(2)} / mục tiêu {plan.goal_theta} ({plan.goal_label})
        </p>
      </div>
    </div>
  );
}

/** Path tuần này kiểu Duolingo: chuỗi node buổi học nối nhau. */
function WeekPath({ items, onStart }: { items: StudyPlanItemInfo[]; onStart: () => void }) {
  const firstPendingIdx = items.findIndex((i) => i.status !== "done");
  return (
    <div className="flex items-start gap-0 overflow-x-auto pb-2">
      {items.map((it, idx) => {
        const done = it.status === "done";
        const current = idx === firstPendingIdx;
        return (
          <div key={it.item_id} className="flex items-start">
            {idx > 0 && (
              <div className={cn("mt-6 h-1 w-8 md:w-14 rounded", done || idx <= firstPendingIdx ? "bg-sky-400" : "bg-slate-200")} />
            )}
            <div className="flex w-24 flex-col items-center text-center">
              <button
                type="button"
                onClick={() => current && onStart()}
                className={cn(
                  "flex h-12 w-12 items-center justify-center rounded-full border-4 text-white shadow-md transition-transform",
                  done
                    ? "border-green-200 bg-green-500"
                    : current
                      ? "border-sky-200 bg-sky-500 animate-pulse cursor-pointer hover:scale-110"
                      : "border-slate-100 bg-slate-300"
                )}
                title={it.topic_name}
              >
                {done ? <CheckCircle2 className="h-6 w-6" /> : current ? <Play className="h-5 w-5" /> : idx + 1}
              </button>
              <p className="mt-1.5 line-clamp-2 text-[11px] leading-tight text-muted-foreground">
                {it.day_name} {it.slot_name}
                <br />
                <span className="font-medium text-foreground">{it.topic_name}</span>
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function LearnerHome({ user }: LearnerHomeProps) {
  const [profile, setProfile] = useState<PersonalProfileInfo | null>(null);
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [plans, setPlans] = useState<Record<number, StudyPlanInfo>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [prof, subs] = await Promise.all([
          personalAPI.getProfile(),
          knowledgeAPI.getSubjects(),
        ]);
        setProfile(prof);
        setSubjects(subs);
        const loaded: Record<number, StudyPlanInfo> = {};
        await Promise.all(
          prof.active_plans.map(async (p) => {
            try {
              loaded[p.subject_id] = await personalAPI.getPlan(p.subject_id);
            } catch { /* plan may be missing */ }
          })
        );
        setPlans(loaded);
      } catch { /* ignore */ }
      setLoading(false);
    })();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary" />
      </div>
    );
  }

  const onboarded = profile?.onboarded && (profile?.active_plans.length || 0) > 0;
  const planList = Object.values(plans);

  // Buổi học tiếp theo (buổi pending đầu tiên của tuần hiện tại, mọi lộ trình)
  const nextUp = (() => {
    for (const plan of planList) {
      const createdAt = plan.created_at ? new Date(plan.created_at).getTime() : Date.now();
      const currentWeek = Math.max(1, Math.floor((Date.now() - createdAt) / (7 * 86400000)) + 1);
      const week = plan.weeks.find((w) => w.week_index === currentWeek) || plan.weeks.find((w) => w.items.some((i) => i.status !== "done"));
      const item = week?.items.find((i) => i.status !== "done");
      if (item) {
        const subjectName = subjects.find((s) => s.id === plan.subject_id)?.name || "";
        return { plan, item, subjectName, week: week!.week_index };
      }
    }
    return null;
  })();

  const doneThisWeek = planList.reduce((acc, plan) => {
    const createdAt = plan.created_at ? new Date(plan.created_at).getTime() : Date.now();
    const currentWeek = Math.max(1, Math.floor((Date.now() - createdAt) / (7 * 86400000)) + 1);
    const week = plan.weeks.find((w) => w.week_index === currentWeek);
    return acc + (week?.items.filter((i) => i.status === "done").length || 0);
  }, 0);

  return (
    <main className="container py-6 space-y-6">
      {/* ---------- Hero ---------- */}
      <div className="overflow-hidden rounded-3xl bg-gradient-to-br from-sky-500 via-sky-600 to-blue-700 p-6 md:p-8 shadow-lg">
        <div className="flex flex-wrap items-center justify-between gap-6">
          <div className="space-y-1.5">
            <p className="text-2xl md:text-3xl font-bold text-white">
              Chào {user.username} 👋
            </p>
            <p className="text-sky-100">
              {onboarded
                ? nextUp
                  ? "Hôm nay là ngày tuyệt vời để tiến thêm một bước!"
                  : "Bạn đã hoàn thành mọi buổi học trong lộ trình 🎉"
                : "Thiết lập lộ trình cá nhân để bắt đầu hành trình của bạn"}
            </p>
            {onboarded && (
              <p className="flex items-center gap-1.5 pt-1 text-sm font-medium text-amber-200">
                <Flame className="h-4 w-4" /> {doneThisWeek} buổi hoàn thành tuần này
              </p>
            )}
          </div>
          {onboarded ? (
            <div className="flex flex-wrap gap-6">
              {planList.map((plan) => (
                <GoalRing
                  key={plan.plan_id}
                  plan={plan}
                  subjectName={subjects.find((s) => s.id === plan.subject_id)?.name || ""}
                />
              ))}
            </div>
          ) : (
            <Link href="/onboarding">
              <Button size="lg" className="bg-white text-sky-700 hover:bg-sky-50">
                <Rocket className="h-5 w-5 mr-2" /> Bắt đầu thiết lập (3 phút)
              </Button>
            </Link>
          )}
        </div>
      </div>

      {/* ---------- Buổi học hôm nay ---------- */}
      {onboarded && nextUp && (
        <Card className="border-2 border-sky-200 shadow-sm">
          <CardContent className="flex flex-wrap items-center justify-between gap-4 py-5">
            <div className="flex items-center gap-4">
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-sky-100">
                <Play className="h-7 w-7 text-sky-600" />
              </span>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-sky-600">
                  Buổi học tiếp theo · Tuần {nextUp.week} · {nextUp.item.day_name} {nextUp.item.slot_name}
                </p>
                <p className="text-lg font-bold">
                  {nextUp.item.topic_name}
                  <span className="ml-2 text-sm font-normal text-muted-foreground">
                    {nextUp.subjectName} · {nextUp.item.activity === "mock_exam" ? "10 câu" : "5 câu"} · ~10 phút
                  </span>
                </p>
              </div>
            </div>
            <Link href="/my-plan">
              <Button size="lg">
                Học ngay <ChevronRight className="h-5 w-5 ml-1" />
              </Button>
            </Link>
          </CardContent>
        </Card>
      )}

      {/* ---------- Path tuần này ---------- */}
      {onboarded && planList.length > 0 && (
        <Card>
          <CardContent className="py-5 space-y-4">
            {planList.map((plan) => {
              const createdAt = plan.created_at ? new Date(plan.created_at).getTime() : Date.now();
              const currentWeek = Math.max(1, Math.floor((Date.now() - createdAt) / (7 * 86400000)) + 1);
              const week = plan.weeks.find((w) => w.week_index === currentWeek) || plan.weeks[0];
              if (!week) return null;
              const subjectName = subjects.find((s) => s.id === plan.subject_id)?.name || "";
              return (
                <div key={plan.plan_id}>
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-sm font-semibold">
                      {subjectName} — Tuần {week.week_index}
                      {plan.projection && (
                        <span className={cn(
                          "ml-2 rounded-full px-2 py-0.5 text-xs",
                          plan.projection.feasible ? "bg-green-100 text-green-700" : "bg-orange-100 text-orange-700"
                        )}>
                          {plan.projection.feasible ? "✓ đúng tiến độ mục tiêu" : "⚠ cần thêm buổi học"}
                        </span>
                      )}
                    </p>
                    <Link href="/my-plan" className="text-xs font-medium text-primary hover:underline">
                      Xem cả lộ trình →
                    </Link>
                  </div>
                  <WeekPath items={week.items} onStart={() => { window.location.href = "/my-plan"; }} />
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {/* ---------- Khám phá ---------- */}
      <div className="grid gap-4 md:grid-cols-4">
        {[
          { href: "/quiz", icon: Sparkles, title: "Thi thích ứng", desc: "Chuỗi đề tự điều chỉnh độ khó theo bạn", color: "bg-violet-100 text-violet-600" },
          { href: "/quiz", icon: FileText, title: "Đề có sẵn", desc: "10 đề/môn phân bổ chuẩn Bloom", color: "bg-amber-100 text-amber-600" },
          { href: "/knowledge", icon: MapIcon, title: "Bản đồ năng lực", desc: "Đồ thị tri thức tô màu mastery của bạn", color: "bg-emerald-100 text-emerald-600" },
          { href: "/stats", icon: BarChart3, title: "Thống kê chi tiết", desc: "Radar năng lực, dự đoán DKT, lịch sử", color: "bg-sky-100 text-sky-600" },
        ].map(({ href, icon: Icon, title, desc, color }) => (
          <Link key={title} href={href}>
            <Card className="h-full transition-all hover:-translate-y-0.5 hover:shadow-md">
              <CardContent className="py-5 space-y-2">
                <span className={cn("inline-flex h-11 w-11 items-center justify-center rounded-xl", color)}>
                  <Icon className="h-5.5 w-5.5" size={22} />
                </span>
                <p className="font-semibold">{title}</p>
                <p className="text-xs text-muted-foreground">{desc}</p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </main>
  );
}
