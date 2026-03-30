import React from "react";

export interface TabDef {
  id: string;
  label: string;
  icon?: React.ElementType;
}

interface Props {
  tabs: TabDef[];
  active: string;
  onSelect: (id: string) => void;
}

export default function TabBar({ tabs, active, onSelect }: Props) {
  return (
    <div className="flex items-center gap-1 border-b border-border">
      {tabs.map((t) => {
        const Icon = t.icon;
        return (
          <button
            key={t.id}
            onClick={() => onSelect(t.id)}
            className={`flex items-center gap-1.5 px-3 py-2 text-xs border-b-2 transition-colors ${
              active === t.id
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {Icon && <Icon className="w-3.5 h-3.5" />}
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
