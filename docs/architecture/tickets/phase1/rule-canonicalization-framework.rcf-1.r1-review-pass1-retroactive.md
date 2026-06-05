# R1 Review (Pass 1, retroactive) — `rcf-1-equivalence-predicate` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family; RETROACTIVE)
**Date**: 2026-06-03
**Implementation under review**: commit `5a5195d` (test commit `e7ab468`)
**Verdict**: APPROVE

## Findings

No blocking findings.

## Checklist

1. **AC 1**: PASS. `is_consolidatable(...)` implemented in Python at `src/bma_standard_formulas/diagnostics/canonicalization_helpers.py`, and TS parity predicate `isConsolidatable(...)` in `src/bma_cfengine_app/ui/src/features/validation/canonicalizationHelpers.ts`.

2. **AC 2**: PASS. Compares all required shared semantic fields: `rule_type`, `from_sources`/source, `payment_style`, `cap_mode`, `condition_trigger`, `condition_invert`, `condition_expr`, `group_id`, `coverage_mode`, `allow_negative_source`.

3. **AC 3**: PASS. Both implementations reject per-target differences in `max_amount_fixed`, `max_amount_expr`, `target_weights`.

4. **AC 4**: PASS. Case (a) `to_targets` contains the shared source is implemented. Case (b) group-routed aliasing is implemented via logical source resolution. Underscore convention is acceptable as conservative Phase 1; dot notation documented out-of-scope.

5. **Case (b) read-as-mutation interpretation**: ACCEPTABLE. An intervening rule that reads from the shared pool consumes/debits that pool in waterfall order; consolidating across that rule would move the later target ahead of the intervening consumer. Safe-side conservatism justified.

6. **`RuleNodeIR` optional parity fields**: PASS. Adding optional `max_amount_expr`, `condition_expr`, `allow_negative_source` is a clean TS parity improvement. Optional fields don't break existing TS callers.

7. **`from_sources` order-sensitive comparison**: PASS. Exact order-sensitive comparison is correct.

## Notes

T1 tests cover the main positive path, per-target rejection, direct intervening write, and group-alias intervening read. They do not exhaustively negative-test every AC 2 field difference, but the implementation itself checks the full field set.

Non-blocking caveat: the broader codebase has some inconsistent-looking group ID examples (`"1"` versus `"GROUP_1"`), while runtime expansion currently follows the existing `GROUP_${group_id}_${token}` behavior. The implementation matches that pattern; any cleanup of group-token naming should be handled as a separate IR/runtime convention issue.
