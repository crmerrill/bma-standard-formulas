# R1 Review (Pass 1) — `rcf-4-interleaved-info-detector`

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family)
**Date**: 2026-06-05
**Implementation under review**: T1 `82036e7`, Fix `3711e35`
**Verdict**: APPROVE

## Summary

The rcf-4 implementation satisfies the five acceptance criteria. Python and TypeScript both reuse the rcf-1 mutation predicate, implement the pinned group-and-transitivity algorithm, emit `INTERLEAVED_RULES_FACTORABLE` as `info`, format paths as sorted comma-separated indices, and preserve the required no-fix parity: Python `fix=None`, TS omitted `fix`.

`Diagnostic catalog parity check PASSED.`

## Findings

No blocking findings.

Non-blocking observations:
- The detector groups by `from_sources[0]` in both stacks. This matches the implemented interpretation of `(rule_type, source, payment_style)` and is appropriate for the info-only heuristic — intentionally broader than `is_consolidatable`'s full-list equality.
- The `check.py` `_TS_CALL_RE` change is a vpc-4 guard workaround that is in scope as an enabling fix (the new `pathSchema: "deal.waterfall_rules[{indices}]"` would otherwise be misparsed). The regex correctly handles simple quoted string literals containing `{}` placeholders.

## AC Closure

- **AC 1 — Algorithm**: CLOSED. Both stacks sort by `order`, group by tuple, inspect non-member rules between min and max, emit one diagnostic when any intervening rule mutates source.
- **AC 2 — Catalog row pinned**: CLOSED. All 7 columns match; points to `canonicalization_validators.py:106`.
- **AC 3 — Severity + path format**: CLOSED. `info` severity; sorted comma-separated indices, no spaces.
- **AC 4 — `fix` parity**: CLOSED. Python `fix=None`; TS omits field. Parity test checks JSON round-trip.
- **AC 5 — Metadata parity + vpc-4 guard**: CLOSED. Python decorator + TS registration + catalog all agree.

## Edge Cases Verified

- Group {1,3,5} with mutator at 2: emits one diagnostic with path `deal.waterfall_rules[1,3,5]`.
- Group {1,5} with no mutator between: no diagnostic.
- Overlapping groups: each tuple key processed independently.

## Verdict Rationale

APPROVE. Implementation meets the rcf-4 contract and vpc-4 parity guard passes. Remaining notes are non-blocking.
