import { beforeEach, describe, expect, test } from "vitest";
import { useDealStore } from "./useDealStore";
import type { BondDefIR, DealDefinitionIR, RuleNodeIR } from "../ir-types";

type DealState = DealDefinitionIR;
type BondDef = BondDefIR;
type RuleWithPriority = RuleNodeIR & { priority: number };

function makeBond(name: string): BondDef {
  return {
    name,
    kind: "CASH_PAY",
    group_id: null,
    coupon: 0.05,
    notional_pct_of_collateral: 10,
    notional: 1_000_000,
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
    relations: [],
    z_accrual_enabled: false,
    z_release_trigger: null,
  };
}

function makeRule(ruleId: string, priority = 1): RuleWithPriority {
  return {
    rule_id: ruleId,
    rule_type: "PAY_PRINCIPAL",
    order: 1,
    from_sources: ["ACT_PRIN"],
    to_targets: ["A1"],
    payment_style: "SEQUENTIAL",
    max_amount_fixed: null,
    condition_trigger: null,
    condition_invert: false,
    priority,
  };
}

function makeDealFixture(): DealState {
  return {
    schema_version: "2.0.0",
    deal_name: "SDS-1 actions fixture",
    bonds: [],
    accounts: [],
    fees: [],
    triggers: [],
    waterfall_rules: [makeRule("rule_seed")],
    collateral_groups: [],
    deal_knobs: {},
  };
}

describe("deal actions (sds-1 scaffolding)", () => {
  beforeEach(() => {
    useDealStore.setState(useDealStore.getInitialState(), true);

    const activeSessionId = useDealStore.getState().activeSessionId;
    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        [activeSessionId]: {
          ...state.sessions[activeSessionId],
          working_tree: makeDealFixture(),
        },
      },
    }));
  });

  test("test_addBond_updates_active_session_working_tree", () => {
    const { activeSessionId, dispatch } = useDealStore.getState();
    const before = useDealStore.getState().sessions[activeSessionId].working_tree.bonds.length;

    dispatch({ type: "addBond", payload: makeBond("A_NEW") });

    const state = useDealStore.getState();
    const bonds = state.sessions[state.activeSessionId].working_tree.bonds;

    expect(bonds).toHaveLength(before + 1);
    expect(bonds[bonds.length - 1]?.name).toBe("A_NEW");
    expect(Object.keys(state.sessions)).toEqual(["main"]);
    expect(state.activeSessionId).toBe("main");
  });

  test("test_setBondKind_and_setRulePriority_dispatch_correctly", () => {
    const { activeSessionId, dispatch } = useDealStore.getState();

    dispatch({ type: "addBond", payload: makeBond("A_KIND_TEST") });
    dispatch({
      type: "setBondKind",
      payload: { bond_id: "A_KIND_TEST", kind: "PAC" },
    });

    const bond = useDealStore
      .getState()
      .sessions[activeSessionId]
      .working_tree.bonds.find((candidate) => candidate.name === "A_KIND_TEST");

    expect(bond?.kind).toBe("PAC");

    dispatch({
      type: "setRulePriority",
      payload: { rule_id: "rule_seed", priority: 5 },
    });

    const rule = useDealStore
      .getState()
      .sessions[activeSessionId]
      .working_tree.waterfall_rules.find((candidate) => candidate.rule_id === "rule_seed") as
      | RuleWithPriority
      | undefined;

    expect(rule?.priority).toBe(5);
  });

  test("test_unknown_action_type_fails_compile_via_never_guard", () => {
    const { activeSessionId, dispatch } = useDealStore.getState();
    const before = useDealStore.getState().sessions[activeSessionId].working_tree;

    // This assertion is compile-time (tsc/vitest --typecheck), not runtime.
    // @ts-expect-error - invalid action type must violate DealAction union.
    expect(() => dispatch({ type: "not-a-real-action", payload: {} })).not.toThrow();

    const after = useDealStore.getState().sessions[activeSessionId].working_tree;
    expect(after).toBe(before);
  });
});
