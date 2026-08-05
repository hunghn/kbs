"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  authAPI,
  knowledgeAPI,
  quizAPI,
  questionsAPI,
  type MatchingPair,
  type QuestionCreatePayload,
  type QuestionFormat,
  type QuestionFormatStats,
  type QuestionManageItem,
  type SubjectSummary,
  type TopicInfo,
  type GeneratedQuestionInfo,
} from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { MathContent } from "@/components/common/math-content";
import {
  FormatBadge,
  QuestionAnswerPreview,
} from "@/components/common/question-answer-preview";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  DEFAULT_GUESSING_C,
  FORMAT_HINT,
  FORMAT_LABEL,
  GUESSING_C_BOUNDS,
  MATCHING_MAX_PAIRS,
  MATCHING_MIN_PAIRS,
  QUESTION_FORMATS,
  describeAnswer,
  emptyMatchingPairs,
  normalizeFormat,
} from "@/lib/question-format";
import {
  Sparkles,
  Filter,
  WandSparkles,
  Pencil,
  Archive,
  ArchiveRestore,
  Trash2,
  ChevronLeft,
  ChevronRight,
  Plus,
  X,
} from "lucide-react";

interface QuestionFormState {
  external_id: string;
  topic_id: number;
  question_format: QuestionFormat;
  stem: string;
  option_a: string;
  option_b: string;
  option_c: string;
  option_d: string;
  correct_answer: string;
  answer_text: string;
  answer_aliases: string[];
  matching_pairs: MatchingPair[];
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
  question_format: "mcq",
  stem: "",
  option_a: "",
  option_b: "",
  option_c: "",
  option_d: "",
  correct_answer: "A",
  answer_text: "",
  answer_aliases: [],
  matching_pairs: emptyMatchingPairs(),
  difficulty_b: "0",
  discrimination_a: "1",
  guessing_c: String(DEFAULT_GUESSING_C.mcq),
  question_type: "thong_hieu",
  time_limit_seconds: "60",
  time_display: "01:00",
};

const PAGE_SIZE = 100;
const GENERATED_SIGNATURES_STORAGE_KEY = "kbs_generated_question_signatures";

