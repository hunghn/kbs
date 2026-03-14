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
          components={{
            p: ({ children }) => <span>{children}</span>,
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