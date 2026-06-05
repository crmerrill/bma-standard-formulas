# R1 Review (Pass 2, retroactive fix-pass) — `vpc-2-catalog-document`

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family)
**Date**: 2026-06-03
**Fix-pass under review**: T1 `dd5b650`, Fix `296e012`
**Verdict**: APPROVE

## Summary

The fix-pass closes the three R1 Minor findings. The parser now reads the catalog with explicit UTF-8, avoids the header-at-EOF `IndexError`, and validates separator-row column count rather than relying only on the separator regex.

`python -m bma_standard_formulas.diagnostics.check` should still pass: the default catalog still has the expected 7-column header, a 7-column separator row, and valid 7-column data rows; the check command delegates to the hardened parser.

## Findings

No blocking findings.

One test-quality note: `test_utf8_message_template_parses` writes the fixture with `encoding="utf-8"` and verifies non-ASCII round-trip through the parser, so it does exercise UTF-8 content. However, on hosts whose default encoding is already UTF-8, this test would likely also pass against the old `read_text()` implementation. The production fix itself is still correct and directly covers the portability concern.

## Closure Assessment

- **Minor 1: separator-row validation** — CLOSED. `test_malformed_separator_row_column_count_raises` uses a 7-column header with a 2-column separator. That separator satisfies the old regex-only shape check, but now fails the new `_split_row()` column-count check.
- **Minor 2: header-at-EOF can raise raw `IndexError`** — CLOSED. Now checks `sep_idx >= len(lines)` before reading `lines[sep_idx]`, raises `MalformedCatalogError` with a clean EOF message.
- **Minor 3: UTF-8 should be explicit** — CLOSED. The parser now uses `catalog_path.read_text(encoding="utf-8")`.

## Verdict Rationale

Approve. The behavioral fixes are narrowly scoped, match the original review recommendations, and should not disturb the default diagnostic catalog check.
