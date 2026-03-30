import React from "react";
import { Loader2 } from "lucide-react";

interface Props {
  message?: string;
}

export default function LoadingState({ message = "Loading..." }: Props) {
  return (
    <div className="flex items-center gap-2 text-muted-foreground text-sm p-8">
      <Loader2 className="w-4 h-4 animate-spin" /> {message}
    </div>
  );
}
