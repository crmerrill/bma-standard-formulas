import React from "react";
import { text } from "./system/ui";

interface Props {
  message?: string;
  children?: React.ReactNode;
}

export default function EmptyState({ message, children }: Props) {
  return (
    <div className={`${text.bodyMuted} p-8 text-center`}>
      {children ?? message ?? "No data available."}
    </div>
  );
}
