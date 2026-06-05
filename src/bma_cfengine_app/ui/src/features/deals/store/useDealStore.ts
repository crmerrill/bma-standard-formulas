import { create } from "zustand";
import type { DealDefinitionIR } from "../ir-types";
import type { DealAction } from "./actions";
import { applyAction } from "./actions";
import type { DiagnosticPayload } from "./diagnostics-types";
import type {
  BranchName,
  DocumentSession,
  DealState,
  TemporalState,
} from "./session";
import { mkBranchName } from "./session";
import { createLifecycleActions } from "./lifecycle";
import type { MergeConflictPayload, CommitBody } from "./api";

export type { DealState };

export type ConflictState = {
  kind: "STALE_PARENT_SHA";
  sessionId: string;
  head_sha: string | null;
  attempted_commit: { author: string; message: string; payload: DealState };
} | null;

export type ApplyConflict = {
  sessionId: string;
  diagnostic: MergeConflictPayload;
} | null;

export type DealStoreState = {
  sessions: Record<string, DocumentSession>;
  activeSessionId: string;
  deal_id: string;
  dispatch_revision: number;
  conflictState: ConflictState;
  applyConflict: ApplyConflict;
  setDealId: (deal_id: string) => void;
  dispatch: (action: DealAction) => void;
  createEphemeralSession: (args: {
    branch_name: BranchName;
    base_sha: string;
    ui_role: "preview";
  }) => Promise<string>;
  setActiveSession: (sessionId: string) => void;
  setDiagnostics: (sessionId: string, payloads: DiagnosticPayload[]) => void;
  mergeDiagnostics: (
    sessionId: string,
    source: "worker" | "backend",
    payloads: DiagnosticPayload[],
  ) => void;
  deleteSession: (sessionId: string) => void;
  commitWithConflictHandling: (
    deal_id: string,
    body: CommitBody,
    sessionId: string,
  ) => Promise<{ sha: string }>;
  previewEphemeralSession: (sessionId: string) => void;
  applyEphemeralSessionToMain: (sessionId: string) => Promise<void>;
  discardEphemeralSession: (sessionId: string) => Promise<void>;
  forceCommit: (sessionId: string) => Promise<void>;
  reloadFromHead: (sessionId: string) => Promise<void>;
  promoteLocalDraft: () => Promise<void>;
};

// ---------------------------------------------------------------------------
// Internal: per-session diagnostic source-retention map (ve-4 R1 NF M5)
//
// Tracks which (sessionId, code, path) tuples were last written by 'worker'
// vs 'backend' so subsequent worker merges cannot overwrite a backend entry.
// Module-private; not exposed on the public store state to preserve sds-2's
// flat DocumentSession.diagnostics: DiagnosticPayload[] contract.
// ---------------------------------------------------------------------------
const _diagnosticSourceMap = new Map<
  string,
  Map<string, "worker" | "backend">
>();

/** Test-only: returns a deep-cloned snapshot of the internal source map.
 *  Callers may freely mutate the returned map without affecting module-private state. */
export function getDiagnosticSourceMapForTesting(): Map<
  string,
  Map<string, "worker" | "backend">
> {
  const snapshot = new Map<string, Map<string, "worker" | "backend">>();
  for (const [sessionId, sessionMap] of _diagnosticSourceMap.entries()) {
    snapshot.set(sessionId, new Map(sessionMap));
  }
  return snapshot;
}

/**
 * Test-only: clears the entire module-private source map.
 *
 * Call this alongside `useDealStore.setState(useDealStore.getInitialState(), true)`
 * in beforeEach hooks so the source-map provenance is fully reset between test
 * cases, matching what a real page reload would do.
 */
export function resetDiagnosticSourceMapForTesting(): void {
  _diagnosticSourceMap.clear();
}

