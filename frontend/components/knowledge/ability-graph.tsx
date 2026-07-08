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

const NODE_W = 190;
const NODE_H = 58;
const COL_GAP = 70;
const ROW_GAP = 26;
const PAD = 24;
const HEADER_H = 40;

interface Positioned {
  node: AbilityGraphNode;
  x: number;
  y: number;
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

    const positioned = new Map<number, Positioned>();
    columns.forEach((col, ci) => {
      col.nodes.forEach((n, ri) => {
        positioned.set(n.id, {
          node: n,
          x: PAD + ci * (NODE_W + COL_GAP),
          y: PAD + HEADER_H + ri * (NODE_H + ROW_GAP),
        });
      });
    });

    const maxRows = Math.max(...columns.map((c) => c.nodes.length), 1);
    const width = PAD * 2 + columns.length * NODE_W + (columns.length - 1) * COL_GAP;
    const height = PAD * 2 + HEADER_H + maxRows * NODE_H + (maxRows - 1) * ROW_GAP;

    return { columns, positioned, width, height };
  }, [graph]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

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
            Mỗi node là một chủ đề, tô màu theo mức mastery của bạn (từ kết quả các bài thi).
            Mũi tên liền: quan hệ tiên quyết · mũi tên đứt: quan hệ suy diễn (R12). Bấm node để xem chi tiết.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Legend */}
          <div className="flex flex-wrap gap-3 mb-3 text-xs">
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
          </div>

          {!graph || !layout ? (
            <p className="text-sm text-muted-foreground py-8 text-center">Đang tải đồ thị...</p>
          ) : (
            <div className="overflow-x-auto">
              <svg
                viewBox={`0 0 ${layout.width} ${layout.height}`}
                style={{ minWidth: Math.min(layout.width, 1100) }}
                className="w-full"
              >
                <defs>
                  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"
                    markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                    <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" />
                  </marker>
                </defs>

                {/* Column headers */}
                {layout.columns.map((col, ci) => (
                  <text
                    key={col.id}
                    x={PAD + ci * (NODE_W + COL_GAP) + NODE_W / 2}
                    y={PAD + 14}
                    textAnchor="middle"
                    fontSize="12"
                    fontWeight="600"
                    fill="currentColor"
                    fillOpacity="0.75"
                  >
                    {col.name.length > 30 ? col.name.slice(0, 28) + "…" : col.name}
                  </text>
                ))}

                {/* Edges */}
                {graph.edges.map((e, i) => {
                  const a = layout.positioned.get(e.from);
                  const b = layout.positioned.get(e.to);
                  if (!a || !b) return null;
                  const x1 = a.x + NODE_W;
                  const y1 = a.y + NODE_H / 2;
                  const x2 = b.x;
                  const y2 = b.y + NODE_H / 2;
                  const sameCol = a.x === b.x;
                  const d = sameCol
                    ? `M ${a.x + NODE_W / 2} ${a.y + NODE_H} C ${a.x + NODE_W / 2 + 40} ${a.y + NODE_H + 10}, ${b.x + NODE_W / 2 + 40} ${b.y - 10}, ${b.x + NODE_W / 2} ${b.y}`
                    : `M ${x1} ${y1} C ${x1 + COL_GAP / 2} ${y1}, ${x2 - COL_GAP / 2} ${y2}, ${x2} ${y2}`;
                  return (
                    <path
                      key={i}
                      d={d}
                      fill="none"
                      stroke="#64748b"
                      strokeWidth="1.5"
                      strokeDasharray={e.type === "inference" ? "5 4" : undefined}
                      markerEnd="url(#arrow)"
                      opacity="0.7"
                    />
                  );
                })}

                {/* Nodes */}
                {Array.from(layout.positioned.values()).map(({ node, x, y }) => {
                  const fill = node.mastery ? MASTERY_FILL[node.mastery] || "#cbd5e1" : "#cbd5e1";
                  const hasData = node.attempted > 0;
                  return (
                    <g
                      key={node.id}
                      onClick={() => setSelected(node)}
                      style={{ cursor: "pointer" }}
                    >
                      <rect
                        x={x} y={y} width={NODE_W} height={NODE_H} rx="10"
                        fill={fill}
                        fillOpacity={hasData ? 0.92 : 0.55}
                        stroke={selected?.id === node.id ? "#0f172a" : "white"}
                        strokeWidth={selected?.id === node.id ? 2.5 : 1.5}
                      />
                      <text x={x + 10} y={y + 22} fontSize="11" fontWeight="700" fill="white">
                        {(node.code ? node.code + " " : "") +
                          (node.name.length > 24 ? node.name.slice(0, 22) + "…" : node.name)}
                      </text>
                      <text x={x + 10} y={y + 42} fontSize="10" fill="white" fillOpacity="0.95">
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
                {selected.code} {selected.name}
                <span className="text-muted-foreground font-normal"> · {selected.major_topic_name}</span>
              </p>
              <div className="mt-1 grid grid-cols-2 md:grid-cols-4 gap-2 text-muted-foreground">
                <span>Mastery: <b className="text-foreground">{selected.mastery ? MASTERY_LABEL[selected.mastery] || selected.mastery : "Chưa có"}</b></span>
                <span>θ: <b className="text-foreground">{selected.theta != null ? selected.theta.toFixed(2) : "—"}</b></span>
                <span>Đã làm: <b className="text-foreground">{selected.correct}/{selected.attempted}</b></span>
                <span>Ngân hàng: <b className="text-foreground">{selected.question_count} câu</b></span>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
