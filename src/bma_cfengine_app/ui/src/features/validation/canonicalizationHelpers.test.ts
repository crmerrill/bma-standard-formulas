/**
 * rcf-1-equivalence-predicate: unit tests for isConsolidatable (TS parity).
 *
 * Mirrors tests/diagnostics/test_canonicalization_helpers.py exactly.
 * All four tests must FAIL before the implementation module is created.
 */

import { describe, it, expect } from "vitest";
import { isConsolidatable, mutatesSource } from "./canonicalizationHelpers";
import type { RuleNodeIR } from "../deals/ir-types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function baseRule(overrides: Partial<RuleNodeIR> = {}): RuleNodeIR {
  return {
    rule_id: "r1",
    rule_type: "PAY",
    order: 0,
    from_sources: ["CASH"],
    to_targets: ["CLASS_A"],
    payment_style: "SEQUENTIAL",
    cap_mode: null,
    condition_trigger: null,
    condition_invert: false,
    condition_expr: null,
    group_id: null,
    coverage_mode: "NORMAL",
    allow_negative_source: false,
    max_amount_fixed: null,
    max_amount_expr: null,
    target_weights: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// AC 1, 2 — positive case
// ---------------------------------------------------------------------------

describe("isConsolidatable", () => {
  it("returns true for two rules with identical predicate fields and no intervening rules (AC 1, 2)", () => {
    const ruleA = baseRule({ rule_id: "r1", to_targets: ["CLASS_A"] });
    const ruleB = baseRule({ rule_id: "r2", to_targets: ["CLASS_B"] });
    expect(isConsolidatable(ruleA, ruleB, [])).toBe(true);
  });

  // -------------------------------------------------------------------------
  // AC 1, 3 — per-target differences
  // -------------------------------------------------------------------------

  it("returns false when max_amount_fixed differs (AC 1, 3)", () => {
    const ruleA = baseRule({ rule_id: "r1", to_targets: ["CLASS_A"], max_amount_fixed: 1000 });
    const ruleB = baseRule({ rule_id: "r2", to_targets: ["CLASS_B"], max_amount_fixed: 2000 });
    expect(isConsolidatable(ruleA, ruleB, [])).toBe(false);
  });

  it("returns false when max_amount_expr differs (AC 1, 3)", () => {
    const ruleA = baseRule({ rule_id: "r1", to_targets: ["CLASS_A"], max_amount_expr: "SCHED_BAL_A" });
    const ruleB = baseRule({ rule_id: "r2", to_targets: ["CLASS_B"], max_amount_expr: "SCHED_BAL_B" });
    expect(isConsolidatable(ruleA, ruleB, [])).toBe(false);
  });

  it("returns false when target_weights differ (AC 1, 3)", () => {
    const ruleA = baseRule({ rule_id: "r1", to_targets: ["CLASS_A"], target_weights: [1.0] });
    const ruleB = baseRule({ rule_id: "r2", to_targets: ["CLASS_B"], target_weights: [0.5] });
    expect(isConsolidatable(ruleA, ruleB, [])).toBe(false);
  });

  // -------------------------------------------------------------------------
  // AC 1, 4 case (a) — intervening to_targets mutation
  // -------------------------------------------------------------------------

  it("returns false when intervening rule writes to the shared source (AC 1, 4a)", () => {
    const ruleA = baseRule({ rule_id: "r1", from_sources: ["CASH"], to_targets: ["CLASS_A"] });
    const ruleB = baseRule({ rule_id: "r3", from_sources: ["CASH"], to_targets: ["CLASS_B"] });
    const intervening = baseRule({
      rule_id: "r2",
      from_sources: ["ACT_INT"],
      to_targets: ["CASH"],  // mutates the shared source
    });
    expect(isConsolidatable(ruleA, ruleB, [intervening])).toBe(false);
  });

  // -------------------------------------------------------------------------
  // AC 1, 4 case (b) — intervening group-alias mutation
  // -------------------------------------------------------------------------

  it("returns false when intervening rule aliases to the shared source via group routing (AC 1, 4b)", () => {
    const ruleA = baseRule({ rule_id: "r1", from_sources: ["CASH"], group_id: "1", to_targets: ["CLASS_A"] });
    const ruleB = baseRule({ rule_id: "r3", from_sources: ["CASH"], group_id: "1", to_targets: ["CLASS_B"] });
    const intervening = baseRule({
      rule_id: "r2",
      from_sources: ["GROUP_1_CASH"],  // aliases via group routing
      group_id: null,
      to_targets: ["CLASS_C"],
    });
    expect(isConsolidatable(ruleA, ruleB, [intervening])).toBe(false);
  });

  // -------------------------------------------------------------------------
  // rcf-4 export contract — mutatesSource must be publicly importable
  // -------------------------------------------------------------------------

  it("mutatesSource is publicly exported and callable (rcf-4 pre-req)", () => {
    expect(typeof mutatesSource).toBe("function");
  });
});
