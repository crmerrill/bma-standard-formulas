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
