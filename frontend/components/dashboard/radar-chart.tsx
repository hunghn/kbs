"use client";

import {
  Radar,
  RadarChart as RechartsRadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import type { TopicProgress } from "@/lib/api";

interface RadarChartProps {
  data: TopicProgress[];
}

export function RadarChart({ data }: RadarChartProps) {
  // Normalize theta from [-4, 4] to [0, 100] for display
  const chartData = data.map((d) => ({
    topic: d.topic_name.length > 20 ? d.topic_name.slice(0, 18) + "..." : d.topic_name,
    fullName: d.topic_name,
    score: Math.round(((d.theta_estimate + 4) / 8) * 100),
    accuracy:
      d.questions_attempted > 0
        ? Math.round((d.questions_correct / d.questions_attempted) * 100)
        : 0,
    mastery: d.mastery_level,
  }));

  return (
    <ResponsiveContainer width="100%" height={350}>
      <RechartsRadarChart data={chartData}>
        <PolarGrid />
        <PolarAngleAxis dataKey="topic" tick={{ fontSize: 11 }} />
        <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fontSize: 10 }} />
        <Radar
          name="Năng lực (θ)"
          dataKey="score"
          stroke="hsl(221.2, 83.2%, 53.3%)"
          fill="hsl(221.2, 83.2%, 53.3%)"
          fillOpacity={0.3}
        />
        <Radar
          name="Độ chính xác"
          dataKey="accuracy"
          stroke="hsl(142, 76%, 36%)"
          fill="hsl(142, 76%, 36%)"
          fillOpacity={0.15}
        />
        <Tooltip
          content={({ payload }) => {
            if (!payload || payload.length === 0) return null;
            const item = payload[0]?.payload;
            return (
              <div className="rounded-lg border bg-background p-3 shadow-md">
                <p className="font-medium">{item?.fullName}</p>
                <p className="text-sm text-muted-foreground">
                  Năng lực: {item?.score}%
                </p>
                <p className="text-sm text-muted-foreground">
                  Chính xác: {item?.accuracy}%
                </p>
                <p className="text-sm text-muted-foreground">
                  Mức độ: {item?.mastery}
                </p>
              </div>
            );
          }}
        />
      </RechartsRadarChart>
    </ResponsiveContainer>
  );
}
