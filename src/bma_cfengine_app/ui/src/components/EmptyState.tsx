import React from "react";

interface Props {
  message?: string;
  children?: React.ReactNode;
}

export default function EmptyState({ message, children }: Props) {
  return (
    <div className="text-muted-foreground text-sm p-8 text-center">
      {children ?? message ?? "No data available."}
    </div>
  );
}
