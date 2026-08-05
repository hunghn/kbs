"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  authAPI, knowledgeAPI, builderAPI,
  type SubjectSummary, type TopicInfo, type BuildDraftInfo, type BuilderItemInfo,
} from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { MathContent } from "@/components/common/math-content";
import { QuestionAnswerPreview } from "@/components/common/question-answer-preview";
import { FORMAT_LABEL, normalizeFormat } from "@/lib/question-format";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { Hammer, RefreshCw, Save, ArrowLeft, Check, X } from "lucide-react";

function ValidationBadges({ item }: { item: BuilderItemInfo }) {
  if (item.source === "bank") {
    return <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700">Ngân hàng — đã hiệu chuẩn</span>;
  }
  const sc = item.validation?.self_check;
  const gm = item.validation?.gemini;
  return (
    <span className="flex flex-wrap gap-1.5">
      {sc && !sc.error && (
        <span className={cn(
          "rounded px-2 py-0.5 text-xs font-medium",
          sc.agrees ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
        )}>
          Self-check {sc.agrees ? "✓" : `✗ (giải ra ${sc.solved_answer})`}
          {sc.estimated_b != null && ` · b≈${sc.estimated_b}`}
        </span>
      )}
      {sc?.error && (
        <span className="rounded bg-yellow-100 px-2 py-0.5 text-xs text-yellow-800">Self-check lỗi</span>
      )}
      {gm && (
        <span className={cn(
          "rounded px-2 py-0.5 text-xs font-medium",
          !gm.enabled ? "bg-slate-100 text-slate-600"
            : gm.agree ? "bg-green-100 text-green-800"
            : gm.agree === false ? "bg-red-100 text-red-800"
            : "bg-yellow-100 text-yellow-800"
        )}>
          Gemini {!gm.enabled ? "tắt" : gm.agree ? "✓ đồng thuận" : gm.agree === false ? "✗ bất đồng" : "?"}
        </span>
      )}
    </span>
  );
}

