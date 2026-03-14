"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { authAPI, adminAPI, type LLMRuntimeConfigInfo } from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function AdminSettingsPage() {
  const router = useRouter();
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [llmApiKeyInput, setLlmApiKeyInput] = useState("");

  const [form, setForm] = useState<LLMRuntimeConfigInfo>({
    llm_enabled: true,
    cat_enable_hybrid_llm_on_answer: false,
    has_llm_api_key: false,
    llm_system_prompt: "",
    llm_base_url: "",
    llm_model: "",
    llm_temperature: 0.2,
    llm_timeout_seconds: 30,
  });

  const loadData = useCallback(async () => {
    try {
      setError(null);
      const me = await authAPI.me();
      setUser(me);

      const config = await adminAPI.getLLMSettings();
      setForm(config);
      setLlmApiKeyInput("");
    } catch (e) {
      if (e instanceof Error) setError(e.message);
      router.push("/");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);
      setMessage(null);

      const updated = await adminAPI.updateLLMSettings({
        llm_enabled: form.llm_enabled,
        cat_enable_hybrid_llm_on_answer: form.cat_enable_hybrid_llm_on_answer,
        llm_api_key: llmApiKeyInput.trim() || undefined,
        llm_system_prompt: form.llm_system_prompt.trim(),
        llm_base_url: form.llm_base_url.trim(),
        llm_model: form.llm_model.trim(),
        llm_temperature: Number(form.llm_temperature),
        llm_timeout_seconds: Number(form.llm_timeout_seconds),
      });

      setForm(updated);
    setLlmApiKeyInput("");
      setMessage("Đã cập nhật cấu hình LLM.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không thể cập nhật cấu hình");
    } finally {
      setSaving(false);
    }
  };

  if (loading || !user) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary" />
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <Navbar user={user} onLogout={() => { localStorage.removeItem("kbs_token"); router.push("/"); }} />
      <main className="container py-6 space-y-6">
        <div className="rounded-2xl border border-slate-200 bg-gradient-to-br from-slate-100 via-white to-slate-50 p-5 shadow-sm">
          <h1 className="text-2xl font-bold tracking-tight">Cấu hình</h1>
          <p className="mt-1 text-sm text-muted-foreground">Quản lý cấu hình runtime cho LLM.</p>
        </div>

        {error && (
          <Card className="border-destructive/60 bg-destructive/5">
            <CardContent className="pt-6 text-destructive text-sm">{error}</CardContent>
          </Card>
        )}

        {message && (
          <Card className="border-emerald-300 bg-emerald-50/60">
            <CardContent className="pt-6 text-emerald-700 text-sm">{message}</CardContent>
          </Card>
        )}

        <Card className="border-violet-200 bg-violet-50/30 shadow-sm">
          <CardContent className="space-y-4 pt-6">
            <label className="flex items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                checked={form.llm_enabled}
                onChange={(e) => setForm((prev) => ({ ...prev, llm_enabled: e.target.checked }))}
              />
              Bật kết nối AI (LLM)
            </label>

            <label className="flex items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                checked={form.cat_enable_hybrid_llm_on_answer}
                onChange={(e) => setForm((prev) => ({ ...prev, cat_enable_hybrid_llm_on_answer: e.target.checked }))}
              />
              Bật LLM kết hợp CAT khi làm bài
            </label>

            <p className="text-sm text-muted-foreground">
              Khi bật, CAT có thể sinh thêm câu hỏi bằng LLM ngay trong luồng trả lời nếu ngân hàng hiện tại không có câu đủ gần mức độ khó mục tiêu.
            </p>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-1">
                <label className="text-sm font-medium">LLM Base URL</label>
                <Input
                  value={form.llm_base_url}
                  onChange={(e) => setForm((prev) => ({ ...prev, llm_base_url: e.target.value }))}
                  placeholder="https://api.openai.com/v1"
                />
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">Model</label>
                <Input
                  value={form.llm_model}
                  onChange={(e) => setForm((prev) => ({ ...prev, llm_model: e.target.value }))}
                  placeholder="gpt-5.1"
                />
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">Temperature</label>
                <Input
                  type="number"
                  step="0.1"
                  min={0}
                  max={2}
                  value={form.llm_temperature}
                  onChange={(e) => setForm((prev) => ({ ...prev, llm_temperature: Number(e.target.value) }))}
                />
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">Timeout (seconds)</label>
                <Input
                  type="number"
                  min={1}
                  max={300}
                  value={form.llm_timeout_seconds}
                  onChange={(e) => setForm((prev) => ({ ...prev, llm_timeout_seconds: Number(e.target.value) }))}
                />
              </div>
            </div>

            {form.llm_enabled && (
              <div>
                <div className="space-y-1">
                  <label className="text-sm font-medium">LLM API Key</label>
                  <Input
                    type="password"
                    value={llmApiKeyInput}
                    onChange={(e) => setLlmApiKeyInput(e.target.value)}
                    placeholder={form.has_llm_api_key ? "Đã có API key, nhập giá trị mới để thay thế" : "Nhập API key"}
                  />
                </div>
                <p className="text-sm text-muted-foreground">
                  {form.has_llm_api_key
                    ? "API key hiện có đang được lưu. Để trống nếu muốn giữ nguyên."
                    : "Chưa có API key được lưu cho cấu hình runtime hiện tại."}
                </p>

                <div className="space-y-1">
                  <label className="text-sm font-medium">System Prompt</label>
                  <textarea
                    value={form.llm_system_prompt}
                    onChange={(e) => setForm((prev) => ({ ...prev, llm_system_prompt: e.target.value }))}
                    rows={16}
                    className="flex min-h-[320px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-xs outline-none transition-[color,box-shadow] placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                    placeholder="Nhập system prompt cho bộ sinh câu hỏi"
                  />
                </div>
                <p className="text-sm text-muted-foreground">
                  Mặc định được bootstrap từ file `backend/prompts/question_generator.system.md`, sau đó có thể chỉnh trực tiếp tại đây.
                </p>
              </div>
            )}

            <Button onClick={handleSave} disabled={saving}>
              {saving ? "Đang lưu..." : "Lưu cấu hình"}
            </Button>
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
