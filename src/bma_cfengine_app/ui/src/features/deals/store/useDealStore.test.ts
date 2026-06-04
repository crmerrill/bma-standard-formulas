import { beforeEach, describe, expect, test } from "vitest";
import {
  useDealStore,
  getDiagnosticSourceMapForTesting,
  resetDiagnosticSourceMapForTesting,
} from "./useDealStore";
import type { BondDefIR, DealDefinitionIR, RuleNodeIR } from "../ir-types";

type DealState = DealDefinitionIR;
type BondDef = BondDefIR;

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
    deal_name: "SDS-1 shape fixture",
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
    deal_knobs: {
      trigger_enabled: true,
    },
  };
}

describe("useDealStore (sds-1 scaffolding)", () => {
  beforeEach(() => {
    useDealStore.setState(useDealStore.getInitialState(), true);
  });

  test("test_store_initializes_with_root_state_shape_pin", () => {
    const state = useDealStore.getState();

    expect(state).toHaveProperty("sessions");
    expect(state).toHaveProperty("activeSessionId");
    expect(state).toHaveProperty("deal_id");
    expect(state).toHaveProperty("conflictState");
    expect(state).toHaveProperty("applyConflict");

    expect(state.activeSessionId).toBe("main");
    expect(state.deal_id).toBe("");
    expect(state.conflictState).toBeNull();
    expect(state.applyConflict).toBeNull();
    expect(Object.keys(state.sessions)).toHaveLength(1);
    expect(state.sessions.main).toBeDefined();
  });

  test("test_store_initializes_with_single_main_session_and_empty_dealstate_shape", () => {
    const mainSession = useDealStore.getState().sessions.main;

    expect(mainSession.ui_role).toBe("primary");
    expect(mainSession.session_id).toBe("main");
    expect(mainSession.branch_name).toBe("main");
    expect(mainSession.working_tree).toEqual(
      expect.objectContaining({
        bonds: expect.any(Array),
        accounts: expect.any(Array),
        waterfall_rules: expect.any(Array),
        deal_knobs: expect.any(Object),
      }),
    );
  });

  test("test_fixture_deal_json_parses_into_working_tree_without_field_renames", () => {
    // R1 sds-1 Minor #1 (deferred to sds-3): once sds-3 lands the canonical
    // fixture emitter (scripts/emit_canonical_fixtures.py producing real
    // <fixture>/deal.json artifacts), the round-trip in compile.roundtrip.test.ts
    // exercises the full Python -> TS shape contract. Until then, this test
    // proves shape integrity using a structurally-faithful synthetic fixture.
    const fixtureJson = JSON.stringify(makeDealFixture());
    const parsedFixture = JSON.parse(fixtureJson) as DealState;
    const { activeSessionId, setDealId } = useDealStore.getState();

    setDealId("test_deal_id");

    // sds-1 pins shape only; load orchestration lands in sds-2.
    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        [activeSessionId]: {
          ...state.sessions[activeSessionId],
          working_tree: parsedFixture,
        },
      },
    }));

    const state = useDealStore.getState();
    const workingTree = state.sessions[state.activeSessionId].working_tree as DealState;

    expect(state.deal_id).toBe("test_deal_id");
    expect(workingTree).toHaveProperty("bonds");
    expect(workingTree).toHaveProperty("accounts");
    expect(workingTree).toHaveProperty("waterfall_rules");
    expect(workingTree).toHaveProperty("deal_knobs");
    expect(workingTree.bonds[0].name).toBe("A1");
    expect(workingTree.accounts[0].name).toBe("Reserve");
    expect(workingTree.waterfall_rules[0].rule_id).toBe("rule_1");
  });

  test("test_setDealId_action_updates_root_deal_id", () => {
    useDealStore.getState().setDealId("deal_abc_123");
    expect(useDealStore.getState().deal_id).toBe("deal_abc_123");
  });
});

