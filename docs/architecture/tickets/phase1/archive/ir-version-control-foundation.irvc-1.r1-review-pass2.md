---
reviewer: R1 (gpt-5.5-extra-high, fresh invocation, readonly, pass 2)
date: 2026-05-30
ticket: irvc-1-core-git-service
fix_pass_commit: e7db24c
verdict: RETURN-FOR-REVISION
---

## Executive Summary
- B1, C1, M2, and M3 are CLOSED with current-code fixes and regression coverage.
- M1 is PARTIAL: empty-repo handling and first-parent merge semantics are fixed and tested, but the new CLI record delimiter can still collide with commit subject content.
- The fix-pass touched only the expected review doc, git service, and git-service tests; no FastAPI endpoints, merge logic, migration code, IR/schema files, `print`, or `shell=True` were introduced.
- Because not every pass-1 finding is CLOSED, the pass-2 verdict is RETURN-FOR-REVISION.

## Pass-1 finding verification
| Finding | Status | Evidence (file:line) | Test |
|---|---|---|---|
| B1 — pygit2 commit_deal writes working tree | CLOSED | `src/bma_cfengine_app/orchestrator/deals/git_service.py:226` serializes the exact bytes; `src/bma_cfengine_app/orchestrator/deals/git_service.py:230-233` commits those bytes as the `deal.json` blob; `src/bma_cfengine_app/orchestrator/deals/git_service.py:248-255` writes a tempfile in `self._repo_path` and atomically installs it with `os.replace`. | `tests/orchestrator/deals/test_git_service_pygit2.py:90-114` asserts `deal.json` exists and compares on-disk bytes to committed content. |
| C1 — pygit2 errors normalized | CLOSED | `_wrap_pygit2` lets `GitServiceError` subclasses pass through at `src/bma_cfengine_app/orchestrator/deals/git_service.py:90-91`, wraps `pygit2.GitError` at `src/bma_cfengine_app/orchestrator/deals/git_service.py:93-96`, and wraps `KeyError` / `ValueError` at `src/bma_cfengine_app/orchestrator/deals/git_service.py:97-100`. The pygit2-backed public paths are covered via decorators at `src/bma_cfengine_app/orchestrator/deals/git_service.py:217`, `:294`, `:304`, `:318`, `:344`, `:409`, `:425`, and `:441`. | `tests/orchestrator/deals/test_git_service_pygit2.py:117-136` patches `pygit2.Repository` to raise `pygit2.GitError` and asserts `branch_list()` raises `GitServiceError`. |
| M1 — CLI log parser hardened | PARTIAL | The textual `---` delimiter is gone; CLI log now emits NUL fields and SOH records at `src/bma_cfengine_app/orchestrator/deals/git_service.py:370-374`, parses them at `src/bma_cfengine_app/orchestrator/deals/git_service.py:382-396`, handles both empty-repo error forms at `src/bma_cfengine_app/orchestrator/deals/git_service.py:375-377`, and documents first-parent behavior at `src/bma_cfengine_app/orchestrator/deals/git_service.py:395-396`. Remaining gap: records are split on `\x01`, but `%s` commit subjects can contain `\x01`; the code does not escape, reject, or otherwise prove the record delimiter cannot appear in commit content. | `tests/orchestrator/deals/test_git_service_cli.py:116-131` covers empty repos, and `tests/orchestrator/deals/test_git_service_cli.py:134-172` covers merge first-parent behavior. No test guards delimiter collision with `\x01` in the subject. |
| M2 — pygit2 parity test | CLOSED | The pygit2 backend methods are the same public operations in `src/bma_cfengine_app/orchestrator/deals/git_service.py:204-453`. | `tests/orchestrator/deals/test_git_service_pygit2.py:139-191` uses `pytest.importorskip("pygit2")` at `:141` and drives `commit_deal`, `branch_create`, `branch_list`, a second `commit_deal`, `log`, `show`, `diff`, `merge_base`, `branch_delete`, and final `branch_list` without silent skips. |
| M3 — _lock_fd thread-local | CLOSED | There is no `self._lock_fd`; lock fd is stored at `self._local.lock_fd` at `src/bma_cfengine_app/orchestrator/deals/git_service.py:143`, read safely with `getattr(self._local, "lock_fd", None)` at `src/bma_cfengine_app/orchestrator/deals/git_service.py:151`, closed and reset at `src/bma_cfengine_app/orchestrator/deals/git_service.py:153-155`, and the required FUTURE marker remains at `src/bma_cfengine_app/orchestrator/deals/git_service.py:126`. | `tests/orchestrator/deals/test_git_service_locking.py:171-214` exercises two threads sharing one `GitService` and asserts each observes a lock fd during the critical section and `None` after release. |

## New findings introduced by the fix-pass
None.

## Verdict justification
RETURN-FOR-REVISION. B1, C1, M2, and M3 are genuinely closed, but M1 remains partially open because the replacement CLI log parser still has a possible record-delimiter collision with commit subject content. Since every pass-1 finding is not CLOSED, this fix-pass does not meet the APPROVE threshold.
