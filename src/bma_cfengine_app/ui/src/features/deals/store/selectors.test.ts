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

  test("test_per_pane_selectors_unchanged_when_other_slices_update", () => {
    // R1 sds-1 Minor #3: prove referential stability holds when an unrelated
    // slice changes (e.g., bonds reference must remain stable when only
    // accounts is mutated). zustand v5's default selector equality is
    // Object.is on the selector return; updating accounts produces a new
    // working_tree object reference, but each selector's slice reference
    // (bonds, rules) must be reused so consuming components do not re-render.
    const { result, rerender } = renderHook(() => ({
      bonds: useBondsSelector(),
      accounts: useAccountsSelector(),
      rules: useRulesSelector(),
    }));

    const bondsBefore = result.current.bonds;
    const rulesBefore = result.current.rules;
    const accountsBefore = result.current.accounts;

    // Mutate accounts only (a non-bonds, non-rules update).
    const sid = useDealStore.getState().activeSessionId;
    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        [sid]: {
          ...state.sessions[sid],
          working_tree: {
            ...state.sessions[sid].working_tree,
            accounts: [
              ...state.sessions[sid].working_tree.accounts,
              {
                name: "Reserve2",
                account_category: "RESERVE",
                starting_amount: 0,
                starting_pct: null,
                starting_basis: "AMOUNT",
              },
            ],
          },
        },
      },
    }));

    rerender();

    // bonds and rules slice references must be stable across the unrelated
    // mutation; accounts must be a new reference.
    expect(result.current.bonds).toBe(bondsBefore);
    expect(result.current.rules).toBe(rulesBefore);
    expect(result.current.accounts).not.toBe(accountsBefore);
    expect(result.current.accounts).toHaveLength(2);
  });
});
