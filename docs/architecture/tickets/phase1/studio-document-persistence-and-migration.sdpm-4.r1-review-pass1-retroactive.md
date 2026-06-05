# R1 Review (Pass 1, retroactive) — `sdpm-4-legacy-studio-migration` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family; RETROACTIVE)
**Date**: 2026-06-03
**Implementation under review**: commit `5c74177` (test commit `c8facf5`)
**Verdict**: RETURN-FOR-REVISION

## Summary

The implementation lands the intended migration hook shape and correctly wires `migrate_studio_payload(payload, ir) -> (sidecar, ir, provenance)` into legacy first-open migration. Layout extraction, basic coordinate parsing, malformed XML handling, missing `block_data`, and the exact AI provenance footer are mostly correct.

However, AC 3 is not fully satisfied against the requested entity matrix: `TrancheRelation.description` is never populated, while closure claims it is. The test commit only covers `CalculationNode` and `RuleNode`, leaving `TriggerNode`, `CollateralGroupDef`, and `TrancheRelation` unpinned.

## Findings

### Major — AC 3 incomplete: `TrancheRelation.description` is not migrated

`src/bma_standard_formulas/deals/schemas/migrations/studio_migration.py` applies notes to calculations, triggers, waterfall rules, and collateral groups, but never walks `bonds[*].relations[*]`.

Evidence:
- `TrancheRelation` has a first-class `description: str = ""` field in `src/bma_standard_formulas/deals/schemas/ir.py`.
- `_apply_block_notes()` handles `calculations[*].name`, `triggers[*].name`, `waterfall_rules[*].rule_id`, `collateral_groups[*].group_id`.
- It does not handle `bonds[*].relations`.

This means legacy notes for tranche relationship blocks are silently dropped. The closure artifact also overstates the landed behavior by saying notes are injected into `TrancheRelation`.

Recommended fix: add deterministic matching for relation notes, likely using the legacy block id convention if one exists, or a documented synthetic id such as `<bond_name>:relation:<index>` / relation block id carried in legacy `block_data`. Add a T1 case proving the mapping.

### Minor — AC 3 test coverage is narrower than the accepted entity surface

`tests/orchestrator/deals/test_studio_migration.py` covers only `CalculationNode.description` and `RuleNode.description`. It does not cover `TriggerNode.description`, `CollateralGroupDef.description`, `TrancheRelation.description`.

### Minor — Blockly XML extraction only inspects top-level `block` elements

`_extract_layout_from_xml()` uses `root.findall("blockly:block", ns) or root.findall("block")`, so it only sees direct child blocks.

## What Landed Well

AC 1 is satisfied: signature is `migrate_studio_payload(studio_version_payload, deal_definition) -> tuple[StudioSidecar, DealDefinition, dict[str, Any] | None]`.

AC 2 is mostly satisfied: Blockly XML is parsed into `StudioSidecar.layout_overrides`, coordinates are parsed as floats, invalid coordinates skipped, malformed XML returns empty layout.

AC 4 is satisfied: commit message formatting is exactly `Migrate v{N}\n\nLegacy-Studio-Provenance:\n<json.dumps(provenance, sort_keys=True, indent=2)>`. The footer is omitted when no provenance is present.

## Verdict Rationale

Return for revision because AC 3 is materially incomplete for `TrancheRelation`, and the tests do not cover the full entity set the implementation and closure claim. The fix is localized.

## Sign-off

Retroactive R1 review complete. Do not treat `sdpm-4` as fully R1-approved until the `TrancheRelation` migration gap and missing entity coverage are addressed.
