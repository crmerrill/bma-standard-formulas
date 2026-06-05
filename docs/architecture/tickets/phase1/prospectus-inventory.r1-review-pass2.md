# R1 Review (Pass 2, retroactive fix-pass) — `prospectus-inventory`

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family)
**Date**: 2026-06-03
**Fix-pass under review**: T1 `a058d1d`, parser `6a3ca16`, drift `6ef72d8`, wording `b1b6434`
**Verdict**: APPROVE

## Summary

The fix-pass closes the pass-1 findings. The parser now rejects duplicate `prospectus_id` values and validates kebab-case IDs. The drift test now checks both directions: per-cell deal names from the `waterfall_ir_design.md` sample table against inventory, and inventory entries citing the design doc back against verbatim document text.

## Findings

No blocking findings.

## Closure Assessment

- **Medium: duplicate `prospectus_id` not rejected — CLOSED.** `_parse_table()` maintains `seen_ids`; `test_duplicate_prospectus_id_raises_malformed_inventory_error` exercises collision.
- **Medium: forward-drift coverage only partial — CLOSED.** Per-cell extraction + inverse check both implemented and tested.
- **Low: parser doesn't validate kebab-case — CLOSED.** `_KEBAB_RE` regex validator wired into `ProspectusEntry.prospectus_id`.
- **Low: STATUS.md wording — CLOSED.** "single source of truth" → "inventory-backed summary".

## Checklist Notes

The design-doc correction (`Verus 2024-9 / 2026-4` → `Verus 2024-9 / Verus 2026-4`) is a substantive-but-corrective documentation change. The prior abbreviation was effectively a documentation bug for machine-checked inventory parity.

Parenthetical-only edge case handled gracefully via fallback to full-row substring matching.

## Verdict Rationale

APPROVE. The original pass-1 issues are closed in code and targeted tests; full-suite pass supports no observed regressions.
