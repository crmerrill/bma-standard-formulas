---
reviewer: R1 (gpt-5.5-extra-high, fresh invocation, readonly)
date: 2026-06-01
ticket: irvc-3-legacy-migration
implementation_commit: 8c68fde
verdict: APPROVE-WITH-CHANGES
---

## Executive Summary
- T1 tests map to AC 1-5, and the implementation satisfies the direct happy-path migration, manifest-collapse, schema-migration-before-validation, and studio-sidecar preservation requirements.
- `migrate_deal_payload` is called before `DealDefinition.model_validate` on the git load path.
- No FastAPI router code was touched, and no Phase 2/3 entities appear in the implementation.
- Two Major issues remain: versioned `load_deal(..., version=N)` no longer works for non-migration saves, and first-open migration is not wrapped as one repo-level write-lock operation.

## Acceptance criteria audit

| AC | Status | Evidence | Notes |
|---|---|---|---|
| 1 — linear migration | ✓ | `tests/orchestrator/deals/test_deal_store_migration.py:120`, `src/bma_cfengine_app/orchestrator/deals/deal_store.py:129` | T1 asserts exact author/message/parent chain/final payload. Implementation commits legacy versions in sorted order with `system:migration <migration@bma>` and `Migrate v{N}`. |
| 2 — idempotency | ✓ | `tests/orchestrator/deals/test_deal_store_migration.py:180`, `src/bma_cfengine_app/orchestrator/deals/deal_store.py:118` | Idempotency is `.git/` based as specified. |
| 3 — manifest collapse | ✓ | `tests/orchestrator/deals/test_deal_store_migration.py:206`, `src/bma_cfengine_app/orchestrator/deals/deal_store.py:160` | Manifest is rewritten to exactly the allowed field set, and the FUTURE annotation is present. |
| 4 — save/load route + schema migration first | partial | `tests/orchestrator/deals/test_deal_store_git.py:100`, `src/bma_cfengine_app/orchestrator/deals/deal_store.py:199` | Git routing and migration-before-validation are present, but versioned loads after normal saves regress. |
| 5 — studio APIs preserved | ✓ | `tests/orchestrator/deals/test_deal_store_legacy_studio.py:91`, `src/bma_cfengine_app/orchestrator/deals/deal_store.py:340` | Studio snapshots remain file-backed via `studio_v{N}.json`; solver preset APIs retain signatures. |

## Findings

### Blocking
None.

### Critical
None.

### M1 — Major — `src/bma_cfengine_app/orchestrator/deals/deal_store.py:189`
**Issue + evidence**: Versioned git loads only search for commits whose message is exactly `Migrate v{version}`. Normal `save_deal` commits use `Save deal {deal.deal_name}` and ignore the `version` argument, while returning `{"version": _commit_count(...)}`. That means a caller can save a deal, receive version `N`, then `load_deal(deal_id, version=N)` returns `None` instead of the saved deal. This breaks the existing router-facing version contract used by `_ensure_canonical_deal(..., version=...)`, run, solve, verify, and solver-template endpoints.

**Recommended fix**: Preserve a stable version-to-commit mapping for all canonical commits, not only migration commits. Options: encode version metadata consistently, maintain a manifest mapping from version number to commit SHA, or make the public API move fully to SHA while keeping old version callers functional during transition. Also restore `load_deal`'s non-optional behavior by raising `FileNotFoundError` for missing versions rather than returning `None`.

### M2 — Major — `src/bma_cfengine_app/orchestrator/deals/deal_store.py:110`
**Issue + evidence**: The migration sequence is not wrapped in one `GitService._write_lock` or equivalent. `_migrate_legacy_to_git` checks `.git/`, runs `git init`, commits each legacy version, and collapses the manifest outside a single migration-level lock. `GitService.commit_deal` locks individual commits, but another request can observe `.git/` after init and before commits/manifest collapse, causing `load_deal` to skip migration and return `None`; two concurrent migrators can also interleave the commit sequence.

**Recommended fix**: Acquire a per-repo migration/write lock before the `.git/` idempotency check and hold it through `git init`, all migration commits, and manifest collapse. Re-check `.git/` inside the lock before doing work.

### Minor
None.

### Nit
None.

## Verdict justification
APPROVE-WITH-CHANGES. The implementation meets the main single-threaded AC paths and respects the ticket's scope, but the two Major issues should be addressed before treating this as merge-ready: versioned canonical load/save compatibility is a router-facing regression, and migration needs a transaction-like write lock to satisfy the operational concurrency intent.
