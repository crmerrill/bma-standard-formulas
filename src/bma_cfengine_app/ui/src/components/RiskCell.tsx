import React from "react";
import { MONO } from "../lib/format";

interface Props {
  label: string;
  value: string;
  highlight?: boolean;
}

export default function RiskCell({ label, value, highlight }: Props) {
  return (
    <div>
      <span
        className={`text-[10px] block ${
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
