"use client";

import { useState, useEffect } from "react";
import { presetAPI, type SubjectSummary, type PresetExamInfo } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { FileText, Play } from "lucide-react";

interface PresetListProps {
  subjects: SubjectSummary[];
  onStart: (presetId: number) => Promise<void> | void;
}

const BLOOM_COLOR: Record<string, string> = {
  "Nhận biết": "bg-sky-100 text-sky-800",
  "Thông hiểu": "bg-yellow-100 text-yellow-800",
  "Vận dụng": "bg-purple-100 text-purple-800",
};

export function PresetList({ subjects, onStart }: PresetListProps) {
  const [subjectId, setSubjectId] = useState<number>(0);
  const [presets, setPresets] = useState<PresetExamInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [startingId, setStartingId] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (subjects.length > 0 && !subjectId) setSubjectId(subjects[0].id);
  }, [subjects, subjectId]);

  useEffect(() => {
    if (!subjectId) return;
    setLoading(true);
    presetAPI
      .list(subjectId)
      .then(setPresets)
      .catch(() => setPresets([]))
      .finally(() => setLoading(false));
  }, [subjectId]);

  const handleStart = async (presetId: number) => {
    setStartingId(presetId);
    setError("");
    try {
      await onStart(presetId);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Có lỗi xảy ra");
      setStartingId(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label>Môn học</Label>
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
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {loading ? (
        <div className="flex justify-center py-10">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
        </div>
      ) : presets.length === 0 ? (
        <p className="text-sm text-muted-foreground py-6 text-center">
          Môn này chưa có đề thi có sẵn.
        </p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {presets.map((p) => (
            <Card key={p.id}>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-base">
                  <FileText className="h-4 w-4 text-primary" />
                  {p.name}
                  <span className="ml-auto text-sm font-normal text-muted-foreground">
                    {p.question_count} câu · {p.topic_count} chủ đề
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(p.bloom_counts).map(([label, count]) => (
                    <span
                      key={label}
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${BLOOM_COLOR[label] || "bg-slate-100 text-slate-700"}`}
                    >
                      {label}: {count}
                    </span>
                  ))}
                </div>
                <Button
                  size="sm"
                  className="w-full"
                  onClick={() => handleStart(p.id)}
                  disabled={startingId !== null}
                >
                  <Play className="h-4 w-4 mr-1" />
                  {startingId === p.id ? "Đang tạo phiên..." : "Làm đề này"}
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
