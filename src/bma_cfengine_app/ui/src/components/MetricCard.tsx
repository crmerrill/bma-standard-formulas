import React from "react";
import { MONO } from "../lib/format";

interface Props {
  icon: React.ElementType;
  label: string;
  value: string;
}

export default function MetricCard({ icon: Icon, label, value }: Props) {
  return (
    <div className="bg-card border border-border rounded-lg p-3">
      <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
        <Icon className="w-3 h-3" />
        <span className="text-[10px] uppercase tracking-wider">{label}</span>
      </div>
      <p className="text-sm font-medium text-foreground" style={MONO}>
        {value}
      </p>
    </div>
  );
}
