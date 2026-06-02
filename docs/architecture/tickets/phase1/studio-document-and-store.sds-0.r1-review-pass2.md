# R1 Review (Pass 2) — `sds-0-commit-endpoint-extension` fix-pass

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; pass-2 fresh from pass-1 reviewer)
**Date**: 2026-06-01
**Fix-pass under review**: commit `9b21bcee748c15db73243bdd21d344d67f9ef308`
**Pass-1 review**: `docs/architecture/tickets/phase1/studio-document-and-store.sds-0.r1-review-pass1.md`
**Verdict**: APPROVE-WITH-CHANGES

## Audit of pass-1 findings

| Finding | Pass-1 category | Pass-2 status | Where it lives now |
|---|---|---|---|
| C1 (parent_sha invariant) | Critical | CLOSED | `src/bma_cfengine_app/orchestrator/deals/git_service.py` L318-L321 and L417-L425 now compare `target_tip != parent_sha` directly and raise `StaleParentShaError`; service tests cover the nullability matrix at `tests/orchestrator/deals/test_git_service_branch_commit.py` L237-L309. |
| C2 (typed stale exception + 409) | Critical | CLOSED | `StaleParentShaError` inherits `GitServiceError` at `src/bma_cfengine_app/orchestrator/deals/git_service.py` L59-L64; both backend paths raise it at L320-L321 and L424-L425; the HTTP endpoint catches it before generic `GitServiceError` and maps `exc.head_sha` into the 409 envelope at `src/bma_cfengine_app/api/routers/deals.py` L1051-L1056. |
| M1 (CLI parity test) | Major | OPEN | The tests are parametrized over `use_cli` at `tests/orchestrator/deals/test_git_service_branch_commit.py` L95-L309, but `_make_service(..., use_cli=True)` restores `git_service_module.pygit2` before the service is used at L81-L87, while `GitService._use_pygit2` is a live property reading the module global at `src/bma_cfengine_app/orchestrator/deals/git_service.py` L180-L182. In an environment with `pygit2` installed, the `"cli"` parametrization still runs the pygit2 backend. |
| M2 (nullability matrix tests) | Major | PARTIAL | The two missing matrix tests were added at `tests/orchestrator/deals/test_git_service_branch_commit.py` L237-L309 and assert `head_sha` on the typed exception. However, because the forced-CLI helper does not actually force CLI when `pygit2` is installed, the "both backends" portion of the pass-1 request remains unproven. |

M1 remains open because the fix-pass added the desired parametrization shape but the helper's assumption is wrong: `GitService` does not cache backend selection at construction. M2 is substantively closed for the matrix itself, but only partial as a backend-parity test because it shares the same helper flaw.

## New findings introduced by the fix

### Blocking
None.

### Critical
None.

### Major
1. **Forced-CLI test helper does not force the CLI backend.** `_make_service` temporarily sets `git_service_module.pygit2 = None`, constructs `GitService`, then restores `pygit2` before returning the service (`tests/orchestrator/deals/test_git_service_branch_commit.py` L81-L87). But `GitService._use_pygit2` is a property that returns `pygit2 is not None` at call time (`src/bma_cfengine_app/orchestrator/deals/git_service.py` L180-L182), not a constructor-cached flag. As a result, on normal dev/CI environments with `pygit2` installed, every supposedly `"cli"` parametrized branch-target test still goes through `_commit_deal_pygit2`. This leaves pass-1 M1 open and means the CLI fallback path, including the `GIT_INDEX_FILE`/`read-tree` sequence at `src/bma_cfengine_app/orchestrator/deals/git_service.py` L432-L445, is still not exercised by these tests.

### Minor
None.

### Nit
1. The comment in `_make_service` says "GitService reads `_use_pygit2` once at `__init__` time from the module-level `pygit2` symbol" (`tests/orchestrator/deals/test_git_service_branch_commit.py` L76-L80), but the implementation is a live property. The comment should be corrected when the helper is fixed.

## Verdict rationale
The two critical correctness issues from pass-1 are cleanly fixed in production code: the service invariant is now an exact tip comparison, stale races raise a typed exception, and the HTTP layer uses `exc.head_sha` for the required 409 response. The remaining issue is test integrity: the CLI fallback parity tests are labeled as parametrized but do not actually drive the fallback backend when `pygit2` is available.

## Sign-off recommendation
PARENT-VERIFY — Major-only fold-back warranted, no further R1 needed

---

## Parent-verify fold-back applied (2026-06-01)

**Parent agent (Claude Opus 4.7)** applied the Major #1 + Nit #1 fixes directly per the standing orders' `PARENT-VERIFY` recommendation (no R1 pass-3 dispatched per the cost-discipline budget).

**Fix**: `_make_service(repo_path, use_cli, monkeypatch)` now takes the pytest `monkeypatch` fixture and uses `monkeypatch.setattr(git_service_module, "pygit2", None, raising=False)` instead of the `try/finally` restore pattern. The patch persists for the duration of the test (auto-restored at teardown), so the `[cli]` parametrization now genuinely runs against `_commit_deal_cli`. Each of the six parametrized test functions accepts `monkeypatch: pytest.MonkeyPatch` and forwards it to `_make_service`.

**Verification**: all 12 parametrized tests pass with the corrected helper; the full repo test suite is at 1522 passed / 3 skipped / 0 failed. Because the CLI backend's `commit_target` code path (`_commit_deal_cli` L420-L468 including the `GIT_INDEX_FILE` / `read-tree` sequence) now actually runs under the `[cli]` parametrization, the M1 + M2 backend-parity coverage is real.

**Verdict after parent-verify**: APPROVE — sds-0 ready for sign-off.
