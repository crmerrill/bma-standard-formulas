import React from "react";
import { Loader2 } from "lucide-react";
import { text } from "./system/ui";

interface Props {
  message?: string;
}

export default function LoadingState({ message = "Loading..." }: Props) {
  return (
    <div className={`flex items-center gap-2 p-8 ${text.bodyMuted}`}>
      <Loader2 className="w-4 h-4 animate-spin" /> {message}
    </div>
  );
}
