"use client";

import { useState, useEffect, useMemo } from "react";
import {
  knowledgeAPI,
  type SubjectSummary,
  type AbilityGraphInfo,
  type AbilityGraphNode,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const MASTERY_FILL: Record<string, string> = {
  master: "#16a34a",
  proficient: "#2563eb",
  developing: "#eab308",
  beginner: "#f97316",
  novice: "#dc2626",
};

const MASTERY_LABEL: Record<string, string> = {
  master: "Xuất sắc",
  proficient: "Giỏi",
  developing: "Khá",
  beginner: "Trung bình",
  novice: "Cần cải thiện",
};

const PREREQ_COLOR = "#475569";
const INFER_COLOR = "#9333ea";

const NODE_W = 200;
const NODE_H = 58;
const COL_GAP = 90;
const ROW_GAP = 42;
const PAD = 28;
const HEADER_H = 44;

interface Positioned {
  node: AbilityGraphNode;
  x: number;
  y: number;
}

/** Topic names already include their code ("1.1 Lệnh DML cơ bản") — avoid "1.1 1.1 ...". */
function nodeLabel(node: AbilityGraphNode): string {
  const name = (node.name || "").trim();
  const code = (node.code || "").trim();
  if (!code || name.startsWith(code)) return name;
  return `${code} ${name}`;
}

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

/** Order nodes inside one column so prerequisite arrows always flow downward. */
function topoSortColumn(
  nodes: AbilityGraphNode[],
  edges: { from: number; to: number }[]
): AbilityGraphNode[] {
  const ids = new Set(nodes.map((n) => n.id));
  const local = edges.filter((e) => ids.has(e.from) && ids.has(e.to));
  const baseOrder = new Map(nodes.map((n, i) => [n.id, i]));
  const indegree = new Map(nodes.map((n) => [n.id, 0]));
  for (const e of local) indegree.set(e.to, (indegree.get(e.to) || 0) + 1);

  const result: AbilityGraphNode[] = [];
  const ready = nodes.filter((n) => (indegree.get(n.id) || 0) === 0);
  const placed = new Set<number>();
  while (ready.length) {
    ready.sort((a, b) => (baseOrder.get(a.id)! - baseOrder.get(b.id)!));
    const cur = ready.shift()!;
    result.push(cur);
    placed.add(cur.id);
    for (const e of local) {
      if (e.from === cur.id && !placed.has(e.to)) {
        indegree.set(e.to, (indegree.get(e.to) || 0) - 1);
        if ((indegree.get(e.to) || 0) === 0) {
          const n = nodes.find((x) => x.id === e.to);
          if (n && !result.includes(n) && !ready.includes(n)) ready.push(n);
        }
      }
    }
  }
  // Cycle fallback: append leftovers in original order
  for (const n of nodes) if (!placed.has(n.id)) result.push(n);
  return result;
}

export function AbilityGraph() {
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const [graph, setGraph] = useState<AbilityGraphInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<AbilityGraphNode | null>(null);

  useEffect(() => {
    knowledgeAPI.getSubjects().then((subs) => {
      setSubjects(subs);
      if (subs.length > 0) setSubjectId(subs[0].id);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    if (!subjectId) return;
    setGraph(null);
    setSelected(null);
    knowledgeAPI.getAbilityGraph(subjectId).then(setGraph).catch(() => setGraph(null));
  }, [subjectId]);

  const layout = useMemo(() => {
    if (!graph) return null;

    // Columns = major topics, ordered
    const columns: { id: number; name: string; nodes: AbilityGraphNode[] }[] = [];
    const colIndex = new Map<number, number>();
    for (const n of graph.nodes) {
      if (!colIndex.has(n.major_topic_id)) {
        colIndex.set(n.major_topic_id, columns.length);
        columns.push({ id: n.major_topic_id, name: n.major_topic_name, nodes: [] });
      }
      columns[colIndex.get(n.major_topic_id)!].nodes.push(n);
    }

    // Sort within each column so intra-column arrows flow downward
    for (const col of columns) {
      col.nodes = topoSortColumn(col.nodes, graph.edges);
    }

    const positioned = new Map<number, Positioned>();
    const rowOf = new Map<number, number>();
    const colOf = new Map<number, number>();
    columns.forEach((col, ci) => {
      col.nodes.forEach((n, ri) => {
        positioned.set(n.id, {
          node: n,
          x: PAD + ci * (NODE_W + COL_GAP),
          y: PAD + HEADER_H + ri * (NODE_H + ROW_GAP),
        });
        rowOf.set(n.id, ri);
        colOf.set(n.id, ci);
      });
    });

    const maxRows = Math.max(...columns.map((c) => c.nodes.length), 1);
    const width = PAD * 2 + columns.length * NODE_W + (columns.length - 1) * COL_GAP;
    const height = PAD * 2 + HEADER_H + maxRows * NODE_H + (maxRows - 1) * ROW_GAP;

    return { columns, positioned, rowOf, colOf, width, height };
  }, [graph]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

  const isEdgeHighlighted = (e: { from: number; to: number }) =>
    selected != null && (e.from === selected.id || e.to === selected.id);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {subjects.map((s) => (
          <Button
            key={s.id}
            variant={subjectId === s.id ? "default" : "outline"}
            size="sm"
            onClick={() => setSubjectId(s.id)}
          >
            {s.name}
          </Button>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Đồ thị tri thức năng lực cá nhân</CardTitle>
          <CardDescription>
            Mỗi node là một chủ đề, tô màu theo mức mastery của bạn. Mũi tên chỉ hướng học:
            từ kiến thức nền đến chủ đề phụ thuộc. Bấm node để xem chi tiết và làm nổi các quan hệ của nó.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Legend */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 mb-4 text-xs">
            {Object.entries(MASTERY_LABEL).map(([key, label]) => (
              <span key={key} className="flex items-center gap-1.5">
                <span className="inline-block h-3 w-3 rounded" style={{ backgroundColor: MASTERY_FILL[key] }} />
                {label}
              </span>
            ))}
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-3 w-3 rounded bg-slate-300" />
              Chưa có dữ liệu
            </span>
            <span className="mx-1 h-4 w-px bg-border" />
            <span className="flex items-center gap-1.5">
              <svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke={PREREQ_COLOR} strokeWidth="2" /></svg>
              Tiên quyết
            </span>
            <span className="flex items-center gap-1.5">
              <svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke={INFER_COLOR} strokeWidth="2" strokeDasharray="5 3" /></svg>
              Suy diễn (R12)
            </span>
          </div>

          {!graph || !layout ? (
            <p className="text-sm text-muted-foreground py-8 text-center">Đang tải đồ thị...</p>
          ) : (
            <div className="overflow-x-auto">
              <svg
                viewBox={`0 0 ${layout.width} ${layout.height}`}
                style={{ minWidth: Math.min(layout.width, 1150) }}
                className="w-full"
              >
                <defs>
                  <marker id="arrow-prereq" viewBox="0 0 10 10" refX="8.5" refY="5"
                    markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
                    <path d="M 0 0 L 10 5 L 0 10 z" fill={PREREQ_COLOR} />
                  </marker>
                  <marker id="arrow-infer" viewBox="0 0 10 10" refX="8.5" refY="5"
                    markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
                    <path d="M 0 0 L 10 5 L 0 10 z" fill={INFER_COLOR} />
                  </marker>
                </defs>

                {/* Column headers */}
                {layout.columns.map((col, ci) => (
                  <g key={col.id}>
                    <text
                      x={PAD + ci * (NODE_W + COL_GAP) + NODE_W / 2}
                      y={PAD + 14}
                      textAnchor="middle"
                      fontSize="13"
                      fontWeight="700"
                      fill="currentColor"
                      fillOpacity="0.8"
                    >
                      {truncate(col.name, 32)}
                    </text>
                    <line
                      x1={PAD + ci * (NODE_W + COL_GAP) + 20}
                      y1={PAD + 24}
                      x2={PAD + ci * (NODE_W + COL_GAP) + NODE_W - 20}
                      y2={PAD + 24}
                      stroke="currentColor"
                      strokeOpacity="0.15"
                    />
                  </g>
                ))}

                {/* Edges (drawn under nodes) */}
                {graph.edges.map((e, i) => {
                  const a = layout.positioned.get(e.from);
                  const b = layout.positioned.get(e.to);
                  if (!a || !b) return null;

                  const highlighted = isEdgeHighlighted(e);
                  const dimmed = selected != null && !highlighted;
                  const color = e.type === "inference" ? INFER_COLOR : PREREQ_COLOR;
                  const marker = e.type === "inference" ? "url(#arrow-infer)" : "url(#arrow-prereq)";
                  const sameCol = layout.colOf.get(e.from) === layout.colOf.get(e.to);

                  let d: string;
                  if (sameCol) {
                    const rowA = layout.rowOf.get(e.from)!;
                    const rowB = layout.rowOf.get(e.to)!;
                    if (Math.abs(rowA - rowB) === 1 && rowB > rowA) {
                      // Adjacent rows: short vertical arrow between the nodes
                      const x = a.x + NODE_W / 2;
                      d = `M ${x} ${a.y + NODE_H} L ${x} ${b.y - 2}`;
                    } else {
                      // Skipping rows (or upward): bow out on the left side
                      const x1 = a.x;
                      const y1 = a.y + NODE_H / 2;
                      const x2 = b.x;
                      const y2 = b.y + NODE_H / 2;
                      const bow = 34;
                      d = `M ${x1} ${y1} C ${x1 - bow} ${y1}, ${x2 - bow} ${y2}, ${x2 - 2} ${y2}`;
                    }
                  } else {
                    // Cross-column: right edge -> left edge
                    const x1 = a.x + NODE_W;
                    const y1 = a.y + NODE_H / 2;
                    const x2 = b.x;
                    const y2 = b.y + NODE_H / 2;
                    d = `M ${x1} ${y1} C ${x1 + COL_GAP / 2} ${y1}, ${x2 - COL_GAP / 2} ${y2}, ${x2 - 2} ${y2}`;
                  }

                  return (
                    <path
                      key={i}
                      d={d}
                      fill="none"
                      stroke={color}
                      strokeWidth={highlighted ? 2.6 : 1.6}
                      strokeDasharray={e.type === "inference" ? "6 4" : undefined}
                      markerEnd={marker}
                      opacity={dimmed ? 0.15 : highlighted ? 1 : 0.55}
                    />
                  );
                })}

                {/* Nodes */}
                {Array.from(layout.positioned.values()).map(({ node, x, y }) => {
                  // Color by decayed mastery (forgetting curve) when available
                  const masteryForColor = node.mastery_effective || node.mastery;
                  const fill = masteryForColor ? MASTERY_FILL[masteryForColor] || "#cbd5e1" : "#cbd5e1";
                  const hasData = node.attempted > 0;
                  const isSelected = selected?.id === node.id;
                  const related =
                    selected != null &&
                    graph.edges.some(
                      (e) =>
                        (e.from === selected.id && e.to === node.id) ||
                        (e.to === selected.id && e.from === node.id)
                    );
                  const dimmed = selected != null && !isSelected && !related;
                  return (
                    <g
                      key={node.id}
                      onClick={() => setSelected(isSelected ? null : node)}
                      style={{ cursor: "pointer" }}
                      opacity={dimmed ? 0.35 : 1}
                    >
                      <rect
                        x={x} y={y} width={NODE_W} height={NODE_H} rx="10"
                        fill={fill}
                        fillOpacity={hasData ? 0.95 : 0.5}
                        stroke={isSelected ? "#0f172a" : "white"}
                        strokeWidth={isSelected ? 3 : 1.5}
                      />
                      <text x={x + 11} y={y + 23} fontSize="12" fontWeight="700" fill="white">
                        {truncate(nodeLabel(node), 27)}
                      </text>
                      <text x={x + 11} y={y + 43} fontSize="10.5" fill="white" fillOpacity="0.95">
                        {hasData
                          ? `θ = ${node.theta?.toFixed(2) ?? "?"} · ${node.correct}/${node.attempted} đúng`
                          : "Chưa làm câu nào"}
                      </text>
                    </g>
                  );
                })}
              </svg>
            </div>
          )}

          {/* Selected node detail */}
          {selected && (
            <div className="mt-4 rounded-lg border p-4 text-sm">
              <p className="font-semibold">
                {nodeLabel(selected)}
                <span className="text-muted-foreground font-normal"> · {selected.major_topic_name}</span>
              </p>
              <div className="mt-1 grid grid-cols-2 md:grid-cols-4 gap-2 text-muted-foreground">
                <span>Mastery: <b className="text-foreground">{selected.mastery ? MASTERY_LABEL[selected.mastery] || selected.mastery : "Chưa có"}</b></span>
                <span>θ: <b className="text-foreground">{selected.theta != null ? selected.theta.toFixed(2) : "—"}</b></span>
                <span>Đã làm: <b className="text-foreground">{selected.correct}/{selected.attempted}</b></span>
                <span>Ngân hàng: <b className="text-foreground">{selected.question_count} câu</b></span>
              </div>
              {selected.theta_effective != null && selected.theta != null
                && selected.theta_effective < selected.theta && (
                <p className="mt-1 text-xs text-orange-600">
                  ⏳ Sau {selected.days_since_practice} ngày không ôn, θ hiệu dụng còn{" "}
                  <b>{selected.theta_effective.toFixed(2)}</b> (đường cong quên Ebbinghaus)
                </p>
              )}
              {(() => {
                if (!graph) return null;
                const nameOf = (id: number) => {
                  const n = graph.nodes.find((x) => x.id === id);
                  return n ? nodeLabel(n) : `#${id}`;
                };
                const prereqs = graph.edges.filter((e) => e.to === selected.id).map((e) => nameOf(e.from));
                const dependents = graph.edges.filter((e) => e.from === selected.id).map((e) => nameOf(e.to));
                if (!prereqs.length && !dependents.length) return null;
                return (
                  <div className="mt-2 grid gap-1 text-xs text-muted-foreground">
                    {prereqs.length > 0 && (
                      <span>← Học trước: <b className="text-foreground">{prereqs.join(", ")}</b></span>
                    )}
                    {dependents.length > 0 && (
                      <span>→ Mở khóa: <b className="text-foreground">{dependents.join(", ")}</b></span>
                    )}
                  </div>
                );
              })()}
              {selected.skills && selected.skills.length > 0 && (
                <div className="mt-2 border-t pt-2">
                  <p className="text-xs text-muted-foreground mb-1">Kỹ năng đo được của chủ đề này:</p>
                  <div className="flex flex-wrap gap-1.5">
                    {selected.skills.map((s) => (
                      <span
                        key={s.id}
                        className={
                          s.kind === "application"
                            ? "rounded-full bg-purple-100 px-2 py-0.5 text-xs text-purple-800"
                            : "rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-800"
                        }
                      >
                        {s.name}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
