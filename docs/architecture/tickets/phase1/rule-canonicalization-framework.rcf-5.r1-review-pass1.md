# R1 Review (Pass 1) — `rcf-5-negative-tests-and-roundtrip`

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family)
**Date**: 2026-06-05
**Implementation under review**: T1 `322cea3`, Fix `2c20d2c`
**Verdict**: APPROVE-WITH-CHANGES

## Summary

The implementation substantially covers the rcf-5 surface: all seven negative cases exist, fixture enumeration is inventory-driven, `run_deal` is imported from `bma_standard_formulas.deals.runtime`, the Python apply helper exists, and the cashflow oracle compares per-tranche/per-period numeric vectors at the required tolerances.

Three Medium hardening gaps remain. The third one revealed a real bug in rcf-3 (TS reducer doesn't sort by `order` while the rcf-2 detector and the Python helper do — divergence on unsorted authored arrays).

## Findings

1. **Medium — Cashflow oracle can pass vacuously on empty cashflow vectors.** The oracle compares tranche sets and row keys but never asserts pre/post cashflows are non-empty. If `run_deal` returned empty `bond_cashflows` for both, the test would pass without exercising any per-period equality.

2. **Medium — WAL/yield governance test is import-only.** `test_roundtrip_quantitative_tie_out_governance_unchanged` only imports `tests.test_fnr_2006_018_staged_tieout` and asserts the module is non-null. That doesn't run or assert any tie-out behavior.

3. **Medium — Helper sorts by `order`; TS reducer uses array as-is — real divergence.** Python helper at `canonicalization_helpers.py:31` sorts `waterfall_rules` by `order`. TS reducer at `actions.ts:89` uses `wt.waterfall_rules` directly without sorting. The rcf-2 detector sorts by `order` and emits indices into the sorted view. If `working_tree.waterfall_rules` is ever in non-`order`-sorted state (which `setRulePriority` does not prevent — it only updates the `priority` field, not array position or `order`), the TS reducer applies the QuickFix to the wrong rules.

## AC Closure

- **AC 1 — Comprehensive negative tests**: CLOSED.
- **AC 2 — Inventory-driven fixture coverage**: CLOSED.
- **AC 3 — Round-trip apply path**: MOSTLY CLOSED. Helper-vs-reducer order divergence not covered.
- **AC 4 — Cashflow equivalence oracle**: MOSTLY CLOSED. Constants and comparison correct; non-empty assertion missing.
- **AC 5 — WAL/yield/trustee tie-out not oracle**: PARTIAL. Governance test is sentinel-level only.
- **AC 6 — Skipped-fixture semantics**: CLOSED.

## Verdict Rationale

APPROVE-WITH-CHANGES. The implementation meets the main shape of rcf-5 and catches semantic regressions for the four fixtures with consolidatable runs. Before this becomes the canonical architectural gate, harden the oracle with non-empty cashflow assertions, strengthen or rename the governance test, and reconcile the helper-vs-reducer order divergence (correct fix is to make the TS reducer sort by `order` to match the detector's view).