function createPerSessionTemporal(
  sessionId: string,
  storeSet: (fn: (state: DealStoreState) => Partial<DealStoreState>) => void,
  storeGet: () => DealStoreState,
): TemporalState<DealState> {
  const past: DealState[] = [];
  const future: DealState[] = [];
  let paused = false;

  return {
    getState: () => ({ pastStates: past, futureStates: future }),
    pause: () => {
      paused = true;
    },
    resume: () => {
      paused = false;
    },
    handleSet: (state: DealState) => {
      if (!paused) {
        past.push(state);
        future.length = 0;
      }
    },
    undo: () => {
      if (past.length === 0) return;
      const current = storeGet().sessions[sessionId]?.working_tree;
      if (current === undefined) return;
      const prev = past.pop()!;
      future.push(current);
      storeSet((s) => ({
        sessions: {
          ...s.sessions,
          [sessionId]: { ...s.sessions[sessionId], working_tree: prev },
        },
      }));
    },
    redo: () => {
      if (future.length === 0) return;
      const current = storeGet().sessions[sessionId]?.working_tree;
      if (current === undefined) return;
      const next = future.pop()!;
      past.push(current);
      storeSet((s) => ({
        sessions: {
          ...s.sessions,
          [sessionId]: { ...s.sessions[sessionId], working_tree: next },
        },
      }));
    },
  };
}

function emptyDealState(): DealState {
  return {
    schema_version: "2.0.0",
    deal_name: "",
    bonds: [],
    accounts: [],
    fees: [],
    triggers: [],
    waterfall_rules: [],
    collateral_groups: [],
    deal_knobs: {},
  };
}

const mainBranch = mkBranchName("main");

