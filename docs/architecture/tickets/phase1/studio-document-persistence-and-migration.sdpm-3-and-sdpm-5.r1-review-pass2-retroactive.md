# R1 Review (Pass 2, retroactive fix-pass) — `sdpm-3` + `sdpm-5` combined

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family)
**Date**: 2026-06-03
**Fix-pass under review**: sdpm-3 T1 `6223af1` Fix `8a8a5a3`; sdpm-5 T1 `de4de33` Fix `c66a8ac`
**Verdict**: APPROVE

## Summary

The combined fix-pass closes both original Major findings structurally.

For `sdpm-3`, the implementation now handles the unborn git repository state inside `_load_from_git`: if version resolution returns `None` but `deal.json` exists, it acquires `_migration_lock(d)`, re-resolves after waiting, and only creates the migration commit itself if the repository is still unborn. That is the right serialization shape for two first-open callers.

For `sdpm-5`, `_update_manifest_on_save` now rebuilds a fresh six-key manifest from scratch and preserves only canonical prior values that are intentionally retained.

## Findings

### `sdpm-3`

No blocking findings.

Observation: `test_unborn_git_repo_completes_migration_instead_of_returning_none` is a faithful sequential simulation of the problematic intermediate state, not a true concurrent race test. It manually creates `.git/`, points `HEAD` at `refs/heads/main`, confirms the repo is unborn, then calls `load_deal()` and asserts recovery. This proves the new unborn-repo recovery path and would have failed the old behavior, but it does not run two callers in parallel or prove lock waiting under actual contention.

The implementation itself is sound for the original race. `_migrate_deal_json_to_git` holds `_migration_lock(d)` across `git init` and `commit_deal`; a concurrent reader that sees `.git/` before the commit reaches `_load_from_git`, gets `sha is None`, then attempts the same `_migration_lock(d)`. If the migrator still holds it, the reader waits; after acquiring it, the reader re-resolves and sees the committed SHA. If no migrator is active and the repo is genuinely unborn, it completes the migration itself.

Residual coverage gap: state-based regression rather than thread/process-based. A future test using two threads or processes with a pause between `_git_init_main` and `commit_deal` would better prove the lock behavior under contention.

### `sdpm-5`

No findings.

`test_save_deal_strips_all_non_canonical_keys_from_dirty_manifest` covers the full forbidden-key set: transitional keys, legacy versioning keys, and an arbitrary stale key. Asserts the post-save manifest key set is exactly the canonical six keys.

`_update_manifest_on_save` constructs a new dict containing only `deal_id`, `deal_name`, `asset_class`, `schema_version_pin`, `created_at`, `updated_at`. Preserves `created_at` when present via `prior.get("created_at")`, creates fresh timestamp when absent.

The deferred minor `_extract_collateral_risk_settings` issue is defensible. `DealDefinition` has no `solver_presets` field; the helper now has explicit docstring documenting that canonical `deal.json` cannot carry solver presets and the legacy fallback was removed in `sdpm-5`.

## Closure Assessment

### `sdpm-3`
- Major M1, concurrent first-open can observe initialized but uncommitted repo: **CLOSED**.
- Race coverage gap, no true concurrent regression test: **PARTIALLY-CLOSED** as test coverage.

### `sdpm-5`
- Major M1, dirty manifest leak on save: **CLOSED**.
- Minor m1, `_extract_collateral_risk_settings` not literally rewired: **DEFERRED**. Acceptable because `DealDefinition` has no `solver_presets`; helper now documents the intentional empty result.

## Verdict Rationale

Approve. The two Major findings are fixed in the implementation, and the new tests are well-targeted for the previously failing states. The only remaining sdpm-3 concern is test-strength: adding a true two-caller concurrency regression would improve confidence, but the current recovery path and lock placement address the reviewed race condition.
