# R1 Review (Pass 1, retroactive) — `ve-2-worker-validator-coverage` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family; RETROACTIVE)
**Date**: 2026-06-03
**Implementation under review**: commit `9795735` (test commit `b276012`)
**Verdict**: RETURN-FOR-REVISION

## Findings

### Major: `REFERENCE_BROKEN` is not faithful to the Pydantic reference validator

The worker/Python structural validator only treats bond names, account names, fee names, built-in streams, and explicit group streams as valid references. The Pydantic `DealDefinition._validate_references` also treats prior `SPLIT_CASH` virtual streams and `deal_knobs.source_formulas` as valid sources/targets.

That means legitimate deals can receive false-positive `REFERENCE_BROKEN` diagnostics for downstream split-stream references or source formula references.

Affected:
- `src/bma_standard_formulas/diagnostics/structural_validators.py`
- `src/bma_cfengine_app/ui/src/features/validation/structuralValidators.ts`

Expected parity with `src/bma_standard_formulas/deals/schemas/ir.py` reference construction for `source_formula_names`, `split_streams`, `valid_sources`, and `valid_targets`.

### Major: invalid group-prefixed `to_targets` can be missed

`REFERENCE_BROKEN` skips every token beginning with `GROUP_` for both `from_sources` and `to_targets`. `MULTI_GROUP_ROUTING_INVALID` only checks `from_sources`.

So an invalid group-prefixed `to_targets` entry can escape both validators, even though the Pydantic reference validator validates group stream names for both source and target sets.

### Major: `MULTI_GROUP_ROUTING_INVALID` does not cover the actual multi-group routing predicate

The implementation checks whether `from_sources` group-prefixed tokens exist in the declared `collateral_groups` stream set. It does not enforce the Pydantic OA5 rule: a rule with `group_id` must not mix bare collateral tokens scoped to that rule group with explicit `GROUP_<other>_*` tokens for a different group.

Example missed case:
- `collateral_groups`: `GROUP_1`, `GROUP_2`
- rule `group_id`: `GROUP_1`
- `from_sources`: `["CASH", "GROUP_GROUP_2_ACT_INT"]`

Pydantic rejects this; the ve-2 validator accepts it.

### Minor: dot notation is not resolved

The implementation resolves only canonical underscore tokens. It does not resolve `GROUP_X.SOURCE` dot notation. This is consistent with the canonicalization helper note that dot aliases are out-of-scope.

## Acceptance Criteria Audit

- **AC 1**: Partially met. All six validators present, but `REFERENCE_BROKEN` and `MULTI_GROUP_ROUTING_INVALID` behaviorally incomplete.
- **AC 2**: Met. Six Python validators decorated with `@diagnostic_code(... owner=Owner.both)`.
- **AC 3**: Met. Six catalog rows added in commit `9795735`.
- **AC 4**: Partially met. Six parity fixtures and tests exist, but fixtures do not cover the gaps above.

## Checklist Notes

- `KIND_SCHEDULE_SOURCE_INCONSISTENT` matches the ticket AC: PAC/TAC with either `schedule_contract` or `schedule_model_type` is valid; PAC/TAC with neither is invalid; non-PAC/TAC with either is invalid.
- `NLA_SUBORDINATION_INCONSISTENT` predicate is exactly XOR on field presence. I did not find a matching Pydantic `model_validator` enforcing this invariant; the Pydantic model defines both fields as independently optional.
- `MULTI_GROUP_ROUTING_INVALID` resolves declared canonical group stream names, but does not validate cross-group mixing relative to `rule.group_id`.

## Required Changes

- Align `REFERENCE_BROKEN` with `DealDefinition._validate_references` by accounting for `split_streams` and `deal_knobs.source_formulas`.
- Ensure invalid group-prefixed `to_targets` are diagnosed.
- Expand `MULTI_GROUP_ROUTING_INVALID` to cover OA5 mixing predicate.
- Add parity fixtures for split-stream references, source formula references, invalid group-prefixed targets, and cross-group mixing.
