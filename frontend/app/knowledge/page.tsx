"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { authAPI } from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { KnowledgeMap } from "@/components/knowledge/knowledge-map";
import { AbilityGraph } from "@/components/knowledge/ability-graph";
import { Button } from "@/components/ui/button";
import { ListTree, Network } from "lucide-react";

export default function KnowledgePage() {
  const router = useRouter();
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);
  const [view, setView] = useState<"tree" | "graph">("graph");

  const checkAuth = useCallback(async () => {
    try {
      const me = await authAPI.me();
      setUser(me);
    } catch {
      router.push("/");
    }
  }, [router]);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  if (!user) return null;

  return (
    <div className="min-h-screen">
      <Navbar user={user} onLogout={() => { localStorage.removeItem("kbs_token"); router.push("/"); }} />
      <main className="container py-6 space-y-4">
        <div className="flex items-center gap-2">
          <Button
            variant={view === "graph" ? "default" : "outline"}
            size="sm"
            onClick={() => setView("graph")}
          >
            <Network className="h-4 w-4 mr-1" />
            Đồ thị năng lực
          </Button>
          <Button
            variant={view === "tree" ? "default" : "outline"}
            size="sm"
            onClick={() => setView("tree")}
          >
            <ListTree className="h-4 w-4 mr-1" />
            Cây tri thức
          </Button>
        </div>
        {view === "graph" ? <AbilityGraph /> : <KnowledgeMap />}
      </main>
    </div>
  );
}
