# R1 Review (Pass 2) — `rcf-5-negative-tests-and-roundtrip` + `rcf-3-consolidation-quick-fix-action` reducer fix

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family)
**Date**: 2026-06-05
**Fix-pass under review**: T1 `a7c0c90`, Reducer fix `9e38a24`, Oracle hardening `248d825`
**Verdict**: APPROVE

## Summary

The combined fix-pass closes all three Pass-1 Medium findings.

The rcf-3 reducer now sorts `wt.waterfall_rules` by `order` before every index, validation, concatenation, and slice operation in `canonicalizeConsolidateRuleRun`. Because `newRules` is built from that sorted array, the persisted output array is also order-sorted, matching the rcf-2 detector and Python helper view for subsequent detector runs.

The rcf-5 round-trip oracle now rejects empty `bond_cashflows` before tranche/key/field comparison. The governance test was intentionally renamed and documented as an import sentinel only.

## Findings

No blocking findings.

Non-blocking note: `_assert_cashflow_equivalence` emits clear side-specific messages but doesn't include fixture name in the assertion. Pytest's parametrize ids cover this in failure output.

## Closure Assessment

- **Finding 3 — TS reducer order divergence: CLOSED.** `actions.ts` now sorts before applying indices; output view is also sorted. T1 covers the divergence with order=[3,1,2,4] case. Helper, reducer, and detector all use the same sorted view.
- **Finding 1 — Cashflow oracle vacuous on empty: CLOSED.** Guards `len(pre_rows) > 0` and `len(post_rows) > 0` before per-tranche comparison.
- **Finding 2 — WAL/yield governance test: CLOSED.** Renamed to `test_governance_module_imports_unchanged`; documented as sentinel-only with CI providing actual governance.

## Verdict Rationale

APPROVE. The reducer fix addresses the actual detector/reducer indexing divergence, the new test would have caught the pre-fix bug, the cashflow oracle no longer accepts empty outputs, and the governance test now accurately represents its sentinel-only scope.
