import React from "react";
import { MONO } from "../lib/format";

interface Props {
  label: string;
  value: string;
  mono?: boolean;
}

export default function SummaryRow({ label, value, mono = true }: Props) {
  return (
    <div className="flex items-baseline gap-2 py-1">
      <span className="text-muted-foreground shrink-0">{label}:</span>
      <span className="text-foreground" style={mono ? MONO : undefined}>
        {value}
      </span>
    </div>
  );
}
