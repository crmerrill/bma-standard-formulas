import React from "react";

export interface PillOption {
  id: string;
  label: string;
}

interface Props {
  label?: string;
  options: PillOption[];
  selected: string;
  onSelect: (id: string) => void;
}

export default function PillToggle({ label, options, selected, onSelect }: Props) {
  return (
    <div className="flex items-center gap-2">
      {label && <span className="text-xs text-muted-foreground">{label}</span>}
      <div className="flex gap-1">
        {options.map((o) => (
          <button
            key={o.id}
            onClick={() => onSelect(o.id)}
            className={`px-2.5 py-1 rounded border text-xs capitalize transition-colors ${
              selected === o.id
                ? "bg-primary/15 text-primary border-primary/30"
                : "text-muted-foreground border-border hover:text-foreground hover:bg-white/5"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