// ---------------------------------------------------------------------------
// ve-4 R1 M1 — _diagnosticSourceMap lifecycle
//
// These three cases are the TDD red phase for the fix-pass. They fail until:
//   • deleteSession cleans up _diagnosticSourceMap
//   • setDiagnostics resets the source map for a session
//   • resetDiagnosticSourceMapForTesting is exported and called in beforeEach
// ---------------------------------------------------------------------------
describe("ve-4 R1 M1 — source map lifecycle", () => {
  beforeEach(() => {
    useDealStore.setState(useDealStore.getInitialState(), true);
    resetDiagnosticSourceMapForTesting();
  });

  test("test_deleteSession_clears_source_map_entries", () => {
    const sessionId = "test_ephem_del";

    // Inject a non-main session by copying the main session structure.
    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        [sessionId]: {
          ...state.sessions.main,
          session_id: sessionId,
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          branch_name: "test-branch" as any,
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          commit_target: "test-branch" as any,
          diagnostics: [],
        },
      },
    }));

    // Record a backend diagnostic so the source map gains an entry.
    useDealStore.getState().mergeDiagnostics(sessionId, "backend", [
      { code: "E001", severity: "error", path: "$.bonds", message: "backend err", payload: {} },
    ]);
    expect(getDiagnosticSourceMapForTesting().has(sessionId)).toBe(true);

    // Deleting the session must remove its source-map entry.
    useDealStore.getState().deleteSession(sessionId);
    expect(getDiagnosticSourceMapForTesting().has(sessionId)).toBe(false);
  });

  test("test_setDiagnostics_clears_source_map_for_session", () => {
    const sessionId = "main";

    // Record a backend win so worker merges are blocked for "E002:$.bonds".
    useDealStore.getState().mergeDiagnostics(sessionId, "backend", [
      { code: "E002", severity: "error", path: "$.bonds", message: "backend err", payload: {} },
    ]);
    useDealStore.getState().mergeDiagnostics(sessionId, "worker", [
      { code: "E002", severity: "warning", path: "$.bonds", message: "worker ignored", payload: {} },
    ]);
    const diags = useDealStore.getState().sessions[sessionId].diagnostics;
    expect(diags.find((d) => d.code === "E002")?.severity).toBe("error");

    // Replacing diagnostics via setDiagnostics must reset the source map so
    // a subsequent worker merge is accepted (backend-wins lock lifted).
    useDealStore.getState().setDiagnostics(sessionId, []);
    useDealStore.getState().mergeDiagnostics(sessionId, "worker", [
      { code: "E002", severity: "warning", path: "$.bonds", message: "worker after clear", payload: {} },
    ]);

    const diagsAfter = useDealStore.getState().sessions[sessionId].diagnostics;
    expect(diagsAfter.find((d) => d.code === "E002")?.severity).toBe("warning");
  });

  test("test_store_reset_clears_source_map", () => {
    const sessionId = "main";

    // Record a backend win so worker merges are blocked.
    useDealStore.getState().mergeDiagnostics(sessionId, "backend", [
      { code: "E003", severity: "error", path: "$.fees", message: "backend err", payload: {} },
    ]);

    // Full store reset — provenance should be gone afterwards.
    // resetDiagnosticSourceMapForTesting() is the required companion to
    // getInitialState() for a complete reset (module-private map is not
    // reachable via Zustand's setState).
    useDealStore.setState(useDealStore.getInitialState(), true);
    resetDiagnosticSourceMapForTesting();

    // Worker merge for the previously-backend key must now be accepted.
    useDealStore.getState().mergeDiagnostics(sessionId, "worker", [
      { code: "E003", severity: "warning", path: "$.fees", message: "worker after reset", payload: {} },
    ]);
    const diags = useDealStore.getState().sessions[sessionId].diagnostics;
    expect(diags.find((d) => d.code === "E003")?.severity).toBe("warning");
  });
});
