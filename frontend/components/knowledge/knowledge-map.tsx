"use client";

import { useState, useEffect } from "react";
import { knowledgeAPI, type SubjectSummary, type SubjectTree } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ChevronDown, ChevronRight, BookOpen, FileQuestion, Layers } from "lucide-react";

export function KnowledgeMap() {
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [selectedSubject, setSelectedSubject] = useState<number | null>(null);
  const [tree, setTree] = useState<SubjectTree | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    knowledgeAPI.getSubjects().then((subs) => {
      setSubjects(subs);
      if (subs.length > 0) {
        setSelectedSubject(subs[0].id);
      }
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    if (selectedSubject) {
      knowledgeAPI.getKnowledgeTree(selectedSubject).then((data) => {
        setTree(data.subject);
        // Expand all by default
        const ids = new Set(data.subject.major_topics.map((mt) => mt.id));
        setExpanded(ids);
      });
    }
  }, [selectedSubject]);

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Bản đồ Tri thức</h1>
        <p className="text-muted-foreground mt-1">
          Cấu trúc Ontology: Môn học → Chủ đề lớn → Chủ đề con → Câu hỏi
        </p>
      </div>

      {/* Subject tabs */}
      <div className="flex gap-2">
        {subjects.map((s) => (
          <Button
            key={s.id}
            variant={selectedSubject === s.id ? "default" : "outline"}
            onClick={() => setSelectedSubject(s.id)}
          >
            <BookOpen className="h-4 w-4 mr-2" />
            {s.name}
          </Button>
        ))}
      </div>

      {/* Ontology tree */}
      {tree && (
        <Card>
          <CardHeader>
            <CardTitle>{tree.name}</CardTitle>
            <CardDescription>{tree.description}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {tree.major_topics.map((mt) => (
                <div key={mt.id} className="border rounded-lg">
                  <button
                    className="w-full flex items-center gap-2 p-4 hover:bg-accent/50 transition-colors text-left"
                    onClick={() => toggleExpand(mt.id)}
                  >
                    {expanded.has(mt.id) ? (
                      <ChevronDown className="h-5 w-5 text-primary" />
                    ) : (
                      <ChevronRight className="h-5 w-5" />
                    )}
                    <Layers className="h-5 w-5 text-primary" />
                    <div>
                      <h3 className="font-semibold">{mt.name}</h3>
                      <p className="text-sm text-muted-foreground">
                        {mt.topics.length} chủ đề · {mt.topics.reduce((sum, t) => sum + t.question_count, 0)} câu hỏi
                      </p>
                    </div>
                  </button>

                  {expanded.has(mt.id) && (
                    <div className="border-t px-4 pb-4">
                      <div className="ml-7 mt-2 space-y-2">
                        {mt.topics.map((topic) => (
                          <div
                            key={topic.id}
                            className="flex items-center justify-between p-3 rounded-md bg-muted/50"
                          >
                            <div className="flex items-center gap-2">
                              <FileQuestion className="h-4 w-4 text-muted-foreground" />
                              <span className="font-medium text-sm">{topic.name}</span>
                            </div>
                            <span className="text-xs text-muted-foreground bg-background rounded-full px-2 py-1">
                              {topic.question_count} câu
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
