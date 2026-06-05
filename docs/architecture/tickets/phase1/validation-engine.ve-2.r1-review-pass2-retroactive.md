# R1 Review (Pass 2, retroactive fix-pass) — `ve-2-worker-validator-coverage`

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family)
**Date**: 2026-06-03
**Fix-pass under review**: T1 `1773b45`, Fix `59bce99`
**Verdict**: RETURN-FOR-REVISION

## Summary

The production validator fixes close the three original Major findings. Python and TS now build valid reference sets with `SPLIT_CASH` virtual streams, `deal_knobs.source_formulas`, declared group streams, and aligned broken-reference checks. The OA5 cross-group mixing predicate is also present in both stacks.

However, the fix introduced a stale TS unit-test expectation in `structuralValidators.test.ts`: the test filters actual diagnostics to `MULTI_GROUP_ROUTING_INVALID` but compares against fixture `expected_diagnostics` that now includes both `MULTI_GROUP_ROUTING_INVALID` and `REFERENCE_BROKEN`.

## Findings

### Major: TS ve-2-specific test expectation is now inconsistent

`tests/fixtures/diagnostic_parity/multi_group_routing_invalid.json` was corrected to expect both diagnostics — semantically correct since the same invalid `GROUP_99_CASH` token is both an invalid reference and an undeclared group-prefixed stream.

But `structuralValidators.test.ts` still filters actual results down to only `MULTI_GROUP_ROUTING_INVALID` and compares to the full fixture expected list. The broader `diagnosticParity.test.ts` all-fixture runner is fine, but this older focused test should either compare against filtered expected diagnostics or stop filtering actuals.

## Closure Assessment

- **Finding 1: CLOSED.** Reference set construction includes split streams + source formulas.
- **Finding 2: CLOSED.** Group-prefixed `to_targets` validated.
- **Finding 3: CLOSED.** OA5 predicate implemented in both stacks.

## Parity And Edge Cases

Python/TS logic structurally aligned. Edge cases correct: empty arrays, bare-token-only with group_id, matching group_id+prefix, cross-group mixing all behave as expected.

## Verdict Rationale

Return for revision only because of the stale TS focused test expectation. The validator fix itself satisfies the original R1 findings, and the dual-diagnostic fixture correction is semantically correct.
