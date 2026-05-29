/**
 * IR round-trip integration tests.
 *
 * Fundamental invariant: generateDealIR(synthesizeWorkspaceState(ir)) must
 * produce the same runtime-critical IR that went in — verbatim for the fields
 * that determine cashflow computation.
 *
 * Any divergence between input IR and round-tripped IR is a bug in either the
 * synthesizer (irToBlocklyState.ts) or the generator (irGenerator.ts).
 *
 * What must be identical (runtime-critical):
 *   - bonds: kind, schedule_contract, relations, z_accrual_enabled, coupon
 *   - waterfall_rules: rule_type, from_sources, to_targets, order, group_id, cap_mode
 *   - collateral_groups: group_id
 *
 * What is allowed to differ (derivation metadata, not runtime-critical):
 *   - rule_id: regenerated when not stashed in block.data (name changes are fine)
 *   - schedule_model_type / schedule_speed_low/high: display-only, runtime uses schedule_contract
 *   - deal_name: not synthesized into the workspace
 */
import { describe, it, expect } from "vitest";
import { generateDealIR } from "./irGenerator";
import { synthesizeWorkspaceState, type IRForSynthesis } from "./irToBlocklyState";
import type { DealDefinitionIR } from "./ir-types";

// ---------------------------------------------------------------------------
// Workspace state → mock Blockly block adapter
// ---------------------------------------------------------------------------
//
// synthesizeWorkspaceState() produces a JSON-compatible workspace state.
// irGenerator.generateDealIR() expects a real Blockly workspace with
// getTopBlocks() / getFieldValue() / getInputTargetBlock() / getNextBlock() API.
//
// This adapter converts the state JSON into mock objects so we can run the
// full synthesize → generate round-trip in a unit test without a real DOM.

type BlockJson = {
  type: string;
  fields?: Record<string, unknown>;
  data?: string;
  inputs?: Record<string, { block?: BlockJson } | null>;
  next?: { block?: BlockJson };
};

type MockBlock = {
  type: string;
  data?: string;
  getFieldValue(name: string): unknown;
  getNextBlock(): MockBlock | null;
  getInputTargetBlock(name: string): MockBlock | null;
};

function blockJsonToMock(json: BlockJson): MockBlock {
  const fields = json.fields ?? {};
  // Eagerly convert all inputs and next so the mock tree is fully built.
  const inputs: Record<string, MockBlock | null> = {};
  for (const [key, val] of Object.entries(json.inputs ?? {})) {
    inputs[key] = val?.block ? blockJsonToMock(val.block) : null;
  }
  const nextBlock = json.next?.block ? blockJsonToMock(json.next.block) : null;

  return {
    type: json.type,
    data: json.data,
    getFieldValue(name: string) { return fields[name] ?? null; },
    getNextBlock() { return nextBlock; },
    getInputTargetBlock(name: string) { return inputs[name] ?? null; },
  };
}

function makeWorkspaceFromState(state: ReturnType<typeof synthesizeWorkspaceState>) {
  const topBlocks = (state?.blocks.blocks ?? []).map(blockJsonToMock as (b: unknown) => MockBlock);
  return { getTopBlocks: () => topBlocks };
}

// ---------------------------------------------------------------------------
// Helper: compare round-tripped IR against input IR
// ---------------------------------------------------------------------------

function roundTrip(ir: IRForSynthesis): DealDefinitionIR {
  const state = synthesizeWorkspaceState(ir);
  expect(state).not.toBeNull();
  const ws = makeWorkspaceFromState(state);
  return generateDealIR(ws as any);
}

/** Compare rule-critical fields ignoring rule_id (which may be regenerated). */
function ruleKey(r: { rule_type: string; from_sources?: string[]; to_targets?: string[]; group_id?: string | null; cap_mode?: string | null }) {
  return `${r.rule_type}|${(r.from_sources ?? []).join(",")}|${(r.to_targets ?? []).sort().join(",")}|${r.group_id ?? ""}|${r.cap_mode ?? ""}`;
}

// ---------------------------------------------------------------------------
// Canonical fixture — covers PAC/TAC, Z, SPLIT_CASH, support bonds, multi-group,
// and cleanup rules (cap_mode=NONE).
// ---------------------------------------------------------------------------

const SCHEDULE_PA = [
  { period: 1,  target_balance: 33_000_000 },
  { period: 12, target_balance: 30_000_000 },
  { period: 24, target_balance: 25_000_000 },
  { period: 36, target_balance: 18_000_000 },
];
const SCHEDULE_TA = [
  { period: 1,  target_balance: 95_000_000 },
  { period: 12, target_balance: 88_000_000 },
  { period: 24, target_balance: 75_000_000 },
];

