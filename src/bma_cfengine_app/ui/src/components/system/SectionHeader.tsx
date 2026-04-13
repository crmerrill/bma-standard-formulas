import React from "react";
import { text } from "./ui";

interface SectionHeaderProps {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}

export default function SectionHeader({ title, subtitle, actions }: SectionHeaderProps) {
  return (
    <div className="flex items-start gap-2">
      <div className="min-w-0 flex-1">
        <h3 className={text.sectionTitle}>{title}</h3>
        {subtitle && <p className={`${text.bodyMuted} mt-1`}>{subtitle}</p>}
      </div>
      {actions ? <div className="shrink-0">{actions}</div> : null}
    </div>
  );
}
