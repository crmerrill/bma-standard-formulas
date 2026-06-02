import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, test, vi } from "vitest";

import type { DealDefinitionIR, RuleNodeIR } from "../ir-types";

type DealState = DealDefinitionIR;

type CompileModule = {
  compileToIR: (working_tree: DealState) => string;
};

const THIS_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(THIS_DIR, "../../../../../../..");
const FNR_FIXTURE_DEAL_JSON = resolve(REPO_ROOT, "tests/fixtures/fnr_2006_018/deal.json");
const FIELD_ORDER_JSON_PATH = resolve(
  THIS_DIR,
  "../field_order.json",
);

const DEAL_DEFINITION_TOP_LEVEL_FIELDS = [
  "schema_version",
  "deal_name",
  "description",
  "origination_date",
  "settlement_date",
  "series_id",
  "discount_factor_pct",
  "deal_state_trigger",
  "initial_deal_state",
  "bonds",
  "accounts",
  "fees",
  "triggers",
  "calculations",
  "waterfall_rules",
  "collateral_groups",
  "deal_knobs",
] as const;

async function loadCompileModule(): Promise<CompileModule> {
  const mod = (await import("./compile")) as Partial<CompileModule>;
  expect(typeof mod.compileToIR).toBe("function");
  return mod as CompileModule;
}

function makeBond(name: string, notional: number): DealState["bonds"][number] {
  return {
    name,
    kind: "CASH_PAY",
    group_id: null,
    coupon: 6.0,
    notional_pct_of_collateral: 10.0,
    notional,
    is_bond: true,
    is_pseudo: false,
    coupon_type: "FIXED",
    index_name: null,
    margin: null,
    pay_mode: "CASH_PAY",
    schedule_model_type: null,
    schedule_priority_tier: null,
    schedule_depends_on: null,
    schedule_speed_low: null,
    schedule_speed_high: null,
    schedule_custom_vector: null,
    schedule_contract: [],
    schedule_tolerance_bps: null,
    schedule_derivation: null,
    relations: [],
    z_accrual_enabled: false,
    z_release_trigger: null,
    nla_starting_balance: null,
    required_subordination_pct: null,
    seniority: null,
  };
}

function makeRule(
  ruleId: string,
  order: number,
  fromSource: string,
  toTarget: string,
): RuleNodeIR {
  return {
    rule_id: ruleId,
    rule_type: "PAY_PRINCIPAL",
    order,
    from_sources: [fromSource],
    to_targets: [toTarget],
    payment_style: "SEQUENTIAL",
    max_amount_fixed: null,
    condition_trigger: null,
    condition_invert: false,
    group_id: null,
    cap_mode: null,
    coverage_mode: "NORMAL",
    target_weights: null,
  };
}

function makeWorkingTree(overrides: Record<string, unknown> = {}): DealState {
  const base = {
    schema_version: "2.0.0",
    deal_name: "sds-3 compile fixture",
    description: "fixture",
    origination_date: null,
    settlement_date: null,
    series_id: null,
    discount_factor_pct: 0.0,
    deal_state_trigger: null,
    initial_deal_state: "REVOLVING",
    bonds: [makeBond("B1", 1000000.0)],
    accounts: [],
    fees: [],
    triggers: [],
    calculations: [],
    waterfall_rules: [makeRule("r1", 0, "ACT_PRIN", "B1")],
    collateral_groups: [],
    deal_knobs: {},
  };

  return { ...base, ...overrides } as DealState;
}

function parseFieldOrderManifest(): Record<string, string[]> {
  expect(existsSync(FIELD_ORDER_JSON_PATH)).toBe(true);
  return JSON.parse(readFileSync(FIELD_ORDER_JSON_PATH, "utf-8")) as Record<string, string[]>;
}

function collectFragmentedTargetRuns(rules: RuleNodeIR[]): string[][] {
  const runs: string[][] = [];
  let idx = 0;
  while (idx < rules.length) {
    const first = rules[idx];
    if (!first) {
      idx += 1;
      continue;
    }

    const firstTargets = first.to_targets ?? [];
    if (firstTargets.length !== 1) {
      idx += 1;
      continue;
    }

    const runKey = `${first.rule_type}|${JSON.stringify(first.from_sources ?? [])}`;
    const targets = [firstTargets[0]];
    let cursor = idx + 1;
    while (cursor < rules.length) {
      const next = rules[cursor];
      if (!next) break;
      const nextTargets = next.to_targets ?? [];
      const nextKey = `${next.rule_type}|${JSON.stringify(next.from_sources ?? [])}`;
      if (nextTargets.length !== 1 || nextKey !== runKey) {
        break;
      }
      targets.push(nextTargets[0]);
      cursor += 1;
    }

    if (targets.length >= 3) {
      runs.push(targets);
    }
    idx = cursor;
  }
  return runs;
}

