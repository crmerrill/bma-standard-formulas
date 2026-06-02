import type { DealDefinitionIR } from "../ir-types";
import type { DiagnosticPayload } from "./diagnostics-types";

export type DealState = DealDefinitionIR;

export type BranchName = string & { readonly __brand: "BranchName" };

const BRANCH_PATTERN =
  /^(main|ai\/turn-[a-z0-9][a-z0-9-]{0,63}|solver\/run-[a-z0-9][a-z0-9-]{0,63}|what-if\/[a-z0-9][a-z0-9-]{0,63})$/;

export function mkBranchName(name: string): BranchName {
  if (!BRANCH_PATTERN.test(name)) {
    throw new Error(`Invalid branch name: "${name}"`);
  }
  return name as BranchName;
}

export type TemporalState<T> = {
  getState: () => { pastStates: T[]; futureStates: T[] };
  pause: () => void;
  resume: () => void;
};

export type DocumentSession = {
  session_id: string;
  branch_name: BranchName;
  base_sha: string;
  working_tree: DealState;
  validation_target: "self";
  commit_target: BranchName;
  zundo_history: TemporalState<DealState>;
  ui_role: "primary" | "preview";
  diagnostics: DiagnosticPayload[];
};
