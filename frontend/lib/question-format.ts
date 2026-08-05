import type { MatchingPair, QuestionFormat } from "@/lib/api";

export const QUESTION_FORMATS: QuestionFormat[] = [
  "mcq",
  "true_false",
  "short_answer",
  "matching",
];

export const FORMAT_LABEL: Record<QuestionFormat, string> = {
  mcq: "Trắc nghiệm",
  true_false: "Đúng/Sai",
  short_answer: "Trả lời ngắn",
  matching: "Ghép đôi",
};

export const FORMAT_HINT: Record<QuestionFormat, string> = {
  mcq: "4 phương án, một đáp án đúng",
  true_false: "Một khẳng định, chọn Đúng hoặc Sai",
  short_answer: "Đáp án là từ/cụm từ ngắn, chấm theo chuẩn hóa",
  matching: "3–6 cặp trái–phải, vế phải xáo trộn khi làm bài",
};

/** Badge colors, kept in one place so every screen labels a format alike. */
export const FORMAT_BADGE_CLASS: Record<QuestionFormat, string> = {
  mcq: "bg-sky-100 text-sky-800",
  true_false: "bg-emerald-100 text-emerald-800",
  short_answer: "bg-amber-100 text-amber-800",
  matching: "bg-violet-100 text-violet-800",
};

/** Mirrors DEFAULT_GUESSING_C in backend/app/services/question_format.py */
export const DEFAULT_GUESSING_C: Record<QuestionFormat, number> = {
  mcq: 0.25,
  true_false: 0.5,
  short_answer: 0.05,
  matching: 0.05,
};

/** Mirrors GUESSING_C_BOUNDS in backend/app/services/question_format.py */
export const GUESSING_C_BOUNDS: Record<QuestionFormat, [number, number]> = {
  mcq: [0, 0.35],
  true_false: [0, 0.6],
  short_answer: [0, 0.2],
  matching: [0, 0.2],
};

export const MATCHING_MIN_PAIRS = 3;
export const MATCHING_MAX_PAIRS = 6;

export function normalizeFormat(value: string | null | undefined): QuestionFormat {
  return QUESTION_FORMATS.includes(value as QuestionFormat)
    ? (value as QuestionFormat)
    : "mcq";
}

/** Letters a learner can pick for this format ([] for constructed responses). */
export function answerLetters(format: QuestionFormat): string[] {
  if (format === "mcq") return ["A", "B", "C", "D"];
  if (format === "true_false") return ["A", "B"];
  return [];
}

export function emptyMatchingPairs(count = MATCHING_MIN_PAIRS): MatchingPair[] {
  return Array.from({ length: count }, () => ({ left: "", right: "" }));
}

/** Short one-line description of the key, for list rows. */
export function describeAnswer(item: {
  question_format: QuestionFormat;
  correct_answer: string;
  answer_text?: string | null;
  matching_pairs?: MatchingPair[];
}): string {
  const format = normalizeFormat(item.question_format);
  if (format === "true_false") {
    return `Đáp án: ${item.correct_answer === "A" ? "Đúng" : "Sai"}`;
  }
  if (format === "short_answer") {
    const aliases = (item.answer_text || "").split("|").filter(Boolean);
    return aliases.length > 1
      ? `Đáp án: ${aliases[0]} (+${aliases.length - 1} cách viết)`
      : `Đáp án: ${aliases[0] || "—"}`;
  }
  if (format === "matching") {
    return `${(item.matching_pairs || []).length} cặp ghép đôi`;
  }
  return `Đáp án: ${item.correct_answer}`;
}
