# R1 Review (Pass 1, retroactive) — `sdpm-3-first-open-behavior` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family; RETROACTIVE — implementation landed at 092a5b5 without a contemporaneous R1 review)
**Date**: 2026-06-03
**Implementation under review**: commit `092a5b5` (test commit `ed38ffe`)
**Verdict**: APPROVE-WITH-CHANGES

## Summary

The sdpm-3 implementation satisfies the direct acceptance criteria for the normal first-open paths:

- Missing `.git/` plus existing `deal.json` initializes git and creates a `system:migration` commit with subject `Migrate deal.json`.
- The migration commit body is empty in the sdpm-3 path.
- Missing `sidecar.json` in the selected commit returns a default `StudioSidecar()` and no diagnostic.
- The migration is idempotent for sequential callers via a per-deal advisory lock and an in-lock `.git/` recheck.

The main residual issue is a first-open concurrency race: `.git/` is created before the migration commit exists, and `load_deal()` treats `.git/` existence as proof that migration is complete. A concurrent opener can therefore skip the migration lock and attempt to load an unborn or mid-migration repo.

## Findings

### Major

- **M1 — Concurrent first-open can observe an initialized but uncommitted repo and return `None` transiently.**
  `src/bma_cfengine_app/orchestrator/deals/deal_store.py:171` creates `.git/`, then `src/bma_cfengine_app/orchestrator/deals/deal_store.py:174-179` creates the migration commit. During that window, a second process entering `load_deal()` will skip `_migrate_deal_json_to_git()` because `.git/` now exists (`src/bma_cfengine_app/orchestrator/deals/deal_store.py:455-457`), then proceed to `_load_from_git()` (`src/bma_cfengine_app/orchestrator/deals/deal_store.py:459-461`). If no commit is visible yet, `_resolve_version_to_sha()` returns `None` and `_load_from_git()` returns `None` (`src/bma_cfengine_app/orchestrator/deals/deal_store.py:308-310`).
  This does not violate the single-process AC tests, but it fails the edge-case expectation for concurrent reads while first-open migration is in flight. The migration lock protects the migrator, but readers do not wait on that lock once `.git/` exists. Recommended fix: before loading a git repo that has `deal.json` but zero commits, acquire `_migration_lock(d)`, re-check commit count, and either wait for the completed migration or finish committing `deal.json` if the repo is still unborn.

## What Landed Well

- **AC 1 mapping is present.** `_migrate_deal_json_to_git()` only runs when `.git/` is absent and `deal.json` exists, initializes the repo, and commits the exact file via `GitService.commit_deal()` (`src/bma_cfengine_app/orchestrator/deals/deal_store.py:153-179`).
- **Commit metadata is correct for the sdpm-3 path.** The author string parses to author name `system:migration` (`src/bma_cfengine_app/orchestrator/deals/deal_store.py:176`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:936-940`), and the message is exactly `Migrate deal.json` with no body.
- **Missing sidecar behavior matches AC 2.** `_load_sidecar_from_commit()` returns `StudioSidecar(), []` when `sidecar.json` is absent.
- **Sequential idempotency is handled.** `_migrate_deal_json_to_git()` has a fast-path `.git/` check and an in-lock recheck.
- **T1 covers the core happy paths.** Author name, subject, empty body, committed `deal.json` content, default sidecar, no `SIDECAR_LOAD_FAILED` for missing sidecar.

## Verdict Rationale

This is not a return-for-revision on AC drift: the specified normal-case behavior is implemented, and the tests pin the central contract. However, the implementation should not be treated as fully reviewed until the first-open race is closed.

No Blocking or Critical findings were identified.

## Sign-off Recommendation

Approve with changes. Add a focused concurrency regression around two simultaneous `load_deal()` calls for a plain `deal.json` directory, with one caller paused after `git init` and before `commit_deal()`. Then patch `load_deal()` or the migration helper so readers encountering an unborn git repo wait under `_migration_lock()` and re-check before loading.
