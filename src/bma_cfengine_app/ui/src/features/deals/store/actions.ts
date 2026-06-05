import type { BondDefIR, RuleNodeIR } from "../ir-types";
import type { DealStoreState } from "./useDealStore";
import { isConsolidatable } from "../../validation/canonicalizationHelpers";

export type AddBondAction = { type: "addBond"; payload: BondDefIR };
export type SetBondKindAction = {
  type: "setBondKind";
  payload: { bond_id: string; kind: BondDefIR["kind"] };
};
export type SetRulePriorityAction = {
  type: "setRulePriority";
  payload: { rule_id: string; priority: number };
};
export type CanonicalizeConsolidateRuleRunAction = {
  type: "canonicalizeConsolidateRuleRun";
  payload: { start_index: number; end_index: number };
};

export type DealAction =
  | AddBondAction
  | SetBondKindAction
  | SetRulePriorityAction
  | CanonicalizeConsolidateRuleRunAction;

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
    case "canonicalizeConsolidateRuleRun": {
      const { start_index, end_index } = action.payload;
      const rules = wt.waterfall_rules;

      const emitStale = (reason: string): Partial<DealStoreState> => ({
        sessions: {
          ...state.sessions,
          [sessionId]: {
            ...session,
            diagnostics: [
              ...session.diagnostics,
              {
                code: "STALE_QUICKFIX",
                severity: "warning" as const,
                path: "deal.waterfall_rules",
                message: `QuickFix could not be applied to range [${start_index}..${end_index}]: ${reason}`,
                payload: {},
              },
            ],
          },
        },
      });

      if (start_index >= end_index) {
        return emitStale("start_index >= end_index");
      }
      if (start_index < 0 || end_index >= rules.length) {
        return emitStale("indices out of bounds");
      }

      for (let i = start_index; i < end_index; i++) {
        if (!isConsolidatable(rules[i], rules[i + 1], [])) {
          return emitStale("rules no longer consolidatable");
        }
      }

      const consolidatedTargets: string[] = [];
      for (let i = start_index; i <= end_index; i++) {
        consolidatedTargets.push(...rules[i].to_targets);
      }
      const consolidated: RuleNodeIR = {
        ...rules[start_index],
        to_targets: consolidatedTargets,
      };

      const newRules = [
        ...rules.slice(0, start_index),
        consolidated,
        ...rules.slice(end_index + 1),
      ];

      return {
        sessions: {
          ...state.sessions,
          [sessionId]: {
            ...session,
            working_tree: { ...wt, waterfall_rules: newRules },
            pending_commit_message: `Canonicalize consolidate rule run [${start_index}..${end_index}]`,
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
