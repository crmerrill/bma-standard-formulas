# R1 Review (Pass 1, retroactive) — `sdpm-5-retire-transitional-apis` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family; RETROACTIVE)
**Date**: 2026-06-03
**Implementation under review**: commit `836451f` (test commit `8d23268`)
**Verdict**: RETURN-FOR-REVISION

## Findings

### Major

**M1 — AC 1 manifest writer is not actually exhaustive on save.**
`_collapse_manifest_post_migration` rebuilds `manifest.json` to the exact six-key set, and the tests cover that path plus a brand-new `save_deal`. But `_update_manifest_on_save` still starts from the existing manifest and only pops `studio_current_version`, `studio_versions`, and `solver_presets_library`. Any other preexisting key, including legacy `current_version` / `versions` from older canonical manifests or arbitrary stale manifest fields, survives the write.

Evidence: `src/bma_cfengine_app/orchestrator/deals/deal_store.py` lines 363-387 reads an existing manifest, mutates it, pops only `_TRANSITIONAL_MANIFEST_KEYS`, then writes it back. That does not satisfy AC 1's "outputs EXACTLY `{deal_id, deal_name, asset_class, schema_version_pin, created_at, updated_at}`" / exhaustive allowed-field set. This is also under-tested: `tests/orchestrator/deals/test_deal_store_manifest.py` does not seed an existing save manifest with `current_version`, `versions`, or unrelated extra keys before calling `save_deal`.

Recommended fix: make `_update_manifest_on_save` rebuild a fresh six-key manifest, preserving only allowed values such as prior `created_at` / `asset_class` where appropriate, and add a regression case with an existing dirty manifest.

### Minor

**m1 — `_extract_collateral_risk_settings` is not literally rewired through canonical `deal.json`.**
The legacy fallback is removed, which is the important behavioral cutover. However, the helper now returns `{}` unconditionally instead of reading canonical `deal.json` via `GitService.show(...)` / `DealDefinition.model_validate(...)` as AC 3 says.

Given `DealDefinition` currently has no `solver_presets`, this is probably behaviorally equivalent for normal run/solve calls because `_ensure_canonical_deal` validates the deal first. Still, the implementation does not match the specified helper rewiring.

### Nit

**n1 — stale sdpm-5 comments remain.**
`src/bma_cfengine_app/orchestrator/deals/deal_store.py` module docstring still says Studio IR snapshots and solver presets continue to operate on flat files. `src/bma_cfengine_app/orchestrator/deals/operational.py` also says restore preserves `studio_current_version` / `studio_versions` per irvc-3. Stale after sdpm-5.

## Checklist Notes

AC 2 passes: the five `deal_store` methods are deleted from production code.

AC 3 route deletion passes: `GET /deals`, `GET /deals/{deal_id}`, `POST /deals`, and both solver preset routes are removed. `POST /deals/{deal_id}/commit` and `GET /deals/{deal_id}/branches` remain present. The test commit relaxed deleted-route assertion to accept `{404, 405}` for Starlette method/path matching behavior.

External callers look addressed: `scripts/seed_fnr_2006_018.py` was rewired off `save_studio_ir`, and test deletions are largely dead-code coverage for the intentionally retired endpoint/function surface.
