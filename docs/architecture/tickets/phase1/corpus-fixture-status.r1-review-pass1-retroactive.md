# R1 Review (Pass 1, retroactive) — `corpus-fixture-status` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family; RETROACTIVE)
**Date**: 2026-06-03
**Implementation under review**: commit `486072f` (test commit `1e1ae68`)
**Verdict**: RETURN-FOR-REVISION

## Findings

1. **Missing prospectuses from `tests/fixtures/STATUS.md`**

   `STATUS.md` does not classify every prospectus/source named in `docs/architecture/waterfall_ir_design.md`.

   Missing from `STATUS.md`:
   - `Ginnie Mae 2024-115 (Multifamily)`
   - `Freddie Mac REMIC general structure (offering circular)`
   - `Citibank Credit Card Issuance Trust`
   - `Discover Card Execution Note Trust`
   - `American Express Credit Account Master Trust`

   Evidence: `waterfall_ir_design.md` names `Ginnie Mae 2024-115` and `Freddie Mac REMIC general OC` in the sample table, and later names five credit-card master trust prospectus families. `STATUS.md` includes only `Capital One COMET` and `Chase Issuance Trust` from that credit-card list.

2. **Meta-tests are not strict enough**

   The tests in `tests/test_corpus_fixture_status.py` can pass against a superficially correct `STATUS.md` that is still missing required content.

   Specific weaknesses:
   - `test_status_md_references_research_only_prospectuses` checks only a representative subset of research-only names, not all names from `waterfall_ir_design.md`.
   - Fixture classification only checks that fixture directory names appear somewhere in the document, not that each is assigned exactly one valid tier.
   - FNR 2006-018 only checks that `QUANTITATIVE GOLDEN` appears somewhere in the document, not near the FNR row and not with all six expected test files.
   - Round-trip commitment only checks for the phrase `round-trip` / `round trip`, not that `(i)` and `(ii)` receive round-trip + canonicalization and `(iii)` explicitly receives no test coverage.
   - The tests do not enforce that every named research-only prospectus is under the `(iii) RESEARCH-ONLY` tier.

## Checklist Results

1. **Every prospectus named in `waterfall_ir_design.md` classified?** No. At least five named sources/prospectuses are missing.
2. **Every fixture with `deal_definition.py` classified?** Yes. All five fixture directories appear in `STATUS.md`.
3. **FNR 2006-018 correctly identified as `(ii) QUANTITATIVE GOLDEN` with six dedicated tie-out test files?** Yes.
4. **Round-trip + canonicalization commitment pinned per tier?** Yes in the document.
5. **Any prospectuses cited in `waterfall_ir_design.md` missing from the doc?** Yes. See Finding 1.
6. **Are the meta-tests adequately strict?** No. They validate broad document shape and a subset of names.

## Required Changes

Before approval:
- Add the missing `waterfall_ir_design.md` entries to `tests/fixtures/STATUS.md`, most likely as `(iii) RESEARCH-ONLY` unless an executable fixture exists.
- Tighten `tests/test_corpus_fixture_status.py` so it enumerates all currently required named prospectuses/sources from the design document.
- Add assertions that each required name appears in the expected tier section or row.
- Add explicit assertions that FNR 2006-018 is classified as `(ii) QUANTITATIVE GOLDEN` and that all six expected FNR test files are listed.
- Strengthen tier-commitment checks so `(i)+(ii)` round-trip/canonicalization and `(iii)` no-test-claim commitments are asserted as content, not just keyword presence.
