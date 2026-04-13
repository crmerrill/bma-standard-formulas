import React from "react";
import { MONO } from "../lib/format";
import { shell, text } from "./system/ui";

interface Props {
  icon: React.ElementType;
  label: string;
  value: string;
}

export default function MetricCard({ icon: Icon, label, value }: Props) {
  return (
    <div className={`${shell.card} p-3`}>
      <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
        <Icon className="w-3 h-3" />
        <span className={text.metricLabel}>{label}</span>
      </div>
      <p className={text.metricValue} style={MONO}>
        {value}
      </p>
    </div>
  );
}
