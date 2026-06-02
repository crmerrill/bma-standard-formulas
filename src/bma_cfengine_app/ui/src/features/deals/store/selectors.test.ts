import { beforeEach, describe, expect, test } from "vitest";
import { renderHook } from "@testing-library/react";
import { useDealStore } from "./useDealStore";
import { useAccountsSelector, useBondsSelector, useRulesSelector } from "./selectors";
import type { BondDefIR, DealDefinitionIR, RuleNodeIR } from "../ir-types";

type BondDef = BondDefIR;
type DealState = DealDefinitionIR;

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

function makeRule(ruleId: string): RuleNodeIR {
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
  };
}

function makeDealFixture(): DealState {
  return {
    schema_version: "2.0.0",
    deal_name: "SDS-1 selector fixture",
    bonds: [makeBond("A1")],
    accounts: [
      {
        name: "Reserve",
        account_category: "RESERVE",
        starting_amount: 0,
        starting_pct: null,
        starting_basis: "AMOUNT",
      },
    ],
    fees: [],
    triggers: [],
    waterfall_rules: [makeRule("rule_1")],
    collateral_groups: [],
    deal_knobs: {},
  };
}

describe("store selectors (sds-1 scaffolding)", () => {
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

  test("test_per_pane_selectors_return_correct_slices_with_referential_stability", () => {
    const state = useDealStore.getState();
    const expectedBonds = state.sessions[state.activeSessionId].working_tree.bonds;
    const expectedAccounts = state.sessions[state.activeSessionId].working_tree.accounts;
    const expectedRules = state.sessions[state.activeSessionId].working_tree.waterfall_rules;

    const { result, rerender } = renderHook(() => ({
      bonds: useBondsSelector(),
      accounts: useAccountsSelector(),
      rules: useRulesSelector(),
    }));

    expect(result.current.bonds).toBe(expectedBonds);
    expect(result.current.accounts).toBe(expectedAccounts);
    expect(result.current.rules).toBe(expectedRules);
    expect(result.current.bonds[0]?.name).toBe("A1");
    expect(result.current.accounts[0]?.name).toBe("Reserve");
    expect(result.current.rules[0]?.rule_id).toBe("rule_1");

    const firstResult = result.current;
    rerender();

    expect(result.current.bonds).toBe(firstResult.bonds);
    expect(result.current.accounts).toBe(firstResult.accounts);
    expect(result.current.rules).toBe(firstResult.rules);
  });
});