const CANONICAL_MULTI_GROUP_IR: IRForSynthesis = {
  deal_name: "Round-Trip Test Deal",
  collateral_groups: [
    { group_id: "GROUP_1", label: "Group 1 (PAC + Z + Support)", description: "30-yr pool" },
    { group_id: "GROUP_2", label: "Group 2 (Sequential)", description: "20-yr pool" },
  ],
  bonds: [
    // Group 1: PAC I
    { name: "PA", kind: "PAC", coupon: 5.5, notional: 33_710_000,
      schedule_contract: SCHEDULE_PA,
      relations: [{ relation_type: "SUPPORTED_BY", targets: ["WA", "WB"] }],
      group_id: "GROUP_1" },
    // Group 1: PAC II
    { name: "TA", kind: "PAC", coupon: 5.5, notional: 95_000_000,
      schedule_contract: SCHEDULE_TA,
      relations: [{ relation_type: "SUPPORTED_BY", targets: ["WA", "WB"] }],
      group_id: "GROUP_1" },
    // Group 1: Z bond
    { name: "Z", kind: "Z", coupon: 5.5, notional: 20_000_000,
      pay_mode: "PIK", z_accrual_enabled: true,
      relations: [{ relation_type: "ACCRETES_TO", targets: ["TA"] }],
      group_id: "GROUP_1" },
    // Group 1: Support
    { name: "WA", kind: "CASH_PAY", coupon: 5.5, notional: 40_000_000, group_id: "GROUP_1" },
    { name: "WB", kind: "CASH_PAY", coupon: 5.5, notional: 20_000_000, group_id: "GROUP_1" },
    // Group 2: Sequential
    { name: "BA", kind: "CASH_PAY", coupon: 5.5, notional: 50_000_000, group_id: "GROUP_2" },
    { name: "BC", kind: "CASH_PAY", coupon: 5.5, notional: 30_000_000, group_id: "GROUP_2" },
    // Residual
    { name: "R", kind: "RESIDUAL", is_bond: false, is_pseudo: true },
  ],
  fees: [],
  triggers: [],
  waterfall_rules: [
    // Group 1 waterfall
    { rule_id: "g1_int",     rule_type: "PAY_INTEREST",   order: 0,  group_id: "GROUP_1", from_sources: ["ACT_INT"],  to_targets: ["PA", "TA", "WA", "WB"], payment_style: "SEQUENTIAL" },
    { rule_id: "g1_pac_i",   rule_type: "PAY_PRINCIPAL",  order: 1,  group_id: "GROUP_1", from_sources: ["ACT_PRIN"], to_targets: ["PA"], payment_style: "SEQUENTIAL" },
    { rule_id: "g1_pac_ii",  rule_type: "PAY_PRINCIPAL",  order: 2,  group_id: "GROUP_1", from_sources: ["ACT_PRIN"], to_targets: ["TA"], payment_style: "SEQUENTIAL" },
    { rule_id: "g1_z",       rule_type: "PAY_PRINCIPAL",  order: 3,  group_id: "GROUP_1", from_sources: ["ACT_PRIN"], to_targets: ["Z"], payment_style: "SEQUENTIAL" },
    { rule_id: "g1_sup_spl", rule_type: "SPLIT_CASH",     order: 4,  group_id: "GROUP_1", from_sources: ["ACT_PRIN"], to_targets: ["WA_BCK", "WB_BCK"], target_weights: [0.65, 0.35] },
    { rule_id: "g1_wa",      rule_type: "PAY_PRINCIPAL",  order: 5,  group_id: "GROUP_1", from_sources: ["WA_BCK"],  to_targets: ["WA"], payment_style: "SEQUENTIAL" },
    { rule_id: "g1_wb",      rule_type: "PAY_PRINCIPAL",  order: 6,  group_id: "GROUP_1", from_sources: ["WB_BCK"],  to_targets: ["WB"], payment_style: "SEQUENTIAL" },
    { rule_id: "g1_sweep",   rule_type: "SPLIT_CASH",     order: 7,  group_id: "GROUP_1", from_sources: ["WA_BCK", "WB_BCK"], to_targets: ["ACT_PRIN"], target_weights: [1.0] },
    { rule_id: "g1_cleanup", rule_type: "PAY_PRINCIPAL",  order: 8,  group_id: "GROUP_1", from_sources: ["ACT_PRIN"], to_targets: ["PA", "TA", "WA", "WB"], payment_style: "SEQUENTIAL", cap_mode: "NONE" },
    { rule_id: "g1_resid",   rule_type: "PAY_RESIDUAL",   order: 9,  group_id: "GROUP_1", from_sources: ["CASH"],    to_targets: ["R"] },
    // Group 2 waterfall
    { rule_id: "g2_int",     rule_type: "PAY_INTEREST",   order: 10, group_id: "GROUP_2", from_sources: ["ACT_INT"],  to_targets: ["BA", "BC"], payment_style: "SEQUENTIAL" },
    { rule_id: "g2_prin",    rule_type: "PAY_PRINCIPAL",  order: 11, group_id: "GROUP_2", from_sources: ["ACT_PRIN"], to_targets: ["BA", "BC"], payment_style: "SEQUENTIAL" },
    { rule_id: "g2_cleanup", rule_type: "PAY_PRINCIPAL",  order: 12, group_id: "GROUP_2", from_sources: ["ACT_PRIN"], to_targets: ["BA", "BC"], payment_style: "SEQUENTIAL", cap_mode: "NONE" },
    { rule_id: "g2_resid",   rule_type: "PAY_RESIDUAL",   order: 13, group_id: "GROUP_2", from_sources: ["CASH"],    to_targets: ["R"] },
  ],
};