export default function ExamBuilderPage() {
  const router = useRouter();
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [topics, setTopics] = useState<TopicInfo[]>([]);
  const [subjectId, setSubjectId] = useState<number>(0);
  const [selectedTopics, setSelectedTopics] = useState<Set<number>>(new Set());
  const [counts, setCounts] = useState({ mcq: 10, true_false: 3, short_answer: 2, matching: 0 });
  const [pcts, setPcts] = useState({ recognition: 30, comprehension: 50, application: 20 });
  const [anchorMode, setAnchorMode] = useState<"manual" | "learners">("manual");
  const [targetB, setTargetB] = useState(0);
  const [useLlm, setUseLlm] = useState(true);
  const [building, setBuilding] = useState(false);
  const [draft, setDraft] = useState<BuildDraftInfo | null>(null);
  const [discarded, setDiscarded] = useState<Set<number>>(new Set());
  const [regenerating, setRegenerating] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
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

  useEffect(() => { checkAuth(); }, [checkAuth]);

  useEffect(() => {
    if (!subjectId) return;
    setSelectedTopics(new Set());
    knowledgeAPI.getTopics(subjectId).then(setTopics).catch(() => setTopics([]));
  }, [subjectId]);

  const totalCount = counts.mcq + counts.true_false + counts.short_answer + counts.matching;

  const handleBuild = async () => {
    setError("");
    setBuilding(true);
    setDraft(null);
    setDiscarded(new Set());
    try {
      const result = await builderAPI.build({
        subject_id: subjectId,
        topic_ids: selectedTopics.size > 0 ? Array.from(selectedTopics) : undefined,
        ...counts,
        recognition_pct: pcts.recognition / 100,
        comprehension_pct: pcts.comprehension / 100,
        application_pct: pcts.application / 100,
        anchor_mode: anchorMode,
        target_b: anchorMode === "manual" ? targetB : undefined,
        use_llm: useLlm,
      });
      setDraft(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Có lỗi xảy ra");
    }
    setBuilding(false);
  };

  const handleRegenerate = async (item: BuilderItemInfo, index: number) => {
    if (!draft) return;
    setRegenerating(item.id);
    try {
      const fresh = await builderAPI.generateOne({
        subject_id: subjectId,
        topic_id: item.topic_id,
        question_format: item.question_format,
        bloom: item.question_type,
        target_b: draft.anchor_b,
      });
      const items = [...draft.items];
      items[index] = fresh;
      setDiscarded((prev) => {
        const next = new Set(prev);
        if (item.source === "llm") next.add(item.id);
        next.delete(fresh.id);
        return next;
      });
      setDraft({ ...draft, items });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Sinh lại thất bại");
    }
    setRegenerating(null);
  };

  const toggleDiscard = (id: number) => {
    setDiscarded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const keptItems = (draft?.items || []).filter((i) => !discarded.has(i.id));

  const handleSave = async () => {
    if (!draft || !name.trim()) {
      setError("Nhập tên đề trước khi lưu");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const discardedGenerated = (draft.items || [])
        .filter((i) => i.source === "llm" && discarded.has(i.id))
        .map((i) => i.id);
      const saved = await builderAPI.save({
        subject_id: subjectId,
        name: name.trim(),
        description: `Tạo bởi ${user?.username} · ${keptItems.length} câu (bank ${keptItems.filter(i => i.source === "bank").length} / LLM ${keptItems.filter(i => i.source === "llm").length})`,
        question_ids: keptItems.map((i) => i.id),
        discarded_generated_ids: discardedGenerated,
      });
      alert(`Đã lưu "${saved.name}" (${saved.question_count} câu) vào danh sách đề có sẵn.`);
      router.push("/quiz");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Lưu thất bại");
    }
    setSaving(false);
  };

  if (!user) return null;

  return (
    <div className="min-h-screen">
      <Navbar user={user} onLogout={() => { localStorage.removeItem("kbs_token"); router.push("/"); }} />
      <main className="container py-6 space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Tạo đề thi</h1>
            <p className="text-muted-foreground mt-1">
              Dựng đề từ ngân hàng + LLM sinh bù, kiểm soát chất lượng từng câu trước khi lưu thành đề có sẵn
            </p>
          </div>
          <Link href="/questions">
            <Button variant="ghost"><ArrowLeft className="h-4 w-4 mr-1" /> Ngân hàng câu hỏi</Button>
          </Link>
        </div>

        {/* Blueprint form */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Hammer className="h-5 w-5" /> Cấu hình đề</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Môn học</Label>
              <div className="flex flex-wrap gap-2">
                {subjects.map((s) => (
                  <Button key={s.id} size="sm"
                    variant={subjectId === s.id ? "default" : "outline"}
                    onClick={() => setSubjectId(s.id)}>
                    {s.name}
                  </Button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <Label>Miền tri thức (bỏ trống = cả môn)</Label>
              <div className="flex flex-wrap gap-1.5">
                {topics.map((t) => (
                  <button key={t.id} type="button"
                    onClick={() => setSelectedTopics((prev) => {
                      const next = new Set(prev);
                      if (next.has(t.id)) next.delete(t.id); else next.add(t.id);
                      return next;
                    })}
                    className={cn(
                      "rounded-full border px-2.5 py-1 text-xs transition-colors",
                      selectedTopics.has(t.id)
                        ? "border-primary bg-primary/10 text-primary font-medium"
                        : "hover:bg-accent"
                    )}>
                    {t.name}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {(Object.keys(counts) as (keyof typeof counts)[]).map((fmt) => (
                <div key={fmt} className="space-y-1">
                  <Label className="text-xs">{FORMAT_LABEL[fmt]}</Label>
                  <Input type="number" min={0} max={50} value={counts[fmt]}
                    onChange={(e) => setCounts((prev) => ({ ...prev, [fmt]: parseInt(e.target.value) || 0 }))} />
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              Tổng: {totalCount} câu. Dạng ngoài trắc nghiệm sẽ do LLM sinh (tối đa 10 câu LLM mỗi lần dựng).
            </p>

            <div className="grid grid-cols-3 gap-3">
              {(["recognition", "comprehension", "application"] as const).map((k, i) => (
                <div key={k} className="space-y-1">
                  <Label className="text-xs">{["Nhận biết %", "Thông hiểu %", "Vận dụng %"][i]}</Label>
                  <Input type="number" min={0} max={100} value={pcts[k]}
                    onChange={(e) => setPcts((prev) => ({ ...prev, [k]: parseInt(e.target.value) || 0 }))} />
                </div>
              ))}
            </div>

            <div className="space-y-2">
              <Label>Neo độ khó</Label>
              <div className="flex flex-wrap items-center gap-3">
                <Button size="sm" variant={anchorMode === "manual" ? "default" : "outline"}
                  onClick={() => setAnchorMode("manual")}>Chỉ định b</Button>
                <Button size="sm" variant={anchorMode === "learners" ? "default" : "outline"}
                  onClick={() => setAnchorMode("learners")}>Theo năng lực người học</Button>
                {anchorMode === "manual" ? (
                  <Input type="number" step={0.1} min={-3} max={3} value={targetB} className="w-28"
                    onChange={(e) => setTargetB(parseFloat(e.target.value) || 0)} />
                ) : (
                  <span className="text-xs text-muted-foreground">
                    Lấy θ trung bình của người học môn này làm mốc chọn/sinh câu
                  </span>
                )}
              </div>
            </div>

            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} className="h-4 w-4" />
              Cho phép LLM sinh bù khi ngân hàng thiếu (qua self-check + Gemini nếu bật)
            </label>

            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button onClick={handleBuild} disabled={building || !subjectId || totalCount === 0}>
              <Hammer className="h-4 w-4 mr-2" />
              {building ? "Đang dựng đề (LLM có thể mất một lúc)..." : "Dựng đề nháp"}
            </Button>
          </CardContent>
        </Card>

        {/* Draft review */}
        {draft && (
          <>
            <Card>
              <CardHeader>
                <CardTitle>Đề nháp — duyệt từng câu</CardTitle>
                <CardDescription>
                  {draft.built}/{draft.requested} câu · ngân hàng {draft.sources.bank} · LLM {draft.sources.llm}
                  {draft.anchor_b != null && ` · neo b = ${draft.anchor_b}`}
                  {" · "}giữ {keptItems.length} câu
                </CardDescription>
                {draft.warnings.length > 0 && (
                  <ul className="mt-1 space-y-0.5 text-xs text-orange-700">
                    {draft.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}
                  </ul>
                )}
              </CardHeader>
              <CardContent className="space-y-3">
                {draft.items.map((item, idx) => {
                  const isDiscarded = discarded.has(item.id);
                  return (
                    <div key={item.id} className={cn(
                      "rounded-lg border p-3 space-y-2",
                      isDiscarded && "opacity-45 bg-muted/50"
                    )}>
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <span className="font-bold">Câu {idx + 1}</span>
                        <span className="rounded bg-primary/10 px-2 py-0.5 text-primary">{FORMAT_LABEL[normalizeFormat(item.question_format)]}</span>
                        <span className="rounded bg-slate-100 px-2 py-0.5">{item.question_type}</span>
                        <span className="rounded bg-slate-100 px-2 py-0.5">b = {item.difficulty_b.toFixed(2)}</span>
                        <span className={cn("rounded px-2 py-0.5 font-medium",
                          item.source === "llm" ? "bg-purple-100 text-purple-800" : "bg-sky-100 text-sky-800")}>
                          {item.source === "llm" ? "LLM sinh" : "Ngân hàng"}
                        </span>
                        <span className="text-muted-foreground">{item.topic_name}</span>
                        <span className="ml-auto flex gap-1.5">
                          {item.source === "llm" && (
                            <Button size="sm" variant="outline" className="h-7 px-2 text-xs"
                              disabled={regenerating !== null}
                              onClick={() => handleRegenerate(item, idx)}>
                              <RefreshCw className={cn("h-3 w-3 mr-1", regenerating === item.id && "animate-spin")} />
                              Sinh lại
                            </Button>
                          )}
                          <Button size="sm" variant={isDiscarded ? "default" : "outline"}
                            className="h-7 px-2 text-xs"
                            onClick={() => toggleDiscard(item.id)}>
                            {isDiscarded ? <><Check className="h-3 w-3 mr-1" />Khôi phục</> : <><X className="h-3 w-3 mr-1" />Loại</>}
                          </Button>
                        </span>
                      </div>

                      <p className="text-sm font-medium"><MathContent content={item.stem} inline /></p>

                      <QuestionAnswerPreview item={item} />

                      <ValidationBadges item={item} />
                    </div>
                  );
                })}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><Save className="h-5 w-5" /> Lưu thành đề có sẵn</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap items-end gap-3">
                <div className="space-y-1 flex-1 min-w-64">
                  <Label>Tên đề</Label>
                  <Input value={name} onChange={(e) => setName(e.target.value)}
                    placeholder="VD: Đề giữa kỳ - Chương 1+2" />
                </div>
                <Button onClick={handleSave} disabled={saving || keptItems.length === 0 || !name.trim()}>
                  <Save className="h-4 w-4 mr-2" />
                  {saving ? "Đang lưu..." : `Lưu đề (${keptItems.length} câu)`}
                </Button>
              </CardContent>
            </Card>
          </>
        )}
      </main>
    </div>
  );
}
