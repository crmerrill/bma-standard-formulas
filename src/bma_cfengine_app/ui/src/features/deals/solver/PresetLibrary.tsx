import React from "react";
import type { SolverSpecDraft } from "./types";

interface PresetDef {
  id: string;
  label: string;
  apply: (draft: SolverSpecDraft) => SolverSpecDraft;
}

const PRESETS: PresetDef[] = [
  {
    id: "balanced",
    label: "Balanced Coupon + WAL",
    apply: (draft) => ({
      ...draft,
      description: "Balanced preset",
      objectives: [
        {
          id: "obj_1",
          name: "target_yield",
          metricPath: "tranche_risk_summary[A].yield_pct",
          objectiveType: "TARGET",
          targetValue: 6,
          weight: 1,
        },
        {
          id: "obj_2",
          name: "minimize_wal",
          metricPath: "tranche_risk_summary[A].wal_years",
          objectiveType: "MINIMIZE",
          targetValue: null,
          weight: 0.5,
        },
      ],
    }),
  },
  {
    id: "speed",
    label: "Fast Feasible Search",
    apply: (draft) => ({
      ...draft,
      maxIterations: 8,
      globalMaxIterations: 24,
      checkpointEveryN: 2,
      description: "Fast preset",
    }),
  },
];

interface Props {
  draft: SolverSpecDraft;
  onApplyPreset: (next: SolverSpecDraft) => void;
}

export default function PresetLibrary({ draft, onApplyPreset }: Props) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {PRESETS.map((preset) => (
        <button
          key={preset.id}
          type="button"
          onClick={() => onApplyPreset(preset.apply(draft))}
          className="px-2 py-1 rounded border border-border text-xs text-muted-foreground hover:text-foreground"
        >
          {preset.label}
        </button>
      ))}
    </div>
  );
}
