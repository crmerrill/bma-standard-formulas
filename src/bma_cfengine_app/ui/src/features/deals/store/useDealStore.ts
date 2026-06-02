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

export type { DealState };

export type ConflictState = {
  kind: "STALE_PARENT_SHA";
  sessionId: string;
  head_sha: string | null;
  attempted_commit: { author: string; message: string; payload: DealState };
} | null;

export type ApplyConflict = {
  sessionId: string;
  diagnostic: unknown;
} | null;

export type DealStoreState = {
  sessions: Record<string, DocumentSession>;
  activeSessionId: string;
  deal_id: string;
  conflictState: ConflictState;
  applyConflict: ApplyConflict;
  setDealId: (deal_id: string) => void;
  dispatch: (action: DealAction) => void;
  createEphemeralSession: (args: {
    branch_name: BranchName;
    base_sha: string;
    ui_role: "primary" | "preview";
  }) => Promise<string>;
  setActiveSession: (sessionId: string) => void;
  setDiagnostics: (sessionId: string, payloads: DiagnosticPayload[]) => void;
  deleteSession: (sessionId: string) => void;
};

function createPerSessionTemporal(
  pastStates: DealState[] = [],
): TemporalState<DealState> {
  return {
    getState: () => ({ pastStates, futureStates: [] }),
    pause: () => {},
    resume: () => {},
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
      zundo_history: createPerSessionTemporal(),
      ui_role: "primary",
      diagnostics: [],
    },
  },
  activeSessionId: "main",
  deal_id: "",
  conflictState: null,
  applyConflict: null,

  setDealId: (deal_id) => set({ deal_id }),

  dispatch: (action) =>
    set((state) => {
      const sessionId = state.activeSessionId;
      const session = state.sessions[sessionId];
      const previousWorkingTree = session.working_tree;

      const result = applyAction(state, action);
      const newSessions = result.sessions ?? state.sessions;
      const updatedSession = newSessions[sessionId];

      if (!session.zundo_history) {
        return result;
      }

      const currentPastStates =
        session.zundo_history.getState().pastStates;

      return {
        ...result,
        sessions: {
          ...newSessions,
          [sessionId]: {
            ...updatedSession,
            zundo_history: createPerSessionTemporal([
              ...currentPastStates,
              previousWorkingTree,
            ]),
          },
        },
      };
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

    const showRes = await fetch(
      `/deals/${deal_id}/show?sha=${base_sha}&path=deal.json`,
    );
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
          zundo_history: createPerSessionTemporal(),
          ui_role,
          diagnostics: [],
        },
      },
    }));

    return session_id;
  },

  setActiveSession: (sessionId) => set({ activeSessionId: sessionId }),

  setDiagnostics: (sessionId, payloads) =>
    set((state) => ({
      sessions: {
        ...state.sessions,
        [sessionId]: {
          ...state.sessions[sessionId],
          diagnostics: payloads,
        },
      },
    })),

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
      return { sessions: rest };
    });
  },
}));
