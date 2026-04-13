import React from "react";
import { Check, X, Loader2 } from "lucide-react";

interface Props {
  status: string;
}

export default function StatusBadge({ status }: Props) {
  if (status === "completed") {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-engine-green/10 px-2 py-0.5 text-xs text-engine-green">
        <Check className="w-2.5 h-2.5" /> Done
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-engine-red/10 px-2 py-0.5 text-xs text-engine-red">
        <X className="w-2.5 h-2.5" /> Failed
      </span>
    );
  }
  if (status === "running") {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-engine-amber/10 px-2 py-0.5 text-xs text-engine-amber">
        <Loader2 className="w-2.5 h-2.5 animate-spin" /> Running
      </span>
    );
  }
  return <span className="text-xs text-muted-foreground">{status}</span>;
}
