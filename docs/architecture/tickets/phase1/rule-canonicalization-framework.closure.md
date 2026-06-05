# Closure: `rule-canonicalization-framework`

**Phase**: 1
**Status**: COMPLETE
**Date**: 2026-06-05
**Branch**: `feature/securitization-structuring-tool`

## Scope delivered

The `rule-canonicalization-framework` todo establishes the canonicalization correctness framework for Phase 1: detection of rule fragmentation, an opt-in consolidation QuickFix, info-only interleaved-rules visibility, and a comprehensive correctness gate proving canonicalization is a true semantic-preserving rewrite.

## Tickets

| # | Ticket | Implementation | R1 verdict | Closure |
|---|---|---|---|---|
| rcf-1 | `equivalence-predicate` | T1 `e7ab468` + I `5a5195d` (+ rcf-1 follow-up T1 `808239e` + Fix `6aac8bf` to export `mutates_source`) | APPROVE (retroactive) | CLOSED |
| rcf-2 | `fragmentation-detector` | T1 `6c5a0f1` + I `aabfc12` | APPROVE | CLOSED |
| rcf-3 | `consolidation-quick-fix-action` | T1 `a194807` + I `61c0c54` + fix-pass T1 `e2b9e06` + Fix `de6584b` + reducer order T1 `a7c0c90` + Fix `9e38a24` | APPROVE (pass 2) | CLOSED |
| rcf-4 | `interleaved-info-detector` | T1 `82036e7` + I `3711e35` | APPROVE | CLOSED |
| rcf-5 | `negative-tests-and-roundtrip` | T1 `322cea3` + I `2c20d2c` + hardening `248d825` | APPROVE (pass 2) | CLOSED |

## Architectural pins

1. **Mutation predicate** (`mutates_source` / `mutatesSource`): publicly exported from `canonicalization_helpers.{py,ts}`. Reused by rcf-1, rcf-2, rcf-4. Defines the semantic-equivalence guarantee for `is_consolidatable`.
2. **Detector algorithm** (rcf-2): consecutive maximal runs sorted by `order`. Empty `rules_between` because adjacent pairs have no intervening rules.
3. **QuickFix dispatch contract** (rcf-3):
   - `pending_commit_message: string | null` slot on `DealSession`; reducer sets, autosave consumes/clears, last-write-wins via non-canonical reducers also clearing the slot.
   - Author always `studio:autosave`.
   - All TS reducers (and the Python helper) operate on `waterfall_rules` sorted by `order` to ensure detector→reducer index alignment.
   - `rule_id` retention from first replaced rule.
4. **Catalog cataloging** (vpc-4 contract): `RULE_FRAGMENTATION_CONSOLIDATABLE`, `INTERLEAVED_RULES_FACTORABLE`, `STALE_QUICKFIX` all cataloged with sentinel decorators when emitted from non-validator paths.
5. **Interleaved info-only** (rcf-4): `fix=None` (Python) / `fix` field omitted (TS); group-and-transitivity algorithm; comma-separated sorted indices in path.
6. **QuickFix registry** (ve-5 contract): `canonicalize_consolidate_rule_run` registered as `DispatchQuickFix` in both Python and TS. Phase 2 problems-panel branches on `kind`.
7. **Cashflow equivalence oracle** (rcf-5): per-period, per-bond vector equality at `abs <= 1e-9 / rel <= 1e-12`; non-empty cashflow guard; WAL/yield/trustee tie-out independently governed by existing fixture tests.
8. **Inventory-driven fixture coverage** (rcf-5 + retroactive prospectus inventory): round-trip enumerates fixtures via `parse_prospectus_inventory.load_inventory()` filtered to `tier in {structural, quantitative_golden}` + non-null `fixture_dir`. STATUS.md is no longer the programmatic source of truth.

## Test deltas

- **Python**: full suite went from 1632 → 1656 passing during rcf delivery (negative tests + roundtrip + new helper unit tests + R1 fix-pass tests).
- **TS**: full UI suite gained 25+ tests (rcf-2 validator, rcf-3 reducer + autosave + registry, rcf-4 validator + parity).
- **vpc-4 CI guard**: passes with all 3 new diagnostic codes properly catalogued.
- **Round-trip equivalence**: 4 of 5 fixtures (FNR 2006-018, Ginnie Mae 2025-203, Verus 2024-9, Ford 2024-C) ran full cashflow equivalence. cc_series_test skipped (no consolidatable runs — clean `pytest.skip`).

## Phase 1 unblocks

This closure unblocks:
- **Phase 2 `problems-panel`**: can now consume `RULE_FRAGMENTATION_CONSOLIDATABLE` diagnostics, dispatch the `canonicalizeConsolidateRuleRun` QuickFix, and render `INTERLEAVED_RULES_FACTORABLE` info diagnostics without QuickFix buttons.
- **Phase 3 `branch-canonicalization-after-waterfall-branch`**: the canonicalization framework pattern (detector + QuickFix + registry + catalog) is reusable for the eventual `SHARED_TRIGGER_BRANCHABLE` diagnostic.

## Outstanding follow-ups (deferred)

- Phase 2/follow-on: design + implement `docs/architecture/prospectus_inventory.md`'s programmatic alignment with deeper waterfall_ir_design.md cross-references (currently a heuristic per-cell + inverse check).
- Phase 2/follow-on: extend QuickFix registry coverage as new dispatch action_ids land.
- Forward-compat fragility: every new `DealAction` reducer must remember to clear `pending_commit_message` to honor last-write-wins. Consider a centralized mechanism in Phase 2 if more action types land.
