import { compileToIR } from "./compile";
import type { DealState, DealStoreState } from "./useDealStore";
import type { useDealStore } from "./useDealStore";

type Store = typeof useDealStore;

// Singleton: only one autosave subscription active at a time.
// Calling subscribeAutosave again replaces the previous subscription so
// tests that call subscribeAutosave multiple times don't accumulate listeners.
let _teardown: (() => void) | null = null;

export function restoreFromSessionStorage(
  store: Store,
  deal_id: string,
  session_id: string,
): void {
  const key = `bma:draft:${deal_id}:${session_id}`;

  let raw: string | null;
  try {
    raw = sessionStorage.getItem(key);
  } catch {
    return;
  }
  if (raw === null) return;

  let entry: { working_tree: unknown; base_sha: string; saved_at: string };
  try {
    entry = JSON.parse(raw) as typeof entry;
  } catch {
    return;
  }

  const state = store.getState();
  const session = state.sessions[session_id];
  if (!session) return;

  const currentBaseSha = session.base_sha;
  const currentWorkingTree = session.working_tree;

  if (entry.base_sha === currentBaseSha) {
    if (JSON.stringify(entry.working_tree) !== JSON.stringify(currentWorkingTree)) {
      store.setState((s) => ({
        sessions: {
          ...s.sessions,
          [session_id]: {
            ...s.sessions[session_id],
            working_tree: entry.working_tree as DealState,
            diagnostics: [
              ...s.sessions[session_id].diagnostics,
              {
                code: "DRAFT_RESTORED",
                severity: "info" as const,
                path: "",
                message: "Restored unsaved edits",
                payload: {},
              },
            ],
          },
        },
      }));
    }
  } else {
    try {
      sessionStorage.removeItem(key);
    } catch {
      // sessionStorage unavailable
    }
    store.setState((s) => ({
      sessions: {
        ...s.sessions,
        [session_id]: {
          ...s.sessions[session_id],
          diagnostics: [
            ...s.sessions[session_id].diagnostics,
            {
              code: "DRAFT_DISCARDED",
              severity: "info" as const,
              path: "",
              message: "Unsaved edits discarded because the deal advanced",
              payload: {},
            },
          ],
        },
      },
    }));
  }
}

export function subscribeAutosave(store: Store): () => void {
  // Tear down any prior subscription and pending timer before re-subscribing.
  if (_teardown) {
    _teardown();
    _teardown = null;
  }

  // Restore any persisted drafts for all current sessions before subscribing.
  const initState = store.getState();
  for (const sessionId of Object.keys(initState.sessions)) {
    restoreFromSessionStorage(store, initState.deal_id, sessionId);
  }

  // Major #1: capture prev tracking values AFTER restores so the restored
  // working_tree doesn't look like a typed dispatch to the subscription.
  const postRestoreState = store.getState();
  let prevActiveSessionId: string = postRestoreState.activeSessionId;
  let prevWorkingTree: unknown =
    postRestoreState.sessions[prevActiveSessionId]?.working_tree;

  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  const unsubscribe = store.subscribe((state: DealStoreState) => {
    const { deal_id, activeSessionId, sessions } = state;
    const session = sessions[activeSessionId];
    if (!session) return;

    const currentWorkingTree = session.working_tree;
    const workingTreeChanged = currentWorkingTree !== prevWorkingTree;
    const sameSession = activeSessionId === prevActiveSessionId;

    // Always advance prev values so future comparisons are correct.
    prevWorkingTree = currentWorkingTree;
    prevActiveSessionId = activeSessionId;

    // Major #1: only react when the active session's working_tree mutated.
    // setDealId, setActiveSession, setDiagnostics, etc. don't trigger.
    if (!workingTreeChanged || !sameSession) return;

    // Synchronously persist working tree to sessionStorage on every typed dispatch.
    const key = `bma:draft:${deal_id}:${activeSessionId}`;
    try {
      sessionStorage.setItem(
        key,
        JSON.stringify({
          working_tree: session.working_tree,
          base_sha: session.base_sha,
          saved_at: new Date().toISOString(),
        }),
      );
    } catch (err) {
      // Major #2: QuotaExceededError or sessionStorage unavailable — surface a
      // warning diagnostic so the UI can inform the user that crash recovery is
      // degraded. Backend autosave remains the durable path.
      store.setState((s) => ({
        sessions: {
          ...s.sessions,
          [activeSessionId]: {
            ...s.sessions[activeSessionId],
            diagnostics: [
              ...s.sessions[activeSessionId].diagnostics,
              {
                code: "SESSIONSTORAGE_WRITE_FAILED",
                severity: "warning" as const,
                path: "$",
                message:
                  "Crash recovery is degraded; backend autosave still durable.",
                payload: { error: String(err) },
              },
            ],
          },
        },
      }));
    }

    // Debounced backend commit: reset timer on every subsequent typed dispatch.
    if (debounceTimer !== null) {
      clearTimeout(debounceTimer);
    }
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      const current = store.getState();

      // Autosave suppressed when a conflict is awaiting resolution.
      if (current.conflictState) return;
      // Local drafts only persist to sessionStorage; no backend commit.
      if (current.deal_id.startsWith("local_draft_")) return;

      const currentSession = current.sessions[activeSessionId];
      if (!currentSession) return;

      const body = {
        author: "autosave",
        message: "autosave",
        parent_sha: currentSession.base_sha,
        branch: currentSession.branch_name,
        payload: JSON.parse(compileToIR(currentSession.working_tree)) as DealState,
      };

      current
        .commitWithConflictHandling(current.deal_id, body, activeSessionId)
        .then((result) => {
          // Critical #1: advance base_sha so the next autosave sends the correct
          // parent_sha and does not generate a spurious self-conflict.
          store.setState((s) => ({
            sessions: {
              ...s.sessions,
              [activeSessionId]: {
                ...s.sessions[activeSessionId],
                base_sha: result.sha,
              },
            },
          }));
        })
        .catch(() => {
          // Conflict written to conflictState by commitWithConflictHandling.
        });
    }, 2000);
  });

  _teardown = () => {
    if (debounceTimer !== null) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    unsubscribe();
  };

  return _teardown;
}
