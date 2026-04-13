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

const PRIME_JUMBO_PRESETS: PresetDef[] = [
  {
    id: "prime_ce_pool",
    label: "Prime Jumbo: CE + Pool Size",
    apply: (draft) => ({
      ...draft,
      description: "Prime Jumbo CE and pool-size profile",
      objectives: [
        {
          id: "obj_prime_1",
          name: "target_ce_A",
          metricPath: "tranche_credit_summary[A].ce_pct",
          objectiveType: "TARGET",
          targetValue: 10,
          weight: 1,
        },
        {
          id: "obj_prime_2",
          name: "target_pool_factor",
          metricPath: "deal_summary.pool_factor",
          objectiveType: "TARGET",
          targetValue: 1,
          weight: 0.35,
        },
      ],
      constraints: [
        {
          id: "con_prime_1",
          name: "A_no_principal_shortfall",
          metricPath: "tranche_shortfall[A].principal_pct",
          operator: "LE",
          minValue: null,
          maxValue: 0,
        },
      ],
      knobs: [
        {
          id: "knob_prime_1",
          knobPath: "deal_knobs.class_a_pct",
          lower: 50,
          upper: 95,
          initial: 80,
          stepHint: 0.5,
        },
        {
          id: "knob_prime_2",
          knobPath: "deal_knobs.pool_notional",
          lower: 50000000,
          upper: 1000000000,
          initial: 250000000,
          stepHint: 5000000,
        },
      ],
    }),
  },
];

const NON_QM_PRESETS: PresetDef[] = [
  {
    id: "nonqm_ce_cumloss",
    label: "Non-QM/QRM: CE + Cum Loss",
    apply: (draft) => ({
      ...draft,
      description: "Non-QM/QRM CE and cumulative-loss profile",
      objectives: [
        {
          id: "obj_nonqm_1",
          name: "target_ce_A",
          metricPath: "tranche_credit_summary[A].ce_pct",
          objectiveType: "TARGET",
          targetValue: 20,
          weight: 1,
        },
        {
          id: "obj_nonqm_2",
          name: "minimize_cum_loss_shortfall",
          metricPath: "deal_credit_summary.cum_loss_multiple_gap",
          objectiveType: "MINIMIZE",
          targetValue: null,
          weight: 0.7,
        },
      ],
      constraints: [
        {
          id: "con_nonqm_1",
          name: "A_no_interest_shortfall",
          metricPath: "tranche_shortfall[A].interest_pct",
          operator: "LE",
          minValue: null,
          maxValue: 0,
        },
        {
          id: "con_nonqm_2",
          name: "A_no_principal_shortfall",
          metricPath: "tranche_shortfall[A].principal_pct",
          operator: "LE",
          minValue: null,
          maxValue: 0,
        },
      ],
      knobs: [
        {
          id: "knob_nonqm_1",
          knobPath: "deal_knobs.class_a_pct",
          lower: 40,
          upper: 90,
          initial: 72,
          stepHint: 0.5,
        },
        {
          id: "knob_nonqm_2",
          knobPath: "deal_knobs.loss_multiple_target",
          lower: 1,
          upper: 4,
          initial: 2,
          stepHint: 0.05,
        },
      ],
      maxIterations: 18,
      globalMaxIterations: 80,
    }),
  },
];

interface Props {
  draft: SolverSpecDraft;
  productFamily?: "AGENCY" | "PRIME_JUMBO" | "NON_QM_QRM" | "CUSTOM";
  onApplyPreset: (next: SolverSpecDraft) => void;
}

function PresetGroup({
  title,
  presets,
  draft,
  onApplyPreset,
}: {
  title: string;
  presets: PresetDef[];
  draft: SolverSpecDraft;
  onApplyPreset: (next: SolverSpecDraft) => void;
}) {
  return (
    <div className="space-y-1.5">
      <div className="text-xs uppercase tracking-wider text-muted-foreground">{title}</div>
      <div className="flex flex-wrap items-center gap-2">
        {presets.map((preset) => (
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
    </div>
  );
}

export default function PresetLibrary({ draft, productFamily, onApplyPreset }: Props) {
  const familyLabel =
    productFamily === "NON_QM_QRM"
      ? "Non-QM / QRM"
      : productFamily === "PRIME_JUMBO"
        ? "Prime Jumbo"
        : productFamily === "AGENCY"
          ? "Agency"
          : "Custom";
  return (
    <div className="space-y-3">
      <PresetGroup title="Shared Shell" presets={PRESETS} draft={draft} onApplyPreset={onApplyPreset} />
      <PresetGroup title="Prime Jumbo Presets" presets={PRIME_JUMBO_PRESETS} draft={draft} onApplyPreset={onApplyPreset} />
      <PresetGroup title="Non-QM / QRM Presets" presets={NON_QM_PRESETS} draft={draft} onApplyPreset={onApplyPreset} />
      {productFamily && (
        <div className="text-xs text-muted-foreground">
          Active product family: {familyLabel}.
        </div>
      )}
    </div>
  );
}
