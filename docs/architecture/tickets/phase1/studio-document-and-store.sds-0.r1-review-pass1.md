# R1 Review (Pass 1) — `sds-0-commit-endpoint-extension` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family from claude-4.6-sonnet implementer + Claude parent + gpt codex T1 author)
**Date**: 2026-06-01
**Implementation under review**: commit `9daa05c4cbf974d96521d37e683267efefc7f901` (test commit `2a70ed7`)
**Verdict**: RETURN-FOR-REVISION

## Summary
The implementation lands the visible extension shape: `CommitRequest.payload`, `CommitRequest.branch`, canonical Pydantic serialization for supplied payloads, branch-name validation reuse, branch-target writes in both backend methods, and the legacy 409 envelope. However, the service-level parent validation for non-main branches is incomplete: it only rejects mismatches when both `parent_sha` and target tip are non-null, so it permits history-breaking commits in exactly the edge cases AC 4/AC 13 are meant to pin. There is also no typed stale-parent exception from the service, so a service-level stale race can surface as HTTP 500 instead of the required 409 envelope. CLI fallback parity is implemented but not exercised by the new branch-target tests.

## Findings

### Blocking
None.

### Critical
1. **(sds-0, AC 4 and AC 13)** — Service-level `parent_sha` validation for non-main branches is under-implemented. In `src/bma_cfengine_app/orchestrator/deals/git_service.py` L309-L328 and L411-L468, the non-main paths reject only when `parent_sha is not None and target_tip is not None and parent_sha != target_tip`. That leaves two invalid states accepted: an existing target branch can be advanced with `parent_sha=None`, creating a new root commit and severing branch history; and an unborn/nonexistent target branch can be created with a non-null `parent_sha`, even though the supplied branch tip is `None`. AC 4 says `parent_sha` is validated against the supplied branch's tip, and AC 13 only permits `parent_sha=None` for the unborn initial-commit path. The T1 test `test_commit_deal_parent_sha_validated_against_supplied_branch_tip_not_main` at `tests/orchestrator/deals/test_git_service_branch_commit.py` L153-L186 does not cover the unborn mismatch described in the ticket; it creates and advances the branch first, then checks a non-null mismatch. **Proposed fix**: in both pygit2 and CLI non-main paths, compare the resolved `target_tip` to `parent_sha` directly and reject whenever they differ, with `target_tip=None, parent_sha=None` as the only unborn success case. Add service tests for `(existing branch tip, parent_sha=None) -> stale` and `(unborn branch, parent_sha=<main tip>) -> stale`, in addition to the existing mismatch test.

2. **(sds-0, AC 3 and AC 11)** — Service-level stale-parent failures on the new branch path are mapped to HTTP 500 rather than the required 409 envelope. The endpoint pre-checks the supplied branch at `src/bma_cfengine_app/api/routers/deals.py` L1019-L1028, but the actual write happens later inside `GitService.commit_deal(...)` under the service write lock at `src/bma_cfengine_app/orchestrator/deals/git_service.py` L275-L291. If the branch advances between the endpoint's `service.log(...)` and the service write, the non-main service path raises a generic `GitServiceError` at L313-L316 or L420-L423; the endpoint catches generic `GitServiceError` at `src/bma_cfengine_app/api/routers/deals.py` L1051-L1052 and returns 500. AC 3 and the objective checklist require stale parent errors to return exactly `{"detail": {"code": "STALE_PARENT_SHA", "head_sha": "<sha>"}}`. **Proposed fix**: introduce a typed stale-parent exception carrying `head_sha`, raise it from both non-main backend paths, and map it in `commit_deal_endpoint` to the existing 409 envelope before the generic 500 handler. Keep the envelope key as `detail.head_sha`.

### Major
1. **(sds-0, AC 4 / AC 8; test contract integrity)** — The new `commit_target` behavior is not tested on the CLI fallback backend. `tests/orchestrator/deals/test_git_service_branch_commit.py` instantiates the default `GitService`, so on environments with `pygit2` installed it exercises only the pygit2 path. Existing CLI tests in `tests/orchestrator/deals/test_git_service_cli.py` L40-L113 cover default main commits and branch CRUD, but never call `commit_deal(..., commit_target="...")`. This misses the objective checklist requirement that the extension work on both backends. It also leaves a fragile CLI detail unverified: `src/bma_cfengine_app/orchestrator/deals/git_service.py` L430-L443 creates an empty `GIT_INDEX_FILE` with `mkstemp` before `git read-tree`; git index initialization is safer when the alternate index path does not already exist. **Proposed fix**: parametrize the branch-target service tests over pygit2 and forced-CLI modes, or add a dedicated CLI fallback test that creates a branch, commits with `commit_target`, asserts branch-only advancement, stale-parent rejection, and unborn-branch behavior. If the empty alternate index fails under that test, switch to a non-existent temp index path or unlink the mkstemp file before `read-tree`.

2. **(sds-0, AC 4 and AC 13; test contract integrity)** — The current service test suite does not assert the full nullability matrix for `parent_sha` on non-main branches. The ticket explicitly calls out `parent_sha=None` as the unborn-branch initial-commit permission, but the service tests only assert a successful existing-branch parent match and a non-null mismatch after the branch has a tip. They do not prove that `parent_sha=None` is rejected when the target branch already has a tip, nor that a non-null `parent_sha` is rejected when the target branch is unborn. **Proposed fix**: add those two tests at service level for both backends. This closes the gap that allowed Critical #1.

### Minor
None.

### Nit
None.

## What landed well
- `CommitRequest` preserves the landed nullable `parent_sha` field and adds exactly `payload: dict[str, Any] | None = None` plus `branch: str = "main"` at `src/bma_cfengine_app/api/routers/deals.py` L896-L902.
- Supplied payloads are validated with `DealDefinition.model_validate(...)` and committed as `validated.model_dump_json(indent=2).encode("utf-8")` at `src/bma_cfengine_app/api/routers/deals.py` L1030-L1036.
- The ordinary HTTP stale-parent pre-check resolves the supplied branch and preserves the legacy envelope at `src/bma_cfengine_app/api/routers/deals.py` L1019-L1028.
- Branch validation reuses the existing irvc-1 `_validate_branch_name` helper at both the endpoint and service layers.
- The new service entry point acquires the existing write lock before dispatching to either backend at `src/bma_cfengine_app/orchestrator/deals/git_service.py` L275-L291.
- The non-main write paths avoid `HEAD` manipulation and update target refs directly, which is the right direction for branch isolation.
- The default/main backend paths are intentionally left close to the prior behavior, preserving the AC 5 regression gate.

## Verdict rationale
The core extension is close, but the service-level parent invariant is not strong enough to satisfy AC 4/AC 13, and the HTTP layer does not map service-detected stale conflicts to the required 409 response. These are correctness issues in the new branch-target write path, not just test polish. The CLI fallback test gap also means one of the explicit review checklist items is not proven.

## Sign-off recommendation
RETURN-FOR-REVISION — Blocking/Critical findings; require fix-pass
