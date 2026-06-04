import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { compileToIR } from "./compile";
import { useDealStore } from "./useDealStore";
import type { DealStoreState } from "./useDealStore";
import type { BondDefIR, DealDefinitionIR, RuleNodeIR } from "../ir-types";

type DealState = DealDefinitionIR;
type BondDef = BondDefIR;

type AutosaveModuleContracts = {
  subscribeAutosave?: (store: typeof useDealStore) => void;
};

type Sds5Actions = {
  promoteLocalDraft?: () => Promise<void>;
};

type SessionStorageSpy = Storage & {
  getItem: ReturnType<typeof vi.fn>;
  setItem: ReturnType<typeof vi.fn>;
  removeItem: ReturnType<typeof vi.fn>;
  clear: ReturnType<typeof vi.fn>;
  key: ReturnType<typeof vi.fn>;
};

const DEAL_ID = "deal_sds5_autosave";
const BASE_SHA = "a".repeat(40);
const HEAD_SHA = "b".repeat(40);
const REAL_DEAL_ID = "deal_promoted_from_local_draft";
const REAL_SHA = "c".repeat(40);
const LOCAL_DRAFT_ID = "local_draft_123e4567-e89b-12d3-a456-426614174000";

const originalSessionStorage = (globalThis as Record<string, unknown>)
  .sessionStorage;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function createSessionStorageMock(seed: Record<string, string> = {}): SessionStorageSpy {
  const backing = new Map<string, string>(Object.entries(seed));

  return {
    get length() {
      return backing.size;
    },
    clear: vi.fn(() => {
      backing.clear();
    }),
    getItem: vi.fn((key: string) => backing.get(key) ?? null),
    key: vi.fn((index: number) => Array.from(backing.keys())[index] ?? null),
    removeItem: vi.fn((key: string) => {
      backing.delete(key);
    }),
    setItem: vi.fn((key: string, value: string) => {
      backing.set(key, String(value));
    }),
  } as SessionStorageSpy;
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
    deal_name: `sds-5 ${label}`,
    bonds: [makeBond(`${label}_A1`)],
    accounts: [],
    fees: [],
    triggers: [],
    waterfall_rules: [],
    collateral_groups: [],
    deal_knobs: {},
  };
}

function makeCanonicalizableRule(ruleId: string, order: number, target: string): RuleNodeIR {
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
  };
}

function seedMainSession(baseSha: string, tree: DealState): void {
  useDealStore.setState((state) => ({
    sessions: {
      ...state.sessions,
      main: {
        ...state.sessions.main,
        base_sha: baseSha,
        working_tree: tree,
      },
    },
  }));
}

function getPromoteLocalDraftAction(): () => Promise<void> {
  const action = (useDealStore.getState() as DealStoreState & Sds5Actions)
    .promoteLocalDraft;
  expect(typeof action).toBe("function");
  return action as () => Promise<void>;
}

