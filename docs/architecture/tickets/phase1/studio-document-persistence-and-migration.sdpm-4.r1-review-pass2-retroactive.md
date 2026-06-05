# R1 Review (Pass 2, retroactive fix-pass) — `sdpm-4-legacy-studio-migration`

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family)
**Date**: 2026-06-03
**Fix-pass under review**: T1 `690e504`, Fix `c0c10a1`
**Verdict**: APPROVE

## Summary

The fix-pass addresses the original R1 findings. T1 adds targeted coverage for the previously untested entity types and specifically exercises the missing `bonds[*].relations[*]` migration path. The fix commit is narrowly scoped: it adds only the `TrancheRelation` walk to `_apply_block_notes()` and does not introduce new `TriggerNode` or `CollateralGroupDef` migration logic.

## Findings

No blocking findings.

The `TrancheRelation` T1 test correctly constructs a deal with `BondDef(name="B1", relations=[TrancheRelation(...)])`, provides `block_data["B1:relation:0"].description`, runs `migrate_studio_payload()`, and asserts that `migrated.bonds[name=B1].relations[0].description` receives the note. This would catch the original regression because pre-fix `_apply_block_notes()` never walked `bonds[*].relations[*]`.

The implementer's claim about existing `TriggerNode` and `CollateralGroupDef` walks holds. The pre-fix helper already handled `triggers[*].name` and `collateral_groups[*].group_id`; `git show c0c10a1 -- src/bma_standard_formulas/deals/schemas/migrations/studio_migration.py` shows only the new `bonds[*].relations[*]` loop.

The synthetic id scheme `<bond_name>:relation:<index>` is deterministic and reasonable. Empty `bonds` and bonds with no `relations` naturally no-op. Bond names containing colons remain deterministic because the implementation constructs exact keys from the actual bond name rather than parsing keys back into parts.

## Closure Assessment

- Original Major — `TrancheRelation.description` not migrated: CLOSED.
- Original Minor — AC 3 test coverage too narrow: CLOSED.

## Verdict Rationale

Approve because the fix directly closes the missing `TrancheRelation` migration path, the T1 test would have failed before the fix, and the fix diff is appropriately narrow.
