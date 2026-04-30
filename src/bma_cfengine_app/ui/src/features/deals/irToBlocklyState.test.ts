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

  describe("FNR-shape rule and bond coverage", () => {
    it("emits a residual_target for PAY_RESIDUAL rules with PAY_TYPE=REMAINING", () => {
      const deal: IRForSynthesis = {
        bonds: [
          { name: "A", coupon: 5, size_dollars: 80_000_000 },
          { name: "R", tranche_type: "RESIDUAL", is_pseudo: true },
        ],
        waterfall_rules: [
          {
            rule_id: "r_resid",
            rule_type: "PAY_RESIDUAL",
            order: 0,
            from_sources: ["INT_CASH"],
            to_targets: ["R"],
            payment_style: "SEQUENTIAL",
          },
        ],
      };
      const state = synthesizeWorkspaceState(deal);
      const seq = state!.blocks.blocks[0];
      expect(seq.type).toBe("pay_sequential");
      expect(seq.fields?.PAY_TYPE).toBe("REMAINING");
      expect(seq.inputs?.TARGETS?.block.type).toBe("residual_target");
    });

    it("preserves the PAC schedule and tranche_type on bond data fields", () => {
      const deal: IRForSynthesis = {
        bonds: [
          {
            name: "PA",
            tranche_type: "PAC",
            tranche_behavior: "PAC",
            coupon: 5.5,
            size_dollars: 33_710_000,
            coupon_type: "FIXED",
            schedule_contract: [
              { period: 1, target_balance: 33_710_000 },
              { period: 12, target_balance: 30_000_000 },
            ],
            support_tranches: ["WA", "WB", "PO"],
          },
        ],
        waterfall_rules: [
          {
            rule_id: "r_prin_PA",
            rule_type: "PAY_PRINCIPAL",
            order: 0,
            from_sources: ["PRIN_CASH"],
            to_targets: ["PA"],
            payment_style: "SEQUENTIAL",
          },
        ],
      };
      const state = synthesizeWorkspaceState(deal);
      const target = state!.blocks.blocks[0].inputs?.TARGETS?.block;
      expect(target?.type).toBe("bond_target");
      expect(target?.fields?.NAME).toBe("PA");
      const data = JSON.parse(target!.data!) as Record<string, unknown>;
      expect(data.tranche_type).toBe("PAC");
      expect(data.tranche_behavior).toBe("PAC");
      expect(data.support_tranches).toEqual(["WA", "WB", "PO"]);
      expect((data.schedule_contract as unknown[]).length).toBe(2);
    });

    it("preserves Z-bond accrual flags on bond data", () => {
      const deal: IRForSynthesis = {
        bonds: [
          {
            name: "Z",
            tranche_type: "Z_BOND",
            tranche_behavior: "Z",
            coupon: 5.5,
            size_dollars: 5_000_000,
            pay_mode: "PIK",
            z_accrual_enabled: true,
            supported_by_tranches: ["TA", "TB"],
          },
        ],
        waterfall_rules: [
          {
            rule_id: "r_prin_Z",
            rule_type: "PAY_PRINCIPAL",
            order: 0,
            from_sources: ["PRIN_CASH"],
            to_targets: ["Z"],
            payment_style: "SEQUENTIAL",
          },
        ],
      };
      const state = synthesizeWorkspaceState(deal);
      const target = state!.blocks.blocks[0].inputs?.TARGETS?.block;
      expect(target?.fields?.PAY_MODE).toBe("PIK");
      const data = JSON.parse(target!.data!) as Record<string, unknown>;
      expect(data.z_accrual_enabled).toBe(true);
      expect(data.supported_by_tranches).toEqual(["TA", "TB"]);
    });

    it("preserves IO tracks_bonds field on notional bonds", () => {
      const deal: IRForSynthesis = {
        bonds: [
          {
            name: "DI",
            tranche_type: "IO",
            tranche_behavior: "SEQUENTIAL",
            coupon: 5.5,
            size_dollars: 11_925_424,
            tracks_bonds: { balance: ["DO"] },
          },
        ],
        waterfall_rules: [
          {
            rule_id: "r_int_DI",
            rule_type: "PAY_INTEREST",
            order: 0,
            from_sources: ["INT_CASH"],
            to_targets: ["DI"],
            payment_style: "SEQUENTIAL",
          },
        ],
      };
      const state = synthesizeWorkspaceState(deal);
      const target = state!.blocks.blocks[0].inputs?.TARGETS?.block;
      const data = JSON.parse(target!.data!) as Record<string, unknown>;
      expect(data.tracks_bonds).toEqual({ balance: ["DO"] });
    });

    it("preserves cap_mode=NONE on cleanup rules", () => {
      const deal: IRForSynthesis = {
        bonds: [{ name: "PA", coupon: 5.5, size_dollars: 33_710_000 }],
        waterfall_rules: [
          {
            rule_id: "r_prin_PA_uncapped",
            rule_type: "PAY_PRINCIPAL",
            order: 0,
            from_sources: ["PRIN_CASH"],
            to_targets: ["PA"],
            payment_style: "SEQUENTIAL",
            cap_mode: "NONE",
          },
        ],
      };
      const state = synthesizeWorkspaceState(deal);
      const block = state!.blocks.blocks[0];
      const data = JSON.parse(block.data!) as Record<string, unknown>;
      expect(data.cap_mode).toBe("NONE");
    });

    it("strips GROUP_<id>_ prefix from source tokens for the UI dropdown", () => {
      const deal: IRForSynthesis = {
        collateral_groups: [{ group_id: "GROUP_1" }],
        bonds: [
          {
            name: "PA", coupon: 5.5, size_dollars: 33_710_000,
            group_id: "GROUP_1",
          },
        ],
        waterfall_rules: [
          {
            rule_id: "r_int_PA",
            rule_type: "PAY_INTEREST",
            order: 0,
            group_id: "GROUP_1",
            from_sources: ["GROUP_GROUP_1_INT_CASH"],
            to_targets: ["PA"],
            payment_style: "SEQUENTIAL",
          },
        ],
      };
      const state = synthesizeWorkspaceState(deal);
      const block = state!.blocks.blocks[0];
      // GROUP_GROUP_1_INT_CASH -> INT_CASH -> "INT_COLLECTION" UI value.
      expect(block.fields?.SOURCE).toBe("INT_COLLECTION");
    });

    it("partitions multi-group rules into one chain per group at distinct x positions", () => {
      const deal: IRForSynthesis = {
        collateral_groups: [
          { group_id: "GROUP_1" },
          { group_id: "GROUP_2" },
        ],
        bonds: [
          { name: "PA", coupon: 5.5, size_dollars: 33_710_000, group_id: "GROUP_1" },
          { name: "BA", coupon: 5.5, size_dollars: 100_000_000, group_id: "GROUP_2" },
        ],
        waterfall_rules: [
          {
            rule_id: "r_int_PA",
            rule_type: "PAY_INTEREST",
            order: 0,
            group_id: "GROUP_1",
            from_sources: ["INT_CASH"],
            to_targets: ["PA"],
            payment_style: "SEQUENTIAL",
          },
          {
            rule_id: "r_int_BA",
            rule_type: "PAY_INTEREST",
            order: 1,
            group_id: "GROUP_2",
            from_sources: ["INT_CASH"],
            to_targets: ["BA"],
            payment_style: "SEQUENTIAL",
          },
        ],
      };
      const state = synthesizeWorkspaceState(deal);
      expect(state!.blocks.blocks).toHaveLength(2);
      const [g1Head, g2Head] = state!.blocks.blocks;
      // Distinct x positions so the canvas reads as two columns.
      expect(g1Head.x).toBeDefined();
      expect(g2Head.x).toBeDefined();
      expect(g2Head.x).not.toBe(g1Head.x);
      // Each chain's top block carries its group_id on data.
      const g1Data = JSON.parse(g1Head.data!) as Record<string, unknown>;
      const g2Data = JSON.parse(g2Head.data!) as Record<string, unknown>;
      expect(g1Data.group_id).toBe("GROUP_1");
      expect(g2Data.group_id).toBe("GROUP_2");
    });

    it("smoke-test: synthesizes the full FNR 2006-018 combined IR shape", () => {
      // Shrunken FNR-like shape: one PAC, one Z (PIK), one Sequential
      // (Group 2), residuals, all the rule types.
      const deal: IRForSynthesis = {
        collateral_groups: [
          { group_id: "GROUP_1" },
          { group_id: "GROUP_2" },
        ],
        bonds: [
          {
            name: "PA",
            tranche_type: "PAC",
            tranche_behavior: "PAC",
            coupon: 5.5,
            size_dollars: 33_710_000,
            group_id: "GROUP_1",
            schedule_contract: [{ period: 1, target_balance: 33_710_000 }],
            support_tranches: ["WA"],
          },
          {
            name: "Z",
            tranche_type: "Z_BOND",
            tranche_behavior: "Z",
            coupon: 5.5,
            size_dollars: 5_000_000,
            pay_mode: "PIK",
            group_id: "GROUP_1",
            z_accrual_enabled: true,
            supported_by_tranches: ["TA"],
          },
          {
            name: "BA",
            coupon: 5.5,
            size_dollars: 100_000_000,
            group_id: "GROUP_2",
          },
          { name: "R", tranche_type: "RESIDUAL", is_pseudo: true },
        ],
        waterfall_rules: [
          {
            rule_id: "r_int_PA",
            rule_type: "PAY_INTEREST",
            order: 0,
            group_id: "GROUP_1",
            from_sources: ["INT_CASH"],
            to_targets: ["PA"],
            payment_style: "SEQUENTIAL",
          },
          {
            rule_id: "r_prin_PA",
            rule_type: "PAY_PRINCIPAL",
            order: 1,
            group_id: "GROUP_1",
            from_sources: ["PRIN_CASH"],
            to_targets: ["PA"],
            payment_style: "SEQUENTIAL",
            cap_mode: "PLANNED",
          },
          {
            rule_id: "r_supp_split",
            rule_type: "SPLIT_CASH",
            order: 2,
            group_id: "GROUP_1",
            from_sources: ["PRIN_CASH"],
            to_targets: ["WAWG_BUCKET", "PO_BUCKET"],
            target_weights: [0.95, 0.05],
          },
          {
            rule_id: "r_resid_g1",
            rule_type: "PAY_RESIDUAL",
            order: 3,
            group_id: "GROUP_1",
            from_sources: ["PRIN_CASH"],
            to_targets: ["R"],
            payment_style: "SEQUENTIAL",
          },
          {
            rule_id: "r_int_BA",
            rule_type: "PAY_INTEREST",
            order: 4,
            group_id: "GROUP_2",
            from_sources: ["INT_CASH"],
            to_targets: ["BA"],
            payment_style: "SEQUENTIAL",
          },
        ],
      };
      const state = synthesizeWorkspaceState(deal);
      expect(state).not.toBeNull();
      // 2 groups -> 2 top-level chains.
      expect(state!.blocks.blocks).toHaveLength(2);
      // Group 1 chain: 4 rules linked by `next`.
      const g1 = state!.blocks.blocks[0];
      let count = 0;
      let cursor: BlocklyBlock | undefined = g1;
      while (cursor) {
        count += 1;
        cursor = cursor.next?.block;
      }
      expect(count).toBe(4);
      // Group 1 PA bond_target carries the PAC schedule on data.
      const paBlock = g1.inputs?.TARGETS?.block;
      const paData = JSON.parse(paBlock!.data!) as Record<string, unknown>;
      expect(paData.tranche_type).toBe("PAC");
      expect((paData.schedule_contract as unknown[]).length).toBeGreaterThan(0);
      // Group 2 chain: 1 rule.
      const g2 = state!.blocks.blocks[1];
      expect(g2.next).toBeUndefined();
    });
  });
});

// Avoid a top-of-file `import type` cycle by referencing the type
// inline where the smoke test needs it.
type BlocklyBlock = NonNullable<
  ReturnType<typeof synthesizeWorkspaceState>
>["blocks"]["blocks"][number];
