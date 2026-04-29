import { describe, expect, it } from "vitest";
import { synthesizeWorkspaceState, type IRForSynthesis } from "./irToBlocklyState";

const SIMPLE_DEAL: IRForSynthesis = {
  bonds: [
    { name: "A", coupon: 5, size_dollars: 21_201_742, size_pct: 50, pay_mode: "CASH_PAY", coupon_type: "FIXED" },
    { name: "B", coupon: 6, size_dollars: 4_240_348, size_pct: 10, pay_mode: "CASH_PAY", coupon_type: "FIXED" },
    { name: "C", coupon: 7, size_dollars: 8_480_696, size_pct: 20, pay_mode: "CASH_PAY", coupon_type: "FIXED" },
    { name: "R", tranche_type: "RESIDUAL" },
  ],
  fees: [
    // irGenerator stores `rate = amount_bps / 100`, so a 10-bps annual
    // trustee fee is rate=0.1 in IR (matches what the API returns for
    // saved Test CMO1 deals).
    { name: "TRUSTEE", basis_type: "COLLATERAL_BALANCE", rate: 0.1, frequency: "MONTHLY" },
  ],
  triggers: [
    { name: "CumLossTrigger", metric_type: "CUMULATIVE_LOSS", threshold_value: 0.05 },
  ],
  waterfall_rules: [
    { rule_id: "fee_0", rule_type: "PAY_FEE", order: 0, from_sources: ["CASH"], to_targets: ["TRUSTEE"], payment_style: "SEQUENTIAL" },
    { rule_id: "rule_1", rule_type: "PAY_INTEREST", order: 1, from_sources: ["CASH"], to_targets: ["A", "B", "C"], payment_style: "SEQUENTIAL" },
    { rule_id: "rule_2", rule_type: "PAY_PRINCIPAL", order: 2, from_sources: ["CASH"], to_targets: ["A", "B", "C"], payment_style: "PRO_RATA" },
  ],
};