export const useDealStore = create<DealStoreState>()((set, get) => ({
  sessions: {
    main: {
      session_id: "main",
      branch_name: mainBranch,
      base_sha: "",
      working_tree: emptyDealState(),
      validation_target: "self",
      commit_target: mainBranch,
      zundo_history: createPerSessionTemporal("main", set, get),
      ui_role: "primary",
      diagnostics: [],
      pending_commit_message: null,
    },
  },
  activeSessionId: "main",
  deal_id: "",
  dispatch_revision: 0,
  conflictState: null,
  applyConflict: null,

  setDealId: (deal_id) => set({ deal_id }),

  dispatch: (action) =>
    set((state) => {
      const sessionId = state.activeSessionId;
      const session = state.sessions[sessionId];
      if (!session) return {};
      const oldWorkingTree = session.working_tree;

      const result = applyAction(state, action);
      const newSessions = result.sessions ?? state.sessions;
      const newWorkingTree = newSessions[sessionId]?.working_tree ?? oldWorkingTree;

      if (newWorkingTree !== oldWorkingTree) {
        session.zundo_history.handleSet(oldWorkingTree);
        return { ...result, dispatch_revision: state.dispatch_revision + 1 };
      }

      return result;
    }),

  createEphemeralSession: async ({ branch_name, base_sha, ui_role }) => {
    const deal_id = get().deal_id;
    const session_id = "ephemeral_" + crypto.randomUUID();

    const branchRes = await fetch(`/deals/${deal_id}/branches`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: branch_name, from_sha: base_sha }),
    });
    if (!branchRes.ok) {
      throw new Error(`Branch creation failed: ${branchRes.status}`);
    }

    const params = new URLSearchParams({ sha: base_sha, path: "deal.json" });
    const showRes = await fetch(`/deals/${deal_id}/show?${params.toString()}`);
    if (!showRes.ok) {
      throw new Error(`Show endpoint failed: ${showRes.status}`);
    }
    const working_tree = (await showRes.clone().json()) as DealState;

    set((state) => ({
      sessions: {
        ...state.sessions,
        [session_id]: {
          session_id,
          branch_name,
          base_sha,
          working_tree,
          validation_target: "self" as const,
          commit_target: branch_name,
          zundo_history: createPerSessionTemporal(session_id, set, get),
          ui_role,
          diagnostics: [],
          pending_commit_message: null,
        },
      },
    }));

    return session_id;
  },

  setActiveSession: (sessionId) => set({ activeSessionId: sessionId }),

  setDiagnostics: (sessionId, payloads) => {
    // Replace the entire diagnostics array and reset the source map for this
    // session so subsequent worker merges are not blocked by stale backend-wins
    // entries that pre-dated the replacement.
    if (payloads.length === 0) {
      _diagnosticSourceMap.delete(sessionId);
    } else {
      // Treat all incoming payloads as 'worker' provenance — setDiagnostics is
      // a full replacement (not a merge), so backend-wins protection should not
      // carry forward from a previous merge cycle.
      const newMap = new Map<string, "worker" | "backend">();
      for (const p of payloads) {
        newMap.set(`${p.code}:${p.path}`, "worker");
      }
      _diagnosticSourceMap.set(sessionId, newMap);
    }
    set((state) => ({
      sessions: {
        ...state.sessions,
        [sessionId]: {
          ...state.sessions[sessionId],
          diagnostics: payloads,
        },
      },
    }));
  },

  mergeDiagnostics: (sessionId, source, payloads) => {
    set((state) => {
      const session = state.sessions[sessionId];
      if (!session) return {};

      // Internal source map: per-session, keyed by `${code}:${path}`.
      // Backend-wins persists across subsequent worker merges per ve-4 AC + R1 NF M5.
      let sessionMap = _diagnosticSourceMap.get(sessionId);
      if (!sessionMap) {
        sessionMap = new Map();
        _diagnosticSourceMap.set(sessionId, sessionMap);
      }

      const newKeysToSourceUpgrade = new Map<string, "worker" | "backend">();
      const skipped = new Set<string>();
      for (const p of payloads) {
        const key = `${p.code}:${p.path}`;
        const existingSource = sessionMap.get(key);
        if (existingSource === "backend" && source === "worker") {
          // Backend wins; skip this worker payload entirely.
          skipped.add(key);
          continue;
        }
        newKeysToSourceUpgrade.set(key, source);
      }

      // Build the next diagnostics array:
      // 1. Carry forward existing diagnostics whose keys are NOT being upserted.
      // 2. Append the (filtered) new payloads.
      const upsertedKeys = newKeysToSourceUpgrade;
      const carriedForward: DiagnosticPayload[] = [];
      for (const e of session.diagnostics) {
        const key = `${e.code}:${e.path}`;
        if (!upsertedKeys.has(key)) {
          carriedForward.push(e);
        }
      }
      const appended: DiagnosticPayload[] = [];
      for (const p of payloads) {
        const key = `${p.code}:${p.path}`;
        if (skipped.has(key)) continue;
        appended.push(p);
        sessionMap.set(key, source);
      }

      return {
        sessions: {
          ...state.sessions,
          [sessionId]: {
            ...session,
            diagnostics: [...carriedForward, ...appended],
          },
        },
      };
    });
  },

  deleteSession: (sessionId) => {
    if (sessionId === "main") {
      set((state) => ({
        sessions: {
          ...state.sessions,
          main: {
            ...state.sessions.main,
            diagnostics: [
              ...state.sessions.main.diagnostics,
              {
                code: "SESSION_DELETE_REJECTED",
                severity: "warning" as const,
                path: "",
                message: "Cannot delete the main session",
                payload: {},
              },
            ],
          },
        },
      }));
      return;
    }
    set((state) => {
      const { [sessionId]: _, ...rest } = state.sessions;
      const activeSessionId =
        state.activeSessionId === sessionId ? "main" : state.activeSessionId;
      return { sessions: rest, activeSessionId };
    });
    _diagnosticSourceMap.delete(sessionId);
  },

  promoteLocalDraft: async () => {
    const state = get();

    // Minor #2: guard against non-local deal_id
    if (!state.deal_id.startsWith("local_draft_")) {
      throw new Error("promoteLocalDraft: deal_id is not a local draft");
    }

    // Blocking #1: the required backend create-deal endpoint (git-init shape with
    // initial_sha) does not yet exist. Surface BLOCKED_ON_BACKEND and abort.
    set((s) => ({
      sessions: {
        ...s.sessions,
        main: {
          ...s.sessions.main,
          diagnostics: [
            ...s.sessions.main.diagnostics,
            {
              code: "BLOCKED_ON_BACKEND",
              severity: "error" as const,
              path: "$",
              message:
                "Local draft promotion requires a backend create-deal endpoint that does not yet exist. Track this in a follow-on ticket.",
              payload: {
                feature: "promoteLocalDraft",
                current_deal_id: state.deal_id,
              },
            },
          ],
        },
      },
    }));

    throw new Error("promoteLocalDraft: BLOCKED_ON_BACKEND — see diagnostic");
  },

  ...createLifecycleActions(set, get),
}));
