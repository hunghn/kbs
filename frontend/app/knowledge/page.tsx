"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { authAPI } from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { KnowledgeMap } from "@/components/knowledge/knowledge-map";

export default function KnowledgePage() {
  const router = useRouter();
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);

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
      <main className="container py-6">
        <KnowledgeMap />
      </main>
    </div>
  );
}
