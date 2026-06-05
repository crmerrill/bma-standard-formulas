# R1 Review (Pass 1, retroactive) — `vpc-4-ci-guard` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family; RETROACTIVE)
**Date**: 2026-06-03
**Implementation under review**: commit `d12b1b5` (test commit `eb49347`)
**Verdict**: RETURN-FOR-REVISION

## Findings

1. **AC 5 is effectively skipped in CI under the checked-in workflow.**

   `.github/workflows/ci.yml` uses `actions/checkout@v4` without `fetch-depth: 0` or equivalent parent-fetch setup. The implementation runs:

   `git diff --name-only HEAD~1 HEAD`

   and treats any `CalledProcessError` as the documented first-commit skip. In GitHub Actions' default shallow checkout, `HEAD~1` is commonly unavailable, so the same-commit catalog update enforcement can silently return `[]` and pass. The T1 test creates a normal local repo with full history, so it does not cover this CI behavior.

   Impact: AC 5 is not reliably enforced where it matters most.

2. **AC 6 is only partially satisfied: there is no `diagnostic-check` CI job.**

   The implementation adds the `diagnostic:check` script in `src/bma_cfengine_app/ui/package.json`, and CI does run `python -m bma_standard_formulas.diagnostics.check`. However, the ticket's file list and reviewer checklist call for a CI workflow `diagnostic-check` job. The implementation adds a step named `Diagnostic catalog parity check` inside the existing matrix `test` job instead.

3. **AC 1 TS aggregation is too narrow in the reviewed commit.**

   In `d12b1b5`, `_DEFAULT_TS_FILES` contains only `src/bma_cfengine_app/ui/src/features/validation/diagnosticRegistry.ts`. That file defines the registry but does not necessarily contain validator registrations. Future worker validators added in sibling files would not be discovered unless callers manually pass `--ts-file`.

4. **Catalog metadata is not fully treated as the source of truth.**

   The checker confirms Python codes exist in the catalog and confirms worker/both catalog entries exist in TS, but it does not compare catalog `severity` / `path_schema` against Python metadata or TS metadata. It only compares Python vs TS when both sides exist.

   Impact: a backend-only Python diagnostic can diverge from the catalog on severity/path schema and still pass.

## AC Checklist

- **AC 1**: Partial. CLI exists, parses catalog + scans Python + scans TS, but defaults are too narrow.
- **AC 2**: Pass. Decorated Python validators missing from the catalog fail.
- **AC 3**: Pass for scanned TS files, but weakened by default TS file scope.
- **AC 4**: Pass for Python-vs-TS on shared codes; incomplete for catalog-vs-registry metadata parity.
- **AC 5**: Fail. CI shallow checkout can skip it; "first commit on new branch" skip is documented inaccurately.
- **AC 6**: Partial. Script exists; CI runs the command but not as a `diagnostic-check` job.

## Required Changes

- Make AC 5 reliable in CI by fetching enough history or using a CI-safe diff base.
- Add the requested `diagnostic-check` job, or update the ticket/checklist if a matrix step is intentionally accepted instead.
- Broaden default TS discovery to all relevant validation worker modules while excluding tests and dependencies.
- Compare catalog metadata against Python and TS metadata, not only Python against TS.
