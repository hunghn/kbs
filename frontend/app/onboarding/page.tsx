"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  authAPI, knowledgeAPI, personalAPI, quizAPI,
  type SubjectSummary, type AvailabilitySlot, type AdaptiveExamInfo, type AnswerSubmit,
} from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { ExamInterface } from "@/components/quiz/exam-interface";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Target, CalendarDays, ClipboardCheck, Rocket } from "lucide-react";

const DAY_NAMES = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
const SLOTS: { key: "sang" | "chieu" | "toi"; label: string }[] = [
  { key: "sang", label: "Sáng" },
  { key: "chieu", label: "Chiều" },
  { key: "toi", label: "Tối" },
];
const GOALS = [
  { key: "kha", label: "Khá", desc: "θ ≥ 0.5 — nắm vững kiến thức cốt lõi" },
  { key: "gioi", label: "Giỏi", desc: "θ ≥ 1.0 — vận dụng thành thạo" },
  { key: "xuat_sac", label: "Xuất sắc", desc: "θ ≥ 1.5 — giải quyết vấn đề phức tạp" },
];

type SubjectSetup = { goal: string; weeks: number; placementDone: boolean };

export default function OnboardingPage() {
  const router = useRouter();
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [step, setStep] = useState(1);
  const [setups, setSetups] = useState<Record<number, SubjectSetup>>({});
  const [availability, setAvailability] = useState<Set<string>>(new Set());
  const [placementSubject, setPlacementSubject] = useState<number | null>(null);
  const [placementExam, setPlacementExam] = useState<AdaptiveExamInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const checkAuth = useCallback(async () => {
    try {
      const me = await authAPI.me();
      setUser(me);
      const subs = await knowledgeAPI.getSubjects();
      setSubjects(subs);
      setSetups(Object.fromEntries(subs.map((s) => [s.id, { goal: "gioi", weeks: 8, placementDone: false }])));
      const profile = await personalAPI.getProfile();
      if (profile.availability.length > 0) {
        setAvailability(new Set(profile.availability.map((a) => `${a.day}:${a.slot}`)));
      }
    } catch {
      router.push("/");
    }
  }, [router]);

  useEffect(() => { checkAuth(); }, [checkAuth]);

  const toggleSlot = (day: number, slot: string) => {
    const key = `${day}:${slot}`;
    setAvailability((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const availabilityList = (): AvailabilitySlot[] =>
    Array.from(availability).map((k) => {
      const [d, s] = k.split(":");
      return { day: parseInt(d), slot: s as AvailabilitySlot["slot"] };
    });

  const saveAvailabilityAndNext = async () => {
    if (availability.size === 0) {
      setError("Chọn ít nhất 1 buổi rảnh mỗi tuần");
      return;
    }
    setError("");
    setBusy(true);
    try {
      await personalAPI.saveProfile({ availability: availabilityList() });
      setStep(3);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Có lỗi xảy ra");
    }
    setBusy(false);
  };

  const startPlacement = async (subjectId: number) => {
    setBusy(true);
    setError("");
    try {
      const started = await personalAPI.startPlacement(subjectId);
      setPlacementSubject(subjectId);
      setPlacementExam({
        chain_id: 0,
        session_id: started.session_id,
        exam_index: 1,
        max_exams: 1,
        questions_per_exam: started.questions.length,
        questions: started.questions,
        theta: 0,
        sem: 999,
        applied_rules: [],
        strategy: "placement",
      });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Không tạo được bài test");
    }
    setBusy(false);
  };

  const submitPlacement = async (answers: AnswerSubmit[]) => {
    if (!placementExam || !placementSubject) return;
    await quizAPI.submit(placementExam.session_id, answers);
    setSetups((prev) => ({
      ...prev,
      [placementSubject]: { ...prev[placementSubject], placementDone: true },
    }));
    setPlacementExam(null);
    setPlacementSubject(null);
  };

  const finishOnboarding = async () => {
    setBusy(true);
    setError("");
    try {
      for (const s of subjects) {
        const cfg = setups[s.id];
        if (cfg?.placementDone) {
          await personalAPI.generatePlan({
            subject_id: s.id,
            goal: cfg.goal,
            target_weeks: cfg.weeks,
          });
        }
      }
      await personalAPI.saveProfile({ availability: availabilityList(), onboarded: true });
      router.push("/my-plan");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Không sinh được lộ trình");
      setBusy(false);
    }
  };

  if (!user) return null;

  const doneCount = subjects.filter((s) => setups[s.id]?.placementDone).length;

  // Placement exam in progress: full-screen exam
  if (placementExam) {
    return (
      <div className="min-h-screen">
        <Navbar user={user} onLogout={() => { localStorage.removeItem("kbs_token"); router.push("/"); }} />
        <main className="container py-6 space-y-4">
          <div className="max-w-4xl mx-auto rounded-lg border bg-sky-50 p-3 text-sm">
            📋 <b>Bài test đầu vào</b> — {subjects.find((s) => s.id === placementSubject)?.name}.
            Làm hết sức để hệ thống đo đúng trình độ và xếp lộ trình phù hợp.
          </div>
          <ExamInterface exam={placementExam} onSubmit={submitPlacement} />
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <Navbar user={user} onLogout={() => { localStorage.removeItem("kbs_token"); router.push("/"); }} />
      <main className="container py-6 max-w-3xl mx-auto space-y-6">
        <div className="text-center">
          <h1 className="text-3xl font-bold tracking-tight">Thiết lập lộ trình cá nhân</h1>
          <p className="text-muted-foreground mt-1">
            3 bước: đặt mục tiêu → chọn lịch rảnh → test đầu vào — hệ thống sẽ dựng lộ trình học theo tuần cho bạn
          </p>
        </div>

        {/* Step indicator */}
        <div className="flex items-center justify-center gap-2 text-sm">
          {[
            { n: 1, label: "Mục tiêu", icon: Target },
            { n: 2, label: "Lịch rảnh", icon: CalendarDays },
            { n: 3, label: "Test đầu vào", icon: ClipboardCheck },
          ].map(({ n, label, icon: Icon }) => (
            <span key={n} className={cn(
              "flex items-center gap-1.5 rounded-full px-3 py-1.5",
              step === n ? "bg-sky-600 text-white" : step > n ? "bg-green-100 text-green-800" : "bg-muted text-muted-foreground"
            )}>
              <Icon className="h-4 w-4" /> {label}
            </span>
          ))}
        </div>

        {error && <p className="text-center text-sm text-destructive">{error}</p>}

        {step === 1 && (
          <Card>
            <CardHeader>
              <CardTitle>Mục tiêu của bạn</CardTitle>
              <CardDescription>Chọn mức muốn đạt và thời gian cho từng môn</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              {subjects.map((s) => (
                <div key={s.id} className="rounded-lg border p-4 space-y-3">
                  <p className="font-semibold">{s.name}</p>
                  <div className="grid gap-2 md:grid-cols-3">
                    {GOALS.map((g) => (
                      <button key={g.key} type="button"
                        onClick={() => setSetups((prev) => ({ ...prev, [s.id]: { ...prev[s.id], goal: g.key } }))}
                        className={cn(
                          "rounded-lg border p-2.5 text-left text-sm transition-colors",
                          setups[s.id]?.goal === g.key ? "border-primary bg-primary/10" : "hover:bg-accent"
                        )}>
                        <p className="font-medium">{g.label}</p>
                        <p className="text-xs text-muted-foreground">{g.desc}</p>
                      </button>
                    ))}
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-muted-foreground">Thời gian:</span>
                    {[4, 8, 12].map((w) => (
                      <Button key={w} size="sm"
                        variant={setups[s.id]?.weeks === w ? "default" : "outline"}
                        onClick={() => setSetups((prev) => ({ ...prev, [s.id]: { ...prev[s.id], weeks: w } }))}>
                        {w} tuần
                      </Button>
                    ))}
                  </div>
                </div>
              ))}
              <Button className="w-full" onClick={() => setStep(2)}>Tiếp tục</Button>
            </CardContent>
          </Card>
        )}

        {step === 2 && (
          <Card>
            <CardHeader>
              <CardTitle>Bạn rảnh những buổi nào?</CardTitle>
              <CardDescription>
                Lộ trình sẽ xếp đúng vào các buổi này — chọn càng nhiều, về đích càng nhanh
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="overflow-x-auto">
                <table className="w-full text-center text-sm">
                  <thead>
                    <tr>
                      <th className="p-1.5"></th>
                      {DAY_NAMES.map((d) => <th key={d} className="p-1.5 font-medium">{d}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {SLOTS.map(({ key, label }) => (
                      <tr key={key}>
                        <td className="p-1.5 text-left font-medium text-muted-foreground">{label}</td>
                        {DAY_NAMES.map((_d, day) => {
                          const active = availability.has(`${day}:${key}`);
                          return (
                            <td key={day} className="p-1">
                              <button type="button" onClick={() => toggleSlot(day, key)}
                                className={cn(
                                  "h-9 w-full min-w-10 rounded-md border transition-colors",
                                  active ? "border-sky-600 bg-sky-500 text-white" : "hover:bg-accent"
                                )}>
                                {active ? "✓" : ""}
                              </button>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-muted-foreground">
                Đã chọn {availability.size} buổi/tuần
              </p>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setStep(1)}>Quay lại</Button>
                <Button className="flex-1" onClick={saveAvailabilityAndNext} disabled={busy}>
                  {busy ? "Đang lưu..." : "Tiếp tục"}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {step === 3 && (
          <Card>
            <CardHeader>
              <CardTitle>Test đầu vào</CardTitle>
              <CardDescription>
                12 câu mỗi môn, trải đều độ khó và chủ đề — kết quả quyết định điểm xuất phát của lộ trình
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {subjects.map((s) => {
                const done = setups[s.id]?.placementDone;
                return (
                  <div key={s.id} className="flex items-center justify-between rounded-lg border p-3">
                    <div>
                      <p className="font-medium">{s.name}</p>
                      <p className="text-xs text-muted-foreground">
                        Mục tiêu: {GOALS.find((g) => g.key === setups[s.id]?.goal)?.label} · {setups[s.id]?.weeks} tuần
                      </p>
                    </div>
                    {done ? (
                      <span className="rounded-full bg-green-100 px-3 py-1 text-sm font-medium text-green-800">
                        ✓ Đã hoàn thành
                      </span>
                    ) : (
                      <Button size="sm" onClick={() => startPlacement(s.id)} disabled={busy}>
                        Làm bài test
                      </Button>
                    )}
                  </div>
                );
              })}
              <div className="flex gap-2 pt-2">
                <Button variant="outline" onClick={() => setStep(2)}>Quay lại</Button>
                <Button className="flex-1" onClick={finishOnboarding} disabled={busy || doneCount === 0}>
                  <Rocket className="h-4 w-4 mr-2" />
                  {busy ? "Đang dựng lộ trình..." : `Dựng lộ trình (${doneCount}/${subjects.length} môn đã test)`}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Có thể test một môn trước, môn còn lại làm sau từ trang Lộ trình.
              </p>
            </CardContent>
          </Card>
        )}
      </main>
    </div>
  );
}
