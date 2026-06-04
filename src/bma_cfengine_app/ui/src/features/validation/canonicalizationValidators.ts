/**
 * Phase 1 rule fragmentation detector (rcf-2).
 *
 * Walks deal.waterfall_rules (sorted by order) and identifies maximal
 * consecutive runs of length >= 2 where every adjacent pair is consolidatable
 * via the rcf-1 isConsolidatable predicate with an empty intervening set.
 *
 * Mirrors src/bma_standard_formulas/diagnostics/canonicalization_validators.py.
 */

import type { RuleNodeIR } from "../deals/ir-types";
import type { DiagnosticPayload } from "../deals/store/diagnostics-types";
import { registerDiagnosticValidator } from "./diagnosticRegistry";
import { isConsolidatable } from "./canonicalizationHelpers";

registerDiagnosticValidator({
  code: "RULE_FRAGMENTATION_CONSOLIDATABLE",
  severity: "warning",
  pathSchema: "deal.waterfall_rules[start_index..end_index]",
  owner: "both",
  fn(deal: unknown): DiagnosticPayload[] {
    const d = deal as Record<string, unknown>;
    const rawRules = Array.isArray(d.waterfall_rules) ? d.waterfall_rules : [];
    if (rawRules.length < 2) return [];

    const rulesSorted = [...rawRules].sort(
      (a: Record<string, unknown>, b: Record<string, unknown>) =>
        ((a.order as number) ?? 0) - ((b.order as number) ?? 0),
    ) as RuleNodeIR[];

    const results: DiagnosticPayload[] = [];
    let i = 0;
    while (i < rulesSorted.length - 1) {
      if (!isConsolidatable(rulesSorted[i], rulesSorted[i + 1], [])) {
        i++;
        continue;
      }

      const start = i;
      let j = i + 1;
      while (
        j < rulesSorted.length - 1 &&
        isConsolidatable(rulesSorted[j], rulesSorted[j + 1], [])
      ) {
        j++;
      }

      const end = j;
      const run = rulesSorted.slice(start, end + 1);
      results.push({
        code: "RULE_FRAGMENTATION_CONSOLIDATABLE",
        severity: "warning",
        path: `deal.waterfall_rules[${start}..${end}]`,
        message: `Rules ${start} through ${end} can be consolidated into one multi-target rule.`,
        payload: {
          start_index: start,
          end_index: end,
          rule_ids: run.map((r) => r.rule_id),
          source: run[0].from_sources[0],
          target_count: run.reduce((acc, r) => acc + r.to_targets.length, 0),
        },
        fix: {
          action_id: "canonicalize_consolidate_rule_run",
          params: { start_index: start, end_index: end },
        },
      });
      i = end + 1;
    }

    return results;
  },
});
