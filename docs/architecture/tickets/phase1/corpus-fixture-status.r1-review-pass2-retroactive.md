# R1 Review (Pass 2, retroactive fix-pass) — `corpus-fixture-status`

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family)
**Date**: 2026-06-03
**Fix-pass under review**: T1 `d4ef0c4`, Fix `cfcb0b0`
**Verdict**: APPROVE-WITH-CHANGES

## Summary

The fix-pass adds all five previously missing prospectus references to `tests/fixtures/STATUS.md` under the `(iii) RESEARCH-ONLY` section:

- `Ginnie Mae 2024-115 (Multifamily)`
- `Freddie Mac REMIC general structure (offering circular)`
- `Citibank Credit Card Issuance Trust`
- `Discover Card Execution Note Trust`
- `American Express Credit Account Master Trust`

Independent re-audit of `docs/architecture/waterfall_ir_design.md` confirms the current research-only set is complete in `STATUS.md`; original omission count was exactly five.

## Findings

1. **Forward-fragility remains in the meta-test**

   `tests/test_corpus_fixture_status.py` declares `WATERFALL_DESIGN_PATH`, but the tightened research-only coverage test does not read or parse it. Instead, `REQUIRED_RESEARCH_ONLY_NAMES` is a hardcoded list.

   Result: if a future patch adds a new prospectus to `docs/architecture/waterfall_ir_design.md` but does not update `STATUS.md` or the hardcoded list, this test will not catch the drift.

2. **Per-row tier assertion is improved but not a strict uniqueness check**

   The new test verifies that each fixture directory appears on at least one row with exactly one valid tier label. It does not prove that each fixture directory appears on exactly one classification row.

## Closure Assessment

**PARTIALLY-CLOSED**

- Missing prospectuses: **CLOSED**
- Independent audit completeness: **CLOSED**
- FNR-specific quantitative golden assertion: **CLOSED**
- Round-trip / no-coverage wording assertion: **CLOSED**
- Per-row tier assertion: **PARTIALLY-CLOSED**
- Forward-drift protection: **OPEN**

## Verdict Rationale

Content fix is correct. Tightened tests are materially better than Pass 1 and close the immediate missing-name gap.

Follow-up requested before fully closed: make the drift guard compare `waterfall_ir_design.md` against `STATUS.md` mechanically, and tighten the fixture-tier check to require exactly one classification row per fixture directory.
