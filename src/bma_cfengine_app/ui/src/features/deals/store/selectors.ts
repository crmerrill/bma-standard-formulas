import { useDealStore } from "./useDealStore";

export function useBondsSelector() {
  return useDealStore(
    (state) => state.sessions[state.activeSessionId].working_tree.bonds,
  );
}

export function useAccountsSelector() {
  return useDealStore(
    (state) => state.sessions[state.activeSessionId].working_tree.accounts,
  );
}

export function useRulesSelector() {
  return useDealStore(
    (state) =>
      state.sessions[state.activeSessionId].working_tree.waterfall_rules,
  );
}

/**
 * ve-5 AC 3: count of severity='error' diagnostics in the named session.
 * Returns 0 if the session does not exist (defensive against hot-swaps).
 *
 * Phase 2 Run/Solve UI gates on `getErrorCount(sessionId) === 0`.
 */
export function getErrorCount(sessionId: string): number {
  const session = useDealStore.getState().sessions[sessionId];
  if (!session) return 0;
  let n = 0;
  for (const d of session.diagnostics) {
    if (d.severity === "error") n += 1;
  }
  return n;
}

/**
 * ve-5 AC 3 (hook variant): subscribes to the active session's diagnostics so
 * components re-render only when the error count changes.
 */
export function useErrorCount(): number {
  return useDealStore((state) => {
    const session = state.sessions[state.activeSessionId];
    if (!session) return 0;
    let n = 0;
    for (const d of session.diagnostics) {
      if (d.severity === "error") n += 1;
    }
    return n;
  });
}
