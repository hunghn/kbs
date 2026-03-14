"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { type SubjectSummary } from "@/lib/api";
import { GraduationCap, Settings2 } from "lucide-react";

interface QuizSetupProps {
  subjects: SubjectSummary[];
  defaultSubjectId?: number;
  onStart: (config: {
    subject_id: number;
    num_questions: number;
    recognition_pct: number;
    comprehension_pct: number;
    application_pct: number;
  }) => void;
}

export function QuizSetup({ subjects, defaultSubjectId, onStart }: QuizSetupProps) {
  const [subjectId, setSubjectId] = useState<number>(0);
  const [numQuestions, setNumQuestions] = useState(20);
  const [recognition, setRecognition] = useState(30);
  const [comprehension, setComprehension] = useState(50);
  const [application, setApplication] = useState(20);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!defaultSubjectId) return;
    if (subjects.some((s) => s.id === defaultSubjectId)) {
      setSubjectId(defaultSubjectId);
    }
  }, [defaultSubjectId, subjects]);

  const handleStart = async () => {
    if (!subjectId || !subjects.some((s) => s.id === subjectId)) {
      setError("Bạn phải chọn môn học trước khi bắt đầu");
      return;
    }

    const total = recognition + comprehension + application;
    if (total !== 100) {
      setError(`Tổng tỷ lệ phải bằng 100% (hiện tại: ${total}%)`);
      return;
    }
    setError("");
    setLoading(true);
    try {
      await onStart({
        subject_id: subjectId,
        num_questions: numQuestions,
        recognition_pct: recognition / 100,
        comprehension_pct: comprehension / 100,
        application_pct: application / 100,
      });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Có lỗi xảy ra");
      setLoading(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Bắt đầu Bài thi</h1>
        <p className="text-muted-foreground mt-1">
          Cấu hình bài thi theo cấu trúc tri thức
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings2 className="h-5 w-5" />
            Cấu hình bài thi
          </CardTitle>
          <CardDescription>
            Chọn môn học và phân bổ tỷ lệ câu hỏi theo mức độ nhận thức
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
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
                  {s.name} ({s.total_questions})
                </Button>
              ))}
            </div>
            {subjectId === 0 && (
              <p className="text-xs text-muted-foreground">
                Chưa chọn môn học.
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="numQuestions">Số câu hỏi</Label>
            <Input
              id="numQuestions"
              type="number"
              min={5}
              max={50}
              value={numQuestions}
              onChange={(e) => setNumQuestions(parseInt(e.target.value) || 20)}
            />
          </div>

          <div className="space-y-3">
            <Label>Phân bổ theo mức độ (%)</Label>
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">Nhận biết</Label>
                <Input
                  type="number"
                  min={0} max={100}
                  value={recognition}
                  onChange={(e) => setRecognition(parseInt(e.target.value) || 0)}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">Thông hiểu</Label>
                <Input
                  type="number"
                  min={0} max={100}
                  value={comprehension}
                  onChange={(e) => setComprehension(parseInt(e.target.value) || 0)}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">Vận dụng</Label>
                <Input
                  type="number"
                  min={0} max={100}
                  value={application}
                  onChange={(e) => setApplication(parseInt(e.target.value) || 0)}
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Tổng: {recognition + comprehension + application}% (phải bằng 100%)
            </p>
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}
        </CardContent>
        <CardFooter>
          <Button onClick={handleStart} disabled={loading} className="w-full" size="lg">
            {loading ? (
              "Đang tạo đề..."
            ) : (
              <>
                <GraduationCap className="h-5 w-5 mr-2" />
                Bắt đầu làm bài
              </>
            )}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
