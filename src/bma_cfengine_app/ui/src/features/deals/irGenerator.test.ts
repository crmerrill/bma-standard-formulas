/**
 * Tests for irGenerator.ts — verifies that generateDealIR correctly reads
 * block.data payloads stashed by irToBlocklyState and produces a DealDefinitionIR
 * that preserves all economic fields through the Blockly round-trip.
 *
 * These tests use mock Blockly block objects with `data` fields populated as
 * irToBlocklyState would produce them.
 */
import { describe, it, expect } from "vitest";
import { generateDealIR } from "./irGenerator";

// ---------------------------------------------------------------------------
// Minimal mock Blockly block factory
// The mocks implement the Blockly block API surface used by irGenerator:
//   - getFieldValue(name): returns a field value
//   - getNextBlock():       returns the next chained block (or null)
//   - getInputTargetBlock(name): returns the first block connected to input `name`
// ---------------------------------------------------------------------------

type MockBlock = {
  type: string;
  data?: string;
  _fields: Record<string, string | number | boolean>;
  _nextBlock: MockBlock | null;
  _inputs: Record<string, MockBlock | null>;
  getFieldValue(name: string): string | number | boolean | null;
  getNextBlock(): MockBlock | null;
  getInputTargetBlock(name: string): MockBlock | null;
};

function makeMockBlock(
  type: string,
  fields: Record<string, string | number | boolean>,
  inputs: Record<string, MockBlock | null> = {},
  dataPayload?: Record<string, unknown>,
): MockBlock {
  const block: MockBlock = {
    type,
    data: dataPayload ? JSON.stringify(dataPayload) : undefined,
    _fields: fields,
    _nextBlock: null,
    _inputs: inputs,
    getFieldValue(name: string) { return this._fields[name] ?? null; },
    getNextBlock() { return this._nextBlock; },
    getInputTargetBlock(name: string) { return this._inputs[name] ?? null; },
  };
  return block;
}

/** Link blocks as a chain: each block's getNextBlock() returns the next one. */
function linkChain(...blocks: MockBlock[]): MockBlock {
  for (let i = 0; i < blocks.length - 1; i++) {
    blocks[i]._nextBlock = blocks[i + 1];
  }
  return blocks[0];
}

function bondTargetBlock(
  name: string,
  face: number,
  dataPayload?: Record<string, unknown>,
): MockBlock {
  return makeMockBlock(
    "bond_target",
    { NAME: name, BOND_TYPE: "FIXED", PAY_MODE: "CASH_PAY", FACE_AMT: face, SIZE_PCT_POOL: 0, COUPON: 5, ACCRUAL: "30_360" },
    {},
    dataPayload,
  );
}

function residualBlock(name = "R"): MockBlock {
  return makeMockBlock("residual_target", { NAME: name }, {}, { kind: "RESIDUAL" });
}

function paySequentialBlock(
  source: string,
  targets: MockBlock[],
  dataPayload?: Record<string, unknown>,
): MockBlock {
  const targetChain = linkChain(...targets);
  return makeMockBlock(
    "pay_sequential",
    { PAY_TYPE: "INTEREST", SOURCE: source, MAX_PAY: 0 },
    { TARGETS: targetChain },
    dataPayload,
  );
}

function splitAccountBlock(
  source: string,
  out1: string,
  out2: string,
  dataPayload?: Record<string, unknown>,
): MockBlock {
  return makeMockBlock(
    "split_account",
    { SOURCE: source, OUT_1: out1, OUT_2: out2 },
    {},
    dataPayload,
  );
}

