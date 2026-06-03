import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { useDealStore } from "./useDealStore";
import type { DealStoreState } from "./useDealStore";
import { mkBranchName } from "./session";
import type { BondDefIR, DealDefinitionIR } from "../ir-types";

type DealState = DealDefinitionIR;
type BondDef = BondDefIR;
type BranchName = import("./session").BranchName;

type Sds4LifecycleActions = {
  createEphemeralSession: (args: {
    branch_name: BranchName;
    base_sha: string;
    ui_role: "preview";
  }) => Promise<string>;
  setActiveSession: (sessionId: string) => void;
  previewEphemeralSession: (sessionId: string) => void;
  applyEphemeralSessionToMain: (sessionId: string) => Promise<void>;
  discardEphemeralSession: (sessionId: string) => Promise<void>;
};

const DEAL_ID = "deal_sds4_lifecycle";
const BASE_SHA = "1".repeat(40);
const NEW_MAIN_SHA = "2".repeat(40);

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

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

function makeDealFixture(label: string): DealState {
  return {
    schema_version: "2.0.0",
    deal_name: `sds-4 ${label}`,
    bonds: [makeBond(`${label}_A1`)],
    accounts: [],
    fees: [],
    triggers: [],
    waterfall_rules: [],
    collateral_groups: [],
    deal_knobs: {},
  };
}

function getLifecycleAction<K extends keyof Sds4LifecycleActions>(
  key: K,
): Sds4LifecycleActions[K] {
  const state = useDealStore.getState() as DealStoreState &
    Partial<Sds4LifecycleActions>;
  const action = state[key];
  expect(typeof action).toBe("function");
  return action as Sds4LifecycleActions[K];
}

function getMainPastStateCount(): number {
  return useDealStore.getState().sessions.main.zundo_history.getState().pastStates.length;
}

async function createEphemeralSessionForTests(
  branchName: BranchName,
  baseSha: string,
): Promise<string> {
  const createEphemeralSession = getLifecycleAction("createEphemeralSession");
  return createEphemeralSession({
    branch_name: branchName,
    base_sha: baseSha,
    ui_role: "preview",
  });
}

