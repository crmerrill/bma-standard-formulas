/**
 * Tests for the QuickFix registry (ve-5 fix-pass).
 *
 * Validates that:
 * - Known manual action IDs resolve to a ManualQuickFix with kind === "manual".
 * - Unknown action IDs throw an error.
 */

import { describe, expect, test } from "vitest";
import {
  getQuickFix,
  UnknownQuickFixError,
} from "./quickFixRegistry";

describe("QuickFix registry", () => {
  test("test_get_quick_fix_for_known_manual_action", () => {
    const descriptor = getQuickFix("manual_resolve_duplicate_bond_name");
    expect(descriptor.kind).toBe("manual");
    expect(typeof (descriptor as { description: string }).description).toBe(
      "string"
    );
    expect((descriptor as { description: string }).description.length).toBeGreaterThan(0);
  });

  test("test_get_quick_fix_for_unknown_id_raises", () => {
    expect(() => getQuickFix("nonexistent_action_id_xyz")).toThrow(
      UnknownQuickFixError
    );
  });

  test("test_canonicalize_consolidate_rule_run_registered_as_dispatch_quick_fix", () => {
    const descriptor = getQuickFix("canonicalize_consolidate_rule_run");
    expect(descriptor.kind).toBe("dispatch");
    expect((descriptor as { actionType: string }).actionType).toBe(
      "canonicalizeConsolidateRuleRun"
    );
    expect((descriptor as { description: string }).description).toBe(
      "Consolidate fragmented rules into a single multi-target rule."
    );
  });
});
