import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { cn } from "@/lib/utils";

interface MathContentProps {
  content: string;
  className?: string;
  inline?: boolean;
}

const LATEX_COMMAND_PATTERN = new RegExp(
  String.raw`\\(?:frac|sqrt|sum|int|forall|exists|neg|land|lor|rightarrow|Rightarrow|leftarrow|Leftarrow|leftrightarrow|Leftrightarrow|in|notin|subset|subseteq|supset|supseteq|cup|cap|cdot|times|pm|mp|leq|geq|neq|equiv|approx|to|iff|implies|therefore|because|alpha|beta|gamma|delta|theta|lambda|mu|pi|sigma|omega)`
);

const MATH_BLOCK_OR_INLINE = /(\$\$[\s\S]*?\$\$|\$[^$\n]*\$)/g;

function mapOutsideMathDelimiters(text: string, mapper: (segment: string) => string): string {
  const segments = text.split(MATH_BLOCK_OR_INLINE);
  return segments
    .map((segment) => {
      if (/^\$\$[\s\S]*\$\$$/.test(segment) || /^\$[^$\n]*\$$/.test(segment)) {
        return segment;
      }
      return mapper(segment);
    })
    .join("");
}

function autoWrapRecurrenceNotation(text: string): string {
  let normalized = mapOutsideMathDelimiters(text, (segment) =>
    // Wrap recurrence-style subscripts: a_n, a_0, a_{n-1}, x_{k+2}, ...
    segment.replace(
      /(^|[^A-Za-z])([A-Za-z])_((?:\{[^{}]+\})|(?:[A-Za-z0-9]+))/g,
      (_m, prefix: string, base: string, sub: string) => `${prefix}$${base}_${sub}$`
    )
  );

  normalized = mapOutsideMathDelimiters(normalized, (segment) =>
    // Wrap exponent notation: 2^n, x^{k+1}, a_n^2, ...
    segment
      .replace(
        /(\([^()]+\)|[A-Za-z0-9.]+(?:_\{[^{}]+\}|_[A-Za-z0-9]+)?)\^\{([^{}]+)\}/g,
        (_m, base: string, exp: string) => `$${base}^{${exp}}$`
      )
      .replace(
        /(\([^()]+\)|[A-Za-z0-9.]+(?:_\{[^{}]+\}|_[A-Za-z0-9]+)?)\^([A-Za-z0-9]+)/g,
        (_m, base: string, exp: string) => `$${base}^${exp}$`
      )
  );

  // Wrap simple inequality fragments frequently used in statements: n ≥ 2, k <= 10, ...
  normalized = mapOutsideMathDelimiters(normalized, (segment) =>
    segment.replace(
      /\b([A-Za-z][A-Za-z0-9]*)\s*(≥|≤|<=|>=)\s*(-?\d+(?:\.\d+)?)\b/g,
      (_m, lhs: string, op: string, rhs: string) => {
        const latexOp = op === "≥" || op === ">=" ? "\\ge" : "\\le";
        return `$${lhs} ${latexOp} ${rhs}$`;
      }
    )
  );

  return normalized;
}

function autoWrapLatexCommandsWithoutDelimiters(text: string): string {
  return mapOutsideMathDelimiters(text, (segment) =>
    // Wrap probable LaTeX command chunks so remark-math can parse them.
    // Example: "A. \\frac{1}{2}" -> "A. $\\frac{1}{2}$"
    segment.replace(
      /(\\[a-zA-Z]+(?:\s*\{[^{}]*\}|\s*_[{][^{}]*[}]|\s*\^[{][^{}]*[}]|\s+[a-zA-Z0-9()+\-*/=<>]+)*)/g,
      (match) => {
        if (!LATEX_COMMAND_PATTERN.test(match)) {
          return match;
        }
        return `$${match.trim()}$`;
      }
    )
  );
}

function normalizeMathDelimiters(text: string): string {
  const normalizedDelimiters = text
    // Some LLM outputs escape dollar delimiters (\$...\$), which prevents remark-math from parsing.
    .replace(/\\\$/g, "$")
    // Normalize one or more escaped bracket delimiters to KaTeX-style dollars.
    .replace(/\\+\[/g, "$$")
    .replace(/\\+\]/g, "$$")
    .replace(/\\+\(/g, "$")
    .replace(/\\+\)/g, "$");

  const withRecurrence = autoWrapRecurrenceNotation(normalizedDelimiters);
  return autoWrapLatexCommandsWithoutDelimiters(withRecurrence);
}

export function MathContent({ content, className, inline = false }: MathContentProps) {
  const normalized = normalizeMathDelimiters(content || "");

  if (inline) {
    return (
      <span className={cn("inline math-content", className)}>
        <ReactMarkdown
          remarkPlugins={[remarkMath]}
          rehypePlugins={[rehypeKatex]}
          unwrapDisallowed
          disallowedElements={[
            "p",
            "div",
            "ul",
            "ol",
            "li",
            "blockquote",
            "pre",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
          ]}
          components={{
            p: ({ children }) => <span>{children}</span>,
            ul: ({ children }) => <span>{children}</span>,
            ol: ({ children }) => <span>{children}</span>,
            li: ({ children }) => <span>{children}</span>,
            div: ({ children }) => <span>{children}</span>,
            table: ({ children }) => <span>{children}</span>,
            tr: ({ children }) => <span>{children}</span>,
            td: ({ children }) => <span>{children}</span>,
            th: ({ children }) => <span>{children}</span>,
          }}
        >
          {normalized}
        </ReactMarkdown>
      </span>
    );
  }

  return (
    <div className={cn("math-content", className)}>
      <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
        {normalized}
      </ReactMarkdown>
    </div>
  );
}