describe("sds-4 patch lifecycle and HTTP integration", () => {
  beforeEach(() => {
    useDealStore.setState(useDealStore.getInitialState(), true);
    useDealStore.getState().setDealId(DEAL_ID);
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("test_preview_ephemeral_session_sets_ui_role_and_active_without_touching_main", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValueOnce(jsonResponse({ ok: true }));
    fetchSpy.mockResolvedValueOnce(jsonResponse(makeDealFixture("preview-seed")));

    const sessionId = await createEphemeralSessionForTests(
      mkBranchName("ai/turn-preview-lifecycle"),
      BASE_SHA,
    );

    const previewEphemeralSession = getLifecycleAction("previewEphemeralSession");
    const mainBefore = useDealStore.getState().sessions.main;
    const mainWorkingTreeBefore = mainBefore.working_tree;
    const mainBaseShaBefore = mainBefore.base_sha;
    const mainZundoBefore = mainBefore.zundo_history;
    const mainPastCountBefore = getMainPastStateCount();

    previewEphemeralSession(sessionId);

    const after = useDealStore.getState();
    expect(after.activeSessionId).toBe(sessionId);
    expect(after.sessions[sessionId]?.ui_role).toBe("preview");
    expect(after.sessions.main.working_tree).toBe(mainWorkingTreeBefore);
    expect(after.sessions.main.base_sha).toBe(mainBaseShaBefore);
    expect(after.sessions.main.zundo_history).toBe(mainZundoBefore);
    expect(getMainPastStateCount()).toBe(mainPastCountBefore);
  });

  test("test_apply_success_path_updates_main_base_sha_and_working_tree_and_deletes_ephemeral", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const ephemeralSeed = makeDealFixture("apply-seed");
    const mergedMainTree = makeDealFixture("main-after-apply");
    const branchName = mkBranchName("ai/turn-apply-success");

    fetchSpy.mockResolvedValueOnce(jsonResponse({ ok: true }));
    fetchSpy.mockResolvedValueOnce(jsonResponse(ephemeralSeed));
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", sha: NEW_MAIN_SHA }),
    );
    fetchSpy.mockResolvedValueOnce(jsonResponse(mergedMainTree));

    const sessionId = await createEphemeralSessionForTests(
      branchName,
      BASE_SHA,
    );

    const setActiveSession = getLifecycleAction("setActiveSession");
    const applyEphemeralSessionToMain = getLifecycleAction(
      "applyEphemeralSessionToMain",
    );

    setActiveSession(sessionId);
    useDealStore.getState().dispatch({
      type: "addBond",
      payload: makeBond("EPHEMERAL_MUTATION_BOND"),
    });

    await applyEphemeralSessionToMain(sessionId);

    const after = useDealStore.getState();
    expect(after.sessions.main.base_sha).toBe(NEW_MAIN_SHA);
    expect(after.sessions.main.working_tree).toEqual(mergedMainTree);
    expect(after.sessions[sessionId]).toBeUndefined();

    const mergeCall = fetchSpy.mock.calls.find(([url]) =>
      String(url).includes(`/deals/${DEAL_ID}/merge`),
    );
    expect(mergeCall).toBeDefined();
    const mergeInit = mergeCall?.[1] as RequestInit;
    expect(mergeInit.method).toBe("POST");
    expect(JSON.parse(String(mergeInit.body))).toEqual({
      branch: branchName,
      into: "main",
    });

    const showFromHeadCall = fetchSpy.mock.calls.find(([url]) => {
      const value = String(url);
      return (
        value.includes(`/deals/${DEAL_ID}/show?`) &&
        value.includes(`sha=${NEW_MAIN_SHA}`) &&
        value.includes("path=deal.json")
      );
    });
    expect(showFromHeadCall).toBeDefined();
  });

  test("test_apply_success_path_appends_exactly_one_zundo_entry_via_pause_resume_on_main_zundo_history", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const branchName = mkBranchName("ai/turn-apply-zundo");
    const mergedMainTree = makeDealFixture("main-after-zundo-apply");

    fetchSpy.mockResolvedValueOnce(jsonResponse({ ok: true }));
    fetchSpy.mockResolvedValueOnce(jsonResponse(makeDealFixture("zundo-seed")));
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", sha: NEW_MAIN_SHA }),
    );
    fetchSpy.mockResolvedValueOnce(jsonResponse(mergedMainTree));

    useDealStore.getState().dispatch({
      type: "addBond",
      payload: makeBond("MAIN_PRE_APPLY_BOND"),
    });

    const sessionId = await createEphemeralSessionForTests(
      branchName,
      BASE_SHA,
    );

    const beforePastCount = getMainPastStateCount();
    const applyEphemeralSessionToMain = getLifecycleAction(
      "applyEphemeralSessionToMain",
    );

    await applyEphemeralSessionToMain(sessionId);

    const afterPastCount = getMainPastStateCount();
    expect(afterPastCount).toBe(beforePastCount + 1);
  });

  test("test_apply_conflict_path_leaves_main_unchanged_and_sets_applyConflict_state", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const conflictDiagnostic = {
      entity_kind: "bond",
      entity_id: "A1",
      field_path: "coupon",
      ours_value: 0.05,
      theirs_value: 0.06,
      ancestor_value: 0.04,
    };

    fetchSpy.mockResolvedValueOnce(jsonResponse({ ok: true }));
    fetchSpy.mockResolvedValueOnce(jsonResponse(makeDealFixture("conflict-seed")));
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "conflict", diagnostic: conflictDiagnostic }),
    );

    const sessionId = await createEphemeralSessionForTests(
      mkBranchName("ai/turn-apply-conflict"),
      BASE_SHA,
    );

    const applyEphemeralSessionToMain = getLifecycleAction(
      "applyEphemeralSessionToMain",
    );
    const mainBefore = useDealStore.getState().sessions.main;
    const mainWorkingTreeBefore = mainBefore.working_tree;
    const mainBaseShaBefore = mainBefore.base_sha;
    const mainPastCountBefore = getMainPastStateCount();

    await applyEphemeralSessionToMain(sessionId);

    const after = useDealStore.getState();
    expect(after.sessions.main.working_tree).toBe(mainWorkingTreeBefore);
    expect(after.sessions.main.base_sha).toBe(mainBaseShaBefore);
    expect(getMainPastStateCount()).toBe(mainPastCountBefore);
    expect(after.applyConflict).toEqual({
      sessionId,
      diagnostic: conflictDiagnostic,
    });
  });

  test("test_apply_conflict_path_preserves_ephemeral_session_and_writes_no_zundo", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValueOnce(jsonResponse({ ok: true }));
    fetchSpy.mockResolvedValueOnce(jsonResponse(makeDealFixture("conflict-seed-2")));
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "conflict",
        diagnostic: {
          entity_kind: "bond",
          entity_id: "B1",
          field_path: "kind",
          ours_value: "PAC",
          theirs_value: "CASH_PAY",
          ancestor_value: "CASH_PAY",
        },
      }),
    );

    const sessionId = await createEphemeralSessionForTests(
      mkBranchName("ai/turn-apply-conflict-preserve"),
      BASE_SHA,
    );

    const applyEphemeralSessionToMain = getLifecycleAction(
      "applyEphemeralSessionToMain",
    );
    const mainPastCountBefore = getMainPastStateCount();

    await applyEphemeralSessionToMain(sessionId);

    const after = useDealStore.getState();
    expect(after.sessions[sessionId]).toBeDefined();
    expect(getMainPastStateCount()).toBe(mainPastCountBefore);
  });

  test("test_discard_ephemeral_session_calls_delete_endpoint_and_leaves_main_untouched", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const branchName = mkBranchName("ai/turn-discard-success");
    fetchSpy.mockResolvedValueOnce(jsonResponse({ ok: true }));
    fetchSpy.mockResolvedValueOnce(jsonResponse(makeDealFixture("discard-seed")));
    fetchSpy.mockResolvedValueOnce(new Response(null, { status: 204 }));

    const sessionId = await createEphemeralSessionForTests(
      branchName,
      BASE_SHA,
    );

    const discardEphemeralSession = getLifecycleAction("discardEphemeralSession");
    const mainBefore = useDealStore.getState().sessions.main;
    const mainWorkingTreeBefore = mainBefore.working_tree;
    const mainBaseShaBefore = mainBefore.base_sha;
    const mainZundoBefore = mainBefore.zundo_history;
    const mainDiagnosticsBefore = mainBefore.diagnostics;

    await discardEphemeralSession(sessionId);

    const after = useDealStore.getState();
    expect(after.sessions[sessionId]).toBeUndefined();
    expect(after.sessions.main.working_tree).toBe(mainWorkingTreeBefore);
    expect(after.sessions.main.base_sha).toBe(mainBaseShaBefore);
    expect(after.sessions.main.zundo_history).toBe(mainZundoBefore);
    expect(after.sessions.main.diagnostics).toBe(mainDiagnosticsBefore);

    const deleteCall = fetchSpy.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === "DELETE",
    );
    expect(deleteCall).toBeDefined();
    const deleteUrl = String(deleteCall?.[0]);
    expect(deleteUrl).toContain(`/deals/${DEAL_ID}/branches/`);
    expect(decodeURIComponent(deleteUrl)).toContain(branchName);
  });

  test("test_discard_http_failure_preserves_session_record", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValueOnce(jsonResponse({ ok: true }));
    fetchSpy.mockResolvedValueOnce(
      jsonResponse(makeDealFixture("discard-failure-seed")),
    );
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ detail: "delete failed" }, 500),
    );

    const sessionId = await createEphemeralSessionForTests(
      mkBranchName("ai/turn-discard-failure"),
      BASE_SHA,
    );

    const discardEphemeralSession = getLifecycleAction("discardEphemeralSession");
    try {
      await discardEphemeralSession(sessionId);
    } catch {
      // Accept either throw-or-diagnostic behavior; preservation is the hard contract.
    }

    const after = useDealStore.getState();
    expect(after.sessions[sessionId]).toBeDefined();
  });
});
