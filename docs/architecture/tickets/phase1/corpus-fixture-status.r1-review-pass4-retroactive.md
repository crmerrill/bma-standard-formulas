# R1 Review (Pass 4, retroactive fix-pass-3) — `corpus-fixture-status`

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family)
**Date**: 2026-06-03
**Fix-pass-3 under review**: T1 `08c5480`, Fix `c622570`
**Verdict**: APPROVE-WITH-CHANGES

## Summary

The fix commits add the requested documentation block above `_PROSPECTUS_PATTERNS` and the requested `## Follow-on tickets` section in `tests/fixtures/STATUS.md`.

The actual documentation content satisfies the pass-3 follow-up. The remaining weakness is in the regression test: `test_prospectus_patterns_documents_known_limitations` does not strictly assert every required documentation string it claims to protect.

## Findings

1. Issuer-family/source-of-truth limitation: adequately checked.
2. "New issuer families require pattern updates" limitation: only partially checked. Test asserts `Hertz`, `BMW`, or `vehicle leasing` appears, but not wording equivalent to "new issuer families" or "require explicit pattern updates."
3. "Wrapped/internally formatted names not detected" limitation: only partially checked. Test asserts line-break / wrapped / split-across wording, but not `internal markdown` or `internal formatting`.
4. `test_status_md_references_future_inventory_followup`: satisfies the requested follow-on guard.
5. Actual comment block above `_PROSPECTUS_PATTERNS`: clearly documents all three limitations.
6. Actual STATUS.md follow-on section: contains both required references.
7. Regression robustness: partial. Whole-comment-block removal would be caught; narrower edits removing specific limitation wording would not.

## Closure Assessment Of Pass-3 Follow-Ups

**PARTIALLY-CLOSED**

- Document `_PROSPECTUS_PATTERNS` as issuer-family inventory, not source of truth: **CLOSED**
- Document known false negatives for new issuer families: **CLOSED in prose; PARTIALLY-CLOSED in test guard**
- Document wrapped / internally formatted names not detected: **CLOSED in prose; PARTIALLY-CLOSED in test guard**
- Add `STATUS.md` follow-on item for future structured inventory artifact: **CLOSED**
- Ensure tests robustly catch documentation regression: **PARTIALLY-CLOSED**

## Verdict Rationale

`APPROVE-WITH-CHANGES` because the user-facing documentation fixes are present and clear, and the STATUS follow-on guard is adequate.

Required change: tighten `test_prospectus_patterns_documents_known_limitations` so it explicitly asserts wording for "new issuer families require explicit pattern updates" and "internal markdown/internal formatting is not detected," not only example issuer names and line-wrap terminology.
