"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  authAPI, knowledgeAPI, evaluationAPI,
  type SubjectSummary, type ConvergenceReportInfo,
} from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LineChart, Play } from "lucide-react";

const STRATEGY_LABEL: Record<string, string> = {
  rules: "Luật R1-R12 (hệ thống)",
  fisher: "Fisher tối ưu",
  random: "Ngẫu nhiên",
  rl: "Reinforcement Learning",
};

const STRATEGY_COLOR: Record<string, string> = {
  rules: "#0284c7",
  fisher: "#9333ea",
  random: "#dc2626",
  rl: "#16a34a",
};

function SemChart({ report }: { report: ConvergenceReportInfo }) {
  const maxExams = Math.max(...report.strategies.map((s) => s.mean_sem_by_exam.length));
  if (maxExams < 1) return null;
  const allVals = report.strategies.flatMap((s) => s.mean_sem_by_exam);
  const maxY = Math.max(...allVals, report.sem_stop) * 1.1;
  const W = 620, H = 220, PAD = 40;

  const x = (i: number) => PAD + (i / Math.max(maxExams - 1, 1)) * (W - PAD * 2);
  const y = (v: number) => H - PAD - (v / maxY) * (H - PAD * 2);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
      {/* axes */}
      <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="currentColor" strokeOpacity="0.3" />
      <line x1={PAD} y1={PAD / 2} x2={PAD} y2={H - PAD} stroke="currentColor" strokeOpacity="0.3" />
      {/* SEM stop threshold */}
      <line x1={PAD} y1={y(report.sem_stop)} x2={W - PAD} y2={y(report.sem_stop)}
        stroke="#16a34a" strokeDasharray="5 4" strokeWidth="1.5" />
      <text x={W - PAD + 2} y={y(report.sem_stop) + 4} fontSize="10" fill="#16a34a">
        {report.sem_stop}
      </text>
      {/* series */}
      {report.strategies.map((s) => (
        <g key={s.strategy}>
          <polyline
            fill="none"
            stroke={STRATEGY_COLOR[s.strategy] || "#64748b"}
            strokeWidth="2"
            points={s.mean_sem_by_exam.map((v, i) => `${x(i)},${y(v)}`).join(" ")}
          />
          {s.mean_sem_by_exam.map((v, i) => (
            <circle key={i} cx={x(i)} cy={y(v)} r="3" fill={STRATEGY_COLOR[s.strategy] || "#64748b"} />
          ))}
        </g>
      ))}
      {/* x labels */}
      {Array.from({ length: maxExams }).map((_, i) => (
        <text key={i} x={x(i)} y={H - PAD + 15} fontSize="10" textAnchor="middle" fill="currentColor" fillOpacity="0.6">
          Đề {i + 1}
        </text>
      ))}
      <text x={12} y={PAD / 2 + 4} fontSize="10" fill="currentColor" fillOpacity="0.6">SEM</text>
    </svg>
  );
}

