/**
 * OA1 acceptance tests: mergeOpaqueIrFields preserves all Phase 5-9 canonical
 * IR fields through a Blockly edit cycle (load → synthesize → generate → merge → save).
 *
 * "Canonical IR fields" here means fields that irGenerator does not emit but which
 * DealDefinition schema 2.0 carries and the runtime depends on. These must survive
 * unchanged when a user opens a deal and saves without editing.
 */

import { describe, expect, it } from "vitest";
import { mergeOpaqueIrFields, extractOpaqueIrFields } from "./scheduleOverlayMerge";

// ---------------------------------------------------------------------------
// Minimal Blockly-generated IR (what irGenerator produces for a simple deal).
// This represents the irGenerator output AFTER the user opens and saves without
// editing any visible Blockly fields.
// ---------------------------------------------------------------------------
const BLOCKLY_GENERATED_IR = {
  schema_version: "2.0.0",
  deal_name: "Test Deal",
  bonds: [
    {
      name: "A",
      kind: "CASH_PAY",
      coupon: 5.5,
      notional: 1_000_000,
      coupon_type: "FIXED",
      is_bond: true,
      is_pseudo: false,
      pay_mode: "CASH_PAY",
      // irGenerator does NOT emit these Phase 6 fields — they must come from savedBase:
      // nla_starting_balance, required_subordination_pct, seniority
      schedule_contract: [],
      schedule_tolerance_bps: null,
      schedule_derivation: null,
      schedule_model_type: null,
      schedule_speed_low: null,
      schedule_speed_high: null,
      schedule_priority_tier: null,
      schedule_depends_on: null,
      schedule_custom_vector: null,
      relations: [],
      z_accrual_enabled: false,
      z_release_trigger: null,
      group_id: null,
      index_name: null,
      margin: null,
      cap: null,
      floor: null,
    },
    {
      name: "R",
      kind: "RESIDUAL",
      is_bond: false,
      is_pseudo: true,
      coupon: 0,
      notional: 0,
      coupon_type: "FIXED",
      pay_mode: "CASH_PAY",
      schedule_contract: [],
      schedule_tolerance_bps: null,
      schedule_derivation: null,
      schedule_model_type: null,
      schedule_speed_low: null,
      schedule_speed_high: null,
      schedule_priority_tier: null,
      schedule_depends_on: null,
      schedule_custom_vector: null,
      relations: [],
      z_accrual_enabled: false,
      z_release_trigger: null,
      group_id: null,
      index_name: null,
      margin: null,
      cap: null,
      floor: null,
    },
  ],
  accounts: [
    {
      name: "RESERVE",
      account_category: "RESERVE",
      starting_amount: 5_000,
      // irGenerator does NOT emit minimum_schedule:
    },
  ],
  fees: [],
  triggers: [
    {
      name: "LossTrigger",
      metric_type: "CUMULATIVE_LOSS",
      threshold_value: 0.05,
      // irGenerator does NOT emit window_periods / comparison:
    },
  ],
  waterfall_rules: [
    {
      rule_id: "r_int",
      rule_type: "PAY_INTEREST",
      order: 0,
      from_sources: ["CASH"],
      to_targets: ["A"],
      payment_style: "SEQUENTIAL",
      cap_mode: null,
      // coverage_mode is Blockly-owned (irToBlocklyState stashes it in block.data,
      // irGenerator reads it back). It is NOT in the opaque passthrough.
      // In a real Blockly round-trip it would be "INTEREST_SHORTFALL" (from block.data).
      // Here we omit it to test that mergeOpaqueIrFields preserves saved backend-only
      // fields (condition_expr, max_amount_expr) while letting Blockly-owned
      // coverage_mode through via the entity merge.
      coverage_mode: "INTEREST_SHORTFALL",  // in real flow, read from block.data
      // irGenerator does NOT emit condition_expr / max_amount_expr — they survive
      // exclusively through the { ...saved, ...g } opaque merge:
    },
  ],
  collateral_groups: [],
};

