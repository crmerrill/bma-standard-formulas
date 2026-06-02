import type { BondDefIR, RuleNodeIR } from "../ir-types";
import type { DealStoreState } from "./useDealStore";

export type AddBondAction = { type: "addBond"; payload: BondDefIR };
export type SetBondKindAction = {
  type: "setBondKind";
  payload: { bond_id: string; kind: BondDefIR["kind"] };
};
export type SetRulePriorityAction = {
  type: "setRulePriority";
  payload: { rule_id: string; priority: number };
};

export type DealAction =
  | AddBondAction
  | SetBondKindAction
  | SetRulePriorityAction;

export function applyAction(
  state: DealStoreState,
  action: DealAction,
): Partial<DealStoreState> {
  const sessionId = state.activeSessionId;
  const session = state.sessions[sessionId];
  const wt = session.working_tree;

  switch (action.type) {
    case "addBond": {
      return {
        sessions: {
          ...state.sessions,
          [sessionId]: {
            ...session,
            working_tree: {
              ...wt,
              bonds: [...wt.bonds, action.payload],
            },
          },
        },
      };
    }
    case "setBondKind": {
      return {
        sessions: {
          ...state.sessions,
          [sessionId]: {
            ...session,
            working_tree: {
              ...wt,
              bonds: wt.bonds.map((b) =>
                b.name === action.payload.bond_id
                  ? { ...b, kind: action.payload.kind }
                  : b,
              ),
            },
          },
        },
      };
    }
    case "setRulePriority": {
      return {
        sessions: {
          ...state.sessions,
          [sessionId]: {
            ...session,
            working_tree: {
              ...wt,
              waterfall_rules: wt.waterfall_rules.map((r) =>
                r.rule_id === action.payload.rule_id
                  ? ({ ...r, priority: action.payload.priority } as unknown as RuleNodeIR)
                  : r,
              ),
            },
          },
        },
      };
    }
    default: {
      // Exhaustive switch enforced by never-guard.
      const _exhaustive: never = action;
      void _exhaustive;
      return {};
    }
  }
}
