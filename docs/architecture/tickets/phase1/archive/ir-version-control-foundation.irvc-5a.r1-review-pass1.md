---
reviewer: R1 (gpt-5.5-extra-high, fresh invocation, readonly)
date: 2026-06-01
ticket: irvc-5a-export-and-fsck
implementation_commit: 29420cd
verdict: RETURN-FOR-REVISION
---

## Executive Summary
- Export hardening is correctly path-free: `export_deal(deal_id, sha)` only calls `service.show(sha, "deal.json")`.
- The `REPO_CORRUPT` diagnostic is registered with `severity=error` and `owner=backend`, and fsck failures carry a `DiagnosticPayload`.
- The T1 tests cover AC 1-7 at the ticket level, but they miss an important direct `GitService`/HTTP commit bypass.
- AC 4 is not fully met: several existing git-touching entry points instantiate `GitService` directly and never run `_run_fsck`.
- `restore_deal` is not atomic: it deletes the existing `.git/` before the replacement clone has succeeded, so a failed restore can leave the deal worse than before.

## Acceptance criteria audit
| AC | Status | Evidence | Notes |
|---|---|---|---|
| 1 — export_deal signature | ✓ | `src/bma_cfengine_app/orchestrator/deals/operational.py` lines 59-70 | Exactly `deal_id, sha`; returns bytes from `service.show(...)`. |
| 2 — forbidden artifacts unreachable | ✓ | `src/bma_cfengine_app/orchestrator/deals/operational.py` lines 67-70 | Function body constructs no user path and hardcodes `"deal.json"`. |
| 3 — HTTP endpoint | ✓ | `src/bma_cfengine_app/api/routers/deals.py` lines 385-392 | `GET /deals/{deal_id}/export`, query only `sha`, returns `application/json`. |
| 4 — memoized fsck | partial | `src/bma_cfengine_app/orchestrator/deals/deal_store.py` lines 291-349; `src/bma_cfengine_app/api/routers/deals.py` lines 1003-1023 | Memoization exists and covers `save_deal`, `load_deal`, `load_studio_snapshot`, and indirect `_ensure_canonical_deal`, but direct `GitService.commit_deal` and router git entry points bypass fsck. |
| 5 — REPO_CORRUPT diagnostic | ✓ | `src/bma_cfengine_app/orchestrator/deals/operational.py` lines 30-35 and 103-115 | Registered via `@diagnostic_code`, and failure payload includes `restore_action`. |
| 6 — restore_deal core | partial | `src/bma_cfengine_app/orchestrator/deals/operational.py` lines 125-197 | Core exists, clones bundle, preserves manifest/studio files, and invalidates memoization, but replacement is not atomic. |
| 7 — audit log | ✓ | `src/bma_cfengine_app/orchestrator/deals/operational.py` lines 99-102, 146-149, 188-196, 205-220 | Writes JSONL to `<deal_dir>/audit.log` with required fields and restore/corruption events. |

## Findings

### Blocking

#### B1 — Blocking — `src/bma_cfengine_app/orchestrator/deals/git_service.py` line 212 / `src/bma_cfengine_app/api/routers/deals.py` line 1003
**Issue + evidence**: AC 4 requires `git fsck --no-progress` on the first git-touching call regardless of entry point, including `commit_deal`. The implementation adds `_fsck_guard` only in `deal_store`, but `GitService.commit_deal` itself has no fsck call, and the HTTP commit endpoint constructs `GitService(repo_path=deal_dir(deal_id))` directly before calling `service.log`, `service.show`, and `service.commit_deal`.

The same bypass pattern exists for branch, merge, diff, log, show, and merge-stream routes. This means a corrupted repo can still be read or mutated through existing API paths without producing `REPO_CORRUPT`.

**Recommended fix**: Put the fsck guard at the shared git-service boundary or otherwise ensure every public git-touching route/service path calls the same memoized guard before `log`, `show`, `commit_deal`, `branch_*`, `diff`, `merge_base`, and `merge`. Add a regression test that corrupts a repo and calls `/api/deals/{id}/commit` or direct `GitService.commit_deal`.

#### B2 — Blocking — `src/bma_cfengine_app/orchestrator/deals/operational.py` lines 161-172
**Issue + evidence**: `restore_deal` removes the existing `.git/` before the bundle clone succeeds:

- lines 161-163 delete `d / ".git"`;
- lines 165-171 then run `git clone`;
- line 172 moves the cloned `.git` into place.

If `git clone` fails because the bundle is invalid, truncated, incompatible, or the process crashes mid-restore, the original `.git/` is already gone. That violates the reviewer checklist's atomic replacement requirement and makes retry/recovery worse.

**Recommended fix**: Clone/unbundle to a temporary directory first, verify the restored repo is usable, then swap `.git` into place only after success. Prefer keeping the original `.git` as a backup during the swap and rolling back on failure. Add a failing-restore test that verifies the original `.git/` remains present and retryable.

### Critical
None.

### Major
None.

### Minor
None.

### Nit
None.

## Verdict justification
RETURN-FOR-REVISION. The implementation has at least one AC-level blocker: fsck is bypassable through direct git entry points despite AC 4's "regardless of entry point" requirement. The restore path also has a blocking operational safety issue because a failed restore can delete the only existing `.git/` before replacement succeeds.
