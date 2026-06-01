---
reviewer: R1 (gpt-5.5-extra-high, fresh invocation, readonly)
date: 2026-06-01
ticket: irvc-5b-backup-restore
implementation_commit: b8d7b39
verdict: APPROVE-WITH-CHANGES
---

## Executive Summary
- AC 1 and AC 2 are implemented and mapped to the T1 tests.
- AC 3 delegates to `operational.restore_deal` and does not reimplement unbundle/swap logic.
- No IR/schema drift, no Phase 2/3+ references, and no scheduled cron implementation.
- Main concern: restore bundle discovery is too broad and can select another deal's bundle on substring collisions.
- Secondary concern: missing/non-git deals fail via raw subprocess exceptions instead of clear CLI errors.

## Acceptance criteria audit
| AC | Status | Evidence | Notes |
|---|---|---|---|
| 1 — per-deal bundle | ✓ | `scripts/backup_deals.py:22-34`; `tests/orchestrator/deals/test_operational_backup.py:138-166` | Runs `git bundle create <out>/deal_{id}.bundle --all` with `cwd` set to the deal repo. `--out` is created with `mkdir(parents=True, exist_ok=True)`. |
| 2 — tenant orchestration | ✓ | `scripts/backup_deals.py:37-58`; `tests/orchestrator/deals/test_operational_backup.py:169-217` | Iterates git-backed deal dirs under `deal_store._DEALS_DIR`, creates per-deal bundles, and adds all bundle paths to `tenant_{tenant_id}.tar`. |
| 3 — restore CLI | partial | `scripts/restore_deal.py:17-44`; `src/bma_cfengine_app/orchestrator/deals/operational.py:126-229`; `tests/orchestrator/deals/test_operational_backup.py:220-256` | Correctly imports and calls `operational.restore_deal(args.deal, bundle_path)`. However, bundle matching is substring-based. |

## Findings

### Blocking
None.

### Critical
None.

### Major

#### M1 — Major — `scripts/restore_deal.py:17`
**Issue + evidence**: `_find_latest_bundle` searches both `deal_{deal_id}*.bundle` and `*{deal_id}*.bundle`, then picks the newest by mtime. This can match another deal whose ID contains the requested ID as a substring and restore the wrong repository into the requested deal.

**Recommended fix**: Restrict candidates to the backup script's naming contract, e.g. exact `deal_{deal_id}.bundle` plus a future timestamp suffix format such as `deal_{deal_id}_*.bundle`. Avoid unrestricted `*{deal_id}*.bundle`.

### Minor

#### m1 — Minor — `scripts/backup_deals.py:22`
**Issue + evidence**: `_backup_one_deal` calls `deal_dir(deal_id)`, and `deal_dir` creates the directory if missing. A nonexistent deal therefore creates an empty directory and then fails through an uncaught `subprocess.CalledProcessError` from `git bundle`.

**Recommended fix**: Resolve the path without creating it, verify it exists and contains `.git`, print a concise stderr error, and return `1`.

### Nit
None.

## Verdict justification
APPROVE-WITH-CHANGES: zero Blocking and zero Critical findings, with one Major and one Minor issue. The implementation satisfies the core ticket shape and test intent, but restore candidate selection should be tightened before relying on this CLI operationally.
