"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  authAPI,
  knowledgeAPI,
  quizAPI,
  questionsAPI,
  type QuestionCreatePayload,
  type QuestionManageItem,
  type SubjectSummary,
  type TopicInfo,
  type GeneratedQuestionInfo,
} from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Sparkles, Filter, WandSparkles, Pencil, Archive, ArchiveRestore, Trash2, ChevronLeft, ChevronRight } from "lucide-react";

interface QuestionFormState {
  external_id: string;
  topic_id: number;
  stem: string;
  option_a: string;
  option_b: string;
  option_c: string;
  option_d: string;
  correct_answer: string;
  difficulty_b: string;
  discrimination_a: string;
  guessing_c: string;
  question_type: string;
  time_limit_seconds: string;
  time_display: string;
}

const emptyForm: QuestionFormState = {
  external_id: "",
  topic_id: 0,
  stem: "",
  option_a: "",
  option_b: "",
  option_c: "",
  option_d: "",
  correct_answer: "A",
  difficulty_b: "0",
  discrimination_a: "1",
  guessing_c: "0.25",
  question_type: "thong_hieu",
  time_limit_seconds: "60",
  time_display: "01:00",
};

const PAGE_SIZE = 100;
const GENERATED_SIGNATURES_STORAGE_KEY = "kbs_generated_question_signatures";

