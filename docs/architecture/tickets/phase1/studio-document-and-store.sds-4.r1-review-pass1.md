# R1 Review (Pass 1) — `sds-4-patch-lifecycle-and-http-integration` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family from claude-4.6-sonnet implementer + Claude parent + gpt codex T1 author)
**Date**: 2026-06-02
**Implementation under review**: commit `a8dae5e` (test commit `43dbdcd`)
**Verdict**: RETURN-FOR-REVISION

## Summary

The happy-path apply/preview machinery is close: `previewEphemeralSession` updates the active preview without touching main, apply success calls `/merge`, reloads `deal.json`, updates main, deletes the ephemeral session, and appends one main zundo entry. The 409 envelope reader correctly uses `detail.head_sha`. Several AC-level and edge-case gaps remain: initial 409 commit attempts do not create `conflictState`, discard failures do not surface diagnostics, show-endpoint failures can corrupt store state, `sha: null` is trusted with a non-null assertion, and lifecycle actions do not guard session identity.

## Findings

### Blocking
None.

### Critical
None.

### Major

1. **AC 5 — initial stale commit cannot create `state.conflictState`.** `commitToBranch` throws `CommitConflictError` with only `head_sha` (`api.ts:39-43`); the only catcher is `forceCommit` which requires existing `conflictState`. Tests pre-seed `conflictState`, masking this. Recommendation: add a normal commit/store helper that catches `CommitConflictError` and writes the full AC 5 `conflictState` from the attempted request.

2. **AC 4 failure path misses the required diagnostic.** `discardEphemeralSession` preserves the session on HTTP failure (because `deleteBranch` throws), but does not append/replace any diagnostic even though AC 4 requires "an error diagnostic is surfaced." Recommendation: catch delete failures, preserve the session, write a session-scoped diagnostic.

3. **Apply/reload trust failed `GET /show` responses as `DealState`.** `lifecycle.ts:44-48` and `lifecycle.ts:146-150` parse JSON without `res.ok` check. A 404/500 body installed as `working_tree`. Recommendation: check `res.ok` before parsing.

4. **Apply success accepts `sha: null` via `result.sha!`.** Converts protocol violation into `/show?sha=null` and `base_sha=null`. Recommendation: treat success-with-null-sha as a hard error.

5. **Lifecycle actions do not reject `sessionId === 'main'`.** `applyEphemeralSessionToMain('main')` destructures `main` out of `sessions` and reconstructs from `restSessions.main` (undefined). `discardEphemeralSession('main')` calls `DELETE /branches/main`. Recommendation: throw or no-op for `main` in preview/apply/discard before any HTTP call.

6. **`forceCommit` and `reloadFromHead` ignore `conflictState.sessionId`.** Calling `forceCommit('B')` while conflict belongs to `A` commits `A`'s payload to `B`'s branch. Recommendation: require `conflictState.sessionId === sessionId`.

7. **Apply success can leave `activeSessionId` dangling after deleting the active ephemeral session.** Recommendation: if applied session is active, reset `activeSessionId` to `main` in the same mutation.

8. **Concurrent apply calls can race.** Two concurrent applies can both succeed and whichever `/show` resolves last wins. Recommendation: serialize applies, re-check main `base_sha`, or reject second in-flight apply.

### Minor

1. **`ApplyConflict.diagnostic` is `unknown`.** AC 3 expects a valid `MergeConflictPayload` on conflict. Use a discriminated union.

2. **Response parsing uses unchecked casts.** `as DealState` and response-shape assertions trust the server blindly.

### Nit

1. Apply/reload build query strings manually; should use `URLSearchParams` for consistency with `createEphemeralSession`.

## What Landed Well

- AC 1 satisfied for valid ephemeral sessions.
- AC 2a happy path matches the intended flow with explicit `pause/resume/handleSet`.
- AC 2b/3 happy conflict path preserves main and ephemeral session and writes `applyConflict`.
- `commitToBranch` reads the irvc-4 envelope field `detail.head_sha`, not a renamed field.
- `forceCommit` retries with `force: true`.
- `commitToBranch(deal_id, body)` interface is broadly reusable for sds-5 autosave.

## Verdict Rationale

The central success path is proven, but SDS-4 is a lifecycle boundary around destructive branch/apply operations. The remaining issues are not cosmetic: stale commit UX cannot be initiated from a clean state, failed HTTP reads can mutate the store as if they succeeded, discard failure omits required diagnostics, and bad or concurrent session inputs can corrupt or misroute main/session state.

## Sign-off Recommendation

RETURN-FOR-REVISION. Apply all 8 Major + 2 Minor + 1 Nit fixes, then parent-verify (no R1 pass-2 needed since 0 Blocking + 0 Critical).
