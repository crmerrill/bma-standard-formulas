import type { DealStoreState } from "./useDealStore";
import {
  mergeBranch,
  deleteBranch,
  commitToBranch,
  CommitConflictError,
  type CommitBody,
} from "./api";
import type { DealState } from "./session";

type Setter = (
  partialOrFn:
    | Partial<DealStoreState>
    | ((state: DealStoreState) => Partial<DealStoreState>),
) => void;
type Getter = () => DealStoreState;

const EPHEMERAL_ONLY_MSG =
  "Cannot operate on main session via ephemeral lifecycle action";

export function createLifecycleActions(set: Setter, get: Getter) {
  const inFlightApplies = new Set<string>();

  return {
    async commitWithConflictHandling(
      deal_id: string,
      body: CommitBody,
      sessionId: string,
    ): Promise<{ sha: string }> {
      try {
        return await commitToBranch(deal_id, body);
      } catch (err) {
        if (err instanceof CommitConflictError) {
          set({
            conflictState: {
              kind: "STALE_PARENT_SHA",
              sessionId,
              head_sha: err.head_sha,
              attempted_commit: {
                author: body.author,
                message: body.message,
                payload: body.payload,
              },
            },
          });
        }
        throw err;
      }
    },

    previewEphemeralSession(sessionId: string): void {
      if (sessionId === "main") {
        throw new Error(EPHEMERAL_ONLY_MSG);
      }
      set((state) => ({
        activeSessionId: sessionId,
        sessions: {
          ...state.sessions,
          [sessionId]: {
            ...state.sessions[sessionId],
            ui_role: "preview" as const,
          },
        },
      }));
    },

    async applyEphemeralSessionToMain(sessionId: string): Promise<void> {
      if (sessionId === "main") {
        throw new Error(EPHEMERAL_ONLY_MSG);
      }
      if (inFlightApplies.has(sessionId)) {
        throw new Error(
          `applyEphemeralSessionToMain: session ${sessionId} already in flight`,
        );
      }
      inFlightApplies.add(sessionId);
      try {
        const state = get();
        const session = state.sessions[sessionId];
        const deal_id = state.deal_id;

        const result = await mergeBranch(deal_id, {
          branch: session.branch_name,
          into: "main",
        });

        if (result.status === "success") {
          const sha = result.sha;
          if (sha === null) {
            throw new Error("Protocol violation: success with null sha");
          }
          const params = new URLSearchParams({ sha, path: "deal.json" });
          const res = await fetch(
            `/deals/${deal_id}/show?${params.toString()}`,
          );
          if (!res.ok) {
            throw new Error(`/show endpoint failed: ${res.status}`);
          }
          const newWorkingTree = (await res.json()) as DealState;

          const mainState = get().sessions.main;
          const oldMainWorkingTree = mainState.working_tree;
          const zundo = mainState.zundo_history;

          zundo.pause();
          set((s) => {
            const { [sessionId]: _dropped, ...restSessions } = s.sessions;
            return {
              sessions: {
                ...restSessions,
                main: {
                  ...restSessions.main,
                  base_sha: sha,
                  working_tree: newWorkingTree,
                },
              },
              activeSessionId:
                s.activeSessionId === sessionId ? "main" : s.activeSessionId,
            };
          });
          zundo.resume();
          zundo.handleSet(oldMainWorkingTree);
        } else {
          set({ applyConflict: { sessionId, diagnostic: result.diagnostic } });
        }
      } finally {
        inFlightApplies.delete(sessionId);
      }
    },

    async discardEphemeralSession(sessionId: string): Promise<void> {
      if (sessionId === "main") {
        throw new Error(EPHEMERAL_ONLY_MSG);
      }
      const state = get();
      const session = state.sessions[sessionId];
      const deal_id = state.deal_id;

      try {
        await deleteBranch(deal_id, session.branch_name);
      } catch (err) {
        set((s) => ({
          sessions: {
            ...s.sessions,
            [sessionId]: {
              ...s.sessions[sessionId],
              diagnostics: [
                ...(s.sessions[sessionId]?.diagnostics ?? []),
                {
                  code: "BRANCH_DELETE_FAILED",
                  severity: "error" as const,
                  path: "$",
                  message:
                    err instanceof Error ? err.message : String(err),
                  payload: { branch_name: session.branch_name },
                },
              ],
            },
          },
        }));
        throw err;
      }

      set((s) => {
        const { [sessionId]: _dropped, ...restSessions } = s.sessions;
        const activeSessionId =
          s.activeSessionId === sessionId ? "main" : s.activeSessionId;
        return { sessions: restSessions, activeSessionId };
      });
    },

    async forceCommit(sessionId: string): Promise<void> {
      const state = get();
      const conflictState = state.conflictState;
      if (!conflictState) {
        throw new Error("forceCommit: no conflictState present");
      }
      if (conflictState.sessionId !== sessionId) {
        throw new Error("conflictState.sessionId mismatch");
      }

      const session = state.sessions[sessionId];
      const deal_id = state.deal_id;
      const { author, message, payload } = conflictState.attempted_commit;
      const parent_sha = session.base_sha;

      try {
        const result = await commitToBranch(deal_id, {
          author,
          message,
          parent_sha,
          branch: session.branch_name,
          payload,
          force: true,
        });

        set((s) => ({
          conflictState: null,
          sessions: {
            ...s.sessions,
            [sessionId]: {
              ...s.sessions[sessionId],
              base_sha: result.sha,
            },
          },
        }));
      } catch (err) {
        if (err instanceof CommitConflictError) {
          const headSha = err.head_sha;
          set((s) => ({
            conflictState: s.conflictState
              ? { ...s.conflictState, head_sha: headSha }
              : null,
          }));
        }
        throw err;
      }
    },

    async reloadFromHead(sessionId: string): Promise<void> {
      const state = get();
      const conflictState = state.conflictState;
      if (!conflictState) {
        throw new Error("reloadFromHead: no conflictState present");
      }
      if (conflictState.sessionId !== sessionId) {
        throw new Error("conflictState.sessionId mismatch");
      }

      const head_sha = conflictState.head_sha;
      if (!head_sha) {
        throw new Error("reloadFromHead: head_sha is null in conflictState");
      }

      const deal_id = state.deal_id;
      const params = new URLSearchParams({ sha: head_sha, path: "deal.json" });
      const res = await fetch(`/deals/${deal_id}/show?${params.toString()}`);
      if (!res.ok) {
        throw new Error(`/show endpoint failed: ${res.status}`);
      }
      const newWorkingTree = (await res.json()) as DealState;

      set((s) => ({
        conflictState: null,
        sessions: {
          ...s.sessions,
          [sessionId]: {
            ...s.sessions[sessionId],
            base_sha: head_sha,
            working_tree: newWorkingTree,
          },
        },
      }));
    },
  };
}
