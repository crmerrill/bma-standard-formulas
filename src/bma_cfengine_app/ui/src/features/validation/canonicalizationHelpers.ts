/**
 * Phase 1 canonicalization equivalence predicate (rcf-1).
 *
 * Pure functions only — no side effects, no I/O.
 * Mirrors src/bma_standard_formulas/diagnostics/canonicalization_helpers.py.
 */

import type { RuleNodeIR } from "../deals/ir-types";

// Builtin stream tokens that may be bare (single-pool) or group-scoped.
// When a RuleNode carries group_id='N', a bare token like 'CASH' in
// from_sources/to_targets is logically equivalent to 'GROUP_N_CASH'.
const BUILTIN_TOKENS = new Set(["CASH", "ACT_INT", "ACT_PRIN", "LOSS"]);

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Return the canonical logical-pool identifier for `token`.
 *
 * If `groupId` is set and `token` is a bare builtin stream token, the logical
 * pool is `GROUP_<groupId>_<token>` (underscore-joined, matching the IR naming
 * convention). All other tokens are returned unchanged.
 *
 * Limitation: dot-notation aliases (e.g. 'GROUP_1.CASH') are NOT resolved
 * because the Phase 1 IR schema uses underscore notation exclusively.
 */
function resolveLogical(token: string, groupId: string | null | undefined): string {
  if (groupId && BUILTIN_TOKENS.has(token)) {
    return `GROUP_${groupId}_${token}`;
  }
  return token;
}

/**
 * Return true iff `intervening` mutates the logical pool identified by
 * (`source`, `sourceGroupId`).
 *
 * Mutation is defined by the rcf-1 AC-4 Mi1 contract:
 *   (a) The intervening rule's `to_targets` contains the shared source
 *       (possibly under its group-resolved form).
 *   (b) The intervening rule's `from_sources` aliases to the shared source
 *       via group routing — i.e. it reads from the same logical pool, which
 *       alters the pool balance and makes rule ordering load-bearing.
 */
export function mutatesSource(
  intervening: RuleNodeIR,
  source: string,
  sourceGroupId: string | null | undefined,
): boolean {
  const logicalShared = resolveLogical(source, sourceGroupId);

  for (const target of intervening.to_targets) {
    if (resolveLogical(target, intervening.group_id) === logicalShared) {
      return true;
    }
  }

  for (const src of intervening.from_sources) {
    if (resolveLogical(src, intervening.group_id) === logicalShared) {
      return true;
    }
  }

  return false;
}

// ---------------------------------------------------------------------------
// Public predicate
// ---------------------------------------------------------------------------

/**
 * Phase 1 canonicalization equivalence predicate per Phase 0 B6.
 *
 * Returns true iff:
 * - Both rules share exactly: rule_type, from_sources, payment_style,
 *   cap_mode, condition_trigger, condition_invert, condition_expr, group_id,
 *   coverage_mode, allow_negative_source.
 * - Both rules have no per-target differences: max_amount_fixed,
 *   max_amount_expr, and target_weights are all equal (or both absent).
 * - No rule in allRulesBetween mutates the shared source (as defined by
 *   the rcf-1 AC-4 Mi1 contract: to_targets contains the source, OR the
 *   intervening source aliases to the same logical pool via group routing).
 *
 * This function is PURE — no side effects, no I/O.
 */
export function isConsolidatable(
  ruleA: RuleNodeIR,
  ruleB: RuleNodeIR,
  allRulesBetween: RuleNodeIR[],
): boolean {
  // AC 2: shared predicate fields must be identical.
  if (ruleA.rule_type !== ruleB.rule_type) return false;

  if (
    ruleA.from_sources.length !== ruleB.from_sources.length ||
    ruleA.from_sources.some((s, i) => s !== ruleB.from_sources[i])
  ) {
    return false;
  }

  if (ruleA.payment_style !== ruleB.payment_style) return false;
  if ((ruleA.cap_mode ?? null) !== (ruleB.cap_mode ?? null)) return false;
  if ((ruleA.condition_trigger ?? null) !== (ruleB.condition_trigger ?? null)) return false;
  if (ruleA.condition_invert !== ruleB.condition_invert) return false;
  if ((ruleA.condition_expr ?? null) !== (ruleB.condition_expr ?? null)) return false;
  if ((ruleA.group_id ?? null) !== (ruleB.group_id ?? null)) return false;
  if ((ruleA.coverage_mode ?? null) !== (ruleB.coverage_mode ?? null)) return false;
  if ((ruleA.allow_negative_source ?? false) !== (ruleB.allow_negative_source ?? false)) return false;

  // AC 3: per-target fields must be identical (or both absent).
  if ((ruleA.max_amount_fixed ?? null) !== (ruleB.max_amount_fixed ?? null)) return false;
  if ((ruleA.max_amount_expr ?? null) !== (ruleB.max_amount_expr ?? null)) return false;

  const weightsA = ruleA.target_weights ?? null;
  const weightsB = ruleB.target_weights ?? null;
  if (weightsA === null && weightsB !== null) return false;
  if (weightsA !== null && weightsB === null) return false;
  if (
    weightsA !== null &&
    weightsB !== null &&
    (weightsA.length !== weightsB.length ||
      weightsA.some((w, i) => w !== weightsB![i]))
  ) {
    return false;
  }

  // AC 4: no intervening rule may mutate any shared source.
  if (allRulesBetween.length > 0) {
    const groupId = ruleA.group_id ?? null;
    for (const source of ruleA.from_sources) {
      for (const intervening of allRulesBetween) {
        if (mutatesSource(intervening, source, groupId)) {
          return false;
        }
      }
    }
  }

  return true;
}