function normalizeForSignature(value: string | undefined): string {
  return (value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function buildGeneratedSignature(question: GeneratedQuestionInfo): string {
  return [
    normalizeForSignature(question.stem),
    normalizeForSignature(question.option_a),
    normalizeForSignature(question.option_b),
    normalizeForSignature(question.option_c),
    normalizeForSignature(question.option_d),
    normalizeForSignature(question.correct_answer),
  ].join("|");
}

export default function QuestionsPage() {
  const router = useRouter();
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);

  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [topics, setTopics] = useState<TopicInfo[]>([]);

  const [selectedSubjectId, setSelectedSubjectId] = useState<number | null>(null);
  const [selectedTopicFilter, setSelectedTopicFilter] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [includeArchived, setIncludeArchived] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const [hasNextPage, setHasNextPage] = useState(false);
  const [totalQuestions, setTotalQuestions] = useState(0);

  const [questions, setQuestions] = useState<QuestionManageItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [form, setForm] = useState<QuestionFormState>(emptyForm);
  const [editingId, setEditingId] = useState<number | null>(null);

  const [targetLevel, setTargetLevel] = useState("Thông hiểu");
  const [contextText, setContextText] = useState("");
  const [genLoading, setGenLoading] = useState(false);
  const [quickAddLoading, setQuickAddLoading] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [generated, setGenerated] = useState<GeneratedQuestionInfo | null>(null);
  const generatedSignaturesRef = useRef<Set<string>>(new Set());

  const selectedTopic = useMemo(
    () => topics.find((topic) => topic.id === form.topic_id),
    [topics, form.topic_id]
  );

  const clearFeedback = () => {
    setError(null);
    setMessage(null);
  };

  const checkAuthAndLoad = useCallback(async () => {
    try {
      const me = await authAPI.me();
      setUser(me);
      const subs = await knowledgeAPI.getSubjects();
      setSubjects(subs);
      if (subs.length > 0) {
        setSelectedSubjectId(subs[0].id);
      }
    } catch {
      router.push("/");
    } finally {
      setLoading(false);
    }
  }, [router]);

  const loadTopics = useCallback(async (subjectId: number) => {
    const topicList = await knowledgeAPI.getTopics(subjectId);
    setTopics(topicList);
    if (topicList.length > 0) {
      setForm((prev) => ({ ...prev, topic_id: prev.topic_id || topicList[0].id }));
    }
  }, []);

  const loadQuestions = useCallback(async () => {
    if (!selectedSubjectId) return;

    const list = await questionsAPI.list({
      subject_id: selectedSubjectId,
      topic_id: selectedTopicFilter ?? undefined,
      search: search.trim() || undefined,
      include_archived: includeArchived,
      skip: (currentPage - 1) * PAGE_SIZE,
      limit: PAGE_SIZE,
    });
    setQuestions(list.items);
    setTotalQuestions(list.total);
    setHasNextPage((list.skip + list.items.length) < list.total);
  }, [currentPage, includeArchived, search, selectedSubjectId, selectedTopicFilter]);

  useEffect(() => {
    checkAuthAndLoad();
  }, [checkAuthAndLoad]);

  useEffect(() => {
    const stored = sessionStorage.getItem(GENERATED_SIGNATURES_STORAGE_KEY);
    if (!stored) return;
    try {
      const parsed = JSON.parse(stored);
      if (Array.isArray(parsed)) {
        generatedSignaturesRef.current = new Set(parsed.filter((item) => typeof item === "string"));
      }
    } catch {
      generatedSignaturesRef.current = new Set();
    }
  }, []);

  useEffect(() => {
    if (!selectedSubjectId) return;

    let cancelled = false;
    const run = async () => {
      try {
        clearFeedback();
        await loadTopics(selectedSubjectId);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Không thể tải topics");
        }
      }
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [selectedSubjectId, loadTopics]);

  useEffect(() => {
    if (!selectedSubjectId) return;

    let cancelled = false;
    const run = async () => {
      try {
        clearFeedback();
        await loadQuestions();
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Không thể tải danh sách câu hỏi");
        }
      }
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [loadQuestions, selectedSubjectId]);

  const resetForm = () => {
    setEditingId(null);
    setForm((prev) => ({
      ...emptyForm,
      topic_id: topics[0]?.id ?? prev.topic_id,
    }));
  };

  const fillForm = (q: QuestionManageItem) => {
    setEditingId(q.id);
    setForm({
      external_id: q.external_id,
      topic_id: q.topic_id,
      stem: q.stem,
      option_a: q.option_a,
      option_b: q.option_b,
      option_c: q.option_c,
      option_d: q.option_d,
      correct_answer: q.correct_answer,
      difficulty_b: String(q.difficulty_b),
      discrimination_a: String(q.discrimination_a),
      guessing_c: String(q.guessing_c),
      question_type: q.question_type,
      time_limit_seconds: String(q.time_limit_seconds),
      time_display: q.time_display || "",
    });
  };

  const parsePayload = (): QuestionCreatePayload => {
    return {
      external_id: form.external_id.trim(),
      topic_id: Number(form.topic_id),
      stem: form.stem.trim(),
      option_a: form.option_a.trim(),
      option_b: form.option_b.trim(),
      option_c: form.option_c.trim(),
      option_d: form.option_d.trim(),
      correct_answer: form.correct_answer.toUpperCase(),
      difficulty_b: Number(form.difficulty_b),
      discrimination_a: Number(form.discrimination_a),
      guessing_c: Number(form.guessing_c),
      question_type: form.question_type.trim(),
      time_limit_seconds: Number(form.time_limit_seconds),
      time_display: form.time_display.trim() || undefined,
    };
  };

  const validatePayload = (payload: QuestionCreatePayload): string | null => {
    if (!payload.external_id) return "External ID là bắt buộc";
    if (!payload.topic_id) return "Topic là bắt buộc";
    if (!payload.stem) return "Nội dung câu hỏi là bắt buộc";
    if (!["A", "B", "C", "D"].includes(payload.correct_answer)) {
      return "Đáp án đúng phải là A/B/C/D";
    }
    if (!Number.isFinite(payload.time_limit_seconds) || payload.time_limit_seconds <= 0) {
      return "Thời gian phải lớn hơn 0";
    }
    if (!Number.isFinite(payload.discrimination_a) || payload.discrimination_a <= 0) {
      return "Tham số a phải lớn hơn 0";
    }
    if (!Number.isFinite(payload.guessing_c) || payload.guessing_c < 0 || payload.guessing_c >= 1) {
      return "Tham số c phải trong [0, 1)";
    }
    return null;
  };

  const handleSave = async () => {
    try {
      clearFeedback();
      const payload = parsePayload();
      const validationError = validatePayload(payload);
      if (validationError) {
        setError(validationError);
        return;
      }

      setIsSaving(true);
      if (editingId) {
        await questionsAPI.update(editingId, payload);
        setMessage("Cập nhật câu hỏi thành công");
      } else {
        await questionsAPI.create(payload);
        setMessage("Tạo câu hỏi thành công");
      }

      resetForm();
      await loadQuestions();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không thể lưu câu hỏi");
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (questionId: number) => {
    if (!window.confirm("Xóa câu hỏi này? Hành động không thể hoàn tác.")) return;

    try {
      clearFeedback();
      await questionsAPI.remove(questionId);
      setMessage("Xóa câu hỏi thành công");
      if (editingId === questionId) {
        resetForm();
      }
      await loadQuestions();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không thể xóa câu hỏi");
    }
  };

  const handleArchiveToggle = async (q: QuestionManageItem) => {
    try {
      clearFeedback();
      if (q.is_archived) {
        await questionsAPI.unarchive(q.id);
        setMessage("Bỏ lưu trữ câu hỏi thành công");
      } else {
        await questionsAPI.archive(q.id);
        setMessage("Đã lưu trữ câu hỏi (sẽ không xuất hiện trong đề mới)");
      }
      if (editingId === q.id && !q.is_archived) {
        resetForm();
      }
      await loadQuestions();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không thể cập nhật trạng thái archive");
    }
  };

  const handleGenerateQuestion = async () => {
    if (!form.topic_id) {
      setGenError("Vui lòng chọn topic trước khi sinh câu hỏi.");
      return;
    }

    try {
      clearFeedback();
      setGenError(null);
      setGenLoading(true);
      const maxRetries = 4;
      let accepted: GeneratedQuestionInfo | null = null;

      for (let attempt = 0; attempt < maxRetries; attempt += 1) {
        const data = await quizAPI.generateQuestion({
          topic_id: Number(form.topic_id),
          knowledge_context: contextText.trim() || undefined,
          target_level: targetLevel,
        });

        const signature = buildGeneratedSignature(data);
        if (!generatedSignaturesRef.current.has(signature)) {
          generatedSignaturesRef.current.add(signature);
          sessionStorage.setItem(
            GENERATED_SIGNATURES_STORAGE_KEY,
            JSON.stringify(Array.from(generatedSignaturesRef.current))
          );
          accepted = data;
          break;
        }
      }

      if (!accepted) {
        setGenError("Hệ thống đang sinh trùng với câu nháp đã tạo trong phiên hiện tại. Vui lòng thử lại hoặc đổi ngữ cảnh.");
        return;
      }

      setGenerated(accepted);
    } catch (e) {
      setGenError(e instanceof Error ? e.message : "Không thể sinh câu hỏi bằng LLM");
    } finally {
      setGenLoading(false);
    }
  };

  const handleQuickAddGenerated = async () => {
    if (!generated) return;

    try {
      clearFeedback();
      setQuickAddLoading(true);

      const externalId = `LG${Date.now().toString().slice(-8)}${Math.floor(Math.random() * 900 + 100)}`;
      await questionsAPI.create({
        external_id: externalId,
        topic_id: Number(form.topic_id),
        stem: generated.stem,
        option_a: generated.option_a,
        option_b: generated.option_b,
        option_c: generated.option_c,
        option_d: generated.option_d,
        correct_answer: generated.correct_answer,
        difficulty_b: generated.difficulty_b,
        discrimination_a: generated.discrimination_a,
        guessing_c: generated.guessing_c,
        question_type: targetLevel,
        time_limit_seconds: targetLevel === "Vận dụng" ? 90 : 60,
        time_display: targetLevel === "Vận dụng" ? "01:30" : "01:00",
      });

      setGenerated(null);
      setMessage("Đã thêm nhanh câu hỏi sinh bởi LLM vào ngân hàng câu hỏi.");
      await loadQuestions();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không thể thêm nhanh câu hỏi vào ngân hàng");
    } finally {
      setQuickAddLoading(false);
    }
  };

  if (loading || !user) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary" />
      </div>
    );
  }

  const archivedCount = questions.filter((q) => q.is_archived).length;
  const activeCount = questions.length - archivedCount;
  const rangeStart = totalQuestions === 0 ? 0 : (currentPage - 1) * PAGE_SIZE + 1;
  const rangeEnd = totalQuestions === 0 ? 0 : Math.min(currentPage * PAGE_SIZE, totalQuestions);
  const totalPages = Math.max(1, Math.ceil(totalQuestions / PAGE_SIZE));
  const pageOptions = Array.from({ length: totalPages }, (_, idx) => {
    const page = idx + 1;
    const start = (page - 1) * PAGE_SIZE + 1;
    const end = Math.min(page * PAGE_SIZE, totalQuestions);
    return { page, label: `${start} - ${end}` };
  });

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
        <div className="rounded-2xl border bg-gradient-to-br from-slate-50 to-white p-5">
          <h1 className="text-2xl font-bold tracking-tight">Quản lý ngân hàng câu hỏi</h1>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border bg-white p-3">
              <p className="text-xs text-muted-foreground">Tổng câu hỏi</p>
              <p className="text-2xl font-semibold">{totalQuestions}</p>
              <p className="text-[11px] text-muted-foreground">Trang {currentPage}</p>
            </div>
            <div className="rounded-lg border bg-white p-3">
              <p className="text-xs text-muted-foreground">Đang hoạt động</p>
              <p className="text-2xl font-semibold text-emerald-600">{activeCount}</p>
            </div>
            <div className="rounded-lg border bg-white p-3">
              <p className="text-xs text-muted-foreground">Đã archive</p>
              <p className="text-2xl font-semibold text-amber-600">{archivedCount}</p>
            </div>
          </div>
        </div>

        <Card>
          <CardContent className="pt-5">
            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-1">
                <label className="text-sm font-medium">Môn học</label>
                <select
                  className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={selectedSubjectId ?? ""}
                  onChange={(e) => {
                    const nextSubject = Number(e.target.value);
                    setSelectedSubjectId(nextSubject);
                    setSelectedTopicFilter(null);
                    setCurrentPage(1);
                    resetForm();
                  }}
                >
                  {subjects.map((subject) => (
                    <option key={subject.id} value={subject.id}>
                      {subject.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">Topic</label>
                <select
                  className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={selectedTopicFilter ?? ""}
                  onChange={(e) => {
                    const nextTopic = e.target.value ? Number(e.target.value) : null;
                    setSelectedTopicFilter(nextTopic);
                    setCurrentPage(1);
                    if (nextTopic) {
                      setForm((prev) => ({ ...prev, topic_id: nextTopic }));
                    }
                  }}
                >
                  <option value="">Tất cả topic</option>
                  {topics.map((topic) => (
                    <option key={topic.id} value={topic.id}>
                      {topic.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </CardContent>
        </Card>

        {error && (
          <Card className="border-destructive">
            <CardContent className="pt-6 text-destructive text-sm">{error}</CardContent>
          </Card>
        )}

        {message && (
          <Card className="border-emerald-500">
            <CardContent className="pt-6 text-emerald-700 text-sm">{message}</CardContent>
          </Card>
        )}

        <div className="space-y-6">
          <Card>
            <CardContent className="space-y-3 pt-5">
              <h3 className="flex items-center gap-2 text-lg font-semibold text-violet-700">
                <WandSparkles className="h-5 w-5" />
                Tạo câu hỏi với LLM
              </h3>
              <div className="grid gap-3 md:grid-cols-3">
                <div className="space-y-1">
                  <label className="text-sm font-medium">Topic sinh câu hỏi</label>
                  <select
                    className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={form.topic_id}
                    onChange={(e) => setForm((prev) => ({ ...prev, topic_id: Number(e.target.value) }))}
                  >
                    {topics.map((topic) => (
                      <option key={topic.id} value={topic.id}>
                        {topic.code ? `${topic.code} - ` : ""}{topic.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="space-y-1">
                  <label className="text-sm font-medium">Mức độ mục tiêu</label>
                  <div className="flex flex-wrap gap-2">
                    {["Nhận biết", "Thông hiểu", "Vận dụng"].map((lvl) => (
                      <Button
                        key={lvl}
                        type="button"
                        variant={targetLevel === lvl ? "default" : "outline"}
                        size="sm"
                        onClick={() => setTargetLevel(lvl)}
                      >
                        {lvl}
                      </Button>
                    ))}
                  </div>
                </div>

                <div className="space-y-1">
                  <label className="text-sm font-medium">Ngữ cảnh bổ sung (optional)</label>
                  <Input
                    placeholder="Ví dụ: mệnh đề kéo theo, JOIN nhiều bảng..."
                    value={contextText}
                    onChange={(e) => setContextText(e.target.value)}
                  />
                </div>
              </div>

              {genError && <p className="text-sm text-destructive">{genError}</p>}

              <div className="flex flex-wrap gap-3">
                <Button type="button" onClick={handleGenerateQuestion} disabled={genLoading || !form.topic_id}>
                  <Sparkles className="mr-1 h-4 w-4" />
                  {genLoading ? "Đang sinh..." : "Sinh câu hỏi nháp"}
                </Button>
                {generated && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={handleQuickAddGenerated}
                    disabled={quickAddLoading}
                  >
                    {quickAddLoading ? "Đang thêm..." : "Thêm nhanh"}
                  </Button>
                )}
              </div>

              {generated && (
                <div className="space-y-3 rounded-xl border bg-violet-50/40 p-3">
                  <p className="text-xs text-muted-foreground">
                    Nguồn: <span className="font-medium text-foreground">{generated.generation_source}</span>
                    {generated.llm_model ? ` (${generated.llm_model})` : ""}
                  </p>
                  <p className="text-sm font-medium">{generated.stem}</p>
                  <div className="grid gap-1 text-xs text-muted-foreground md:grid-cols-2">
                    <p>A. {generated.option_a}</p>
                    <p>B. {generated.option_b}</p>
                    <p>C. {generated.option_c}</p>
                    <p>D. {generated.option_d}</p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
                    <p>Đáp án: {generated.correct_answer}</p>
                    <p>b: {generated.difficulty_b}</p>
                    <p>a: {generated.discrimination_a}</p>
                    <p>c: {generated.guessing_c}</p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <div className="grid gap-6 xl:grid-cols-12">
            <Card className="xl:col-span-7">
            <CardContent className="space-y-4 pt-5">
              <div className="space-y-2">
                <label className="text-sm font-medium">Tìm theo nội dung</label>
                <div className="flex gap-2">
                  <Input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Nhập từ khóa trong stem..."
                  />
                  <Button onClick={() => setCurrentPage(1)} variant="outline" className="shrink-0">
                    <Filter className="mr-1 h-4 w-4" /> Lọc
                  </Button>
                </div>
              </div>

              <label className="flex items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={includeArchived}
                  onChange={(e) => {
                    setIncludeArchived(e.target.checked);
                    setCurrentPage(1);
                  }}
                />
                Hiển thị cả câu đã archive
              </label>

              <div className="max-h-[68vh] space-y-3 overflow-auto pr-1">
                {questions.length === 0 && (
                  <p className="text-sm text-muted-foreground">Không có câu hỏi nào phù hợp bộ lọc.</p>
                )}

                {questions.map((q) => (
                  <div key={q.id} className="rounded-xl border bg-white p-3 shadow-sm">
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <p className="text-xs text-muted-foreground">
                          #{q.id} | {q.external_id}
                        </p>
                        <p className="text-xs text-muted-foreground">{q.major_topic_name} - {q.topic_name}</p>
                        {q.is_archived && (
                          <p className="text-[11px] font-medium text-amber-700">ARCHIVED</p>
                        )}
                        <p className="line-clamp-2 text-sm font-medium">{q.stem}</p>
                      </div>
                      <div className="flex gap-2">
                        <Button
                          size="icon"
                          variant="outline"
                          onClick={() => fillForm(q)}
                          disabled={q.is_archived}
                          title="Sửa"
                          aria-label="Sửa câu hỏi"
                          className="h-9 w-9 text-sky-600 hover:text-sky-700"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          size="icon"
                          variant="secondary"
                          onClick={() => handleArchiveToggle(q)}
                          title={q.is_archived ? "Bỏ archive" : "Archive"}
                          aria-label={q.is_archived ? "Bỏ archive câu hỏi" : "Archive câu hỏi"}
                          className={q.is_archived ? "h-9 w-9 text-emerald-700 hover:text-emerald-800" : "h-9 w-9 text-amber-700 hover:text-amber-800"}
                        >
                          {q.is_archived ? <ArchiveRestore className="h-4 w-4" /> : <Archive className="h-4 w-4" />}
                        </Button>
                        <Button
                          size="icon"
                          variant="destructive"
                          onClick={() => handleDelete(q.id)}
                          title="Xóa"
                          aria-label="Xóa câu hỏi"
                          className="h-9 w-9"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>

                    <div className="mt-2 grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
                      <p>A. {q.option_a}</p>
                      <p>B. {q.option_b}</p>
                      <p>C. {q.option_c}</p>
                      <p>D. {q.option_d}</p>
                    </div>

                    <p className="mt-2 text-[11px] text-muted-foreground">
                      Correct: {q.correct_answer} | b={q.difficulty_b} | a={q.discrimination_a} | c={q.guessing_c} | Time: {q.time_display || `${q.time_limit_seconds}s`}
                    </p>
                  </div>
                ))}
              </div>

              <div className="flex items-center justify-between rounded-lg border bg-slate-50 px-3 py-2">
                <p className="text-xs text-muted-foreground">
                  {rangeStart}-{rangeEnd}/{totalQuestions}
                </p>
                <div className="flex items-center gap-2">
                  <select
                    className="h-9 rounded-md border border-input bg-background px-2 text-xs"
                    value={currentPage}
                    onChange={(e) => setCurrentPage(Number(e.target.value))}
                    disabled={totalQuestions === 0}
                  >
                    {pageOptions.map((opt) => (
                      <option key={opt.page} value={opt.page}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setCurrentPage((prev) => Math.max(1, prev - 1))}
                    disabled={currentPage === 1 || totalQuestions === 0}
                  >
                    <ChevronLeft className="mr-1 h-4 w-4" /> Trước
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setCurrentPage((prev) => prev + 1)}
                    disabled={!hasNextPage}
                  >
                    Sau <ChevronRight className="ml-1 h-4 w-4" />
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

            <Card className="xl:col-span-5">
              <CardContent className="space-y-3 pt-5">
              <p className="text-sm text-muted-foreground">
                {editingId ? `Đang chỉnh sửa câu #${editingId}` : (selectedTopic ? `Topic hiện tại: ${selectedTopic.name}` : "Chọn topic để nhập câu hỏi")}
              </p>
              <div className="space-y-1">
                <label className="text-sm font-medium">External ID</label>
                <Input
                  placeholder="VD: DM999"
                  value={form.external_id}
                  onChange={(e) => setForm((prev) => ({ ...prev, external_id: e.target.value }))}
                />
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">Topic</label>
                <select
                  className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={form.topic_id}
                  onChange={(e) => setForm((prev) => ({ ...prev, topic_id: Number(e.target.value) }))}
                >
                  {topics.map((topic) => (
                    <option key={topic.id} value={topic.id}>
                      {topic.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">Nội dung câu hỏi</label>
                <textarea
                  className="min-h-[90px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  placeholder="Nhập stem của câu hỏi"
                  value={form.stem}
                  onChange={(e) => setForm((prev) => ({ ...prev, stem: e.target.value }))}
                />
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">Đáp án A</label>
                <Input
                  placeholder="Nội dung đáp án A"
                  value={form.option_a}
                  onChange={(e) => setForm((prev) => ({ ...prev, option_a: e.target.value }))}
                />
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">Đáp án B</label>
                <Input
                  placeholder="Nội dung đáp án B"
                  value={form.option_b}
                  onChange={(e) => setForm((prev) => ({ ...prev, option_b: e.target.value }))}
                />
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">Đáp án C</label>
                <Input
                  placeholder="Nội dung đáp án C"
                  value={form.option_c}
                  onChange={(e) => setForm((prev) => ({ ...prev, option_c: e.target.value }))}
                />
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">Đáp án D</label>
                <Input
                  placeholder="Nội dung đáp án D"
                  value={form.option_d}
                  onChange={(e) => setForm((prev) => ({ ...prev, option_d: e.target.value }))}
                />
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <div className="space-y-1">
                  <label className="text-sm font-medium">Đáp án đúng</label>
                  <select
                    className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={form.correct_answer}
                    onChange={(e) => setForm((prev) => ({ ...prev, correct_answer: e.target.value }))}
                  >
                    <option value="A">A</option>
                    <option value="B">B</option>
                    <option value="C">C</option>
                    <option value="D">D</option>
                  </select>
                </div>

                <div className="space-y-1">
                  <label className="text-sm font-medium">Độ khó b</label>
                  <Input
                    placeholder="Ví dụ: 0.5"
                    value={form.difficulty_b}
                    onChange={(e) => setForm((prev) => ({ ...prev, difficulty_b: e.target.value }))}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-sm font-medium">Độ phân biệt a</label>
                  <Input
                    placeholder="Ví dụ: 1.2"
                    value={form.discrimination_a}
                    onChange={(e) => setForm((prev) => ({ ...prev, discrimination_a: e.target.value }))}
                  />
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <div className="space-y-1">
                  <label className="text-sm font-medium">Đoán mò c</label>
                  <Input
                    placeholder="Ví dụ: 0.25"
                    value={form.guessing_c}
                    onChange={(e) => setForm((prev) => ({ ...prev, guessing_c: e.target.value }))}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-sm font-medium">Loại câu hỏi</label>
                  <Input
                    placeholder="VD: thong_hieu"
                    value={form.question_type}
                    onChange={(e) => setForm((prev) => ({ ...prev, question_type: e.target.value }))}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-sm font-medium">Thời gian (giây)</label>
                  <Input
                    placeholder="Ví dụ: 60"
                    value={form.time_limit_seconds}
                    onChange={(e) => setForm((prev) => ({ ...prev, time_limit_seconds: e.target.value }))}
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">Thời gian hiển thị (MM:SS)</label>
                <Input
                  placeholder="Để trống để tự tính"
                  value={form.time_display}
                  onChange={(e) => setForm((prev) => ({ ...prev, time_display: e.target.value }))}
                />
              </div>

              <div className="flex gap-2">
                <Button onClick={handleSave} disabled={isSaving}>
                  {isSaving ? "Đang lưu..." : editingId ? "Cập nhật" : "Tạo mới"}
                </Button>
                {editingId && (
                  <Button variant="outline" onClick={resetForm}>
                    Hủy chỉnh sửa
                  </Button>
                )}
              </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </main>
    </div>
  );
}
