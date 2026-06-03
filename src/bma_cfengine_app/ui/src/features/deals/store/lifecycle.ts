import type { DealStoreState } from "./useDealStore";
import {
  mergeBranch,
  deleteBranch,
  commitToBranch,
  CommitConflictError,
} from "./api";
import type { DealState } from "./session";

type Setter = (
  partialOrFn:
    | Partial<DealStoreState>
    | ((state: DealStoreState) => Partial<DealStoreState>),
) => void;
type Getter = () => DealStoreState;

export function createLifecycleActions(set: Setter, get: Getter) {
  return {
    previewEphemeralSession(sessionId: string): void {
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
      const state = get();
      const session = state.sessions[sessionId];
      const deal_id = state.deal_id;

      const result = await mergeBranch(deal_id, {
        branch: session.branch_name,
        into: "main",
      });

      if (result.status === "success") {
        const sha = result.sha!;
        const res = await fetch(
          `/deals/${deal_id}/show?sha=${sha}&path=deal.json`,
        );
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
          };
        });
        zundo.resume();
        zundo.handleSet(oldMainWorkingTree);
      } else {
        set({ applyConflict: { sessionId, diagnostic: result.diagnostic } });
      }
    },

    async discardEphemeralSession(sessionId: string): Promise<void> {
      const state = get();
      const session = state.sessions[sessionId];
      const deal_id = state.deal_id;

      await deleteBranch(deal_id, session.branch_name);

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

      const head_sha = conflictState.head_sha;
      if (!head_sha) {
        throw new Error("reloadFromHead: head_sha is null in conflictState");
      }

      const deal_id = state.deal_id;
      const res = await fetch(
        `/deals/${deal_id}/show?sha=${head_sha}&path=deal.json`,
      );
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