function normalizeForSignature(value: string | undefined | null): string {
  return (value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

/** Identity of a draft depends on the format: options only matter for mcq/T-F. */
function buildGeneratedSignature(question: GeneratedQuestionInfo): string {
  const format = normalizeFormat(question.question_format);
  const parts = [format, normalizeForSignature(question.stem)];

  if (format === "short_answer") {
    parts.push(normalizeForSignature(question.answer_text));
  } else if (format === "matching") {
    parts.push(
      (question.matching_pairs || [])
        .map((pair) => `${normalizeForSignature(pair.left)}>${normalizeForSignature(pair.right)}`)
        .join(",")
    );
  } else {
    parts.push(
      normalizeForSignature(question.option_a),
      normalizeForSignature(question.option_b),
      normalizeForSignature(question.option_c),
      normalizeForSignature(question.option_d),
      normalizeForSignature(question.correct_answer)
    );
  }

  return parts.join("|");
}

export default function QuestionsPage() {
  const router = useRouter();
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);

  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [topics, setTopics] = useState<TopicInfo[]>([]);

  const [selectedSubjectId, setSelectedSubjectId] = useState<number | null>(null);
  const [selectedTopicFilter, setSelectedTopicFilter] = useState<number | null>(null);
  const [formatFilter, setFormatFilter] = useState<QuestionFormat | "">("");
  const [search, setSearch] = useState("");
  const [includeArchived, setIncludeArchived] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const [hasNextPage, setHasNextPage] = useState(false);
  const [totalQuestions, setTotalQuestions] = useState(0);
  const [formatStats, setFormatStats] = useState<QuestionFormatStats | null>(null);

  const [questions, setQuestions] = useState<QuestionManageItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [form, setForm] = useState<QuestionFormState>(emptyForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [aliasDraft, setAliasDraft] = useState("");

  const [targetLevel, setTargetLevel] = useState("Thông hiểu");
  const [genFormat, setGenFormat] = useState<QuestionFormat>("mcq");
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

    const filters = {
      subject_id: selectedSubjectId,
      topic_id: selectedTopicFilter ?? undefined,
      search: search.trim() || undefined,
      include_archived: includeArchived,
    };

    const [list, stats] = await Promise.all([
      questionsAPI.list({
        ...filters,
        question_format: formatFilter || undefined,
        skip: (currentPage - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
      questionsAPI.formatStats(filters),
    ]);

    setQuestions(list.items);
    setTotalQuestions(list.total);
    setHasNextPage(list.skip + list.items.length < list.total);
    setFormatStats(stats);
  }, [currentPage, formatFilter, includeArchived, search, selectedSubjectId, selectedTopicFilter]);

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
    setAliasDraft("");
    setForm((prev) => ({
      ...emptyForm,
      matching_pairs: emptyMatchingPairs(),
      topic_id: topics[0]?.id ?? prev.topic_id,
    }));
  };

  /** Switching format resets the answer side to that format's defaults. */
  const changeFormat = (format: QuestionFormat) => {
    setAliasDraft("");
    setForm((prev) => ({
      ...prev,
      question_format: format,
      correct_answer: "A",
      option_a: format === "mcq" ? prev.option_a : "",
      option_b: format === "mcq" ? prev.option_b : "",
      option_c: format === "mcq" ? prev.option_c : "",
      option_d: format === "mcq" ? prev.option_d : "",
      answer_text: format === "short_answer" ? prev.answer_text : "",
      answer_aliases: format === "short_answer" ? prev.answer_aliases : [],
      matching_pairs:
        format === "matching"
          ? prev.matching_pairs.length >= MATCHING_MIN_PAIRS
            ? prev.matching_pairs
            : emptyMatchingPairs()
          : emptyMatchingPairs(),
      guessing_c: String(DEFAULT_GUESSING_C[format]),
    }));
  };

  const fillForm = (q: QuestionManageItem) => {
    const format = normalizeFormat(q.question_format);
    const aliases = (q.answer_text || "").split("|").filter(Boolean);
    setEditingId(q.id);
    setAliasDraft("");
    setForm({
      external_id: q.external_id,
      topic_id: q.topic_id,
      question_format: format,
      stem: q.stem,
      option_a: format === "mcq" ? q.option_a : "",
      option_b: format === "mcq" ? q.option_b : "",
      option_c: format === "mcq" ? q.option_c : "",
      option_d: format === "mcq" ? q.option_d : "",
      correct_answer: q.correct_answer,
      answer_text: aliases[0] || "",
      answer_aliases: aliases.slice(1),
      matching_pairs:
        format === "matching" && q.matching_pairs.length > 0
          ? q.matching_pairs.map((pair) => ({ ...pair }))
          : emptyMatchingPairs(),
      difficulty_b: String(q.difficulty_b),
      discrimination_a: String(q.discrimination_a),
      guessing_c: String(q.guessing_c),
      question_type: q.question_type,
      time_limit_seconds: String(q.time_limit_seconds),
      time_display: q.time_display || "",
    });
  };

  const updatePair = (index: number, side: "left" | "right", value: string) => {
    setForm((prev) => ({
      ...prev,
      matching_pairs: prev.matching_pairs.map((pair, idx) =>
        idx === index ? { ...pair, [side]: value } : pair
      ),
    }));
  };

  const addPair = () => {
    setForm((prev) =>
      prev.matching_pairs.length >= MATCHING_MAX_PAIRS
        ? prev
        : { ...prev, matching_pairs: [...prev.matching_pairs, { left: "", right: "" }] }
    );
  };

  const removePair = (index: number) => {
    setForm((prev) =>
      prev.matching_pairs.length <= MATCHING_MIN_PAIRS
        ? prev
        : { ...prev, matching_pairs: prev.matching_pairs.filter((_, idx) => idx !== index) }
    );
  };

  const addAlias = () => {
    const value = aliasDraft.trim();
    if (!value) return;
    setForm((prev) =>
      prev.answer_aliases.includes(value)
        ? prev
        : { ...prev, answer_aliases: [...prev.answer_aliases, value] }
    );
    setAliasDraft("");
  };

  const removeAlias = (alias: string) => {
    setForm((prev) => ({
      ...prev,
      answer_aliases: prev.answer_aliases.filter((item) => item !== alias),
    }));
  };

  const parsePayload = (): QuestionCreatePayload => {
    const format = form.question_format;
    const isMcq = format === "mcq";
    const aliases = [form.answer_text.trim(), ...form.answer_aliases]
      .map((item) => item.trim())
      .filter(Boolean);

    return {
      external_id: form.external_id.trim(),
      topic_id: Number(form.topic_id),
      question_format: format,
      stem: form.stem.trim(),
      option_a: isMcq ? form.option_a.trim() : "",
      option_b: isMcq ? form.option_b.trim() : "",
      option_c: isMcq ? form.option_c.trim() : "",
      option_d: isMcq ? form.option_d.trim() : "",
      correct_answer:
        isMcq || format === "true_false" ? form.correct_answer.toUpperCase() : "A",
      answer_text: format === "short_answer" ? aliases.join("|") : undefined,
      matching_pairs:
        format === "matching"
          ? form.matching_pairs
              .map((pair) => ({ left: pair.left.trim(), right: pair.right.trim() }))
              .filter((pair) => pair.left && pair.right)
          : [],
      difficulty_b: Number(form.difficulty_b),
      discrimination_a: Number(form.discrimination_a),
      guessing_c: form.guessing_c.trim() === "" ? undefined : Number(form.guessing_c),
      question_type: form.question_type.trim(),
      time_limit_seconds: Number(form.time_limit_seconds),
      time_display: form.time_display.trim() || undefined,
    };
  };

  /** Mirrors backend/app/services/question_format.py so errors surface before the request. */
  const validatePayload = (payload: QuestionCreatePayload): string | null => {
    if (!payload.external_id) return "External ID là bắt buộc";
    if (!payload.topic_id) return "Topic là bắt buộc";
    if (!payload.stem) return "Nội dung câu hỏi là bắt buộc";

    const format = payload.question_format;
    if (format === "mcq") {
      const missing = (["A", "B", "C", "D"] as const).filter(
        (letter) => !payload[`option_${letter.toLowerCase()}` as "option_a"]
      );
      if (missing.length > 0) return `Trắc nghiệm: thiếu nội dung đáp án ${missing.join(", ")}`;
      if (!["A", "B", "C", "D"].includes(payload.correct_answer)) {
        return "Trắc nghiệm: đáp án đúng phải thuộc A/B/C/D";
      }
    } else if (format === "true_false") {
      if (!["A", "B"].includes(payload.correct_answer)) {
        return "Đúng/Sai: chọn Đúng hoặc Sai";
      }
    } else if (format === "short_answer") {
      if (!payload.answer_text) return "Trả lời ngắn: nhập đáp án chuẩn";
    } else {
      const pairs = payload.matching_pairs;
      if (pairs.length < MATCHING_MIN_PAIRS) {
        return `Ghép đôi: cần ít nhất ${MATCHING_MIN_PAIRS} cặp hợp lệ`;
      }
      if (pairs.length > MATCHING_MAX_PAIRS) return `Ghép đôi: tối đa ${MATCHING_MAX_PAIRS} cặp`;
      const rights = pairs.map((pair) => pair.right);
      if (new Set(rights).size !== rights.length) return "Ghép đôi: các vế phải phải khác nhau";
    }

    if (!Number.isFinite(payload.time_limit_seconds) || payload.time_limit_seconds <= 0) {
      return "Thời gian phải lớn hơn 0";
    }
    if (!Number.isFinite(payload.discrimination_a) || payload.discrimination_a <= 0) {
      return "Tham số a phải lớn hơn 0";
    }
    if (payload.guessing_c != null) {
      const [low, high] = GUESSING_C_BOUNDS[format];
      if (!Number.isFinite(payload.guessing_c) || payload.guessing_c < low || payload.guessing_c > high) {
        return `Dạng ${FORMAT_LABEL[format]}: tham số c phải trong [${low}, ${high}]`;
      }
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
          question_format: genFormat,
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

      const format = normalizeFormat(generated.question_format);
      const externalId = `LG${Date.now().toString().slice(-8)}${Math.floor(Math.random() * 900 + 100)}`;
      await questionsAPI.create({
        external_id: externalId,
        topic_id: Number(form.topic_id),
        question_format: format,
        stem: generated.stem,
        option_a: generated.option_a,
        option_b: generated.option_b,
        option_c: generated.option_c,
        option_d: generated.option_d,
        correct_answer: generated.correct_answer,
        answer_text: format === "short_answer" ? generated.answer_text : undefined,
        matching_pairs: format === "matching" ? generated.matching_pairs : [],
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

  /** Editing an item that already has answers cannot change its format. */
  const loadFormIntoEditor = (q: QuestionManageItem) => {
    fillForm(q);
    clearFeedback();
  };

  if (loading || !user) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary" />
      </div>
    );
  }

  const rangeStart = totalQuestions === 0 ? 0 : (currentPage - 1) * PAGE_SIZE + 1;
  const rangeEnd = totalQuestions === 0 ? 0 : Math.min(currentPage * PAGE_SIZE, totalQuestions);
  const totalPages = Math.max(1, Math.ceil(totalQuestions / PAGE_SIZE));
  const pageOptions = Array.from({ length: totalPages }, (_, idx) => {
    const page = idx + 1;
    const start = (page - 1) * PAGE_SIZE + 1;
    const end = Math.min(page * PAGE_SIZE, totalQuestions);
    return { page, label: `${start} - ${end}` };
  });

  const activeFormat = form.question_format;
  const [cLow, cHigh] = GUESSING_C_BOUNDS[activeFormat];

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
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold tracking-tight">Quản lý ngân hàng câu hỏi</h1>
              <p className="text-sm text-muted-foreground">
                Hỗ trợ 4 dạng: trắc nghiệm, đúng/sai, trả lời ngắn, ghép đôi.
              </p>
            </div>
            <Button onClick={() => router.push("/questions/builder")}>Tạo đề thi</Button>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
            <div className="rounded-lg border bg-white p-3">
              <p className="text-xs text-muted-foreground">Tổng câu hỏi</p>
              <p className="text-2xl font-semibold">{formatStats?.total ?? 0}</p>
            </div>
            {QUESTION_FORMATS.map((fmt) => (
              <button
                key={fmt}
                type="button"
                onClick={() => {
                  setFormatFilter((prev) => (prev === fmt ? "" : fmt));
                  setCurrentPage(1);
                }}
                className={cn(
                  "rounded-lg border bg-white p-3 text-left transition hover:border-primary/60",
                  formatFilter === fmt && "border-primary ring-1 ring-primary"
                )}
              >
                <p className="text-xs text-muted-foreground">{FORMAT_LABEL[fmt]}</p>
                <p className="text-2xl font-semibold">{formatStats?.[fmt] ?? 0}</p>
              </button>
            ))}
            <div className="rounded-lg border bg-white p-3">
              <p className="text-xs text-muted-foreground">Đã archive</p>
              <p className="text-2xl font-semibold text-amber-600">{formatStats?.archived ?? 0}</p>
            </div>
          </div>
        </div>

        <Card>
          <CardContent className="pt-5">
            <div className="grid gap-3 md:grid-cols-3">
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
              <div className="space-y-1">
                <label className="text-sm font-medium">Dạng câu hỏi</label>
                <select
                  className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={formatFilter}
                  onChange={(e) => {
                    setFormatFilter((e.target.value || "") as QuestionFormat | "");
                    setCurrentPage(1);
                  }}
                >
                  <option value="">Tất cả dạng</option>
                  {QUESTION_FORMATS.map((fmt) => (
                    <option key={fmt} value={fmt}>
                      {FORMAT_LABEL[fmt]}
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
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
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
                  <label className="text-sm font-medium">Dạng câu hỏi</label>
                  <select
                    className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={genFormat}
                    onChange={(e) => {
                      setGenFormat(e.target.value as QuestionFormat);
                      setGenerated(null);
                    }}
                  >
                    {QUESTION_FORMATS.map((fmt) => (
                      <option key={fmt} value={fmt}>
                        {FORMAT_LABEL[fmt]}
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
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <FormatBadge format={generated.question_format} />
                    <span>
                      Nguồn: <span className="font-medium text-foreground">{generated.generation_source}</span>
                      {generated.llm_model ? ` (${generated.llm_model})` : ""}
                    </span>
                  </div>
                  <div className="text-sm font-medium">
                    <MathContent content={generated.stem} inline className="min-w-0" />
                  </div>
                  <QuestionAnswerPreview item={generated} />
                  <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
                    <p>{describeAnswer(generated)}</p>
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
                          <div className="flex flex-wrap items-center gap-2">
                            <FormatBadge format={q.question_format} />
                            <p className="text-xs text-muted-foreground">
                              #{q.id} | {q.external_id}
                            </p>
                            {q.is_archived && (
                              <span className="rounded bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800">
                                ARCHIVED
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-muted-foreground">
                            {q.major_topic_name} - {q.topic_name}
                          </p>
                          <div className="text-sm font-medium">
                            <MathContent content={q.stem} inline className="min-w-0" />
                          </div>
                        </div>
                        <div className="flex gap-2">
                          <Button
                            size="icon"
                            variant="outline"
                            onClick={() => loadFormIntoEditor(q)}
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

                      <QuestionAnswerPreview item={q} className="mt-2" />

                      <p className="mt-2 text-[11px] text-muted-foreground">
                        {describeAnswer(q)} | b={q.difficulty_b} | a={q.discrimination_a} | c={q.guessing_c} | Time: {q.time_display || `${q.time_limit_seconds}s`}
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
                  {editingId
                    ? `Đang chỉnh sửa câu #${editingId}`
                    : selectedTopic
                      ? `Topic hiện tại: ${selectedTopic.name}`
                      : "Chọn topic để nhập câu hỏi"}
                </p>

                <div className="space-y-1.5">
                  <label className="text-sm font-medium">Dạng câu hỏi</label>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {QUESTION_FORMATS.map((fmt) => (
                      <Button
                        key={fmt}
                        type="button"
                        size="sm"
                        variant={activeFormat === fmt ? "default" : "outline"}
                        onClick={() => changeFormat(fmt)}
                      >
                        {FORMAT_LABEL[fmt]}
                      </Button>
                    ))}
                  </div>
                  <p className="text-xs text-muted-foreground">{FORMAT_HINT[activeFormat]}</p>
                  {editingId && (
                    <p className="text-xs text-amber-700">
                      Câu đã có lịch sử làm bài không thể đổi dạng — hãy archive và tạo câu mới.
                    </p>
                  )}
                </div>

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
                  <label className="text-sm font-medium">
                    {activeFormat === "true_false" ? "Khẳng định" : "Nội dung câu hỏi"}
                  </label>
                  <textarea
                    className="min-h-[90px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    placeholder={
                      activeFormat === "true_false"
                        ? "Nhập khẳng định để người học đánh giá Đúng/Sai"
                        : activeFormat === "matching"
                          ? "Nhập yêu cầu ghép đôi"
                          : "Nhập stem của câu hỏi"
                    }
                    value={form.stem}
                    onChange={(e) => setForm((prev) => ({ ...prev, stem: e.target.value }))}
                  />
                </div>

                {activeFormat === "mcq" && (
                  <>
                    {(["a", "b", "c", "d"] as const).map((letter) => (
                      <div key={letter} className="space-y-1">
                        <label className="text-sm font-medium">Đáp án {letter.toUpperCase()}</label>
                        <Input
                          placeholder={`Nội dung đáp án ${letter.toUpperCase()}`}
                          value={form[`option_${letter}`]}
                          onChange={(e) =>
                            setForm((prev) => ({ ...prev, [`option_${letter}`]: e.target.value }))
                          }
                        />
                      </div>
                    ))}
                    <div className="space-y-1">
                      <label className="text-sm font-medium">Đáp án đúng</label>
                      <select
                        className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                        value={form.correct_answer}
                        onChange={(e) => setForm((prev) => ({ ...prev, correct_answer: e.target.value }))}
                      >
                        {["A", "B", "C", "D"].map((letter) => (
                          <option key={letter} value={letter}>
                            {letter}
                          </option>
                        ))}
                      </select>
                    </div>
                  </>
                )}

                {activeFormat === "true_false" && (
                  <div className="space-y-1">
                    <label className="text-sm font-medium">Khẳng định trên là</label>
                    <div className="flex gap-2">
                      {[
                        { value: "A", label: "Đúng" },
                        { value: "B", label: "Sai" },
                      ].map((option) => (
                        <Button
                          key={option.value}
                          type="button"
                          className="flex-1"
                          variant={form.correct_answer === option.value ? "default" : "outline"}
                          onClick={() => setForm((prev) => ({ ...prev, correct_answer: option.value }))}
                        >
                          {option.label}
                        </Button>
                      ))}
                    </div>
                  </div>
                )}

                {activeFormat === "short_answer" && (
                  <div className="space-y-3">
                    <div className="space-y-1">
                      <label className="text-sm font-medium">Đáp án chuẩn</label>
                      <Input
                        placeholder="VD: 4"
                        value={form.answer_text}
                        onChange={(e) => setForm((prev) => ({ ...prev, answer_text: e.target.value }))}
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-sm font-medium">Cách viết khác được chấp nhận</label>
                      <div className="flex gap-2">
                        <Input
                          placeholder="VD: bốn"
                          value={aliasDraft}
                          onChange={(e) => setAliasDraft(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              addAlias();
                            }
                          }}
                        />
                        <Button type="button" variant="outline" className="shrink-0" onClick={addAlias}>
                          <Plus className="h-4 w-4" />
                        </Button>
                      </div>
                      {form.answer_aliases.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 pt-1">
                          {form.answer_aliases.map((alias) => (
                            <span
                              key={alias}
                              className="flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-xs"
                            >
                              {alias}
                              <button
                                type="button"
                                onClick={() => removeAlias(alias)}
                                aria-label={`Xóa cách viết ${alias}`}
                                className="text-muted-foreground hover:text-destructive"
                              >
                                <X className="h-3 w-3" />
                              </button>
                            </span>
                          ))}
                        </div>
                      )}
                      <p className="text-xs text-muted-foreground">
                        Chấm điểm bỏ qua hoa/thường và khoảng trắng thừa.
                      </p>
                    </div>
                  </div>
                )}

                {activeFormat === "matching" && (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <label className="text-sm font-medium">
                        Các cặp ghép đôi ({form.matching_pairs.length}/{MATCHING_MAX_PAIRS})
                      </label>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={addPair}
                        disabled={form.matching_pairs.length >= MATCHING_MAX_PAIRS}
                      >
                        <Plus className="mr-1 h-4 w-4" /> Thêm cặp
                      </Button>
                    </div>
                    {form.matching_pairs.map((pair, index) => (
                      <div key={index} className="flex items-center gap-2">
                        <Input
                          placeholder={`Vế trái ${index + 1}`}
                          value={pair.left}
                          onChange={(e) => updatePair(index, "left", e.target.value)}
                        />
                        <span className="text-muted-foreground">→</span>
                        <Input
                          placeholder={`Vế phải ${index + 1}`}
                          value={pair.right}
                          onChange={(e) => updatePair(index, "right", e.target.value)}
                        />
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          className="h-9 w-9 shrink-0"
                          onClick={() => removePair(index)}
                          disabled={form.matching_pairs.length <= MATCHING_MIN_PAIRS}
                          aria-label={`Xóa cặp ${index + 1}`}
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      </div>
                    ))}
                    <p className="text-xs text-muted-foreground">
                      Cần {MATCHING_MIN_PAIRS}–{MATCHING_MAX_PAIRS} cặp, các vế phải khác nhau. Khi làm
                      bài cột phải sẽ được xáo trộn.
                    </p>
                  </div>
                )}

                <div className="grid gap-3 sm:grid-cols-3">
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
                  <div className="space-y-1">
                    <label className="text-sm font-medium">
                      Đoán mò c <span className="text-muted-foreground">[{cLow}–{cHigh}]</span>
                    </label>
                    <Input
                      placeholder={String(DEFAULT_GUESSING_C[activeFormat])}
                      value={form.guessing_c}
                      onChange={(e) => setForm((prev) => ({ ...prev, guessing_c: e.target.value }))}
                    />
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="space-y-1">
                    <label className="text-sm font-medium">Mức Bloom</label>
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
                  <div className="space-y-1">
                    <label className="text-sm font-medium">Hiển thị (MM:SS)</label>
                    <Input
                      placeholder="Để trống để tự tính"
                      value={form.time_display}
                      onChange={(e) => setForm((prev) => ({ ...prev, time_display: e.target.value }))}
                    />
                  </div>
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
