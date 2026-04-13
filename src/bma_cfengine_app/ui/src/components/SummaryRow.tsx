import React from "react";
import { MONO } from "../lib/format";
import { text } from "./system/ui";

interface Props {
  label: string;
  value: string;
  mono?: boolean;
}

export default function SummaryRow({ label, value, mono = true }: Props) {
  return (
    <div className="flex items-baseline gap-2 py-1">
      <span className={`${text.bodyMuted} shrink-0`}>{label}:</span>
      <span className={text.body} style={mono ? MONO : undefined}>
        {value}
      </span>
    </div>
  );
}
