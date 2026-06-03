import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { useDealStore } from "./useDealStore";
import type { DealStoreState } from "./useDealStore";
import type { BondDefIR, DealDefinitionIR } from "../ir-types";

type DealState = DealDefinitionIR;
type BondDef = BondDefIR;

type Sds4ApiActions = {
  forceCommit: (sessionId: string) => Promise<void>;
  reloadFromHead: (sessionId: string) => Promise<void>;
};

const DEAL_ID = "deal_sds4_api";
const BASE_SHA = "a".repeat(40);
const HEAD_SHA = "b".repeat(40);

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

function getApiAction<K extends keyof Sds4ApiActions>(key: K): Sds4ApiActions[K] {
  const state = useDealStore.getState() as DealStoreState & Partial<Sds4ApiActions>;
  const action = state[key];
  expect(typeof action).toBe("function");
  return action as Sds4ApiActions[K];
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

function seedConflictState(sessionId: string, attemptedPayload: DealState): void {
  useDealStore.setState({
    conflictState: {
      kind: "STALE_PARENT_SHA",
      sessionId,
      head_sha: null,
      attempted_commit: {
        author: "test-author",
        message: "test stale parent commit",
        payload: attemptedPayload,
      },
    },
  });
}

describe("sds-4 API 409 conflict integration", () => {
  beforeEach(() => {
    useDealStore.setState(useDealStore.getInitialState(), true);
    useDealStore.getState().setDealId(DEAL_ID);
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("test_commit_409_conflict_reads_detail_head_sha_from_irvc4_envelope", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const attemptedPayload = makeDealFixture("attempted-commit-head-sha");
    seedMainSession(BASE_SHA, attemptedPayload);
    seedConflictState("main", attemptedPayload);

    fetchSpy.mockResolvedValueOnce(
      jsonResponse(
        {
          detail: {
            code: "STALE_PARENT_SHA",
            head_sha: HEAD_SHA,
          },
          current_head_sha: "WRONG_FIELD_MUST_NOT_BE_USED",
        },
        409,
      ),
    );

    const forceCommit = getApiAction("forceCommit");
    try {
      await forceCommit("main");
    } catch {
      // Keep assertions on state; runtime throw policy is implementation-defined.
    }

    const after = useDealStore.getState();
    expect(after.conflictState?.kind).toBe("STALE_PARENT_SHA");
    expect(after.conflictState?.head_sha).toBe(HEAD_SHA);
  });

  test("test_commit_409_conflict_sets_conflictState_with_head_sha_and_attempted_payload", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const attemptedPayload = makeDealFixture("attempted-commit-shape");
    seedMainSession(BASE_SHA, attemptedPayload);
    seedConflictState("main", attemptedPayload);

    fetchSpy.mockResolvedValueOnce(
      jsonResponse(
        {
          detail: {
            code: "STALE_PARENT_SHA",
            head_sha: HEAD_SHA,
          },
        },
        409,
      ),
    );

    const forceCommit = getApiAction("forceCommit");
    try {
      await forceCommit("main");
    } catch {
      // Keep assertions on state; runtime throw policy is implementation-defined.
    }

    expect(useDealStore.getState().conflictState).toEqual({
      kind: "STALE_PARENT_SHA",
      sessionId: "main",
      head_sha: HEAD_SHA,
      attempted_commit: {
        author: "test-author",
        message: "test stale parent commit",
        payload: attemptedPayload,
      },
    });
  });

  test("test_forceCommit_retries_with_force_true_and_clears_conflictState_on_success", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const attemptedPayload = makeDealFixture("force-commit-success");
    seedMainSession(BASE_SHA, attemptedPayload);
    seedConflictState("main", attemptedPayload);

    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "ok",
        sha: "c".repeat(40),
      }),
    );

    const forceCommit = getApiAction("forceCommit");
    await forceCommit("main");

    const commitCall = fetchSpy.mock.calls.find(([url]) =>
      String(url).includes(`/deals/${DEAL_ID}/commit`),
    );
    expect(commitCall).toBeDefined();
    const commitInit = commitCall?.[1] as RequestInit;
    expect(commitInit.method).toBe("POST");
    expect(JSON.parse(String(commitInit.body))).toEqual(
      expect.objectContaining({
        force: true,
        payload: attemptedPayload,
        parent_sha: BASE_SHA,
        branch: "main",
      }),
    );

    expect(useDealStore.getState().conflictState).toBeNull();
  });

  test("test_reloadFromHead_discards_pending_and_reseeds_working_tree_from_head_sha", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const pendingTree = makeDealFixture("pending-local-edits");
    const headTree = makeDealFixture("head-reseeded");
    pendingTree.bonds.push(makeBond("LOCAL_UNCOMMITTED_BOND"));

    seedMainSession(BASE_SHA, pendingTree);
    useDealStore.setState({
      conflictState: {
        kind: "STALE_PARENT_SHA",
        sessionId: "main",
        head_sha: HEAD_SHA,
        attempted_commit: {
          author: "test-author",
          message: "pending write",
          payload: pendingTree,
        },
      },
    });

    fetchSpy.mockResolvedValueOnce(jsonResponse(headTree));

    const reloadFromHead = getApiAction("reloadFromHead");
    await reloadFromHead("main");

    const after = useDealStore.getState();
    expect(after.sessions.main.base_sha).toBe(HEAD_SHA);
    expect(after.sessions.main.working_tree).toEqual(headTree);
    expect(after.sessions.main.working_tree).not.toEqual(pendingTree);
    expect(after.conflictState).toBeNull();

    const showCall = fetchSpy.mock.calls.find(([url]) => {
      const value = String(url);
      return (
        value.includes(`/deals/${DEAL_ID}/show?`) &&
        value.includes(`sha=${HEAD_SHA}`) &&
        value.includes("path=deal.json")
      );
    });
    expect(showCall).toBeDefined();
  });
});
