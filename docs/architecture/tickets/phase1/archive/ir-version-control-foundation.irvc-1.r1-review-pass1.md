---
reviewer: R1 (gpt-5.5-extra-high, fresh invocation, readonly)
date: 2026-05-30
ticket: irvc-1-core-git-service
implementation_commit: d57927a
verdict: RETURN-FOR-REVISION
---

## Executive Summary
- The implementation lands the intended public surface, optional `pygit2` extra, CLI fallback, lock file location, branch validation, and CI matrix shape.
- AC 2 is not fully met on the `pygit2` path: `commit_deal` creates a git object/commit but does not write `deal.json` into the working tree.
- The `pygit2` backend leaks internal exceptions from several public methods instead of normalizing them to `GitServiceError`.
- CLI fallback subprocess usage is list-form and avoids `shell=True`, but the CLI log parser is brittle for empty repos, delimiter collisions, and merge commits.
- No IR/schema files, FastAPI endpoints, migration code, or typed merge logic were introduced.

## Acceptance criteria audit
| AC | Status | Evidence | Notes |
|---|---|---|---|
| 1 — pygit2 optional + lazy import | ✓ | `src/bma_cfengine_app/orchestrator/deals/git_service.py:22`, `pyproject.toml:37`, `pyproject.toml:42`, `pyproject.toml:45` | Module-level `pygit2` is patchable; default dependencies exclude it; `git` and `all` extras include it. |
| 2 — commit_deal | partial | `src/bma_cfengine_app/orchestrator/deals/git_service.py:184`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:205`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:218`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:236` | CLI writes `deal.json`; `pygit2` commits a blob but leaves the working tree stale. |
| 3 — operations parity | partial | `src/bma_cfengine_app/orchestrator/deals/git_service.py:263`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:285`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:310`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:366`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:381`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:396` | All eight operations have both branches, and CLI uses list-form args, but pygit2 exception leaks and CLI log edge cases remain. |
| 4 — locking | ✓ | `src/bma_cfengine_app/orchestrator/deals/git_service.py:102`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:104`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:106`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:115`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:121` | Meets path, timeout, nonblocking flock, reentrancy, and FUTURE marker requirements; thread-sharing concern noted below. |
| 5 — branch validation | ✓ | `src/bma_cfengine_app/orchestrator/deals/git_service.py:29`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:141`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:263`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:272` | Grammar and error code match; create/delete validate at entry. |
| 6 — CI matrix | ✓ | `.github/workflows/ci.yml:14`, `.github/workflows/ci.yml:16`, `.github/workflows/ci.yml:18`, `.github/workflows/ci.yml:31`, `.github/workflows/ci.yml:35`, `.github/workflows/ci.yml:39` | Python 3.12/3.13 crossed with no-pygit2/pygit2 install dimensions; both run full tests. |

## Findings

### B1 — Blocking — `src/bma_cfengine_app/orchestrator/deals/git_service.py:205`
**Issue + evidence**: The `pygit2` implementation of `commit_deal` serializes the payload and creates a blob/tree/commit, but never writes `deal.json` to `self._repo_path`. The CLI path does write the file at `src/bma_cfengine_app/orchestrator/deals/git_service.py:237`, so backend behavior diverges and AC 2's "writes `deal.json`" requirement is only met for CLI.

**Recommended fix**: In the `pygit2` path, write the exact committed bytes to `self._repo_path / "deal.json"` while under the write lock, and keep the committed blob and working-tree file in sync.

### C1 — Critical — `src/bma_cfengine_app/orchestrator/deals/git_service.py:266`
**Issue + evidence**: Public `pygit2` paths call libgit2 APIs directly without translating `pygit2.GitError` or related lookup failures. Examples include branch creation, show, diff, and merge-base at `src/bma_cfengine_app/orchestrator/deals/git_service.py:266`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:367`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:382`, and `src/bma_cfengine_app/orchestrator/deals/git_service.py:397`. The CLI helper normalizes `CalledProcessError` at `src/bma_cfengine_app/orchestrator/deals/git_service.py:174`; the pygit2 path should provide the same public API boundary.

**Recommended fix**: Wrap pygit2-backed public operations and re-raise `GitServiceError` or existing subclasses with useful context, preserving the original exception as `from exc`.

### M1 — Major — `src/bma_cfengine_app/orchestrator/deals/git_service.py:334`
**Issue + evidence**: CLI `log` parsing uses a textual `---` delimiter and `%s` subject-only format. This is brittle for empty repos, merge commits with multiple parents, and commit subjects containing the delimiter. It also collapses multiple parents to the first at `src/bma_cfengine_app/orchestrator/deals/git_service.py:351`.

**Recommended fix**: Use an unambiguous format such as NUL-delimited records/fields, handle empty-repo `git log` failures intentionally, and either model multiple parents explicitly or document and test first-parent behavior.

### M2 — Major — `tests/orchestrator/deals/test_git_service_pygit2.py:39`
**Issue + evidence**: T1 only exercises `commit_deal` on the pygit2 backend. The full operation parity test covers CLI fallback at `tests/orchestrator/deals/test_git_service_cli.py:40`, but pygit2 branch/list/log/show/diff/merge-base parity is not tested.

**Recommended fix**: Add a pygit2 parity test mirroring the CLI fallback journey, or parameterize the existing parity test across backends.

### M3 — Major — `src/bma_cfengine_app/orchestrator/deals/git_service.py:91`
**Issue + evidence**: `self._lock_fd` is shared mutable state on the service instance, while `lock_depth` is thread-local. Two threads sharing one `GitService` can race on `_lock_fd` during acquire/release at `src/bma_cfengine_app/orchestrator/deals/git_service.py:123` and `src/bma_cfengine_app/orchestrator/deals/git_service.py:131`.

**Recommended fix**: Store the fd in thread-local state as well, and add a process-local/thread-local mutex or `RLock` if same-process threads must serialize before relying on the cross-process file lock.

### Minor
None.

### Nit
None.

## Verdict justification
RETURN-FOR-REVISION. The core shape is sound and the implementation is close, but AC 2 is not satisfied for the pygit2 backend because the working-tree `deal.json` is not written. Additionally, pygit2 exceptions leak through the public API, which violates the reviewer checklist's public API stability requirement.

After those are fixed, the remaining major items are suitable for a focused fix pass: strengthen pygit2 parity tests, harden CLI log parsing, and remove the shared `_lock_fd` race.
