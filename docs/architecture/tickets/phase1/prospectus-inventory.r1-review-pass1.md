# R1 Review (Pass 1) — `prospectus-inventory` build

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family)
**Date**: 2026-06-03
**Commits under review**: T1 `7e7b0cb`, audit `c4b77a3`, parser `05bcea8`, refactor `c297680`, status-update `e29acc7`
**Verdict**: APPROVE-WITH-CHANGES

## Summary

The build substantially resolves the original recursive doc-test-test trap by replacing `_PROSPECTUS_PATTERNS` with a structured `docs/architecture/prospectus_inventory.md` artifact and inventory-driven parity tests.

The inventory itself appears complete for the current corpus: 24 entries, all 5 fixture directories with `deal_definition.py`, all research-only entries in `tests/fixtures/STATUS.md`, and the prospectuses visible in `docs/architecture/waterfall_ir_design.md`.

## Findings

### Medium — Duplicate `prospectus_id` is not rejected

`load_inventory()` / `_parse_table()` never checks uniqueness of `prospectus_id`. Rows are appended directly after Pydantic validation, so duplicate IDs would parse successfully.

Recommended change: add a duplicate-ID check in `_parse_table()` after parsing each row, raising `MalformedInventoryError` with the duplicate ID and approximate line number.

### Medium — Forward-drift coverage is only partial

`test_inventory_covers_all_waterfall_design_references()` parses only the sample-size table in `waterfall_ir_design.md` and considers a row covered if any inventory `display_name` appears in that row. This catches a new standalone sample-table row but does not catch:
- A new prospectus added outside the sample-size table.
- A new prospectus added into an existing row that already contains a known display name.
- Removal of one inventory entry from multi-deal rows such as `CAS 2024-R05, CAS 2024-R06` or `Verus 2024-9 / 2026-4`.

Recommended change: parse expected deal names from the table cells more explicitly, or maintain a structured expected-name list derived from the design doc and assert each extracted name maps to exactly one inventory entry.

### Low — Parser does not validate `prospectus_id` kebab-case

Current values are kebab-case and unique by inspection, but the parser doesn't enforce the schema-documented requirement.

### Low — `STATUS.md` wording

The top correctly says the source of truth is `prospectus_inventory.md`. However, the following paragraph still says "This document is the single source of truth..." — slight wording inconsistency.

## Closure Assessment

**PARTIALLY-CLOSED**

The architectural direction closes the recursive doc-test-test trap in substance: the corpus now has a canonical inventory artifact, tests consume that artifact, and the brittle regex inventory is gone.

Residual gaps remain around inventory integrity enforcement and forward-drift detection.

## Verdict Rationale

APPROVE-WITH-CHANGES. The build is directionally correct and the current inventory content is complete. Required follow-up: reject duplicate `prospectus_id` values and strengthen the waterfall-design drift test.
