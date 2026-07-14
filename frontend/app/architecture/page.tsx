"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { authAPI, agentsAPI, type AgentArchitectureInfo, type AgentInfo } from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";

const KIND_FILL: Record<string, string> = {
  symbolic: "#0284c7", // rule/symbolic reasoning
  llm: "#9333ea",      // LLM-powered
  neural: "#16a34a",   // learned models (DKT/RL)
};

const KIND_LABEL: Record<string, string> = {
  symbolic: "Suy diễn ký hiệu (luật/IRT)",
  llm: "Tác tử LLM",
  neural: "Mô hình học (DKT/RL)",
};

const NODE_W = 200;
const NODE_H = 74;
const EXT_W = 170;
const EXT_H = 56;

// Hand-tuned layout: planner is the hub, learner on the left, KB bottom-left
const POS: Record<string, { x: number; y: number }> = {
  learner: { x: 40, y: 300 },
  kb: { x: 40, y: 560 },
  planner: { x: 330, y: 280 },
  generator: { x: 330, y: 60 },
  validator: { x: 640, y: 60 },
  assessor: { x: 640, y: 300 },
  strategist: { x: 330, y: 540 },
  tracer: { x: 640, y: 540 },
  explainer: { x: 950, y: 180 },
  pathfinder: { x: 950, y: 380 },
  calibrator: { x: 950, y: 560 },
};

const W = 1200;
const H = 680;

function centerOf(id: string, isExternal: boolean) {
  const p = POS[id] || { x: 0, y: 0 };
  const w = isExternal ? EXT_W : NODE_W;
  const h = isExternal ? EXT_H : NODE_H;
  return { cx: p.x + w / 2, cy: p.y + h / 2, w, h, x: p.x, y: p.y };
}