function getCommitCalls(fetchSpy: ReturnType<typeof vi.spyOn>) {
  return fetchSpy.mock.calls.filter(([url]) =>
    String(url).includes("/commit"),
  );
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

async function subscribeAutosaveForTests(): Promise<void> {
  const autosaveModulePath = `./${"autosave"}`;
  const mod = (await import(
    /* @vite-ignore */ autosaveModulePath
  ).catch(
    () => ({} as AutosaveModuleContracts),
  )) as AutosaveModuleContracts;
  expect(typeof mod.subscribeAutosave).toBe("function");
  mod.subscribeAutosave?.(useDealStore);
}

describe("sds-5 autosave and draft persistence", () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;
  let sessionStorageMock: SessionStorageSpy;

  beforeEach(() => {
    vi.useFakeTimers();
    useDealStore.setState(useDealStore.getInitialState(), true);
    useDealStore.getState().setDealId(DEAL_ID);
    seedMainSession(BASE_SHA, makeDealFixture("initial"));

    sessionStorageMock = createSessionStorageMock();
    Object.defineProperty(globalThis, "sessionStorage", {
      configurable: true,
      value: sessionStorageMock,
    });

    fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValue(
      jsonResponse({
        status: "ok",
        sha: "d".repeat(40),
      }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    Object.defineProperty(globalThis, "sessionStorage", {
      configurable: true,
      value: originalSessionStorage,
    });
  });

  test("test_debounced_autosave_fires_single_commit_at_2000ms_with_extended_payload", async () => {
    await subscribeAutosaveForTests();

    useDealStore.getState().dispatch({
      type: "addBond",
      payload: makeBond("AUTOSAVE_SINGLE_COMMIT"),
    });

    const expectedPayload = JSON.parse(
      compileToIR(useDealStore.getState().sessions.main.working_tree),
    );

    vi.advanceTimersByTime(1999);
    expect(getCommitCalls(fetchSpy)).toHaveLength(0);

    vi.advanceTimersByTime(1);

    const commitCalls = getCommitCalls(fetchSpy);
    expect(commitCalls).toHaveLength(1);

    const [url, init] = commitCalls[0];
    expect(String(url)).toContain(`/deals/${DEAL_ID}/commit`);
    const commitBody = JSON.parse(String((init as RequestInit).body)) as {
      author: string;
      message: string;
      parent_sha: string;
      branch: string;
      payload: DealState;
    };

    expect(commitBody.author).toEqual(expect.any(String));
    expect(commitBody.message).toEqual(expect.any(String));
    expect(commitBody.parent_sha).toBe(BASE_SHA);
    expect(commitBody.branch).toBe("main");
    expect(commitBody.payload).toEqual(expectedPayload);
  });

  test("test_action_burst_within_debounce_window_produces_exactly_one_commit", async () => {
    await subscribeAutosaveForTests();

    for (let i = 0; i < 5; i += 1) {
      useDealStore.getState().dispatch({
        type: "addBond",
        payload: makeBond(`BURST_${i}`),
      });
      if (i < 4) {
        vi.advanceTimersByTime(300);
      }
    }

    vi.advanceTimersByTime(1999);
    expect(getCommitCalls(fetchSpy)).toHaveLength(0);

    vi.advanceTimersByTime(1);
    expect(getCommitCalls(fetchSpy)).toHaveLength(1);
  });

  test("test_working_tree_persists_synchronously_to_sessionStorage_on_every_action", async () => {
    await subscribeAutosaveForTests();

    const expectedKey = `bma:draft:${DEAL_ID}:main`;
    useDealStore.getState().dispatch({
      type: "addBond",
      payload: makeBond("SYNC_SESSION_STORAGE_WRITE"),
    });

    expect(sessionStorageMock.setItem).toHaveBeenCalledWith(
      expectedKey,
      expect.any(String),
    );
    expect(getCommitCalls(fetchSpy)).toHaveLength(0);
  });

  test("test_sessionStorage_key_uses_root_state_deal_id", async () => {
    await subscribeAutosaveForTests();

    useDealStore.getState().setDealId("deal_id_from_root_state");
    sessionStorageMock.setItem.mockClear();

    useDealStore.getState().dispatch({
      type: "addBond",
      payload: makeBond("ROOT_DEAL_ID_KEY"),
    });

    expect(sessionStorageMock.setItem).toHaveBeenCalledWith(
      "bma:draft:deal_id_from_root_state:main",
      expect.any(String),
    );
  });

  test("test_store_init_restores_when_sessionStorage_base_sha_matches_and_working_tree_differs", async () => {
    const currentTree = makeDealFixture("current-before-restore");
    const restoredTree = makeDealFixture("restored-from-session-storage");
    restoredTree.bonds.push(makeBond("RESTORED_BOND"));
    seedMainSession(BASE_SHA, currentTree);

    const key = `bma:draft:${DEAL_ID}:main`;
    sessionStorageMock.setItem(
      key,
      JSON.stringify({
        working_tree: restoredTree,
        base_sha: BASE_SHA,
        saved_at: new Date().toISOString(),
      }),
    );

    await subscribeAutosaveForTests();

    const after = useDealStore.getState();
    expect(after.sessions.main.working_tree).toEqual(restoredTree);
    expect(
      after.sessions.main.diagnostics.some(
        (d) =>
          d.code === "DRAFT_RESTORED" &&
          d.message === "Restored unsaved edits" &&
          String(d.severity).toLowerCase() === "info",
      ),
    ).toBe(true);
  });

  test("test_store_init_discards_when_sessionStorage_base_sha_does_not_match", async () => {
    const currentTree = makeDealFixture("current-before-discard");
    seedMainSession(BASE_SHA, currentTree);

    const key = `bma:draft:${DEAL_ID}:main`;
    sessionStorageMock.setItem(
      key,
      JSON.stringify({
        working_tree: makeDealFixture("stale-draft"),
        base_sha: HEAD_SHA,
        saved_at: new Date().toISOString(),
      }),
    );

    await subscribeAutosaveForTests();

    const after = useDealStore.getState();
    expect(
      after.sessions.main.diagnostics.some(
        (d) =>
          d.code === "DRAFT_DISCARDED" &&
          d.message === "Unsaved edits discarded because the deal advanced" &&
          String(d.severity).toLowerCase() === "info",
      ),
    ).toBe(true);
    expect(sessionStorageMock.removeItem).toHaveBeenCalledWith(key);
    expect(sessionStorageMock.getItem(key)).toBeNull();
  });

  test("test_local_draft_state_deal_id_does_not_autosave_to_backend", async () => {
    await subscribeAutosaveForTests();
    useDealStore.getState().setDealId(LOCAL_DRAFT_ID);

    useDealStore.getState().dispatch({
      type: "addBond",
      payload: makeBond("LOCAL_DRAFT_NO_BACKEND_AUTOSAVE"),
    });

    vi.advanceTimersByTime(2000);

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(sessionStorageMock.setItem).toHaveBeenCalledWith(
      `bma:draft:${LOCAL_DRAFT_ID}:main`,
      expect.any(String),
    );
  });

  test("test_promote_local_draft_emits_blocked_on_backend_until_endpoint_exists", async () => {
    await subscribeAutosaveForTests();
    useDealStore.getState().setDealId(LOCAL_DRAFT_ID);

    const stateBefore = useDealStore.getState();
    const dealIdBefore = stateBefore.deal_id;
    const baseShasBefore = Object.fromEntries(
      Object.entries(stateBefore.sessions).map(([id, s]) => [id, s.base_sha]),
    );
    const workingTreesBefore = Object.fromEntries(
      Object.entries(stateBefore.sessions).map(([id, s]) => [id, s.working_tree]),
    );

    const promoteLocalDraft = getPromoteLocalDraftAction();

    // (a) the action throws with BLOCKED_ON_BACKEND
    await expect(promoteLocalDraft()).rejects.toThrow("BLOCKED_ON_BACKEND");

    const after = useDealStore.getState();

    // (b) BLOCKED_ON_BACKEND ERROR diagnostic is appended to main session
    expect(
      after.sessions.main.diagnostics.some(
        (d) =>
          d.code === "BLOCKED_ON_BACKEND" &&
          d.severity === "error" &&
          d.path === "$" &&
          String(d.message).includes("follow-on ticket"),
      ),
    ).toBe(true);

    // (c) state is unchanged: deal_id, base_sha, working_tree untouched
    expect(after.deal_id).toBe(dealIdBefore);
    for (const [id, sha] of Object.entries(baseShasBefore)) {
      expect(after.sessions[id]?.base_sha).toBe(sha);
    }
    for (const [id, tree] of Object.entries(workingTreesBefore)) {
      expect(after.sessions[id]?.working_tree).toEqual(tree);
    }

    // No backend fetch was attempted
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("test_sequential_autosaves_advance_base_sha_without_self_conflict", async () => {
    await subscribeAutosaveForTests();

    const SHA1 = "1".repeat(40);
    const SHA2 = "2".repeat(40);

    // First autosave: mock fetch returns SHA1
    fetchSpy.mockResolvedValueOnce(jsonResponse({ status: "ok", sha: SHA1 }));
    useDealStore.getState().dispatch({
      type: "addBond",
      payload: makeBond("SEQ_AUTOSAVE_1"),
    });
    await vi.advanceTimersByTimeAsync(2000);

    expect(useDealStore.getState().sessions.main.base_sha).toBe(SHA1);

    // Second autosave: mock fetch returns SHA2
    fetchSpy.mockResolvedValueOnce(jsonResponse({ status: "ok", sha: SHA2 }));
    useDealStore.getState().dispatch({
      type: "addBond",
      payload: makeBond("SEQ_AUTOSAVE_2"),
    });
    await vi.advanceTimersByTimeAsync(2000);

    const commitCalls = getCommitCalls(fetchSpy);
    expect(commitCalls).toHaveLength(2);

    const secondBody = JSON.parse(
      String((commitCalls[1][1] as RequestInit).body),
    ) as { parent_sha: string };
    expect(secondBody.parent_sha).toBe(SHA1);

    expect(useDealStore.getState().sessions.main.base_sha).toBe(SHA2);
  });

  test("test_autosave_does_not_fire_on_setActiveSession_or_setDealId_or_setDiagnostics", async () => {
    await subscribeAutosaveForTests();

    // Seed state with one dispatch, then consume its debounce so the fetchSpy
    // accumulates no calls from the seed itself.
    useDealStore.getState().dispatch({
      type: "addBond",
      payload: makeBond("SEED_FOR_NO_DISPATCH_TEST"),
    });
    await vi.advanceTimersByTimeAsync(2000);
    fetchSpy.mockClear();

    // These mutations change store state but NOT the active session's working_tree.
    useDealStore.getState().setDealId("deal_changed_no_dispatch_test");
    useDealStore.getState().setDiagnostics("main", [
      {
        code: "NOOP_DIAG",
        severity: "info" as const,
        path: "",
        message: "no-op diagnostic",
        payload: {},
      },
    ]);
    useDealStore.getState().setActiveSession("main");

    await vi.advanceTimersByTimeAsync(2000);

    // No backend commit should have been scheduled or fired.
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("test_sessionstorage_quota_error_surfaces_warning_diagnostic", async () => {
    await subscribeAutosaveForTests();

    // Override setItem to simulate a QuotaExceededError after subscription is live.
    sessionStorageMock.setItem.mockImplementation(() => {
      throw new DOMException("QuotaExceededError", "QuotaExceededError");
    });

    useDealStore.getState().dispatch({
      type: "addBond",
      payload: makeBond("QUOTA_EXCEEDED_BOND"),
    });

    const after = useDealStore.getState();
    expect(
      after.sessions.main.diagnostics.some(
        (d) =>
          d.code === "SESSIONSTORAGE_WRITE_FAILED" &&
          d.severity === "warning" &&
          d.path === "$" &&
          String(d.message).includes("durable"),
      ),
    ).toBe(true);
  });

  test("test_autosave_is_suppressed_when_conflictState_is_set", async () => {
    await subscribeAutosaveForTests();

    const payload = useDealStore.getState().sessions.main.working_tree;
    useDealStore.setState({
      conflictState: {
        kind: "STALE_PARENT_SHA",
        sessionId: "main",
        head_sha: HEAD_SHA,
        attempted_commit: {
          author: "conflict-author",
          message: "conflict-message",
          payload,
        },
      },
    });

    useDealStore.getState().dispatch({
      type: "addBond",
      payload: makeBond("CONFLICT_SUPPRESSED_AUTOSAVE"),
    });

    vi.advanceTimersByTime(2000);
    expect(getCommitCalls(fetchSpy)).toHaveLength(0);
  });

  test("test_autosave_does_not_fire_on_reloadFromHead", async () => {
    await subscribeAutosaveForTests();

    // Dispatch then consume the debounce so we have a clean baseline.
    useDealStore.getState().dispatch({
      type: "addBond",
      payload: makeBond("RELOAD_SETUP_BOND"),
    });
    await vi.advanceTimersByTimeAsync(2000);
    fetchSpy.mockClear();

    // Use mockImplementation so each fetch call gets a fresh Response body
    // (a single Response object can only be read once).
    fetchSpy.mockImplementation((url: RequestInfo | URL) => {
      if (String(url).includes("/show")) {
        return Promise.resolve(jsonResponse(makeDealFixture("head-tree")));
      }
      return Promise.resolve(jsonResponse({ status: "ok", sha: "e".repeat(40) }));
    });

    // Simulate a conflict so reloadFromHead is callable.
    const payload = useDealStore.getState().sessions.main.working_tree;
    useDealStore.setState({
      conflictState: {
        kind: "STALE_PARENT_SHA",
        sessionId: "main",
        head_sha: HEAD_SHA,
        attempted_commit: { author: "a", message: "m", payload },
      },
    });

    // reloadFromHead mutates working_tree via set() — does NOT increment
    // dispatch_revision — must NOT schedule or fire another autosave commit.
    await useDealStore.getState().reloadFromHead("main");

    await vi.advanceTimersByTimeAsync(2000);

    // Only the /show fetch from reloadFromHead itself; zero commit calls.
    expect(getCommitCalls(fetchSpy)).toHaveLength(0);
  });

  test("test_autosave_skips_when_deal_id_is_empty", async () => {
    // Override deal_id back to "" (initial/uninitialized state).
    useDealStore.setState({ deal_id: "" });

    await subscribeAutosaveForTests();

    useDealStore.getState().dispatch({
      type: "addBond",
      payload: makeBond("EMPTY_DEAL_ID_BOND"),
    });

    await vi.advanceTimersByTimeAsync(2000);

    // No backend fetch and no sessionStorage write when deal_id is blank.
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(sessionStorageMock.setItem).not.toHaveBeenCalled();
  });

  test("test_autosave_success_rewrites_sessionStorage_with_advanced_base_sha", async () => {
    const SHA1 = "1".repeat(40);
    fetchSpy.mockResolvedValue(jsonResponse({ status: "ok", sha: SHA1 }));

    await subscribeAutosaveForTests();

    useDealStore.getState().dispatch({
      type: "addBond",
      payload: makeBond("REWRITE_SESSION_STORAGE_ON_SUCCESS"),
    });

    // Advance past debounce; await the commit promise resolution.
    await vi.advanceTimersByTimeAsync(2000);

    // After commit resolves with SHA1, sessionStorage must be re-written with
    // base_sha: SHA1 so a crash-restore sees the advanced base.
    const expectedKey = `bma:draft:${DEAL_ID}:main`;
    const setItemCalls = sessionStorageMock.setItem.mock.calls as [string, string][];
    const lastWrite = [...setItemCalls]
      .reverse()
      .find(([k]) => k === expectedKey);

    expect(lastWrite).toBeDefined();
    const persisted = JSON.parse(lastWrite![1]) as {
      working_tree: unknown;
      base_sha: string;
      saved_at: string;
    };
    expect(persisted.base_sha).toBe(SHA1);
    expect(persisted).toHaveProperty("working_tree");
    expect(persisted).toHaveProperty("saved_at");
  });

  test("test_autosave_consumes_pending_commit_message_and_clears_slot", async () => {
    await subscribeAutosaveForTests();

    useDealStore.setState((state) => {
      const mainWithPending = {
        ...state.sessions.main,
        pending_commit_message: "Canonicalize consolidate rule run [2..3]",
      } as typeof state.sessions.main;
      return {
        sessions: {
          ...state.sessions,
          main: mainWithPending,
        },
      };
    });

    useDealStore.getState().dispatch({
      type: "addBond",
      payload: makeBond("PENDING_MESSAGE_CONSUMED"),
    });

    await vi.advanceTimersByTimeAsync(2000);

    const commitCalls = getCommitCalls(fetchSpy);
    expect(commitCalls).toHaveLength(1);
    const commitBody = JSON.parse(String((commitCalls[0][1] as RequestInit).body)) as {
      message: string;
    };
    expect(commitBody.message).toBe("Canonicalize consolidate rule run [2..3]");

    const mainSession = useDealStore.getState().sessions.main as unknown as {
      pending_commit_message?: string | null;
    };
    expect(mainSession.pending_commit_message).toBeNull();
  });

  test("test_autosave_falls_back_to_default_message_when_pending_is_null", async () => {
    await subscribeAutosaveForTests();

    const before = useDealStore.getState().sessions.main as unknown as {
      pending_commit_message?: string | null;
    };
    expect(before.pending_commit_message).toBeNull();

    useDealStore.getState().dispatch({
      type: "addBond",
      payload: makeBond("DEFAULT_AUTOSAVE_MESSAGE"),
    });

    await vi.advanceTimersByTimeAsync(2000);

    const commitCalls = getCommitCalls(fetchSpy);
    expect(commitCalls).toHaveLength(1);
    const commitBody = JSON.parse(String((commitCalls[0][1] as RequestInit).body)) as {
      message: string;
    };
    expect(commitBody.message).toBe("autosave");
  });

  test("test_autosave_last_write_wins_when_two_actions_within_debounce_window", async () => {
    await subscribeAutosaveForTests();

    useDealStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        main: {
          ...state.sessions.main,
          working_tree: {
            ...state.sessions.main.working_tree,
            waterfall_rules: [
              makeCanonicalizableRule("run0", 0, "A1"),
              makeCanonicalizableRule("run1", 1, "A2"),
              makeCanonicalizableRule("run2", 2, "A3"),
              makeCanonicalizableRule("run3", 3, "A4"),
            ],
          },
        },
      },
    }));

    dispatchCanonicalizeConsolidateRuleRun(2, 3);
    vi.advanceTimersByTime(300);
    dispatchCanonicalizeConsolidateRuleRun(0, 1);

    const preCommitSession = useDealStore.getState().sessions.main as unknown as {
      pending_commit_message?: string | null;
    };
    expect(preCommitSession.pending_commit_message).toBe("Canonicalize consolidate rule run [0..1]");

    await vi.advanceTimersByTimeAsync(2000);

    const commitCalls = getCommitCalls(fetchSpy);
    expect(commitCalls).toHaveLength(1);
    const commitBody = JSON.parse(String((commitCalls[0][1] as RequestInit).body)) as {
      message: string;
    };
    expect(commitBody.message).toBe("Canonicalize consolidate rule run [0..1]");
    expect(commitBody.message).not.toBe("Canonicalize consolidate rule run [2..3]");

    const postCommitSession = useDealStore.getState().sessions.main as unknown as {
      pending_commit_message?: string | null;
    };
    expect(postCommitSession.pending_commit_message).toBeNull();
  });
});
