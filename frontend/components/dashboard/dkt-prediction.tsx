"use client";

import { useState, useEffect, useCallback } from "react";
import { userAPI, knowledgeAPI, type SubjectSummary, type DKTPredictionInfo } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { BrainCircuit } from "lucide-react";

export function DKTPrediction() {
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const [prediction, setPrediction] = useState<DKTPredictionInfo | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    knowledgeAPI.getSubjects().then((subs) => {
      setSubjects(subs);
      if (subs.length > 0) setSubjectId(subs[0].id);
    });
  }, []);

  const load = useCallback(async (sid: number) => {
    setPrediction(null);
    setError("");
    try {
      setPrediction(await userAPI.getAbilityPrediction(sid));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Không tải được dự đoán");
    }
  }, []);

  useEffect(() => {
    if (subjectId) load(subjectId);
  }, [subjectId, load]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BrainCircuit className="h-5 w-5 text-purple-500" />
          Dự đoán năng lực (Deep Knowledge Tracing)
        </CardTitle>
        <CardDescription>
          Mạng RNN học từ chuỗi câu trả lời của bạn để dự đoán xác suất trả lời đúng câu tiếp theo trên từng chủ đề
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
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

        {error && (
          <p className="text-sm text-muted-foreground py-2">{error}</p>
        )}

        {prediction && (
          <>
            <p className="text-xs text-muted-foreground">
              Dựa trên {prediction.history_length} câu trả lời gần nhất của bạn
            </p>
            <div className="space-y-1.5">
              {prediction.predictions.map((p) => (
                <div key={p.topic_id} className="flex items-center gap-2 text-xs">
                  <span className="w-44 shrink-0 truncate" title={p.topic_name}>
                    {p.code && !p.topic_name.startsWith(p.code) ? `${p.code} ` : ""}{p.topic_name}
                  </span>
                  <Progress value={p.p_correct_next * 100} className="h-2 flex-1" />
                  <span className="w-12 shrink-0 text-right font-mono">
                    {Math.round(p.p_correct_next * 100)}%
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