describe("synthesizeWorkspaceState", () => {
  it("returns null for an IR with no synthesizable rules", () => {
    expect(synthesizeWorkspaceState({})).toBeNull();
    expect(synthesizeWorkspaceState({ waterfall_rules: [] })).toBeNull();
  });

  it("produces a top-level Blockly state with one chained block list", () => {
    const state = synthesizeWorkspaceState(SIMPLE_DEAL);
    expect(state).not.toBeNull();
    expect(state!.blocks.languageVersion).toBe(0);
    expect(state!.blocks.blocks).toHaveLength(1);
    expect(state!.blocks.blocks[0].x).toBe(80);
    expect(state!.blocks.blocks[0].y).toBe(60);
  });

  it("synthesizes a pay_fee block from a PAY_FEE rule", () => {
    const state = synthesizeWorkspaceState(SIMPLE_DEAL);
    const head = state!.blocks.blocks[0];
    expect(head.type).toBe("pay_fee");
    expect(head.fields).toMatchObject({
      PAYEE: "TRUSTEE",
      SOURCE: "COLLECTION",
      BASIS: "PCT_POOL",
      FREQ: "MONTHLY",
    });
    // rate 0.1 in IR -> AMOUNT 10 (annual bps display) per
    // irGenerator's `rate = amount / 100` convention.
    expect(head.fields?.AMOUNT).toBe(10);
  });

  it("chains rules via the next pointer in IR order", () => {
    const state = synthesizeWorkspaceState(SIMPLE_DEAL);
    const head = state!.blocks.blocks[0];
    const second = head.next?.block;
    const third = second?.next?.block;
    expect(head.type).toBe("pay_fee");
    expect(second?.type).toBe("pay_sequential");
    expect(third?.type).toBe("pay_pro_rata");
  });

  it("synthesizes a pay_sequential block with bond_target children for PAY_INTEREST", () => {
    const state = synthesizeWorkspaceState(SIMPLE_DEAL);
    const seq = state!.blocks.blocks[0].next!.block;
    expect(seq.type).toBe("pay_sequential");
    expect(seq.fields).toMatchObject({
      PAY_TYPE: "INTEREST",
      SOURCE: "COLLECTION",
      LIMIT: "UNTIL_ZERO",
      MAX_PAY: 0,
    });
    const targetA = seq.inputs?.TARGETS?.block;
    expect(targetA?.type).toBe("bond_target");
    expect(targetA?.fields).toMatchObject({
      NAME: "A",
      BOND_TYPE: "FIXED",
      PAY_MODE: "CASH_PAY",
      FACE_AMT: 21_201_742,
      SIZE_PCT_POOL: 50,
      COUPON: 5,
    });
    const targetB = targetA?.next?.block;
    const targetC = targetB?.next?.block;
    expect(targetB?.fields?.NAME).toBe("B");
    expect(targetC?.fields?.NAME).toBe("C");
  });

  it("synthesizes a pay_pro_rata block with BALANCE basis for PRO_RATA rules", () => {
    const state = synthesizeWorkspaceState(SIMPLE_DEAL);
    const proRata = state!.blocks.blocks[0].next!.block.next!.block;
    expect(proRata.type).toBe("pay_pro_rata");
    expect(proRata.fields?.BASIS).toBe("BALANCE");
    expect(proRata.fields?.PAY_TYPE).toBe("PRINCIPAL");
  });

  it("emits a residual_target for residual bonds", () => {
    const dealWithResidual: IRForSynthesis = {
      bonds: [
        { name: "A", coupon: 5, size_dollars: 80_000_000 },
        { name: "R", tranche_type: "RESIDUAL" },
      ],
      waterfall_rules: [
        {
          rule_id: "r1",
          rule_type: "PAY_PRINCIPAL",
          order: 0,
          from_sources: ["CASH"],
          to_targets: ["A", "R"],
          payment_style: "SEQUENTIAL",
        },
      ],
    };
    const state = synthesizeWorkspaceState(dealWithResidual);
    const seq = state!.blocks.blocks[0];
    const targetA = seq.inputs?.TARGETS?.block;
    const residual = targetA?.next?.block;
    expect(residual?.type).toBe("residual_target");
    expect(residual?.fields?.NAME).toBe("R");
  });

  it("wraps trigger-gated rules in a trigger_wrapper", () => {
    const dealWithTrigger: IRForSynthesis = {
      bonds: [{ name: "A", coupon: 5, size_dollars: 80_000_000 }],
      triggers: [
        { name: "CumLossTrigger", metric_type: "CUMULATIVE_LOSS", threshold_value: 0.05 },
      ],
      waterfall_rules: [
        {
          rule_id: "r1",
          rule_type: "PAY_PRINCIPAL",
          order: 0,
          from_sources: ["CASH"],
          to_targets: ["A"],
          payment_style: "SEQUENTIAL",
          condition_trigger: "CumLossTrigger",
          condition_invert: false,
        },
      ],
    };
    const state = synthesizeWorkspaceState(dealWithTrigger);
    const head = state!.blocks.blocks[0];
    expect(head.type).toBe("trigger_wrapper");
    expect(head.fields).toMatchObject({
      TRIGGER_NAME: "CumLossTrigger",
      METRIC: "CUM_LOSS",
      THRESHOLD: 0.05,
    });
    expect(head.inputs?.RULES?.block.type).toBe("pay_sequential");
  });

  it("groups consecutive trigger-gated rules under one wrapper", () => {
    const deal: IRForSynthesis = {
      bonds: [
        { name: "A", coupon: 5, size_dollars: 80_000_000 },
        { name: "B", coupon: 6, size_dollars: 10_000_000 },
      ],
      triggers: [{ name: "T", metric_type: "CUMULATIVE_LOSS", threshold_value: 0.05 }],
      waterfall_rules: [
        {
          rule_id: "r1",
          rule_type: "PAY_INTEREST",
          order: 0,
          from_sources: ["CASH"],
          to_targets: ["A"],
          payment_style: "SEQUENTIAL",
          condition_trigger: "T",
        },
        {
          rule_id: "r2",
          rule_type: "PAY_PRINCIPAL",
          order: 1,
          from_sources: ["CASH"],
          to_targets: ["A", "B"],
          payment_style: "SEQUENTIAL",
          condition_trigger: "T",
        },
      ],
    };
    const state = synthesizeWorkspaceState(deal);
    const head = state!.blocks.blocks[0];
    expect(head.type).toBe("trigger_wrapper");
    const innerHead = head.inputs?.RULES?.block;
    const innerSecond = innerHead?.next?.block;
    expect(innerHead?.type).toBe("pay_sequential");
    expect(innerSecond?.type).toBe("pay_sequential");
    expect(innerSecond?.fields?.PAY_TYPE).toBe("PRINCIPAL");
  });

  it("skips unsupported rule types (PAC/TAC/Z) without crashing", () => {
    const dealWithPAC: IRForSynthesis = {
      bonds: [{ name: "A", coupon: 5, size_dollars: 80_000_000 }],
      waterfall_rules: [
        {
          rule_id: "fee0",
          rule_type: "PAY_FEE",
          order: 0,
          from_sources: ["CASH"],
          to_targets: ["TRUSTEE"],
          payment_style: "SEQUENTIAL",
        },
        {
          rule_id: "pac1",
          rule_type: "PAY_PRINCIPAL_PAC_SCHEDULE",
          order: 1,
          from_sources: ["CASH"],
          to_targets: ["A"],
        },
      ],
      fees: [
        { name: "TRUSTEE", basis_type: "COLLATERAL_BALANCE", rate: 0.001, frequency: "MONTHLY" },
      ],
    };
    const state = synthesizeWorkspaceState(dealWithPAC);
    expect(state).not.toBeNull();
    // Only the fee rule synthesizes; the PAC rule is skipped.
    expect(state!.blocks.blocks[0].type).toBe("pay_fee");
    expect(state!.blocks.blocks[0].next).toBeUndefined();
  });

  it("emits a split_account block for SPLIT_CASH rules", () => {
    const deal: IRForSynthesis = {
      waterfall_rules: [
        {
          rule_id: "split_1",
          rule_type: "SPLIT_CASH",
          order: 0,
          from_sources: ["CASH"],
          to_targets: ["PRIN_BUCKET", "INT_BUCKET"],
          target_weights: [0.5, 0.5],
        },
      ],
    };
    const state = synthesizeWorkspaceState(deal);
    expect(state!.blocks.blocks[0].type).toBe("split_account");
    expect(state!.blocks.blocks[0].fields).toMatchObject({
      OUT_1: "PRIN_BUCKET",
      OUT_2: "INT_BUCKET",
    });
  });
});
