import React from "react";
import { MONO } from "../lib/format";

interface Props {
  children: React.ReactNode;
  size?: "sm" | "xs";
}

export default function MonoChip({ children, size = "sm" }: Props) {
  return (
    <span
      className={`rounded bg-secondary ${
        size === "xs" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-0.5 text-xs"
      }`}
      style={MONO}
    >
      {children}
    </span>
  );
}
