import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { useDealStore } from "./useDealStore";
import type { DealDefinitionIR, BondDefIR, RuleNodeIR } from "../ir-types";
import type { DealStoreState } from "./useDealStore";

type DealState = DealDefinitionIR;
type BondDef = BondDefIR;
type BranchName = import("./session").BranchName;
type DocumentSession = import("./session").DocumentSession;
type DiagnosticPayload = import("./diagnostics-types").DiagnosticPayload;

type Sds2StoreActions = {
  createEphemeralSession: (args: {
    branch_name: BranchName;
    base_sha: string;
    ui_role: "preview";
  }) => Promise<string>;
  setActiveSession: (sessionId: string) => void;
  setDiagnostics: (sessionId: string, payloads: DiagnosticPayload[]) => void;
  deleteSession: (sessionId: string) => void;
};

type SessionModuleContracts = {
  mkBranchName: (name: string) => BranchName;
};

type TemporalWithPastStates = {
  getState: () => {
    pastStates: unknown[];
  };
};

const BASE_SHA = "1".repeat(40);

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

function makeDealFixture(label: string): DealState {
  return {
    schema_version: "2.0.0",
    deal_name: `sds-2 ${label}`,
    bonds: [makeBond(`${label}_A1`)],
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
    waterfall_rules: [makeRule(`${label}_rule_1`)],
    collateral_groups: [],
    deal_knobs: {},
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function getSds2Action<K extends keyof Sds2StoreActions>(
  key: K,
): Sds2StoreActions[K] {
  const state = useDealStore.getState() as DealStoreState & Partial<Sds2StoreActions>;
  const action = state[key];
  expect(typeof action).toBe("function");
  return action as Sds2StoreActions[K];
}

async function loadSessionContracts(): Promise<SessionModuleContracts> {
  const mod = (await import("./session")) as Partial<SessionModuleContracts>;
  expect(typeof mod.mkBranchName).toBe("function");
  return mod as SessionModuleContracts;
}

function getPastStateCount(sessionId: string): number {
  const session = useDealStore.getState().sessions[sessionId] as {
    zundo_history: TemporalWithPastStates | null;
  };
  expect(session.zundo_history).toBeTruthy();
  return session.zundo_history?.getState().pastStates.length ?? -1;
}

describe("sds-2 document session model", () => {
  beforeEach(() => {
    useDealStore.setState(useDealStore.getInitialState(), true);
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("test_document_session_type_pins_all_field_shapes_with_literal_precision", async () => {
    const { mkBranchName } = await loadSessionContracts();
    const mainBranch = mkBranchName("main");

    // Compile-time guard: raw strings must not be assignable to BranchName.
    if (false) {
      // @ts-expect-error - raw string must not satisfy BranchName brand.
      const invalidBranch: BranchName = "raw-string";
      expect(invalidBranch).toBe("raw-string");
    }

    const session = {
      session_id: "main",
      branch_name: mainBranch,
      base_sha: BASE_SHA,
      working_tree: makeDealFixture("literal-shape"),
      validation_target: "self",
      commit_target: mainBranch,
      zundo_history: { getState: () => ({ pastStates: [] }) } as unknown as DocumentSession["zundo_history"],
      ui_role: "primary",
      diagnostics: [],
    } satisfies DocumentSession;

    expect(session.session_id).toBe("main");
    expect(session.branch_name).toBe("main");
    expect(session.base_sha).toMatch(/^[0-9a-f]{40}$/);
    expect(session.working_tree.deal_name).toBe("sds-2 literal-shape");
    expect(session.validation_target).toBe("self");
    expect(session.commit_target).toBe("main");
    expect(session).toHaveProperty("zundo_history");
    expect(session.ui_role).toBe("primary");
    expect(Array.isArray(session.diagnostics)).toBe(true);
  });

  test("test_branch_name_brand_rejects_invalid_slug_matches_irvc1_regex", async () => {
    const { mkBranchName } = await loadSessionContracts();
    const slug64 = "a".repeat(64);
    const slug65 = "a".repeat(65);

    const valid = [
      "main",
      "ai/turn-abc",
      "ai/turn-a",
      `ai/turn-${slug64}`,
      "solver/run-x",
      "what-if/foo",
    ];

    for (const branch of valid) {
      expect(() => mkBranchName(branch)).not.toThrow();
      expect(mkBranchName(branch)).toBe(branch);
    }

    const invalid = [
      "../escape",
      "UPPERCASE",
      "ai/turn-",
      "ai/turn-Foo",
      "ai/turn--bar",
      `ai/turn-${slug65}`,
      "",
    ];

    for (const branch of invalid) {
      expect(() => mkBranchName(branch)).toThrow();
    }
  });

  test("test_session_access_path_is_flat_no_wrapper_object", () => {
    const state = useDealStore.getState();
    const session = state.sessions.main as Record<string, unknown>;

    expect(session.working_tree).toBeDefined();
    expect(session.state).toBeUndefined();
    expect(session.zundo_history).toBeTruthy();

    // Compile-time guard: sanctioned shape is sessions[id].working_tree (flat).
    // @ts-expect-error - wrapper shape sessions[id].state is disallowed.
    void state.sessions.main.state;
  });

  test("test_createEphemeralSession_uses_root_deal_id_in_branches_and_show_urls", async () => {
    const { mkBranchName } = await loadSessionContracts();
    const createEphemeralSession = getSds2Action("createEphemeralSession");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const responseDeal = makeDealFixture("seeded-by-show");

    fetchSpy.mockResolvedValueOnce(jsonResponse({ ok: true }));
    fetchSpy.mockResolvedValueOnce(jsonResponse(responseDeal));

    useDealStore.getState().setDealId("test_deal_abc");
    await createEphemeralSession({
      branch_name: mkBranchName("ai/turn-test123"),
      base_sha: BASE_SHA,
      ui_role: "preview",
    });

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    const firstUrl = String(fetchSpy.mock.calls[0]?.[0]);
    const firstInit = fetchSpy.mock.calls[0]?.[1] as RequestInit;
    const firstBody = JSON.parse(String(firstInit.body)) as {
      name: string;
      from_sha: string;
    };

    expect(firstUrl).toContain("/deals/test_deal_abc/branches");
    expect(firstInit.method).toBe("POST");
    expect(firstBody).toEqual({ name: "ai/turn-test123", from_sha: BASE_SHA });

    const secondUrl = String(fetchSpy.mock.calls[1]?.[0]);
    expect(secondUrl).toContain("/deals/test_deal_abc/show?");
    expect(secondUrl).toContain(`sha=${BASE_SHA}`);
    expect(secondUrl).toContain("path=deal.json");
  });

  test("test_createEphemeralSession_calls_branches_and_show_endpoints_and_seeds_working_tree", async () => {
    const { mkBranchName } = await loadSessionContracts();
    const createEphemeralSession = getSds2Action("createEphemeralSession");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const seededDeal = makeDealFixture("ephemeral-seed");

    fetchSpy.mockResolvedValueOnce(jsonResponse({ ok: true }));
    fetchSpy.mockResolvedValueOnce(jsonResponse(seededDeal));

    const before = useDealStore.getState();
    useDealStore.getState().setDealId("test_deal_abc");
    const newSessionId = await createEphemeralSession({
      branch_name: mkBranchName("ai/turn-seeded"),
      base_sha: BASE_SHA,
      ui_role: "preview",
    });

    const after = useDealStore.getState();
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(after.sessions[newSessionId]).toBeDefined();
    expect(after.sessions[newSessionId]?.working_tree).toEqual(seededDeal);
    expect(after.activeSessionId).toBe(before.activeSessionId);
    expect(after.sessions.main.working_tree).toBe(before.sessions.main.working_tree);
  });

  test("test_createEphemeralSession_does_not_mutate_main_session", async () => {
    const { mkBranchName } = await loadSessionContracts();
    const createEphemeralSession = getSds2Action("createEphemeralSession");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValueOnce(jsonResponse({ ok: true }));
    fetchSpy.mockResolvedValueOnce(jsonResponse(makeDealFixture("does-not-touch-main")));

    const before = useDealStore.getState().sessions.main;
    const beforeWorkingTree = before.working_tree;
    const beforeZundo = before.zundo_history;
    const beforeDiagnostics = before.diagnostics;
    useDealStore.getState().setDealId("test_deal_abc");

    await createEphemeralSession({
      branch_name: mkBranchName("ai/turn-main-immutable"),
      base_sha: BASE_SHA,
      ui_role: "preview",
    });

    const afterMain = useDealStore.getState().sessions.main;
    expect(afterMain.working_tree).toBe(beforeWorkingTree);
    expect(afterMain.zundo_history).toBe(beforeZundo);
    expect(afterMain.diagnostics).toBe(beforeDiagnostics);
  });

  test("test_createEphemeralSession_http_failure_does_not_create_partial_session_record", async () => {
    const { mkBranchName } = await loadSessionContracts();
    const createEphemeralSession = getSds2Action("createEphemeralSession");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockRejectedValueOnce(new Error("network-failure"));

    useDealStore.getState().setDealId("test_deal_abc");
    const beforeCount = Object.keys(useDealStore.getState().sessions).length;

    let surfacedError = false;
    try {
      const result = await createEphemeralSession({
        branch_name: mkBranchName("ai/turn-http-failure"),
        base_sha: BASE_SHA,
        ui_role: "preview",
      });
      surfacedError = typeof result !== "string";
    } catch {
      surfacedError = true;
    }

    const afterCount = Object.keys(useDealStore.getState().sessions).length;
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(surfacedError).toBe(true);
    expect(afterCount).toBe(beforeCount);
  });

  test("test_actions_mutate_only_active_session_working_tree", async () => {
    const { mkBranchName } = await loadSessionContracts();
    const createEphemeralSession = getSds2Action("createEphemeralSession");
    const setActiveSession = getSds2Action("setActiveSession");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValue(jsonResponse(makeDealFixture("multi-session")));

    useDealStore.getState().setDealId("test_deal_abc");
    const sid1 = await createEphemeralSession({
      branch_name: mkBranchName("ai/turn-a"),
      base_sha: BASE_SHA,
      ui_role: "preview",
    });
    const sid2 = await createEphemeralSession({
      branch_name: mkBranchName("ai/turn-b"),
      base_sha: BASE_SHA,
      ui_role: "preview",
    });
    const sid3 = await createEphemeralSession({
      branch_name: mkBranchName("ai/turn-c"),
      base_sha: BASE_SHA,
      ui_role: "preview",
    });

    const before = useDealStore.getState();
    const beforeMainTree = before.sessions.main.working_tree;
    const beforeSid1Tree = before.sessions[sid1]?.working_tree;
    const beforeSid2Tree = before.sessions[sid2]?.working_tree;
    const beforeSid3Tree = before.sessions[sid3]?.working_tree;

    setActiveSession(sid2);
    useDealStore.getState().dispatch({ type: "addBond", payload: makeBond("ACTIVE_ONLY_BOND") });

    const after = useDealStore.getState();
    expect(after.sessions[sid2]?.working_tree).not.toBe(beforeSid2Tree);
    expect(after.sessions[sid2]?.working_tree.bonds.some((b) => b.name === "ACTIVE_ONLY_BOND")).toBe(true);
    expect(after.sessions.main.working_tree).toBe(beforeMainTree);
    expect(after.sessions[sid1]?.working_tree).toBe(beforeSid1Tree);
    expect(after.sessions[sid3]?.working_tree).toBe(beforeSid3Tree);
  });

  test("test_zundo_per_session_instance_isolated_between_sessions", async () => {
    const { mkBranchName } = await loadSessionContracts();
    const createEphemeralSession = getSds2Action("createEphemeralSession");
    const setActiveSession = getSds2Action("setActiveSession");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValue(jsonResponse(makeDealFixture("zundo-isolation")));

    useDealStore.getState().setDealId("test_deal_abc");
    const sidA = await createEphemeralSession({
      branch_name: mkBranchName("ai/turn-zundo-a"),
      base_sha: BASE_SHA,
      ui_role: "preview",
    });
    const sidB = await createEphemeralSession({
      branch_name: mkBranchName("ai/turn-zundo-b"),
      base_sha: BASE_SHA,
      ui_role: "preview",
    });

    setActiveSession("main");
    useDealStore.getState().dispatch({ type: "addBond", payload: makeBond("MAIN_BOND_1") });
    setActiveSession(sidA);
    useDealStore.getState().dispatch({ type: "addBond", payload: makeBond("A_BOND_1") });
    useDealStore.getState().dispatch({ type: "addBond", payload: makeBond("A_BOND_2") });
    setActiveSession(sidB);
    useDealStore.getState().dispatch({ type: "addBond", payload: makeBond("B_BOND_1") });
    useDealStore.getState().dispatch({ type: "addBond", payload: makeBond("B_BOND_2") });
    useDealStore.getState().dispatch({ type: "addBond", payload: makeBond("B_BOND_3") });

    expect(getPastStateCount("main")).toBe(1);
    expect(getPastStateCount(sidA)).toBe(2);
    expect(getPastStateCount(sidB)).toBe(3);

    const beforeSwitchMain = getPastStateCount("main");
    setActiveSession(sidA);
    setActiveSession(sidB);
    setActiveSession("main");
    expect(getPastStateCount("main")).toBe(beforeSwitchMain);
  });

  test("test_active_session_switch_does_not_emit_temporal_entry", async () => {
    const { mkBranchName } = await loadSessionContracts();
    const createEphemeralSession = getSds2Action("createEphemeralSession");
    const setActiveSession = getSds2Action("setActiveSession");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValue(jsonResponse(makeDealFixture("switch-no-temporal")));

    useDealStore.getState().setDealId("test_deal_abc");
    const sid = await createEphemeralSession({
      branch_name: mkBranchName("ai/turn-no-temporal"),
      base_sha: BASE_SHA,
      ui_role: "preview",
    });

    const beforeMainCount = getPastStateCount("main");
    setActiveSession(sid);
    const afterMainCount = getPastStateCount("main");
    expect(afterMainCount).toBe(beforeMainCount);
  });

  test("test_multiple_ephemeral_sessions_coexist_with_independent_mutations", async () => {
    const { mkBranchName } = await loadSessionContracts();
    const createEphemeralSession = getSds2Action("createEphemeralSession");
    const setActiveSession = getSds2Action("setActiveSession");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValue(jsonResponse(makeDealFixture("coexist")));

    useDealStore.getState().setDealId("test_deal_abc");
    const sid1 = await createEphemeralSession({
      branch_name: mkBranchName("ai/turn-coexist-1"),
      base_sha: BASE_SHA,
      ui_role: "preview",
    });
    const sid2 = await createEphemeralSession({
      branch_name: mkBranchName("ai/turn-coexist-2"),
      base_sha: BASE_SHA,
      ui_role: "preview",
    });
    const sid3 = await createEphemeralSession({
      branch_name: mkBranchName("ai/turn-coexist-3"),
      base_sha: BASE_SHA,
      ui_role: "preview",
    });

    const beforeSid1 = useDealStore.getState().sessions[sid1]?.working_tree;
    const beforeSid3 = useDealStore.getState().sessions[sid3]?.working_tree;

    setActiveSession(sid2);
    useDealStore.getState().dispatch({ type: "addBond", payload: makeBond("ONLY_SID2_CHANGES") });

    const after = useDealStore.getState();
    expect(after.sessions[sid1]?.working_tree).toBe(beforeSid1);
    expect(after.sessions[sid3]?.working_tree).toBe(beforeSid3);
    expect(after.sessions[sid2]?.working_tree.bonds.some((b) => b.name === "ONLY_SID2_CHANGES")).toBe(true);
    expect(Object.keys(after.sessions).length).toBe(4);
  });

  test("test_setDiagnostics_replaces_slot_atomically_per_session", async () => {
    const { mkBranchName } = await loadSessionContracts();
    const createEphemeralSession = getSds2Action("createEphemeralSession");
    const setDiagnostics = getSds2Action("setDiagnostics");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValue(jsonResponse(makeDealFixture("diagnostics-slot")));

    useDealStore.getState().setDealId("test_deal_abc");
    const sid = await createEphemeralSession({
      branch_name: mkBranchName("ai/turn-diag"),
      base_sha: BASE_SHA,
      ui_role: "preview",
    });

    const payloads: DiagnosticPayload[] = [
      {
        code: "TEST",
        severity: "error",
        path: "$.bonds[0]",
        message: "msg",
        payload: {},
      },
    ];

    const otherBefore = useDealStore.getState().sessions[sid]?.diagnostics;
    setDiagnostics("main", payloads);

    const after = useDealStore.getState();
    expect(after.sessions.main.diagnostics).toBe(payloads);
    expect(after.sessions[sid]?.diagnostics).toBe(otherBefore);
  });

  test("test_store_initializes_with_main_session_primary_role", () => {
    const state = useDealStore.getState();
    const mainSession = state.sessions.main as {
      ui_role: string;
      session_id: string;
      zundo_history: TemporalWithPastStates | null;
    };

    expect(Object.keys(state.sessions)).toEqual(["main"]);
    expect(mainSession.session_id).toBe("main");
    expect(mainSession.ui_role).toBe("primary");
    expect(typeof mainSession.zundo_history?.getState).toBe("function");
  });

  test("test_main_session_cannot_be_deleted", () => {
    const deleteSession = getSds2Action("deleteSession");
    const before = useDealStore.getState();
    let threw = false;

    try {
      deleteSession("main");
    } catch {
      threw = true;
    }

    const after = useDealStore.getState();
    expect(before.sessions.main).toBeDefined();
    expect(after.sessions.main).toBeDefined();

    if (!threw) {
      const diagnostics = after.sessions.main.diagnostics as Array<{
        code?: string;
        severity?: string;
      }>;
      expect(
        diagnostics.some((d) => d.severity === "warning" || d.code === "WARNING"),
      ).toBe(true);
    }
  });
});
