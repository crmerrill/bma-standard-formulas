import { beforeEach, describe, expect, test } from "vitest";
import { useDealStore } from "./useDealStore";
import type { BondDefIR, DealDefinitionIR, RuleNodeIR } from "../ir-types";
import { mkBranchName } from "./session";
import type { TemporalState } from "./session";

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

function makeCanonicalizableRule(
  ruleId: string,
  order: number,
  target: string,
  overrides: Partial<RuleNodeIR> = {},
): RuleNodeIR {
  return {
    rule_id: ruleId,
    rule_type: "PAY_PRINCIPAL",
    order,
    from_sources: ["ACT_PRIN"],
    to_targets: [target],
    payment_style: "SEQUENTIAL",
    max_amount_fixed: null,
    max_amount_expr: null,
    condition_trigger: null,
    condition_invert: false,
    condition_expr: null,
    group_id: null,
    cap_mode: null,
    coverage_mode: "NORMAL",
    allow_negative_source: false,
    target_weights: null,
    ...overrides,
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

function dispatchCanonicalizeConsolidateRuleRun(start_index: number, end_index: number): void {
  const dispatch = useDealStore.getState().dispatch as unknown as (action: {
    type: string;
    payload: Record<string, unknown>;
  }) => void;
  dispatch({
    type: "canonicalizeConsolidateRuleRun",
    payload: { start_index, end_index },
  });
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

  test("test_dispatch_rejects_unknown_action_type_via_discriminated_union", () => {
    const { activeSessionId, dispatch } = useDealStore.getState();
    const before = useDealStore.getState().sessions[activeSessionId].working_tree;

    // The @ts-expect-error directive proves at compile time that the
    // DealAction discriminated union rejects unknown `type` values; tsc -b
    // (and vitest --typecheck) flag any line where the directive is no
    // longer needed. At runtime the dispatcher's never-guard default branch
    // returns the empty partial state object, leaving the working_tree
    // referentially unchanged — proven by the toBe() assertion below.
    // @ts-expect-error - invalid action type must violate DealAction union.
    expect(() => dispatch({ type: "not-a-real-action", payload: {} })).not.toThrow();

    const after = useDealStore.getState().sessions[activeSessionId].working_tree;
    expect(after).toBe(before);
  });

  test("test_action_dispatch_only_mutates_active_session_not_siblings", () => {
    // R1 sds-1 Minor #2: prove inactive-session isolation by seeding a
    // sibling session, switching activeSessionId, dispatching, and asserting
    // the inactive session is referentially unchanged.
    const siblingId = "ephemeral_sibling_for_isolation_test";
    const siblingTree = makeDealFixture();
    siblingTree.bonds = [makeBond("SIBLING_PRESEEDED")];

    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        [siblingId]: {
          session_id: siblingId,
          branch_name: mkBranchName("ai/turn-isolation-test"),
          base_sha: "",
          working_tree: siblingTree,
          validation_target: "self",
          commit_target: mkBranchName("ai/turn-isolation-test"),
          zundo_history: {
            getState: () => ({ pastStates: [], futureStates: [] }),
            pause: () => {},
            resume: () => {},
            handleSet: () => {},
            undo: () => {},
            redo: () => {},
          } satisfies TemporalState<DealState>,
          ui_role: "preview",
          diagnostics: [],
        },
      },
    }));

    const siblingTreeBefore = useDealStore.getState().sessions[siblingId].working_tree;
    const mainTreeBefore = useDealStore.getState().sessions.main.working_tree;

    // Dispatch with main as the active session (default).
    useDealStore.getState().dispatch({ type: "addBond", payload: makeBond("MAIN_NEW") });

    const stateAfter = useDealStore.getState();
    expect(stateAfter.sessions[siblingId].working_tree).toBe(siblingTreeBefore);
    expect(stateAfter.sessions.main.working_tree).not.toBe(mainTreeBefore);
    expect(
      stateAfter.sessions[siblingId].working_tree.bonds.find((b) => b.name === "MAIN_NEW"),
    ).toBeUndefined();
    expect(
      stateAfter.sessions.main.working_tree.bonds.find((b) => b.name === "MAIN_NEW"),
    ).toBeDefined();

    // Now switch to the sibling and dispatch; main must be untouched.
    useDealStore.setState({ activeSessionId: siblingId });
    const mainTreeBeforeSiblingDispatch = useDealStore.getState().sessions.main.working_tree;
    useDealStore.getState().dispatch({ type: "addBond", payload: makeBond("SIBLING_NEW") });
    expect(useDealStore.getState().sessions.main.working_tree).toBe(mainTreeBeforeSiblingDispatch);
    expect(
      useDealStore
        .getState()
        .sessions[siblingId]
        .working_tree.bonds.find((b) => b.name === "SIBLING_NEW"),
    ).toBeDefined();
  });

  test("test_canonicalize_consolidate_rule_run_replaces_rules_on_active_session", () => {
    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        main: {
          ...state.sessions.main,
          working_tree: {
            ...state.sessions.main.working_tree,
            waterfall_rules: [
              makeCanonicalizableRule("r1", 0, "A1"),
              makeCanonicalizableRule("r2", 1, "A2"),
              makeCanonicalizableRule("r3", 2, "A3"),
            ],
          },
        },
      },
    }));

    dispatchCanonicalizeConsolidateRuleRun(0, 2);

    const rules = useDealStore.getState().sessions.main.working_tree.waterfall_rules;
    expect(rules).toHaveLength(1);
    expect(rules[0]?.to_targets).toEqual(["A1", "A2", "A3"]);
    expect(rules[0]?.from_sources).toEqual(["ACT_PRIN"]);
    expect(rules[0]?.payment_style).toBe("SEQUENTIAL");
  });

  test("test_canonicalize_consolidate_rule_run_does_not_touch_other_sessions", () => {
    const siblingId = "ephemeral_canonicalize_sibling";
    const siblingTree = {
      ...makeDealFixture(),
      waterfall_rules: [
        makeCanonicalizableRule("s1", 0, "S1"),
        makeCanonicalizableRule("s2", 1, "S2"),
      ],
    };

    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        main: {
          ...state.sessions.main,
          working_tree: {
            ...state.sessions.main.working_tree,
            waterfall_rules: [
              makeCanonicalizableRule("m1", 0, "M1"),
              makeCanonicalizableRule("m2", 1, "M2"),
            ],
          },
        },
        [siblingId]: {
          session_id: siblingId,
          branch_name: mkBranchName("ai/turn-canonicalize-isolation"),
          base_sha: "",
          working_tree: siblingTree,
          validation_target: "self",
          commit_target: mkBranchName("ai/turn-canonicalize-isolation"),
          zundo_history: {
            getState: () => ({ pastStates: [], futureStates: [] }),
            pause: () => {},
            resume: () => {},
            handleSet: () => {},
            undo: () => {},
            redo: () => {},
          } satisfies TemporalState<DealState>,
          ui_role: "preview",
          diagnostics: [],
        },
      },
      activeSessionId: "main",
    }));

    const siblingBefore = useDealStore.getState().sessions[siblingId].working_tree;
    dispatchCanonicalizeConsolidateRuleRun(0, 1);

    const stateAfter = useDealStore.getState();
    expect(stateAfter.sessions[siblingId].working_tree).toBe(siblingBefore);
    expect(stateAfter.sessions.main.working_tree.waterfall_rules).toHaveLength(1);
  });

  test("test_canonicalize_consolidate_rule_run_increments_dispatch_revision", () => {
    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        main: {
          ...state.sessions.main,
          working_tree: {
            ...state.sessions.main.working_tree,
            waterfall_rules: [
              makeCanonicalizableRule("rev1", 0, "A1"),
              makeCanonicalizableRule("rev2", 1, "A2"),
            ],
          },
        },
      },
    }));
    const beforeRevision = useDealStore.getState().dispatch_revision;

    dispatchCanonicalizeConsolidateRuleRun(0, 1);

    expect(useDealStore.getState().dispatch_revision).toBe(beforeRevision + 1);
  });

  test("test_canonicalize_consolidate_rule_run_sets_pending_commit_message_on_active_session", () => {
    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        main: {
          ...state.sessions.main,
          working_tree: {
            ...state.sessions.main.working_tree,
            waterfall_rules: [
              makeCanonicalizableRule("msg0", 0, "A0"),
              makeCanonicalizableRule("msg1", 1, "A1"),
              makeCanonicalizableRule("msg2", 2, "A2"),
            ],
          },
        },
      },
    }));

    dispatchCanonicalizeConsolidateRuleRun(1, 2);

    const activeSession = useDealStore.getState().sessions.main as unknown as {
      pending_commit_message?: string | null;
    };
    expect(activeSession.pending_commit_message).toBe(
      "Canonicalize consolidate rule run [1..2]",
    );
  });

  test("test_canonicalize_consolidate_rule_run_preserves_first_rule_id", () => {
    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        main: {
          ...state.sessions.main,
          working_tree: {
            ...state.sessions.main.working_tree,
            waterfall_rules: [
              makeCanonicalizableRule("rule_first", 0, "A1"),
              makeCanonicalizableRule("rule_second", 1, "A2"),
            ],
          },
        },
      },
    }));

    dispatchCanonicalizeConsolidateRuleRun(0, 1);

    const rules = useDealStore.getState().sessions.main.working_tree.waterfall_rules;
    expect(rules).toHaveLength(1);
    expect(rules[0]?.rule_id).toBe("rule_first");
  });

  test("test_canonicalize_consolidate_rule_run_invalid_range_is_noop_with_stale_diagnostic", () => {
    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        main: {
          ...state.sessions.main,
          working_tree: {
            ...state.sessions.main.working_tree,
            waterfall_rules: [
              makeCanonicalizableRule("invalid0", 0, "A1"),
              makeCanonicalizableRule("invalid1", 1, "A2"),
            ],
          },
        },
      },
    }));
    const beforeTree = useDealStore.getState().sessions.main.working_tree;

    dispatchCanonicalizeConsolidateRuleRun(1, 1);

    const afterState = useDealStore.getState();
    expect(afterState.sessions.main.working_tree).toBe(beforeTree);
    expect(
      afterState.sessions.main.diagnostics.some(
        (d) => d.code === "STALE_QUICKFIX" && d.severity === "warning",
      ),
    ).toBe(true);
  });

  test("test_add_bond_after_canonicalize_clears_pending_commit_message", () => {
    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        main: {
          ...state.sessions.main,
          working_tree: {
            ...state.sessions.main.working_tree,
            waterfall_rules: [
              makeCanonicalizableRule("clear_r0", 0, "A0"),
              makeCanonicalizableRule("clear_r1", 1, "A1"),
            ],
          },
        },
      },
    }));

    dispatchCanonicalizeConsolidateRuleRun(0, 1);

    const afterCanon = useDealStore.getState().sessions.main as unknown as {
      pending_commit_message?: string | null;
    };
    expect(afterCanon.pending_commit_message).not.toBeNull();

    useDealStore.getState().dispatch({ type: "addBond", payload: makeBond("CLEAR_SLOT_BOND") });

    const afterAction = useDealStore.getState().sessions.main as unknown as {
      pending_commit_message?: string | null;
    };
    expect(afterAction.pending_commit_message).toBeNull();
  });

  test("test_set_bond_kind_after_canonicalize_clears_pending_commit_message", () => {
    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        main: {
          ...state.sessions.main,
          working_tree: {
            ...state.sessions.main.working_tree,
            bonds: [makeBond("KIND_CLEAR_BOND")],
            waterfall_rules: [
              makeCanonicalizableRule("kind_r0", 0, "A0"),
              makeCanonicalizableRule("kind_r1", 1, "A1"),
            ],
          },
        },
      },
    }));

    dispatchCanonicalizeConsolidateRuleRun(0, 1);

    const afterCanon = useDealStore.getState().sessions.main as unknown as {
      pending_commit_message?: string | null;
    };
    expect(afterCanon.pending_commit_message).not.toBeNull();

    useDealStore.getState().dispatch({
      type: "setBondKind",
      payload: { bond_id: "KIND_CLEAR_BOND", kind: "PAC" },
    });

    const afterAction = useDealStore.getState().sessions.main as unknown as {
      pending_commit_message?: string | null;
    };
    expect(afterAction.pending_commit_message).toBeNull();
  });

  test("test_set_rule_priority_after_canonicalize_clears_pending_commit_message", () => {
    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        main: {
          ...state.sessions.main,
          working_tree: {
            ...state.sessions.main.working_tree,
            waterfall_rules: [
              makeCanonicalizableRule("prio_r0", 0, "A0"),
              makeCanonicalizableRule("prio_r1", 1, "A1"),
            ],
          },
        },
      },
    }));

    dispatchCanonicalizeConsolidateRuleRun(0, 1);

    const afterCanon = useDealStore.getState().sessions.main as unknown as {
      pending_commit_message?: string | null;
    };
    expect(afterCanon.pending_commit_message).not.toBeNull();

    useDealStore.getState().dispatch({
      type: "setRulePriority",
      payload: { rule_id: "prio_r0", priority: 9 },
    });

    const afterAction = useDealStore.getState().sessions.main as unknown as {
      pending_commit_message?: string | null;
    };
    expect(afterAction.pending_commit_message).toBeNull();
  });

  test("test_canonicalize_consolidate_rule_run_uses_order_sorted_indices", () => {
    // Rules authored with array positions that do NOT match their order values:
    //   array[0]=order3/T3, array[1]=order1/T1, array[2]=order2/T2, array[3]=order4/T4
    // The detector emits indices into the ORDER-SORTED view:
    //   sorted[0]={order:1,T1}, sorted[1]={order:2,T2}, sorted[2]={order:3,T3}, sorted[3]={order:4,T4}
    // Dispatching start_index=0,end_index=1 must consolidate order=1+order=2 → ["T1","T2"],
    // NOT array positions 0+1 which would yield the wrong ["T3","T1"].
    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        main: {
          ...state.sessions.main,
          working_tree: {
            ...state.sessions.main.working_tree,
            waterfall_rules: [
              makeCanonicalizableRule("r_order3", 3, "T3"),
              makeCanonicalizableRule("r_order1", 1, "T1"),
              makeCanonicalizableRule("r_order2", 2, "T2"),
              makeCanonicalizableRule("r_order4", 4, "T4"),
            ],
          },
        },
      },
    }));

    dispatchCanonicalizeConsolidateRuleRun(0, 1);

    const rules = useDealStore.getState().sessions.main.working_tree.waterfall_rules;
    // Sorted indices [0,1] → order=1 and order=2 consolidated; 4−1 = 3 rules remain.
    expect(rules).toHaveLength(3);
    // Consolidated rule must carry targets from the order=1 and order=2 rules.
    const consolidated = rules.find((r) => r.to_targets.length > 1);
    expect(consolidated?.to_targets).toEqual(["T1", "T2"]);
    expect(consolidated?.rule_id).toBe("r_order1");
    // order=3 and order=4 rules must survive untouched.
    expect(rules.some((r) => r.rule_id === "r_order3")).toBe(true);
    expect(rules.some((r) => r.rule_id === "r_order4")).toBe(true);
  });

  test("test_canonicalize_consolidate_rule_run_preserves_surrounding_rules", () => {
    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        main: {
          ...state.sessions.main,
          working_tree: {
            ...state.sessions.main.working_tree,
            waterfall_rules: [
              makeCanonicalizableRule("before", 0, "B0", { from_sources: ["INT_CASH"] }),
              makeCanonicalizableRule("run1", 1, "A1"),
              makeCanonicalizableRule("run2", 2, "A2"),
              makeCanonicalizableRule("after", 3, "B9", { from_sources: ["RESERVE"] }),
            ],
          },
        },
      },
    }));

    dispatchCanonicalizeConsolidateRuleRun(1, 2);

    const rules = useDealStore.getState().sessions.main.working_tree.waterfall_rules;
    expect(rules).toHaveLength(3);
    expect(rules[0]?.rule_id).toBe("before");
    expect(rules[1]?.rule_id).toBe("run1");
    expect(rules[1]?.to_targets).toEqual(["A1", "A2"]);
    expect(rules[2]?.rule_id).toBe("after");
  });
});