function makeWorkspace(topBlocks: MockBlock[]) {
  return {
    getTopBlocks: () => topBlocks,
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function run(workspace: ReturnType<typeof makeWorkspace>) {
  return generateDealIR(workspace as any);
}

// ---------------------------------------------------------------------------
// Tests: kind + group_id round-trip (B1 + general data reading)
// ---------------------------------------------------------------------------

describe("generateDealIR block.data round-trip", () => {
  it("preserves kind from bond block.data", () => {
    const ws = makeWorkspace([
      paySequentialBlock("CASH", [
        bondTargetBlock("PAC_A", 100, { kind: "PAC", schedule_contract: [{ period: 1, target_principal: 10 }] }),
      ]),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const pac = ir.bonds.find((b) => b.name === "PAC_A");
    expect(pac?.kind).toBe("PAC");
  });

  it("preserves group_id on bond and derives collateral_groups", () => {
    const ws = makeWorkspace([
      paySequentialBlock(
        "CASH",
        [bondTargetBlock("A", 100, { kind: "CASH_PAY", group_id: "GROUP_1" })],
        { rule_id: "r1", group_id: "GROUP_1" },
      ),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const bond = ir.bonds.find((b) => b.name === "A");
    expect(bond?.group_id).toBe("GROUP_1");
    expect(ir.collateral_groups.map((g) => g.group_id)).toContain("GROUP_1");
    expect(ir.collateral_groups.length).toBe(1);
  });

  it("derives collateral_groups from multiple group_ids across bonds and rules", () => {
    const ws = makeWorkspace([
      paySequentialBlock(
        "CASH",
        [bondTargetBlock("A", 100, { kind: "CASH_PAY", group_id: "GROUP_1" })],
        { rule_id: "r1", group_id: "GROUP_1" },
      ),
      paySequentialBlock(
        "CASH",
        [bondTargetBlock("B", 80, { kind: "CASH_PAY", group_id: "GROUP_2" })],
        { rule_id: "r2", group_id: "GROUP_2" },
      ),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const gids = ir.collateral_groups.map((g) => g.group_id);
    expect(gids).toContain("GROUP_1");
    expect(gids).toContain("GROUP_2");
    expect(ir.collateral_groups.length).toBe(2);
  });

  it("emits empty collateral_groups when no group_id is set", () => {
    const ws = makeWorkspace([
      paySequentialBlock("CASH", [bondTargetBlock("A", 100)]),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    expect(ir.collateral_groups).toEqual([]);
  });

  // -------------------------------------------------------------------
  // B2: schedule_contract preserves target_balance entries
  // -------------------------------------------------------------------

  it("preserves target_balance in schedule_contract from block.data (B2)", () => {
    const ws = makeWorkspace([
      paySequentialBlock("CASH", [
        bondTargetBlock("PAC_A", 100, {
          kind: "PAC",
          schedule_contract: [
            { period: 1, target_balance: 90 },
            { period: 2, target_balance: 80 },
          ],
        }),
      ]),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const pac = ir.bonds.find((b) => b.name === "PAC_A");
    expect(pac?.schedule_contract[0]).toHaveProperty("target_balance", 90);
    expect(pac?.schedule_contract[1]).toHaveProperty("target_balance", 80);
  });

  // -------------------------------------------------------------------
  // B3: coverage_mode round-trip
  // -------------------------------------------------------------------

  it("preserves coverage_mode on rules from block.data (B3)", () => {
    const ws = makeWorkspace([
      paySequentialBlock("CASH", [
        bondTargetBlock("A", 100),
      ], {
        rule_id: "r_sf",
        coverage_mode: "INTEREST_SHORTFALL",
      }),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const r = ir.waterfall_rules.find((r) => r.rule_id === "r_sf");
    expect(r?.coverage_mode).toBe("INTEREST_SHORTFALL");
  });

  // -------------------------------------------------------------------
  // B4: SPLIT_CASH emission from split_account blocks
  // -------------------------------------------------------------------

  it("emits SPLIT_CASH rule for split_account block (B4)", () => {
    const ws = makeWorkspace([
      splitAccountBlock("CASH", "BUCKET_1", "BUCKET_2", {
        rule_id: "split_r1",
        target_weights: [0.6, 0.4],
      }),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const split = ir.waterfall_rules.find((r) => r.rule_type === "SPLIT_CASH");
    expect(split).toBeDefined();
    expect(split?.to_targets).toEqual(["BUCKET_1", "BUCKET_2"]);
    expect(split?.target_weights).toEqual([0.6, 0.4]);
    expect(split?.rule_id).toBe("split_r1");
  });

  // -------------------------------------------------------------------
  // M6: z_accrual_enabled explicit boolean (including false)
  // -------------------------------------------------------------------

  it("preserves z_accrual_enabled:false when stashed in block.data (M6)", () => {
    const ws = makeWorkspace([
      paySequentialBlock("CASH", [
        bondTargetBlock("Z", 50, { kind: "Z", z_accrual_enabled: false }),
      ]),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const z = ir.bonds.find((b) => b.name === "Z");
    expect(z?.z_accrual_enabled).toBe(false);
  });

  it("preserves z_accrual_enabled:true when stashed in block.data (M6)", () => {
    const ws = makeWorkspace([
      paySequentialBlock("CASH", [
        bondTargetBlock("Z", 50, { kind: "Z", z_accrual_enabled: true }),
      ]),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const z = ir.bonds.find((b) => b.name === "Z");
    expect(z?.z_accrual_enabled).toBe(true);
  });

  // -------------------------------------------------------------------
  // M7: full relation payload
  // -------------------------------------------------------------------

  it("preserves full relation payload including weights and leverage (M7)", () => {
    const ws = makeWorkspace([
      paySequentialBlock("CASH", [
        bondTargetBlock("IO", 0, {
          kind: "IO",
          relations: [
            {
              relation_type: "NOTIONAL_TRACKS",
              targets: ["A"],
              weights: [1.0],
              leverage: 2.5,
              cap: 12.0,
              floor: 0.0,
              description: "notional tracker",
            },
          ],
        }),
      ]),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const io = ir.bonds.find((b) => b.name === "IO");
    const rel = io?.relations?.[0] as Record<string, unknown>;
    expect(rel?.relation_type).toBe("NOTIONAL_TRACKS");
    expect(rel?.weights).toEqual([1.0]);
    expect(rel?.leverage).toBe(2.5);
    expect(rel?.cap).toBe(12.0);
    expect(rel?.description).toBe("notional tracker");
  });

  // -------------------------------------------------------------------
  // M8: coupon_type from block.data
  // -------------------------------------------------------------------

  it("uses coupon_type from block.data to override visible BOND_TYPE field (M8)", () => {
    // PO bonds have coupon_type=ZERO but BOND_TYPE dropdown may show FIXED.
    const ws = makeWorkspace([
      paySequentialBlock("CASH", [
        bondTargetBlock("PO", 0, { kind: "PO", coupon_type: "ZERO" }),
      ]),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const po = ir.bonds.find((b) => b.name === "PO");
    expect(po?.coupon_type).toBe("ZERO");
  });

  // -------------------------------------------------------------------
  // M9: unknown source tokens pass through unchanged
  // -------------------------------------------------------------------

  it("passes through unknown source tokens instead of collapsing to CASH (M9)", () => {
    const ws = makeWorkspace([
      paySequentialBlock("RESERVE_ACCT", [bondTargetBlock("A", 100)]),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const r = ir.waterfall_rules.find((r) => r.to_targets?.includes("A"));
    expect(r?.from_sources).toContain("RESERVE_ACCT");
  });

  it("INT_COLLECTION maps to ACT_INT (not CASH)", () => {
    const ws = makeWorkspace([
      paySequentialBlock("INT_COLLECTION", [bondTargetBlock("A", 100)]),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const r = ir.waterfall_rules.find((r) => r.to_targets?.includes("A"));
    expect(r?.from_sources).toContain("ACT_INT");
    expect(r?.from_sources).not.toContain("CASH");
  });

  // -------------------------------------------------------------------
  // cap_mode round-trip
  // -------------------------------------------------------------------

  it("preserves cap_mode on rules from block.data", () => {
    const ws = makeWorkspace([
      paySequentialBlock("CASH", [
        bondTargetBlock("A", 100),
      ], { rule_id: "cleanup_r", cap_mode: "NONE" }),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const r = ir.waterfall_rules.find((r) => r.rule_id === "cleanup_r");
    expect(r?.cap_mode).toBe("NONE");
  });
});


// ---------------------------------------------------------------------------
// SR2: PropertyPanel carry tie-out uses TrancheKind (not coupon type)
// SR3: schedule_derivation and schedule_tolerance_bps round-trip via block.data
// ---------------------------------------------------------------------------

describe("SR2 + SR3 block.data round-trip", () => {
  it("SR2: trancheKind=RESIDUAL read from block.data flows to kind field in IR", () => {
    // Residual target has {kind:"RESIDUAL"} in block.data (set by irToBlocklyState)
    const ws = makeWorkspace([
      paySequentialBlock("CASH", [
        bondTargetBlock("A", 100),
      ]),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const r = ir.bonds.find((b) => b.name === "R" || b.kind === "RESIDUAL");
    expect(r?.kind).toBe("RESIDUAL");
    // RESIDUAL bonds must have is_pseudo=true so carry tie-out skips them
    expect(r?.is_pseudo).toBe(true);
  });

  it("SR3: schedule_derivation round-trips from block.data", () => {
    const derivation = { method: "PSA_RANGE", inputs: { psa_low: 100, psa_high: 250, support_names: "S" } };
    const ws = makeWorkspace([
      paySequentialBlock("CASH", [
        bondTargetBlock("PAC_A", 100, {
          kind: "PAC",
          schedule_contract: [{ period: 1, target_principal: 10 }],
          schedule_derivation: derivation,
        }),
      ]),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const pac = ir.bonds.find((b) => b.name === "PAC_A");
    expect(pac?.schedule_derivation).toEqual(derivation);
  });

  it("SR3: schedule_tolerance_bps round-trips from block.data", () => {
    const ws = makeWorkspace([
      paySequentialBlock("CASH", [
        bondTargetBlock("PAC_A", 100, {
          kind: "PAC",
          schedule_contract: [{ period: 1, target_principal: 5 }],
          schedule_tolerance_bps: 50,
        }),
      ]),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const pac = ir.bonds.find((b) => b.name === "PAC_A");
    expect(pac?.schedule_tolerance_bps).toBe(50);
  });

  it("SR3: schedule_derivation=null when not in block.data", () => {
    const ws = makeWorkspace([
      paySequentialBlock("CASH", [bondTargetBlock("A", 100)]),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const a = ir.bonds.find((b) => b.name === "A");
    expect(a?.schedule_derivation).toBeNull();
  });

  it("SR3: schedule_tolerance_bps defaults to 25 for PAC kind without block.data override", () => {
    // A PAC bond with kind=PAC in block.data but no schedule_tolerance_bps
    // should use the default 25 bps from generateDealIR.
    const ws = makeWorkspace([
      paySequentialBlock("CASH", [
        bondTargetBlock("PAC_A", 100, {
          kind: "PAC",
          schedule_contract: [{ period: 1, target_principal: 5 }],
          // No schedule_tolerance_bps in block.data
        }),
      ]),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const pac = ir.bonds.find((b) => b.name === "PAC_A");
    // Default tolerance is 25 bps when not in block.data
    expect(pac?.schedule_tolerance_bps).toBe(25);
  });

  it("SR3: schedule_model_type and speed band round-trip from block.data (load path)", () => {
    // When a saved IR is loaded via irToBlocklyState (no PAC rule block created),
    // irGenerator must recover schedule_model_type/speed_low/high/priority_tier
    // from bond_target block.data, not lose them.
    const ws = makeWorkspace([
      paySequentialBlock("CASH", [
        bondTargetBlock("PA", 1000, {
          kind: "PAC",
          schedule_model_type: "PSA",
          schedule_speed_low: 100,
          schedule_speed_high: 250,
          schedule_priority_tier: 1,
          schedule_depends_on: "PB",
          schedule_contract: [{ period: 1, target_principal: 5 }],
        }),
      ]),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const pa = ir.bonds.find((b) => b.name === "PA");
    expect(pa?.schedule_model_type).toBe("PSA");
    expect(pa?.schedule_speed_low).toBe(100);
    expect(pa?.schedule_speed_high).toBe(250);
    expect(pa?.schedule_priority_tier).toBe(1);
    expect(pa?.schedule_depends_on).toBe("PB");
  });

  it("SR3/PAC: block.data schedule_contract preserved through PAC block round-trip", () => {
    // When irToBlocklyState synthesizes a PAC block from a prospectus-derived IR,
    // it sets MODEL_TYPE=CUSTOM_VECTOR with empty CUSTOM_VECTOR text. Previously
    // applyPacTacSemantics would overwrite the bond's block.data schedule_contract
    // with the empty synthetic result, destroying the prospectus schedule.
    // This test verifies the stored schedule is preserved.
    const prospectusSchedule = [
      { period: 1, target_balance: 900 },
      { period: 12, target_balance: 800 },
      { period: 24, target_balance: 600 },
    ];
    const ws = makeWorkspace([
      makeMockBlock("pay_pac_schedule", {
        MODEL_TYPE: "CUSTOM_VECTOR",
        SPEED_LOW: 0,
        SPEED_HIGH: 0,
        CUSTOM_VECTOR: "",    // empty — as synthesized by irToBlocklyState
        SOURCE: "ACT_PRIN",
        PRIORITY_TIER: 1,
        DEPENDS_ON: "",
      }, {
        TARGETS: bondTargetBlock("PA", 1000, {
          kind: "PAC",
          schedule_contract: prospectusSchedule,  // stored in block.data
        }),
        SUPPORT_BONDS: bondTargetBlock("WA", 200),
      }),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const pa = ir.bonds.find((b) => b.name === "PA");
    expect(pa?.schedule_contract).toHaveLength(3);
    expect(pa?.schedule_contract[0]).toMatchObject({ period: 1 });
    expect(pa?.schedule_contract[2]).toMatchObject({ period: 24 });
  });

  it("SR3: live PSA schedule overrides block.data when non-empty", () => {
    // When the user has set real PSA parameters, the synthetic schedule should win
    // over any stale schedule in block.data.
    const staleBlockDataSchedule = [{ period: 1, target_balance: 999 }];
    const ws = makeWorkspace([
      makeMockBlock("pay_pac_schedule", {
        MODEL_TYPE: "PSA",
        SPEED_LOW: 100,
        SPEED_HIGH: 250,
        CUSTOM_VECTOR: "",
        SOURCE: "ACT_PRIN",
        PRIORITY_TIER: 1,
        DEPENDS_ON: "",
      }, {
        TARGETS: bondTargetBlock("PA", 1000, {
          kind: "PAC",
          schedule_contract: staleBlockDataSchedule,  // stale
        }),
        SUPPORT_BONDS: bondTargetBlock("WA", 200),
      }),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const pa = ir.bonds.find((b) => b.name === "PA");
    // PSA derivation with speed_low=100, speed_high=250 produces synthetic
    // schedule (2 entries: lo and hi).  It must override the stale block.data.
    expect(pa?.schedule_contract.length).toBeGreaterThan(0);
    // The stale single-entry schedule should NOT appear.
    expect(pa?.schedule_contract[0]).not.toMatchObject({ target_balance: 999 });
  });

  it("SR3: schedule_model_type=null when absent from block.data (normal bond)", () => {
    const ws = makeWorkspace([
      paySequentialBlock("CASH", [bondTargetBlock("A", 100)]),
      paySequentialBlock("CASH", [residualBlock()]),
    ]);
    const ir = run(ws);
    const a = ir.bonds.find((b) => b.name === "A");
    expect(a?.schedule_model_type).toBeNull();
    expect(a?.schedule_speed_low).toBeNull();
    expect(a?.schedule_speed_high).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// OA5: Account category is always a valid schema enum value
// ---------------------------------------------------------------------------

describe("OA5: account_category emits only valid AccountCategory enum values", () => {
  const VALID_CATEGORIES = new Set([
    "RESERVE", "PREFUNDING", "REVOLVING", "PAYMENT", "SPREAD_ACCOUNT",
  ]);

  function accountBlock(name: string): ReturnType<typeof makeMockBlock> {
    return makeMockBlock("account_target", {
      ACCOUNT_TYPE: name,
      INITIAL_MODE: "PCT_STACK",
      INITIAL_AMT: 0,
    });
  }

  it("standard category names pass through unchanged", () => {
    for (const cat of VALID_CATEGORIES) {
      const ws = makeWorkspace([
        paySequentialBlock("CASH", [accountBlock(cat)]),
        paySequentialBlock("CASH", [residualBlock()]),
      ]);
      const ir = run(ws);
      const acct = ir.accounts?.find((a) => a.name === cat);
      expect(acct?.account_category).toBe(cat);
    }
  });

  it("non-standard source-vocabulary names fall through to RESERVE (documented default)", () => {
    // OA5: CAP_INTEREST, EXPENSE, SWAP_HEDGE, YIELD_SUPPLEMENT are in
    // FEE_SOURCE_OPTIONS but not valid AccountCategory values.
    // _canonicalAccountCategory maps them all to RESERVE (the documented
    // fallback for unrecognised names — these are source labels, not
    // structural account categories). Assert the specific mapping so a
    // future change to the fallback is caught by this test.
    const expectedFallback: Record<string, string> = {
      CAP_INTEREST:     "RESERVE",
      EXPENSE:          "RESERVE",
      SWAP_HEDGE:       "RESERVE",
      YIELD_SUPPLEMENT: "RESERVE",
    };
    for (const [name, expected] of Object.entries(expectedFallback)) {
      const ws = makeWorkspace([
        paySequentialBlock("CASH", [accountBlock(name)]),
        paySequentialBlock("CASH", [residualBlock()]),
      ]);
      const ir = run(ws);
      const acct = ir.accounts?.find((a) => a.name === name);
      expect(acct).toBeDefined();
      expect(acct!.account_category).toBe(expected);
    }
  });
});
