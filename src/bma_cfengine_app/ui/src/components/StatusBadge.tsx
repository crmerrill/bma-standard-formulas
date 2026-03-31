import React from "react";
import { Check, X, Loader2 } from "lucide-react";

interface Props {
  status: string;
}

export default function StatusBadge({ status }: Props) {
  if (status === "completed") {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-engine-green/10 text-engine-green text-[9px]">
        <Check className="w-2.5 h-2.5" /> Done
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-engine-red/10 text-engine-red text-[9px]">
        <X className="w-2.5 h-2.5" /> Failed
      </span>
    );
  }
  if (status === "running") {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-engine-amber/10 text-engine-amber text-[9px]">
        <Loader2 className="w-2.5 h-2.5 animate-spin" /> Running
      </span>
    );
  }
  return <span className="text-muted-foreground text-[9px]">{status}</span>;
}
