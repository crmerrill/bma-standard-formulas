/**
 * Phase 1 rule canonicalization validators (rcf-2, rcf-4).
 *
 * rcf-2: Walks deal.waterfall_rules (sorted by order) and identifies maximal
 * consecutive runs of length >= 2 where every adjacent pair is consolidatable
 * via the rcf-1 isConsolidatable predicate with an empty intervening set.
 *
 * rcf-4: Groups rules by (rule_type, source, payment_style) and flags groups
 * whose members are interleaved with a source-mutating intervening rule.
 *
 * Mirrors src/bma_standard_formulas/diagnostics/canonicalization_validators.py.
 */

import type { RuleNodeIR } from "../deals/ir-types";
import type { DiagnosticPayload } from "../deals/store/diagnostics-types";
import { registerDiagnosticValidator } from "./diagnosticRegistry";
import { isConsolidatable, mutatesSource } from "./canonicalizationHelpers";

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

// STALE_QUICKFIX sentinel — emitted by the TS reducer in actions.ts when a
// canonicalize quick-fix range is invalid or no longer consolidatable. This
// no-op validator registration exists only to satisfy the vpc-4 catalog parity
// guard (catalog row has owner=both, which requires both Python @diagnostic_code
// and a TS registerDiagnosticValidator). Mirrors the Python sentinel pattern in
// canonicalization_validators.py.
registerDiagnosticValidator({
  code: "STALE_QUICKFIX",
  severity: "warning",
  pathSchema: "deal.waterfall_rules",
  owner: "both",
  fn(): DiagnosticPayload[] {
    return [];
  },
});

// rcf-4: interleaved-info detector. Groups rules by (rule_type, source, payment_style)
// and emits one info-only diagnostic (no fix) per group whose members are interleaved
// with a rule that mutates the shared source. Mirrors detect_interleaved_rules in Python.
registerDiagnosticValidator({
  code: "INTERLEAVED_RULES_FACTORABLE",
  severity: "info",
  pathSchema: "deal.waterfall_rules[{indices}]",
  owner: "both",
  fn(deal: unknown): DiagnosticPayload[] {
    const d = deal as Record<string, unknown>;
    const rawRules = Array.isArray(d.waterfall_rules) ? d.waterfall_rules : [];
    if (rawRules.length < 2) return [];

    const rulesSorted = [...rawRules].sort(
      (a: Record<string, unknown>, b: Record<string, unknown>) =>
        ((a.order as number) ?? 0) - ((b.order as number) ?? 0),
    ) as RuleNodeIR[];

    // Build groups: composite key of (rule_type, from_sources[0], payment_style)
    const groups = new Map<string, number[]>();
    for (let idx = 0; idx < rulesSorted.length; idx++) {
      const rule = rulesSorted[idx];
      if (!Array.isArray(rule.from_sources) || rule.from_sources.length === 0) continue;
      const key = `${rule.rule_type}\x00${rule.from_sources[0]}\x00${rule.payment_style}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(idx);
    }

    const results: DiagnosticPayload[] = [];
    for (const [key, indices] of groups) {
      if (indices.length < 2) continue;

      const minIdx = Math.min(...indices);
      const maxIdx = Math.max(...indices);
      const groupSet = new Set(indices);
      const [rt, src, ps] = key.split("\x00");
      const sharedGroupId = rulesSorted[indices[0]].group_id ?? null;

      let hasMutator = false;
      for (let i = minIdx + 1; i < maxIdx; i++) {
        if (!groupSet.has(i) && mutatesSource(rulesSorted[i], src, sharedGroupId)) {
          hasMutator = true;
          break;
        }
      }
      if (!hasMutator) continue;

      const sortedIndices = [...indices].sort((a, b) => a - b);
      results.push({
        code: "INTERLEAVED_RULES_FACTORABLE",
        severity: "info",
        path: `deal.waterfall_rules[${sortedIndices.join(",")}]`,
        message: `Rules at ${JSON.stringify(sortedIndices)} share (rule_type, source, payment_style) but are interleaved with a source mutation; manual review recommended.`,
        payload: {
          indices: sortedIndices,
          rule_type: rt,
          source: src,
          payment_style: ps,
        },
      });
    }

    return results;
  },
});
