import React from "react";
import type { SolverSpecDraft } from "./types";

interface PresetDef {
  id: string;
  label: string;
  apply: (draft: SolverSpecDraft) => SolverSpecDraft;
}

type PrimitiveParams = Record<string, number | string | boolean | null>;
const pp = (params: PrimitiveParams): PrimitiveParams => params;

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
          targetPrimitive: null,
          primitiveParams: pp({}),
        },
        {
          id: "obj_2",
          name: "minimize_wal",
          metricPath: "tranche_risk_summary[A].wal_years",
          objectiveType: "MINIMIZE",
          targetValue: null,
          weight: 0.5,
          targetPrimitive: null,
          primitiveParams: pp({}),
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
    id: "prime_cumloss_no_shortfall",
    label: "Prime Jumbo: CumLoss + No Shortfall",
    apply: (draft) => ({
      ...draft,
      description: "Prime Jumbo constrained pack (cum-loss multiple + no shortfall + trigger resilience)",
      objectives: [
        {
          id: "obj_prime_1",
          name: "cum_loss_multiple_gap_A",
          metricPath: "primitive:CUM_LOSS_MULTIPLE_GAP",
          objectiveType: "MINIMIZE",
          targetValue: null,
          weight: 1,
          targetPrimitive: "CUM_LOSS_MULTIPLE_GAP",
          primitiveParams: pp({ tranche_id: "A", target_multiple: 2.0 }),
        },
        {
          id: "obj_prime_2",
          name: "ce_target_delta_A",
          metricPath: "primitive:CE_TARGET_DELTA",
          objectiveType: "MINIMIZE",
          targetValue: null,
          weight: 0.75,
          targetPrimitive: "CE_TARGET_DELTA",
          primitiveParams: pp({ tranche_id: "A", target_ce_pct: 10.0 }),
        },
      ],
      constraints: [
        {
          id: "con_prime_1",
          name: "A_no_interest_shortfall",
          metricPath: "primitive:NO_SHORTFALL_INTEREST",
          operator: "LE",
          minValue: null,
          maxValue: 0,
          targetPrimitive: "NO_SHORTFALL_INTEREST",
          primitiveParams: pp({ tranche_id: "A" }),
        },
        {
          id: "con_prime_2",
          name: "A_no_principal_shortfall",
          metricPath: "primitive:NO_SHORTFALL_PRINCIPAL",
          operator: "LE",
          minValue: null,
          maxValue: 0,
          targetPrimitive: "NO_SHORTFALL_PRINCIPAL",
          primitiveParams: pp({ tranche_id: "A" }),
        },
        {
          id: "con_prime_3",
          name: "oc_ic_trigger_resilience",
          metricPath: "primitive:OC_IC_TRIGGER_RESILIENCE",
          operator: "LE",
          minValue: null,
          maxValue: 0,
          targetPrimitive: "OC_IC_TRIGGER_RESILIENCE",
          primitiveParams: pp({}),
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
    id: "nonqm_waterfall_safety",
    label: "Non-QM/QRM: Waterfall Safety Pack",
    apply: (draft) => ({
      ...draft,
      description: "Non-QM/QRM constrained pack (cum-loss, no shortfall, step-down and reserve safety)",
      objectives: [
        {
          id: "obj_nonqm_1",
          name: "cum_loss_multiple_gap_A",
          metricPath: "primitive:CUM_LOSS_MULTIPLE_GAP",
          objectiveType: "MINIMIZE",
          targetValue: null,
          weight: 1,
          targetPrimitive: "CUM_LOSS_MULTIPLE_GAP",
          primitiveParams: pp({ tranche_id: "A", target_multiple: 2.5 }),
        },
        {
          id: "obj_nonqm_2",
          name: "ce_target_delta_A",
          metricPath: "primitive:CE_TARGET_DELTA",
          objectiveType: "MINIMIZE",
          targetValue: null,
          weight: 0.7,
          targetPrimitive: "CE_TARGET_DELTA",
          primitiveParams: pp({ tranche_id: "A", target_ce_pct: 20.0 }),
        },
      ],
      constraints: [
        {
          id: "con_nonqm_1",
          name: "A_no_interest_shortfall",
          metricPath: "primitive:NO_SHORTFALL_INTEREST",
          operator: "LE",
          minValue: null,
          maxValue: 0,
          targetPrimitive: "NO_SHORTFALL_INTEREST",
          primitiveParams: pp({ tranche_id: "A" }),
        },
        {
          id: "con_nonqm_2",
          name: "A_no_principal_shortfall",
          metricPath: "primitive:NO_SHORTFALL_PRINCIPAL",
          operator: "LE",
          minValue: null,
          maxValue: 0,
          targetPrimitive: "NO_SHORTFALL_PRINCIPAL",
          primitiveParams: pp({ tranche_id: "A" }),
        },
        {
          id: "con_nonqm_3",
          name: "stepdown_eligibility_safety",
          metricPath: "primitive:STEPDOWN_ELIGIBILITY_SAFETY",
          operator: "LE",
          minValue: null,
          maxValue: 0,
          targetPrimitive: "STEPDOWN_ELIGIBILITY_SAFETY",
          primitiveParams: pp({}),
        },
        {
          id: "con_nonqm_4",
          name: "subordination_floor",
          metricPath: "primitive:SUBORDINATION_FLOOR_GAP",
          operator: "LE",
          minValue: null,
          maxValue: 0,
          targetPrimitive: "SUBORDINATION_FLOOR_GAP",
          primitiveParams: pp({ tranche_id: "A", floor_pct: 18.0 }),
        },
        {
          id: "con_nonqm_5",
          name: "reserve_carry_sufficiency",
          metricPath: "primitive:RESERVE_SUFFICIENCY_GAP",
          operator: "LE",
          minValue: null,
          maxValue: 0,
          targetPrimitive: "RESERVE_SUFFICIENCY_GAP",
          primitiveParams: pp({ reserve_floor: 0.0 }),
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

const CMO_PAC_TAC_Z_PRESETS: PresetDef[] = [
  {
    id: "cmo_pac_tac_guardrail",
    label: "CMO: PAC/TAC Guardrail",
    apply: (draft) => ({
      ...draft,
      description: "CMO PAC/TAC schedule adherence with support burn-down control",
      objectives: [
        {
          id: "obj_cmo_1",
          name: "pac_schedule_miss_A",
          metricPath: "primitive:PAC_SCHEDULE_MISS",
          objectiveType: "MINIMIZE",
          targetValue: null,
          weight: 1,
          targetPrimitive: "PAC_SCHEDULE_MISS",
          primitiveParams: pp({ tranche_id: "A" }),
        },
        {
          id: "obj_cmo_2",
          name: "tac_schedule_miss_B",
          metricPath: "primitive:TAC_SCHEDULE_MISS",
          objectiveType: "MINIMIZE",
          targetValue: null,
          weight: 0.7,
          targetPrimitive: "TAC_SCHEDULE_MISS",
          primitiveParams: pp({ tranche_id: "B" }),
        },
      ],
      constraints: [
        {
          id: "con_cmo_1",
          name: "z_release_gap",
          metricPath: "primitive:Z_ACCRUAL_RELEASE_GAP",
          operator: "LE",
          minValue: null,
          maxValue: 0,
          targetPrimitive: "Z_ACCRUAL_RELEASE_GAP",
          primitiveParams: pp({ tranche_id: "Z" }),
        },
        {
          id: "con_cmo_2",
          name: "support_burndown_gap",
          metricPath: "primitive:SUPPORT_BURNDOWN_GAP",
          operator: "LE",
          minValue: null,
          maxValue: 0,
          targetPrimitive: "SUPPORT_BURNDOWN_GAP",
          primitiveParams: pp({ tranche_id: "B", support_floor: 0 }),
        },
      ],
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
      {(productFamily === "PRIME_JUMBO" || productFamily === "CUSTOM") && (
        <PresetGroup
          title="Prime Jumbo Presets"
          presets={PRIME_JUMBO_PRESETS}
          draft={draft}
          onApplyPreset={onApplyPreset}
        />
      )}
      {(productFamily === "NON_QM_QRM" || productFamily === "CUSTOM") && (
        <PresetGroup
          title="Non-QM / QRM Presets"
          presets={NON_QM_PRESETS}
          draft={draft}
          onApplyPreset={onApplyPreset}
        />
      )}
      {(productFamily === "AGENCY" || productFamily === "CUSTOM") && (
        <PresetGroup
          title="CMO PAC/TAC/Z Presets"
          presets={CMO_PAC_TAC_Z_PRESETS}
          draft={draft}
          onApplyPreset={onApplyPreset}
        />
      )}
      {productFamily && (
        <div className="text-xs text-muted-foreground">
          Active product family: {familyLabel}. Template packs are guardrailed to this family.
        </div>
      )}
    </div>
  );
}
