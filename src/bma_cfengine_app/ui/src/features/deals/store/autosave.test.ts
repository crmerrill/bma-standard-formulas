import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { compileToIR } from "./compile";
import { useDealStore } from "./useDealStore";
import type { DealStoreState } from "./useDealStore";
import type { BondDefIR, DealDefinitionIR } from "../ir-types";

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

  test("test_promote_local_draft_rewrites_state_deal_id_and_migrates_sessionStorage_keys", async () => {
    await subscribeAutosaveForTests();
    useDealStore.getState().setDealId(LOCAL_DRAFT_ID);

    const oldKey = `bma:draft:${LOCAL_DRAFT_ID}:main`;
    const currentTree = useDealStore.getState().sessions.main.working_tree;
    sessionStorageMock.setItem(
      oldKey,
      JSON.stringify({
        working_tree: currentTree,
        base_sha: BASE_SHA,
        saved_at: new Date().toISOString(),
      }),
    );

    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        deal_id: REAL_DEAL_ID,
        id: REAL_DEAL_ID,
        initial_sha: REAL_SHA,
        sha: REAL_SHA,
      }),
    );

    const promoteLocalDraft = getPromoteLocalDraftAction();
    await promoteLocalDraft();

    const after = useDealStore.getState();
    expect(after.deal_id).toBe(REAL_DEAL_ID);
    expect(after.sessions.main.base_sha).toBe(REAL_SHA);
    expect(sessionStorageMock.getItem(oldKey)).toBeNull();
    expect(
      sessionStorageMock.getItem(`bma:draft:${REAL_DEAL_ID}:main`),
    ).not.toBeNull();
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
});
