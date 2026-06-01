---
reviewer: R1 (gpt-5.5-extra-high, fresh invocation, readonly, pass 2)
date: 2026-06-01
ticket: irvc-5a-export-and-fsck
fix_pass_commit: 48ef77a
verdict: APPROVE
---

## Executive Summary
- B1 is closed: `GitService.__init__` now runs fsck for direct git-service construction, with per-process memoization and app-level structured HTTP surfacing for `REPO_CORRUPT`.
- B2 is closed: `restore_deal` now clones into a temporary directory, validates the cloned HEAD, swaps `.git/` through `.git.old`, rolls back on swap failure, and audits failure.
- The original deal-store fsck guard and new GitService init guard coexist safely for deal-store-mediated calls: `_fsck_guard` verifies first, then `GitService.__init__` observes the shared verified set and skips duplicate work.
- Regression coverage was added for direct `GitService` corruption, HTTP corruption surfacing through a direct-GitService route, and failed restore preserving the original `.git/`.
- Additional sweep found no new `print` statements, no `shell=True`, no lint diagnostics in reviewed files, and no new Blocking/Critical/Major issues.

## Pass-1 finding verification
| Finding | Status | Evidence (file:line) | Test |
|---|---|---|---|
| B1 — fsck bypass | CLOSED | `src/bma_cfengine_app/orchestrator/deals/git_service.py:109-121` runs fsck from `GitService.__init__`; `:129-170` memoizes/checks corruption and raises `RepoCorruptError`; `src/bma_cfengine_app/orchestrator/deals/deal_store.py:291-298` uses the deal-store fsck guard; `src/bma_cfengine_app/api/main.py:65-75` returns structured 503 JSON with `code`, `message`, `diagnostic`; direct router construction at `src/bma_cfengine_app/api/routers/deals.py:1003-1006` and `:1029-1033`. | `tests/orchestrator/deals/test_operational_fsck.py:188-206` corrupts a repo and asserts direct `GitService(repo_path=...)` raises `RepoCorruptError`; `tests/api/routers/test_deals_export.py:70-103` asserts HTTP route returns `503 REPO_CORRUPT`; deal-store memoization preserved by `tests/orchestrator/deals/test_operational_fsck.py:161-185`. |
| B2 — restore not atomic | CLOSED | `src/bma_cfengine_app/orchestrator/deals/operational.py:166-175` clones the bundle into a temporary directory before touching `.git/`; `:176-186` validates cloned `HEAD`; `:188-200` renames original `.git/` → `.git.old` and installs the cloned `.git/`; `:201-206` rolls back `.git.old` on swap failure; `:207-209` removes `.git.old` on success; `:223-228` audits failed restores. | `tests/orchestrator/deals/test_operational_restore.py:165-198` uses an invalid bundle, asserts original `.git/` remains intact, asserts a `restore_result` failure audit record. |

## New findings introduced by the fix-pass
None.

## Verdict justification
APPROVE. Both pass-1 blocking findings are closed in current code and are guarded by targeted regression tests. No new Blocking, Critical, or Major findings were introduced by the fix-pass.