// ---------------------------------------------------------------------------
// A full saved IR with all Phase 5-9 fields that Blockly cannot generate.
// This is what was loaded from the backend / deal store.
// ---------------------------------------------------------------------------
const SAVED_IR_WITH_BACKEND_FIELDS = {
  schema_version: "2.0.0",
  deal_name: "Test Deal",
  description: "My phase 6-9 deal",
  series_id: "CC-SERIES-2024-A",

  // Phase 9: deal state machine
  deal_state_trigger: "LossTrigger",
  initial_deal_state: "REVOLVING",

  // Phase 7: discount option
  discount_factor_pct: 2.5,

  // Top-level backend fields
  calculations: [
    { name: "cum_loss_pct", expression: "sum(loss[0:i+1]) / orig_collat_bal", description: "Cumulative loss pct" },
  ],
  deal_knobs: { index_rate: 5.25, servicing_fee_bps: 25.0 },

  bonds: [
    {
      name: "A",
      kind: "CASH_PAY",
      coupon: 5.5,
      notional: 1_000_000,
      coupon_type: "FIXED",
      is_bond: true,
      is_pseudo: false,
      pay_mode: "CASH_PAY",
      // Phase 6 fields:
      nla_starting_balance: 1_000_000,
      required_subordination_pct: 20.0,
      seniority: 1,
      schedule_contract: [],
      schedule_tolerance_bps: null,
      schedule_derivation: null,
      schedule_model_type: null,
      schedule_speed_low: null,
      schedule_speed_high: null,
      schedule_priority_tier: null,
      schedule_depends_on: null,
      schedule_custom_vector: null,
      relations: [],
      z_accrual_enabled: false,
      z_release_trigger: null,
      group_id: null,
      index_name: null,
      margin: null,
      cap: null,
      floor: null,
    },
    {
      name: "R",
      kind: "RESIDUAL",
      is_bond: false,
      is_pseudo: true,
      coupon: 0,
      notional: 0,
      coupon_type: "FIXED",
      pay_mode: "CASH_PAY",
      schedule_contract: [],
      schedule_tolerance_bps: null,
      schedule_derivation: null,
      schedule_model_type: null,
      schedule_speed_low: null,
      schedule_speed_high: null,
      schedule_priority_tier: null,
      schedule_depends_on: null,
      schedule_custom_vector: null,
      relations: [],
      z_accrual_enabled: false,
      z_release_trigger: null,
      group_id: null,
      index_name: null,
      margin: null,
      cap: null,
      floor: null,
    },
  ],
  accounts: [
    {
      name: "RESERVE",
      account_category: "RESERVE",
      starting_amount: 5_000,
      // Phase 7: funding account schedule
      minimum_schedule: [
        { period: 1, minimum_balance: 1_000 },
        { period: 13, minimum_balance: 5_000 },
      ],
    },
  ],
  fees: [],
  triggers: [
    {
      name: "LossTrigger",
      metric_type: "CUMULATIVE_LOSS",
      threshold_value: 0.05,
      // Phase 9: rolling window
      window_periods: 3,
      comparison: "<",
    },
  ],
  waterfall_rules: [
    {
      rule_id: "r_int",
      rule_type: "PAY_INTEREST",
      order: 0,
      from_sources: ["CASH"],
      to_targets: ["A"],
      payment_style: "SEQUENTIAL",
      cap_mode: null,
      coverage_mode: "INTEREST_SHORTFALL",
      // Backend-only expression fields:
      condition_expr: "deal_state == 'EARLY_AMORTIZATION'",
      max_amount_expr: "A_required_subordination",
    },
  ],
  collateral_groups: [],
};

