import React from "react";
import { MONO } from "../lib/format";
import { text } from "./system/ui";

interface Props {
  label: string;
  value: string;
  highlight?: boolean;
}

export default function RiskCell({ label, value, highlight }: Props) {
  return (
    <div>
      <span
        className={`${text.metricLabel} block ${
          highlight ? "text-primary" : "text-muted-foreground"
        }`}
      >
        {label}
      </span>
      <span
        className={`text-base font-medium ${
          highlight ? "text-primary" : "text-foreground"
        }`}
        style={MONO}
      >
        {value}
      </span>
    </div>
  );
}
