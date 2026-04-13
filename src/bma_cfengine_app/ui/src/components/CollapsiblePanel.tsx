import React, { useState } from "react";
import { ChevronRight, Check, AlertTriangle } from "lucide-react";
import { shell, text } from "./system/ui";

interface Props {
  icon?: React.ElementType;
  title: string;
  badge?: string;
  defaultOpen?: boolean;
  open?: boolean;
  onToggle?: () => void;
  status?: "ok" | "error" | "neutral";
  children: React.ReactNode;
}

export default function CollapsiblePanel({
  icon: Icon,
  title,
  badge,
  defaultOpen = true,
  open: controlledOpen,
  onToggle,
  status,
  children,
}: Props) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const isOpen = controlledOpen ?? internalOpen;
  const toggle = onToggle ?? (() => setInternalOpen((v) => !v));

  return (
    <div className={shell.panel}>
      <button
        type="button"
        onClick={toggle}
        className="w-full bg-grid-header px-3 py-2 text-xs flex items-center gap-2 hover:bg-grid-row-hover transition-colors"
      >
        <ChevronRight
          className={`w-3.5 h-3.5 text-muted-foreground transition-transform ${
            isOpen ? "rotate-90" : ""
          }`}
        />
        {Icon && <Icon className="w-3.5 h-3.5 text-primary" />}
        <span className={text.sectionTitle}>{title}</span>
        {badge && (
          <span className="text-muted-foreground font-normal ml-1">
            {badge}
          </span>
        )}
        {status && (
          <div className="ml-auto">
            {status === "ok" && (
              <Check className="w-3.5 h-3.5 text-engine-green" />
            )}
            {status === "error" && (
              <AlertTriangle className="w-3.5 h-3.5 text-engine-red" />
            )}
          </div>
        )}
      </button>
      {isOpen && children}
    </div>
  );
}