// ---------------------------------------------------------------------------
// Round-trip tests
// ---------------------------------------------------------------------------

describe("IR round-trip: synthesizeWorkspaceState → generateDealIR", () => {

  it("waterfall rules: type, sources, targets, group_id, cap_mode all match verbatim", () => {
    const original = CANONICAL_MULTI_GROUP_IR;
    const regen = roundTrip(original);

    const origKeys = new Set((original.waterfall_rules ?? []).map(ruleKey));
    const regenKeys = new Set((regen.waterfall_rules ?? []).map(ruleKey));

    // Every original rule must appear in the round-tripped IR.
    const missing = [...origKeys].filter((k) => !regenKeys.has(k));
    const extra = [...regenKeys].filter((k) => !origKeys.has(k));

    expect(missing, `Missing rules: ${missing.join("\n")}\nExtra rules: ${extra.join("\n")}`).toHaveLength(0);
    expect(extra, `Extra rules: ${extra.join("\n")}`).toHaveLength(0);
  });

  it("PAC bond kind preserved through round-trip", () => {
    const regen = roundTrip(CANONICAL_MULTI_GROUP_IR);
    const pa = regen.bonds?.find((b) => b.name === "PA");
    const ta = regen.bonds?.find((b) => b.name === "TA");
    expect(pa?.kind).toBe("PAC");
    expect(ta?.kind).toBe("PAC");
  });

  it("PAC schedule_contract preserved verbatim through round-trip", () => {
    const regen = roundTrip(CANONICAL_MULTI_GROUP_IR);
    const pa = regen.bonds?.find((b) => b.name === "PA");
    const ta = regen.bonds?.find((b) => b.name === "TA");

    // PA schedule must be the full SCHEDULE_PA array, not [] or a synthetic stub.
    expect(pa?.schedule_contract).toHaveLength(SCHEDULE_PA.length);
    pa?.schedule_contract.forEach((entry: Record<string, unknown>, i: number) => {
      expect(entry.period).toBe(SCHEDULE_PA[i].period);
      expect(entry.target_balance).toBe(SCHEDULE_PA[i].target_balance);
    });

    // TA schedule must be the full SCHEDULE_TA array.
    expect(ta?.schedule_contract).toHaveLength(SCHEDULE_TA.length);
    ta?.schedule_contract.forEach((entry: Record<string, unknown>, i: number) => {
      expect(entry.period).toBe(SCHEDULE_TA[i].period);
      expect(entry.target_balance).toBe(SCHEDULE_TA[i].target_balance);
    });
  });

  it("PAC SUPPORTED_BY relations preserved through round-trip", () => {
    const regen = roundTrip(CANONICAL_MULTI_GROUP_IR);
    const pa = regen.bonds?.find((b) => b.name === "PA");
    const supportedBy = pa?.relations?.find(
      (r: Record<string, unknown>) => r.relation_type === "SUPPORTED_BY"
    );
    expect(supportedBy).toBeDefined();
    expect((supportedBy as Record<string, unknown>)?.targets).toContain("WA");
    expect((supportedBy as Record<string, unknown>)?.targets).toContain("WB");
  });

  it("Z bond kind, z_accrual_enabled, ACCRETES_TO relation preserved", () => {
    const regen = roundTrip(CANONICAL_MULTI_GROUP_IR);
    const z = regen.bonds?.find((b) => b.name === "Z");
    expect(z?.kind).toBe("Z");
    expect(z?.z_accrual_enabled).toBe(true);
    const accretesTo = z?.relations?.find(
      (r: Record<string, unknown>) => r.relation_type === "ACCRETES_TO"
    );
    expect(accretesTo).toBeDefined();
    expect((accretesTo as Record<string, unknown>)?.targets).toContain("TA");
  });

  it("cap_mode=NONE cleanup rules not promoted to PAC blocks", () => {
    const regen = roundTrip(CANONICAL_MULTI_GROUP_IR);
    const cleanupRules = (regen.waterfall_rules ?? []).filter(
      (r) => r.cap_mode === "NONE"
    );
    // Both g1_cleanup and g2_cleanup should survive.
    expect(cleanupRules.length).toBe(2);
    // They should be PAY_PRINCIPAL, not PAC schedule.
    for (const r of cleanupRules) {
      expect(r.rule_type).toBe("PAY_PRINCIPAL");
    }
  });

  it("SPLIT_CASH rules preserved with target_weights", () => {
    const regen = roundTrip(CANONICAL_MULTI_GROUP_IR);
    const splitRules = (regen.waterfall_rules ?? []).filter(
      (r) => r.rule_type === "SPLIT_CASH"
    );
    expect(splitRules.length).toBe(2); // support split + sweep-back
    const supportSplit = splitRules.find(
      (r) => (r.to_targets ?? []).includes("WA_BCK")
    );
    expect(supportSplit).toBeDefined();
    expect(supportSplit?.target_weights).toBeDefined();
    expect(supportSplit?.target_weights![0]).toBeCloseTo(0.65, 2);
    expect(supportSplit?.target_weights![1]).toBeCloseTo(0.35, 2);
  });

  it("group_ids on rules preserved for both groups", () => {
    const regen = roundTrip(CANONICAL_MULTI_GROUP_IR);
    const g1Rules = (regen.waterfall_rules ?? []).filter((r) => r.group_id === "GROUP_1");
    const g2Rules = (regen.waterfall_rules ?? []).filter((r) => r.group_id === "GROUP_2");
    expect(g1Rules.length).toBeGreaterThan(0);
    expect(g2Rules.length).toBeGreaterThan(0);
    // No rules should lack a group_id (all rules in this deal are group-tagged).
    const ungrouped = (regen.waterfall_rules ?? []).filter((r) => !r.group_id);
    expect(ungrouped.length).toBe(0);
  });

  it("collateral_groups preserved through round-trip", () => {
    const regen = roundTrip(CANONICAL_MULTI_GROUP_IR);
    const groupIds = (regen.collateral_groups ?? []).map((g) => g.group_id);
    expect(groupIds).toContain("GROUP_1");
    expect(groupIds).toContain("GROUP_2");
  });

  it("bond coupons and notionals preserved", () => {
    const regen = roundTrip(CANONICAL_MULTI_GROUP_IR);
    const pa = regen.bonds?.find((b) => b.name === "PA");
    const ba = regen.bonds?.find((b) => b.name === "BA");
    expect(pa?.coupon).toBe(5.5);
    expect(pa?.notional).toBe(33_710_000);
    expect(ba?.coupon).toBe(5.5);
    expect(ba?.notional).toBe(50_000_000);
  });

  it("rule ordering is preserved (order field matches)", () => {
    const regen = roundTrip(CANONICAL_MULTI_GROUP_IR);
    const original = CANONICAL_MULTI_GROUP_IR;
    const origBySourceTarget = new Map(
      (original.waterfall_rules ?? []).map((r) => [
        `${r.rule_type}|${(r.to_targets ?? []).sort().join(",")}|${r.group_id ?? ""}|${r.cap_mode ?? ""}`,
        r.order,
      ])
    );
    for (const regenRule of regen.waterfall_rules ?? []) {
      const key = `${regenRule.rule_type}|${(regenRule.to_targets ?? []).sort().join(",")}|${regenRule.group_id ?? ""}|${regenRule.cap_mode ?? ""}`;
      if (origBySourceTarget.has(key)) {
        expect(regenRule.order).toBe(origBySourceTarget.get(key));
      }
    }
  });
});
