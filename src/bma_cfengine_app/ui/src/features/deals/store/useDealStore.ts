import { create } from "zustand";
import type { DealDefinitionIR } from "../ir-types";
import type { DealAction } from "./actions";
import { applyAction } from "./actions";

export type DealState = DealDefinitionIR;

export type ConflictState = {
  kind: "STALE_PARENT_SHA";
  sessionId: string;
  head_sha: string | null;
  attempted_commit: { author: string; message: string; payload: DealState };
} | null;

export type ApplyConflict = {
  sessionId: string;
  diagnostic: unknown; // MergeConflictPayload — placeholder; real type lives in irvc-2 envelope
} | null;

export type DocumentSession = {
  session_id: string;
  branch_name: string; // sds-2 will brand this as BranchName; sds-1 keeps it as string
  base_sha: string;
  working_tree: DealState;
  validation_target: "self";
  commit_target: string;
  zundo_history: unknown; // sds-2 will tighten to TemporalState<DealState>
  ui_role: "primary" | "preview";
  diagnostics: unknown[]; // sds-2 pins this to DiagnosticPayload[]
};

export type DealStoreState = {
  sessions: Record<string, DocumentSession>;
  activeSessionId: string;
  deal_id: string;
  conflictState: ConflictState;
  applyConflict: ApplyConflict;
  // Actions (sds-1 initial vocabulary)
  setDealId: (deal_id: string) => void;
  dispatch: (action: DealAction) => void;
};

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

export const useDealStore = create<DealStoreState>()((set, get) => ({
  sessions: {
    main: {
      session_id: "main",
      branch_name: "main",
      base_sha: "",
      working_tree: emptyDealState(),
      validation_target: "self",
      commit_target: "main",
      zundo_history: null, // sds-2 will populate
      ui_role: "primary",
      diagnostics: [],
    },
  },
  activeSessionId: "main",
  deal_id: "",
  conflictState: null,
  applyConflict: null,
  setDealId: (deal_id) => set({ deal_id }),
  dispatch: (action) => set((state) => applyAction(state, action)),
}));