export default function ArchitecturePage() {
  const router = useRouter();
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);
  const [arch, setArch] = useState<AgentArchitectureInfo | null>(null);
  const [selected, setSelected] = useState<AgentInfo | null>(null);

  const loadData = useCallback(async () => {
    try {
      const me = await authAPI.me();
      setUser(me);
      setArch(await agentsAPI.getArchitecture());
    } catch {
      router.push("/");
    }
  }, [router]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (!user) return null;

  const externalIds = new Set((arch?.externals || []).map((e) => e.id));

  const isRelated = (edge: { from: string; to: string }) =>
    selected != null && (edge.from === selected.id || edge.to === selected.id);

  return (
    <div className="min-h-screen">
      <Navbar user={user} onLogout={() => { localStorage.removeItem("kbs_token"); router.push("/"); }} />
      <main className="container py-6 space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Kiến trúc Multi-Agent System</h1>
          <p className="text-muted-foreground mt-1">
            Hệ thống được tổ chức thành các tác tử chuyên biệt trao đổi thông điệp quanh Planner.
            Số trên mỗi tác tử là số quyết định thực tế đã ghi trong rule logs. Bấm tác tử để xem chi tiết.
          </p>
        </div>

        <Card>
          <CardHeader className="pb-2">
            <div className="flex flex-wrap gap-4 text-xs">
              {Object.entries(KIND_LABEL).map(([kind, label]) => (
                <span key={kind} className="flex items-center gap-1.5">
                  <span className="inline-block h-3 w-3 rounded" style={{ backgroundColor: KIND_FILL[kind] }} />
                  {label}
                </span>
              ))}
              <span className="flex items-center gap-1.5">
                <span className="inline-block h-3 w-3 rounded bg-slate-400" />
                Thành phần ngoài (người học, CSDL tri thức)
              </span>
            </div>
          </CardHeader>
          <CardContent>
            {!arch ? (
              <div className="flex justify-center py-16">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <svg viewBox={`0 0 ${W} ${H}`} style={{ minWidth: 1000 }} className="w-full">
                  <defs>
                    <marker id="mas-arrow" viewBox="0 0 10 10" refX="8.5" refY="5"
                      markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                      <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" />
                    </marker>
                  </defs>

                  {/* Edges */}
                  {arch.edges.map((e, i) => {
                    const a = centerOf(e.from, externalIds.has(e.from));
                    const b = centerOf(e.to, externalIds.has(e.to));
                    if (!POS[e.from] || !POS[e.to]) return null;
                    const highlighted = isRelated(e);
                    const dimmed = selected != null && !highlighted;
                    // Connect nearest edges horizontally
                    const fromRight = a.cx < b.cx;
                    const x1 = fromRight ? a.x + a.w : a.x;
                    const x2 = fromRight ? b.x : b.x + b.w;
                    const midX = (x1 + x2) / 2;
                    const d = `M ${x1} ${a.cy} C ${midX} ${a.cy}, ${midX} ${b.cy}, ${x2} ${b.cy}`;
                    return (
                      <g key={i} opacity={dimmed ? 0.12 : 1}>
                        <path d={d} fill="none" stroke="#64748b"
                          strokeWidth={highlighted ? 2.4 : 1.4} markerEnd="url(#mas-arrow)" opacity="0.75" />
                        {(highlighted || selected == null) && (
                          <text x={midX} y={(a.cy + b.cy) / 2 - 5} fontSize="9.5" textAnchor="middle"
                            fill="currentColor" fillOpacity={highlighted ? 0.95 : 0.55}>
                            {e.label}
                          </text>
                        )}
                      </g>
                    );
                  })}

                  {/* External nodes */}
                  {arch.externals.map((ext) => {
                    const p = POS[ext.id];
                    if (!p) return null;
                    return (
                      <g key={ext.id}>
                        <rect x={p.x} y={p.y} width={EXT_W} height={EXT_H} rx="28"
                          fill="#94a3b8" fillOpacity="0.9" stroke="white" strokeWidth="1.5" />
                        <text x={p.x + EXT_W / 2} y={p.y + EXT_H / 2 + 4} fontSize="12"
                          fontWeight="700" textAnchor="middle" fill="white">
                          {ext.name.length > 24 ? ext.name.slice(0, 22) + "…" : ext.name}
                        </text>
                      </g>
                    );
                  })}

                  {/* Agent nodes */}
                  {arch.agents.map((agent) => {
                    const p = POS[agent.id];
                    if (!p) return null;
                    const fill = KIND_FILL[agent.kind] || "#64748b";
                    const isSel = selected?.id === agent.id;
                    const dimmed = selected != null && !isSel &&
                      !arch.edges.some((e) => isRelated(e) && (e.from === agent.id || e.to === agent.id));
                    return (
                      <g key={agent.id} style={{ cursor: "pointer" }}
                        opacity={dimmed ? 0.35 : 1}
                        onClick={() => setSelected(isSel ? null : agent)}>
                        <rect x={p.x} y={p.y} width={NODE_W} height={NODE_H} rx="12"
                          fill={fill} fillOpacity="0.94"
                          stroke={isSel ? "#0f172a" : "white"} strokeWidth={isSel ? 3 : 1.5} />
                        <text x={p.x + 12} y={p.y + 24} fontSize="13" fontWeight="700" fill="white">
                          {agent.name}
                        </text>
                        <text x={p.x + 12} y={p.y + 42} fontSize="9.5" fill="white" fillOpacity="0.9">
                          {agent.rules.length > 0 ? "Luật: " + agent.rules.join(", ") : "Dịch vụ phân tích"}
                        </text>
                        <text x={p.x + 12} y={p.y + 58} fontSize="9" fill="white" fillOpacity="0.75">
                          {agent.module.split("/").pop()}
                        </text>
                        {agent.activity_count > 0 && (
                          <>
                            <rect x={p.x + NODE_W - 46} y={p.y - 10} width="46" height="20" rx="10"
                              fill="#0f172a" />
                            <text x={p.x + NODE_W - 23} y={p.y + 4} fontSize="10" fontWeight="700"
                              textAnchor="middle" fill="white">
                              {agent.activity_count}
                            </text>
                          </>
                        )}
                      </g>
                    );
                  })}
                </svg>
              </div>
            )}

            {selected && (
              <div className="mt-4 rounded-lg border p-4 text-sm space-y-1.5">
                <p className="font-semibold flex items-center gap-2">
                  <span className="inline-block h-3 w-3 rounded" style={{ backgroundColor: KIND_FILL[selected.kind] }} />
                  {selected.name}
                  <span className="text-xs font-normal text-muted-foreground">({KIND_LABEL[selected.kind]})</span>
                </p>
                <p className="text-muted-foreground">{selected.role}</p>
                <div className="grid gap-1 text-xs text-muted-foreground md:grid-cols-2">
                  <span>Mô-đun: <code className="text-foreground">{selected.module}</code></span>
                  <span>
                    Luật sở hữu:{" "}
                    <b className="text-foreground">{selected.rules.length ? selected.rules.join(", ") : "—"}</b>
                    {selected.activity_count > 0 && <> · đã kích hoạt <b className="text-foreground">{selected.activity_count}</b> lần</>}
                  </span>
                  {selected.endpoints.length > 0 && (
                    <span className="md:col-span-2">
                      Endpoint: {selected.endpoints.map((e) => (
                        <code key={e} className="text-foreground mr-2">{e}</code>
                      ))}
                    </span>
                  )}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Bảng tác tử</CardTitle>
            <CardDescription>Mỗi tác tử sở hữu một nhóm luật suy diễn và một mô-đun cài đặt riêng</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="py-2 pr-4">Tác tử</th>
                    <th className="py-2 pr-4">Vai trò</th>
                    <th className="py-2 pr-4">Luật</th>
                    <th className="py-2">Hoạt động</th>
                  </tr>
                </thead>
                <tbody>
                  {(arch?.agents || []).map((a) => (
                    <tr key={a.id} className="border-b last:border-0 align-top">
                      <td className="py-2 pr-4 font-medium whitespace-nowrap">
                        <span className="inline-block h-2.5 w-2.5 rounded-full mr-2"
                          style={{ backgroundColor: KIND_FILL[a.kind] }} />
                        {a.name}
                      </td>
                      <td className="py-2 pr-4 text-muted-foreground">{a.role}</td>
                      <td className="py-2 pr-4 whitespace-nowrap">{a.rules.join(", ") || "—"}</td>
                      <td className="py-2">{a.activity_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
