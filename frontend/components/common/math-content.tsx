import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { cn } from "@/lib/utils";

interface MathContentProps {
  content: string;
  className?: string;
  inline?: boolean;
}

function normalizeMathDelimiters(text: string): string {
  return text
    .replace(/\\\\\[/g, "$$")
    .replace(/\\\\\]/g, "$$")
    .replace(/\\\\\(/g, "$")
    .replace(/\\\\\)/g, "$")
    .replace(/\\\[/g, "$$")
    .replace(/\\\]/g, "$$")
    .replace(/\\\(/g, "$")
    .replace(/\\\)/g, "$");
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