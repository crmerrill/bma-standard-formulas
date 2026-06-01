---
reviewer: R1 (gpt-5.5-extra-high, fresh invocation, readonly)
date: 2026-06-01
ticket: irvc-4-http-api
implementation_commit: cc6a32f
verdict: RETURN-FOR-REVISION
---

## Executive Summary
- The implementation lands the requested FastAPI git surface and correctly delegates merge/branch operations through `GitService` and `deal_dir()`.
- `CommitMeta.committed_at` is backward-compatible and both pygit2/CLI log paths populate it correctly.
- Return for revision: the new public branch-delete endpoint can target `main`; the service validator explicitly allows `main` and the delete path has no guard.
- T1 covers the happy-path endpoint contract, stale 409, force bypass, slash-bearing branch names, and SSE closure, but it misses several edge cases called out in the reviewer checklist.
- No IR/schema files, Zustand store, UI components, or Phase 2/3 entities were introduced.

## Acceptance criteria audit
| AC | Status | Evidence | Notes |
|---|---|---|---|
| 1 — endpoint surface | partial | `src/bma_cfengine_app/api/routers/deals.py:979`, `:1005`, `:1023`, `:1040`, `:1052`, `:1075`, `:1090`, `:1114`, `:1124` | All routes are present, including `{name:path}`. Partial because SSE failure diagnostics are not reliably populated and branch deletion exposes `main`. |
| 2 — 409 on stale | ✓ | `src/bma_cfengine_app/api/routers/deals.py:985`, `tests/api/routers/test_deals_git.py:138` | Stale non-forced commits raise 409 with structured detail. |
| 3 — force LWW | ✓ | `src/bma_cfengine_app/api/routers/deals.py:985`, `:992`, `tests/api/routers/test_deals_git.py:165` | `force=True` bypasses the stale check. The endpoint is metadata-only; payload persistence remains on the existing save path. |
| 4 — FUTURE markers | partial | `src/bma_cfengine_app/api/routers/deals.py:986`, ticket line 184 | Python marker is exact. No TypeScript marker exists (acceptable for backend-only ticket); T1 does not assert either marker. |

## Findings

### Blocking
None.

### C1 — Critical — `src/bma_cfengine_app/api/routers/deals.py:1040`, `src/bma_cfengine_app/orchestrator/deals/git_service.py:163`
**Issue + evidence**: `DELETE /deals/{deal_id}/branches/{name:path}` passes `name` directly to `GitService.branch_delete()`. The service validator explicitly returns successfully for `name == "main"`, and `branch_delete()` then attempts to delete whatever branch object is returned. This exposes deletion of the primary branch through a public API route, violating the edge-case requirement that `/branches/main` be rejected by the service or validator and surfaced as a sensible 4xx.

**Recommended fix**: Add an explicit `main` guard in `GitService.branch_delete()` or the endpoint, returning 409/422 before touching git. Add API coverage for `DELETE /branches/main` and service coverage for both pygit2 and CLI backends.

### M1 — Major — `src/bma_cfengine_app/api/routers/deals.py:881`
**Issue + evidence**: `CommitRequest.parent_sha` is typed as non-null `str`, so `parent_sha=null` is rejected by FastAPI/Pydantic before the LWW comparison runs. The reviewer checklist explicitly calls out two nullable cases: `null` against an existing HEAD should produce the stale-parent 409, and `null` against a brand-new no-commit deal should be accepted.

**Recommended fix**: Change `parent_sha` to `str | None = None`, preserve the existing `head_sha != body.parent_sha` comparison, and add tests for both nullable edge cases.

### M2 — Major — `src/bma_cfengine_app/api/routers/deals.py:1146`, `:1152`
**Issue + evidence**: The SSE terminal `merge_failed` event does not consistently carry a useful diagnostic. Typed merge conflicts emit only `result.payload`, dropping the code/severity/path/message shape used by the synchronous merge response, and the broad exception path emits `merge_failed` with no diagnostic at all.

**Recommended fix**: Serialize the same diagnostic shape as `GitMergeResult` for typed conflicts, and catch expected service/validation exceptions with a structured diagnostic payload. Avoid swallowing all exceptions without at least a code/message.

### m1 — Minor — `src/bma_cfengine_app/api/routers/deals.py:958`
**Issue + evidence**: `_flatten_diff()` recurses through dictionaries but treats any list change as a whole-list `modified` entry. Core deal structures are list-heavy (`bonds`, `accounts`, `fees`, `waterfall_rules`), so a one-field bond edit returns a coarse diff for the entire list rather than a structural path to the changed element.

**Recommended fix**: Recurse through lists by index at minimum, or preferably by stable entity keys where the IR provides them.

### m2 — Minor — `tests/api/routers/test_deals_git.py:165`
**Issue + evidence**: T1 maps AC4 to `test_commit_endpoint_force_true_overwrites`, but that test only asserts a successful forced commit and valid SHA. It does not verify the `FUTURE: collaboration` marker. Inspection confirms the Python marker exists, but the acceptance criterion is not test-pinned.

**Recommended fix**: Add a small marker test or document that the TypeScript marker is deferred until the frontend conflict UI lands.

### Nit
None.

## Verdict justification
RETURN-FOR-REVISION. The endpoint surface is mostly complete and the `CommitMeta` extension looks safe, but the new public API can attempt to delete `main`, which is a critical data-integrity risk. Per the threshold, any Critical finding requires return for revision.
