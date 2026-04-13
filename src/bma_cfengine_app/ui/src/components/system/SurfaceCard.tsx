import React from "react";
import { cx, shell } from "./ui";

interface SurfaceCardProps {
  children: React.ReactNode;
  className?: string;
  padded?: boolean;
}

export default function SurfaceCard({ children, className, padded = true }: SurfaceCardProps) {
  return (
    <div className={cx(shell.card, padded ? shell.sectionPad : "", className)}>
      {children}
    </div>
  );
}
