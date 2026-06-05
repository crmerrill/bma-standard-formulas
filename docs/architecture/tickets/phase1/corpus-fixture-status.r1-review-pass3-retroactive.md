# R1 Review (Pass 3, retroactive fix-pass-2) — `corpus-fixture-status`

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family)
**Date**: 2026-06-03
**Fix-pass-2 under review**: T1 `7783648`, Fix `009c0be`
**Verdict**: APPROVE-WITH-CHANGES

## Summary

Fix-pass-2 materially improves the pass-2 gaps. The drift test now reads `docs/architecture/waterfall_ir_design.md` and extracts candidates dynamically via `_parse_waterfall_prospectuses()`, and the tier-row uniqueness test now checks exactly one classification row per executable fixture directory.

However, the drift guard is still heuristic. `_PROSPECTUS_PATTERNS` is an issuer-family regex inventory, not a source-of-truth parser. It catches additions within known families, but it would not catch new issuer families such as `Hertz Vehicle Financing` or `BMW Vehicle Owner Trust` unless the regex list is updated.

## Findings

1. **Forward-drift protection is improved but still partial.** The parser reads the design doc and applies `_PROSPECTUS_PATTERNS` over the full text, returning 22 candidates, all present in `STATUS.md`. Simulated additions: `Ford Credit Auto Owner Trust 2025-A` caught; `Hertz Vehicle Financing 2024-1` not caught; `BMW Vehicle Owner Trust 2024-A` not caught.

2. **Per-row fixture uniqueness follow-up is closed.** Counts only lines where both fixture directory name and at least one tier label appear. Verified counts are exactly one row each for `cc_series_test`, `fnr_2006_018`, `ford_2024_c`, `ginniemae_2025_203`, `verus_2024_9`.

3. **No human-missed current drift found.** All 22 candidates extracted are present in current STATUS.md.

4. **Formatting and line-wrap edge cases remain.** Regexes handle markdown wrapping around the whole name (e.g., `**Toyota Auto Receivables 2025-A**`) but not names split across line breaks or with markdown inserted internally.

## Closure Assessment

**PARTIALLY-CLOSED**

- Per-row uniqueness: **CLOSED**
- Current 22-name extraction and STATUS.md presence: **CLOSED**
- Forward-drift protection for known issuer families: **CLOSED**
- Forward-drift protection for new issuer families: **PARTIALLY-CLOSED**
- Wrapped / internally formatted prospectus names: **PARTIALLY-CLOSED**

## Verdict Rationale

`APPROVE-WITH-CHANGES` because the fix closes the concrete current defects and is a pragmatic improvement over a hardcoded full-name list.

Required follow-up: document `_PROSPECTUS_PATTERNS` as an issuer-family inventory with known false negatives, or replace it with a more robust source of truth. The cleaner long-term mechanism would be a maintained prospectus inventory table/document that both `STATUS.md` and `waterfall_ir_design.md` reference.