describe("sds-3 compile canonical serialization", () => {
  test("test_compile_returns_string_with_pydantic_field_order", async () => {
    const { compileToIR } = await loadCompileModule();
    const compiled = compileToIR(makeWorkingTree());

    expect(typeof compiled).toBe("string");
    const keys = Object.keys(JSON.parse(compiled) as Record<string, unknown>);
    expect(keys.slice(0, DEAL_DEFINITION_TOP_LEVEL_FIELDS.length)).toEqual(
      DEAL_DEFINITION_TOP_LEVEL_FIELDS,
    );
  });

  test("test_compile_uses_field_order_manifest_for_every_top_level_dealdef_field", async () => {
    const { compileToIR } = await loadCompileModule();
    const manifest = parseFieldOrderManifest();

    const manifestDealOrder = manifest.DealDefinition;
    expect(Array.isArray(manifestDealOrder)).toBe(true);
    expect(manifestDealOrder).toEqual(DEAL_DEFINITION_TOP_LEVEL_FIELDS);

    const compiled = compileToIR(makeWorkingTree());
    const keys = Object.keys(JSON.parse(compiled) as Record<string, unknown>);
    expect(keys.slice(0, manifestDealOrder.length)).toEqual(manifestDealOrder);

    for (const field of DEAL_DEFINITION_TOP_LEVEL_FIELDS) {
      expect(manifestDealOrder).toContain(field);
      expect(keys).toContain(field);
    }
  });

  test("test_compile_fails_when_model_missing_from_field_order_manifest", async () => {
    vi.resetModules();
    vi.doMock("../field_order.json", () => ({
      default: {
        DealDefinition: DEAL_DEFINITION_TOP_LEVEL_FIELDS,
      },
    }));

    try {
      const { compileToIR } = (await import("./compile")) as CompileModule;
      expect(() => compileToIR(makeWorkingTree())).toThrow(
        /field[_ -]?order|manifest|missing/i,
      );
    } finally {
      vi.doUnmock("../field_order.json");
      vi.resetModules();
    }
  });

  test("test_compile_preserves_list_order_no_sort", async () => {
    const { compileToIR } = await loadCompileModule();
    const workingTree = makeWorkingTree({
      bonds: [
        makeBond("TRANCHE_C", 3000000.0),
        makeBond("TRANCHE_B", 2000000.0),
        makeBond("TRANCHE_A", 1000000.0),
      ],
      waterfall_rules: [
        makeRule("r_c", 0, "ACT_PRIN", "TRANCHE_C"),
        makeRule("r_b", 1, "ACT_PRIN", "TRANCHE_B"),
        makeRule("r_a", 2, "ACT_PRIN", "TRANCHE_A"),
      ],
    });

    const compiled = compileToIR(workingTree);
    const parsed = JSON.parse(compiled) as { bonds: Array<{ name: string }> };
    expect(parsed.bonds.map((bond) => bond.name)).toEqual([
      "TRANCHE_C",
      "TRANCHE_B",
      "TRANCHE_A",
    ]);
  });

  test("test_compile_float_enum_null_formatting_matches_pydantic", async () => {
    const { compileToIR } = await loadCompileModule();
    const workingTree = makeWorkingTree({
      bonds: [
        {
          ...makeBond("A_FLOAT", 1.0),
          coupon_type: "FIXED",
          margin: null,
          schedule_model_type: null,
        },
      ],
    });

    const compiled = compileToIR(workingTree);
    expect(compiled).toContain('"coupon_type": "FIXED"');
    expect(compiled).toContain('"margin": null');
    expect(compiled).toContain('"schedule_model_type": null');
    expect(compiled).toContain('"notional": 1.0');
    expect(compiled).toContain('"discount_factor_pct": 0.0');
    expect(compiled).not.toMatch(/\d+e[+-]?\d+/i);
  });

  test("test_compile_does_not_auto_canonicalize_fragmented_multi_target_rules", async () => {
    const { compileToIR } = await loadCompileModule();

    expect(existsSync(FNR_FIXTURE_DEAL_JSON)).toBe(true);
    const sourceWorkingTree = JSON.parse(readFileSync(FNR_FIXTURE_DEAL_JSON, "utf-8")) as DealState;
    const sourceRuns = collectFragmentedTargetRuns(sourceWorkingTree.waterfall_rules ?? []);
    expect(sourceRuns.length).toBeGreaterThan(0);

    const compiled = compileToIR(sourceWorkingTree);
    const parsed = JSON.parse(compiled) as { waterfall_rules: RuleNodeIR[] };
    const compiledRuns = collectFragmentedTargetRuns(parsed.waterfall_rules ?? []);
    expect(compiledRuns).toEqual(sourceRuns);
  });
});