export default function EvaluationPage() {
  const router = useRouter();
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [subjectId, setSubjectId] = useState<number>(0);
  const [nStudents, setNStudents] = useState(20);
  const [perExam, setPerExam] = useState(6);
  const [maxExams, setMaxExams] = useState(5);
  const [includeRl, setIncludeRl] = useState(true);
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<ConvergenceReportInfo | null>(null);
  const [error, setError] = useState("");

  const checkAuth = useCallback(async () => {
    try {
      const me = await authAPI.me();
      setUser(me);
      const subs = await knowledgeAPI.getSubjects();
      setSubjects(subs);
      if (subs.length > 0) setSubjectId(subs[0].id);
    } catch {
      router.push("/");
    }
  }, [router]);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const runStudy = async () => {
    if (!subjectId) return;
    setRunning(true);
    setError("");
    try {
      const rep = await evaluationAPI.convergence({
        subject_id: subjectId,
        n_students: nStudents,
        questions_per_exam: perExam,
        max_exams: maxExams,
        include_rl: includeRl,
      });
      setReport(rep);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Có lỗi xảy ra");
    }
    setRunning(false);
  };

  if (!user) return null;

  return (
    <div className="min-h-screen">
      <Navbar user={user} onLogout={() => { localStorage.removeItem("kbs_token"); router.push("/"); }} />
      <main className="container py-6 space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Đánh giá độ hội tụ năng lực</h1>
          <p className="text-muted-foreground mt-1">
            Mô phỏng sinh viên có năng lực θ thật đã biết, so sánh chiến lược sinh đề của hệ thống
            (luật R1-R12) với Fisher tối ưu và chọn ngẫu nhiên
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <LineChart className="h-5 w-5" />
              Tham số mô phỏng
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Môn học</Label>
              <div className="flex flex-wrap gap-2">
                {subjects.map((s) => (
                  <Button
                    key={s.id}
                    variant={subjectId === s.id ? "default" : "outline"}
                    size="sm"
                    onClick={() => setSubjectId(s.id)}
                  >
                    {s.name} ({s.total_questions})
                  </Button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Số SV giả lập (5-60)</Label>
                <Input type="number" min={5} max={60} value={nStudents}
                  onChange={(e) => setNStudents(parseInt(e.target.value) || 20)} />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Số câu mỗi đề</Label>
                <Input type="number" min={3} max={20} value={perExam}
                  onChange={(e) => setPerExam(parseInt(e.target.value) || 6)} />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Số đề tối đa</Label>
                <Input type="number" min={1} max={8} value={maxExams}
                  onChange={(e) => setMaxExams(parseInt(e.target.value) || 5)} />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={includeRl}
                onChange={(e) => setIncludeRl(e.target.checked)}
                className="h-4 w-4"
              />
              Thêm chiến lược Reinforcement Learning (bandit học qua các sinh viên giả lập)
            </label>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button onClick={runStudy} disabled={running || !subjectId}>
              <Play className="h-4 w-4 mr-2" />
              {running ? "Đang mô phỏng..." : "Chạy mô phỏng"}
            </Button>
          </CardContent>
        </Card>

        {report && (
          <>
            <Card>
              <CardHeader>
                <CardTitle>Kết quả so sánh chiến lược</CardTitle>
                <CardDescription>
                  {report.n_students} sinh viên (θ thật trải đều [-2.5, 2.5]) ·{" "}
                  {report.questions_per_exam} câu/đề · tối đa {report.max_exams} đề ·
                  ngân hàng {report.pool_size} câu · dừng khi SEM &lt; {report.sem_stop}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left text-muted-foreground">
                        <th className="py-2 pr-4">Chiến lược</th>
                        <th className="py-2 pr-4">Bias</th>
                        <th className="py-2 pr-4">RMSE ↓</th>
                        <th className="py-2 pr-4">MAE ↓</th>
                        <th className="py-2 pr-4">Tương quan ↑</th>
                        <th className="py-2 pr-4">Tỷ lệ hội tụ</th>
                        <th className="py-2">Số câu TB</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.strategies.map((s) => (
                        <tr key={s.strategy} className="border-b last:border-0">
                          <td className="py-2 pr-4 font-medium">
                            <span className="inline-block h-2.5 w-2.5 rounded-full mr-2"
                              style={{ backgroundColor: STRATEGY_COLOR[s.strategy] || "#64748b" }} />
                            {STRATEGY_LABEL[s.strategy] || s.strategy}
                          </td>
                          <td className="py-2 pr-4">{s.bias.toFixed(3)}</td>
                          <td className="py-2 pr-4 font-semibold">{s.rmse.toFixed(3)}</td>
                          <td className="py-2 pr-4">{s.mae.toFixed(3)}</td>
                          <td className="py-2 pr-4 font-semibold">{s.correlation.toFixed(3)}</td>
                          <td className="py-2 pr-4">{Math.round(s.convergence_rate * 100)}%</td>
                          <td className="py-2">{s.mean_items_used}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Quỹ đạo hội tụ SEM theo số đề</CardTitle>
                <CardDescription>
                  SEM trung bình (posterior SD của Bayesian EAP) sau mỗi đề — đường xanh lá là ngưỡng dừng
                </CardDescription>
              </CardHeader>
              <CardContent>
                <SemChart report={report} />
                <div className="flex flex-wrap gap-4 mt-2 text-xs">
                  {report.strategies.map((s) => (
                    <span key={s.strategy} className="flex items-center gap-1.5">
                      <span className="inline-block h-2.5 w-2.5 rounded-full"
                        style={{ backgroundColor: STRATEGY_COLOR[s.strategy] || "#64748b" }} />
                      {STRATEGY_LABEL[s.strategy] || s.strategy}
                    </span>
                  ))}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>θ ước lượng so với θ thật (chiến lược của hệ thống)</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto max-h-72 overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left text-muted-foreground sticky top-0 bg-background">
                        <th className="py-1.5 pr-4">θ thật</th>
                        <th className="py-1.5 pr-4">θ ước lượng</th>
                        <th className="py-1.5 pr-4">Sai số</th>
                        <th className="py-1.5 pr-4">Số câu</th>
                        <th className="py-1.5 pr-4">SEM cuối</th>
                        <th className="py-1.5">Hội tụ</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(report.strategies.find((s) => s.strategy === "rules")?.students || []).map((st, i) => (
                        <tr key={i} className="border-b last:border-0">
                          <td className="py-1.5 pr-4">{st.true_theta.toFixed(2)}</td>
                          <td className="py-1.5 pr-4">{st.theta_hat.toFixed(2)}</td>
                          <td className={`py-1.5 pr-4 ${Math.abs(st.error) > 0.5 ? "text-red-600" : "text-green-700"}`}>
                            {st.error > 0 ? "+" : ""}{st.error.toFixed(2)}
                          </td>
                          <td className="py-1.5 pr-4">{st.items_used}</td>
                          <td className="py-1.5 pr-4">{st.final_sem.toFixed(3)}</td>
                          <td className="py-1.5">{st.converged ? "✓" : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          </>
        )}
      </main>
    </div>
  );
}
