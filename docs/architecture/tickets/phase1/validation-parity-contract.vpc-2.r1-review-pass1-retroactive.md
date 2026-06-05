# R1 Review (Pass 1, retroactive) — `vpc-2-catalog-document` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family; RETROACTIVE)
**Date**: 2026-06-03
**Implementation under review**: commit `18bdd35` (test commit `77f083c`)
**Verdict**: APPROVE-WITH-CHANGES

## Summary

The implementation satisfies the core vpc-2 acceptance criteria: the diagnostic catalog document establishes the required 7-column schema, the parser returns structured `TypedDict` records, and the covered malformed-header cases raise clear `MalformedCatalogError`s.

I would not block the retroactive R1 on the current implementation, but I recommend a small hardening follow-up before vpc-4 depends on this parser in CI.

## Checklist

- **AC 1: PASS.** `docs/architecture/diagnostic_catalog.md` defines the required 7-column table.
- **AC 2: PASS.** `scripts/parse_diagnostic_catalog.py` extracts catalog rows into structured `CatalogRecord` `TypedDict` records.
- **AC 3: PASS with minor hardening recommended.** Missing/wrong header schemas fail clearly, and malformed data-row column counts fail clearly. However, separator-row validation is weaker than the rest of the parser.
- **Robustness: mostly PASS.** Extra whitespace cells stripped. Mixed-case header rows accepted. UTF-8 message content should work, but the parser relies on `Path.read_text()` default encoding rather than explicit `encoding="utf-8"`.
- **Forward compatibility: PASS.** Future column additions currently fail closed with a clear expected-header message.

## Findings

1. **Minor: separator-row validation can miss malformed table schemas.** Suggested fix: parse the separator row with `_split_row()` and require `len(separator_cells) == len(EXPECTED_HEADERS)`.

2. **Minor: header-at-EOF malformed input can raise `IndexError` instead of `MalformedCatalogError`.** Suggested fix: split bounds check from content check, or use safe placeholder.

3. **Minor: UTF-8 should be explicit for CI portability.** Suggested fix: `catalog_path.read_text(encoding="utf-8")`.

## Test Review

The T1 commit covers the main happy path and the most important malformed-header case. Missing tests for: mixed-case headers, extra-whitespace cells, UTF-8 message text, malformed separator row shape, header present with no following separator row, future extra-column behavior.
