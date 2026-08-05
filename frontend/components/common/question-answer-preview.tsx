"use client";

import { MathContent } from "@/components/common/math-content";
import { cn } from "@/lib/utils";
import type { MatchingPair, QuestionFormat } from "@/lib/api";
import {
  FORMAT_BADGE_CLASS,
  FORMAT_LABEL,
  answerLetters,
  normalizeFormat,
} from "@/lib/question-format";

export interface AnswerViewItem {
  question_format: QuestionFormat | string;
  option_a: string;
  option_b: string;
  option_c: string;
  option_d: string;
  correct_answer: string;
  answer_text?: string | null;
  matching_pairs?: MatchingPair[];
}

export function FormatBadge({
  format,
  className,
}: {
  format: QuestionFormat | string;
  className?: string;
}) {
  const fmt = normalizeFormat(format);
  return (
    <span
      className={cn(
        "rounded px-2 py-0.5 text-[11px] font-medium",
        FORMAT_BADGE_CLASS[fmt],
        className
      )}
    >
      {FORMAT_LABEL[fmt]}
    </span>
  );
}

/**
 * Read-only rendering of a question's answer side, branching on format.
 * Shared by the question bank, the LLM draft preview and the exam builder so
 * all three describe an item the same way.
 */
export function QuestionAnswerPreview({
  item,
  className,
}: {
  item: AnswerViewItem;
  className?: string;
}) {
  const format = normalizeFormat(item.question_format);

  if (format === "short_answer") {
    const aliases = (item.answer_text || "").split("|").filter(Boolean);
    return (
      <div className={cn("flex flex-wrap items-center gap-1.5 text-xs", className)}>
        <span className="text-muted-foreground">Đáp án:</span>
        {aliases.length === 0 && <span className="text-muted-foreground">—</span>}
        {aliases.map((alias, idx) => (
          <span
            key={`${alias}-${idx}`}
            className={cn(
              "rounded px-2 py-0.5",
              idx === 0
                ? "bg-emerald-100 font-medium text-emerald-800"
                : "bg-slate-100 text-slate-600"
            )}
          >
            {alias}
          </span>
        ))}
      </div>
    );
  }

  if (format === "matching") {
    const pairs = item.matching_pairs || [];
    if (pairs.length === 0) {
      return <p className={cn("text-xs text-muted-foreground", className)}>Chưa có cặp ghép đôi</p>;
    }
    return (
      <div className={cn("space-y-0.5 text-xs", className)}>
        {pairs.map((pair, idx) => (
          <p key={`${pair.left}-${idx}`} className="flex flex-wrap items-start gap-1.5">
            <MathContent content={pair.left} inline className="min-w-0" />
            <span className="text-muted-foreground">→</span>
            <span className="text-emerald-700">
              <MathContent content={pair.right} inline className="min-w-0" />
            </span>
          </p>
        ))}
      </div>
    );
  }

  const letters = answerLetters(format);
  const optionOf = (letter: string) =>
    ({
      A: item.option_a,
      B: item.option_b,
      C: item.option_c,
      D: item.option_d,
    })[letter] || "";

  return (
    <div
      className={cn(
        "grid gap-1.5 text-xs",
        format === "mcq" ? "sm:grid-cols-2" : "sm:grid-cols-2",
        className
      )}
    >
      {letters.map((letter) => {
        const isCorrect = letter === (item.correct_answer || "").toUpperCase();
        return (
          <div
            key={letter}
            className={cn(
              "flex items-start gap-1.5",
              isCorrect ? "font-medium text-emerald-700" : "text-muted-foreground"
            )}
          >
            <span className="font-medium">{letter}.</span>
            <MathContent content={optionOf(letter)} inline className="min-w-0" />
            {isCorrect && <span aria-hidden>✓</span>}
          </div>
        );
      })}
    </div>
  );
}
