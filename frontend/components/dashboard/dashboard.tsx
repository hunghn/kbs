"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { userAPI, knowledgeAPI, type DashboardInfo, type SubjectSummary } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  GraduationCap, Target, TrendingUp, BookOpen,
  CheckCircle2, Clock, ArrowRight,
} from "lucide-react";
import { RadarChart } from "@/components/dashboard/radar-chart";

export function Dashboard() {
  const [dashboard, setDashboard] = useState<DashboardInfo | null>(null);
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      userAPI.getDashboard().catch(() => null),
      knowledgeAPI.getSubjects().catch(() => []),
    ]).then(([dash, subs]) => {
      setDashboard(dash);
      setSubjects(subs);
      setLoading(false);
    });
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

  const accuracy = dashboard ? Math.round(dashboard.overall_accuracy * 100) : 0;

  return (
    <main className="container py-6 space-y-6">
      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Số bài thi</CardTitle>
            <GraduationCap className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{dashboard?.total_quizzes ?? 0}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Câu hỏi đã làm</CardTitle>
            <Target className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{dashboard?.total_questions_attempted ?? 0}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Độ chính xác</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{accuracy}%</div>
            <Progress value={accuracy} className="mt-2" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Chủ đề đã học</CardTitle>
            <BookOpen className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{dashboard?.topic_progress?.length ?? 0}</div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Radar Chart */}
        <Card>
          <CardHeader>
            <CardTitle>Bản đồ Năng lực</CardTitle>
            <CardDescription>Đánh giá theo từng chủ đề kiến thức</CardDescription>
          </CardHeader>
          <CardContent>
            {dashboard?.topic_progress && dashboard.topic_progress.length > 0 ? (
              <RadarChart data={dashboard.topic_progress} />
            ) : (
              <div className="flex flex-col items-center justify-center py-10 text-muted-foreground">
                <Target className="h-12 w-12 mb-2" />
                <p>Chưa có dữ liệu. Hãy làm bài thi để xem biểu đồ!</p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Subjects to practice */}
        <Card>
          <CardHeader>
            <CardTitle>Môn học</CardTitle>
            <CardDescription>Chọn môn học để bắt đầu làm bài</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {subjects.map((subject) => (
              <div
                key={subject.id}
                className="flex items-center justify-between p-4 rounded-lg border hover:bg-accent/50 transition-colors"
              >
                <div>
                  <h3 className="font-semibold">{subject.name}</h3>
                  <p className="text-sm text-muted-foreground">
                    {subject.total_questions} câu hỏi · {subject.total_topics} chủ đề
                  </p>
                </div>
                <Link href={`/quiz?subject=${subject.id}`}>
                  <Button size="sm">
                    Làm bài <ArrowRight className="h-4 w-4 ml-1" />
                  </Button>
                </Link>
              </div>
            ))}
            {subjects.length === 0 && (
              <p className="text-muted-foreground text-center py-4">Chưa có dữ liệu môn học</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent sessions */}
      {dashboard?.recent_sessions && dashboard.recent_sessions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Lịch sử làm bài</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {dashboard.recent_sessions.map((session) => (
                <div
                  key={session.id}
                  className="flex items-center justify-between p-3 rounded-lg border"
                >
                  <div className="flex items-center gap-3">
                    <CheckCircle2 className={`h-5 w-5 ${session.completed_at ? "text-green-500" : "text-yellow-500"}`} />
                    <div>
                      <p className="font-medium">
                        Bài thi #{session.id}
                      </p>
                      <p className="text-sm text-muted-foreground">
                        {session.correct_answers}/{session.total_questions} đúng
                        {session.total_score != null && ` · ${Math.round(session.total_score)}%`}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Clock className="h-4 w-4" />
                    {session.started_at
                      ? new Date(session.started_at).toLocaleDateString("vi-VN")
                      : "N/A"}
                    {session.completed_at && (
                      <Link href={`/results/${session.id}`}>
                        <Button variant="outline" size="sm">Xem kết quả</Button>
                      </Link>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </main>
  );
}