// ---------------------------------------------------------------------------
// Helper: simulate the DealEditor save flow
// ---------------------------------------------------------------------------
function simulateSaveMerge(generatedIr: unknown, savedIrJson: string): Record<string, unknown> {
  const savedBase = extractOpaqueIrFields(savedIrJson);
  return mergeOpaqueIrFields(generatedIr, savedBase) as Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// OA1 tests
// ---------------------------------------------------------------------------

describe("OA1: mergeOpaqueIrFields preserves all Phase 5-9 canonical IR fields", () => {
  const savedIrJson = JSON.stringify(SAVED_IR_WITH_BACKEND_FIELDS);

  it("preserves top-level Phase 7-9 scalar fields", () => {
    const merged = simulateSaveMerge(BLOCKLY_GENERATED_IR, savedIrJson);
    expect(merged.series_id).toBe("CC-SERIES-2024-A");
    expect(merged.deal_state_trigger).toBe("LossTrigger");
    expect(merged.initial_deal_state).toBe("REVOLVING");
    expect(merged.discount_factor_pct).toBe(2.5);
    expect(merged.description).toBe("My phase 6-9 deal");
  });

  it("preserves calculations array (Blockly cannot generate it)", () => {
    const merged = simulateSaveMerge(BLOCKLY_GENERATED_IR, savedIrJson);
    const calcs = merged.calculations as unknown[];
    expect(Array.isArray(calcs)).toBe(true);
    expect(calcs).toHaveLength(1);
    expect((calcs[0] as Record<string, unknown>).name).toBe("cum_loss_pct");
  });

  it("preserves deal_knobs (shallow merge: saved entries fill gaps)", () => {
    const merged = simulateSaveMerge(BLOCKLY_GENERATED_IR, savedIrJson);
    const knobs = merged.deal_knobs as Record<string, unknown>;
    expect(knobs.index_rate).toBe(5.25);
    expect(knobs.servicing_fee_bps).toBe(25.0);
  });

  it("preserves Phase 6 NLA fields on bond A", () => {
    const merged = simulateSaveMerge(BLOCKLY_GENERATED_IR, savedIrJson);
    const bonds = merged.bonds as Array<Record<string, unknown>>;
    const a = bonds.find((b) => b.name === "A");
    expect(a).toBeDefined();
    expect(a!.nla_starting_balance).toBe(1_000_000);
    expect(a!.required_subordination_pct).toBe(20.0);
    expect(a!.seniority).toBe(1);
  });

  it("preserves account minimum_schedule (Phase 7)", () => {
    const merged = simulateSaveMerge(BLOCKLY_GENERATED_IR, savedIrJson);
    const accounts = merged.accounts as Array<Record<string, unknown>>;
    const reserve = accounts.find((a) => a.name === "RESERVE");
    expect(reserve).toBeDefined();
    const sched = reserve!.minimum_schedule as unknown[];
    expect(Array.isArray(sched)).toBe(true);
    expect(sched).toHaveLength(2);
    expect((sched[0] as Record<string, unknown>).minimum_balance).toBe(1_000);
  });

  it("preserves Phase 9 trigger window_periods and comparison", () => {
    const merged = simulateSaveMerge(BLOCKLY_GENERATED_IR, savedIrJson);
    const triggers = merged.triggers as Array<Record<string, unknown>>;
    const t = triggers.find((x) => x.name === "LossTrigger");
    expect(t).toBeDefined();
    expect(t!.window_periods).toBe(3);
    expect(t!.comparison).toBe("<");
  });

  it("preserves backend-only rule expressions (condition_expr, max_amount_expr)", () => {
    // condition_expr and max_amount_expr are not emitted by irGenerator (no block field).
    // They survive exclusively through the { ...saved, ...g } opaque entity merge.
    const merged = simulateSaveMerge(BLOCKLY_GENERATED_IR, savedIrJson);
    const rules = merged.waterfall_rules as Array<Record<string, unknown>>;
    const r = rules.find((x) => x.rule_id === "r_int");
    expect(r).toBeDefined();
    expect(r!.condition_expr).toBe("deal_state == 'EARLY_AMORTIZATION'");
    expect(r!.max_amount_expr).toBe("A_required_subordination");
  });

  it("Blockly-owned coverage_mode is preserved when emitted by irGenerator", () => {
    // coverage_mode is Blockly-owned — irToBlocklyState stashes it in block.data,
    // irGenerator reads it back. The entity merge { ...saved, ...g } lets the
    // generated value win (which, in a real round-trip, is correct because it
    // came from block.data in the first place).
    const merged = simulateSaveMerge(BLOCKLY_GENERATED_IR, savedIrJson);
    const rules = merged.waterfall_rules as Array<Record<string, unknown>>;
    const r = rules.find((x) => x.rule_id === "r_int");
    // In our test the generated IR includes "INTEREST_SHORTFALL" (mimicking a real
    // round-trip where block.data was correctly populated by irToBlocklyState).
    expect(r!.coverage_mode).toBe("INTEREST_SHORTFALL");
  });

  it("deal_name from Blockly wins (Blockly owns visible scalars)", () => {
    const altGenerated = { ...BLOCKLY_GENERATED_IR, deal_name: "Renamed Deal" };
    const merged = simulateSaveMerge(altGenerated, savedIrJson);
    expect(merged.deal_name).toBe("Renamed Deal");
  });

  it("bond visible fields from Blockly win; backend-only fields from saved", () => {
    // Blockly changes bond A coupon to 6.0; NLA must still come from saved.
    const altBonds = [
      { ...BLOCKLY_GENERATED_IR.bonds[0], coupon: 6.0 },
      ...BLOCKLY_GENERATED_IR.bonds.slice(1),
    ];
    const altGenerated = { ...BLOCKLY_GENERATED_IR, bonds: altBonds };
    const merged = simulateSaveMerge(altGenerated, savedIrJson);
    const bonds = merged.bonds as Array<Record<string, unknown>>;
    const a = bonds.find((b) => b.name === "A");
    expect(a!.coupon).toBe(6.0);            // Blockly wins for visible field
    expect(a!.nla_starting_balance).toBe(1_000_000); // saved wins for backend-only
  });

  it("round-trip is deterministic: merging twice produces same result", () => {
    const first = simulateSaveMerge(BLOCKLY_GENERATED_IR, savedIrJson);
    const firstJson = JSON.stringify(first);
    const second = simulateSaveMerge(first, savedIrJson);
    expect(JSON.stringify(second)).toBe(firstJson);
  });
});
