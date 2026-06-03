# R1 Review (Pass 1) — `sds-5-autosave-and-draft-persistence` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family from claude-4.6-sonnet implementer + Claude parent + gpt codex T1 author)
**Date**: 2026-06-02
**Implementation under review**: commit `66dc8be` (test commit `3a425c4`)
**Verdict**: RETURN-FOR-REVISION

## Summary

The implementation lands the basic debounce shape, sessionStorage key format, restore/discard diagnostics, local-draft autosave suppression, and 409 forwarding through `commitWithConflictHandling`. However, two issues are return-level: `promoteLocalDraft()` is wired to an incompatible existing `/deals` backend contract, so AC 4 does not work against the real app; and successful autosaves never advance the session `base_sha`, so the next autosave after a successful commit will reuse a stale parent SHA and self-conflict. There are also major/minor robustness gaps around subscribing to all store changes instead of typed dispatches and swallowing sessionStorage quota failures without the required warning diagnostic.

## Findings

### Blocking

1. **AC 4 promotion calls the wrong backend shape and will fail in the real app.** `promoteLocalDraft()` posts `body: JSON.stringify({ working_tree: state.sessions.main?.working_tree })` to `/deals`, then expects `deal_id` plus `initial_sha`/`sha`. But the existing backend `POST /deals` expects `StudioDealSaveBody` with required `ir` and optional `deal_name`/`deal_id`, and returns studio snapshot metadata only (`{deal_id, deal_name, version, created_at}`). So the real request is likely a 422, and even if adapted to pass `ir`, the response does not include an initial git commit SHA. The implementation falls back to `realSha = ""`, which cannot satisfy "every session's `base_sha` is set to the initial commit SHA." Spec expectation allows escalation if the backend path is missing — should surface `BLOCKED_ON_BACKEND` diagnostic rather than silently assuming a contract that does not exist.

### Critical

1. **Successful autosave does not update `session.base_sha`, causing the next autosave to self-conflict.** The autosave commit uses `commitWithConflictHandling()` correctly, sending `parent_sha: currentSession.base_sha`. But `commitWithConflictHandling()` returns the new SHA without writing it back to the session. Autosave also ignores the successful result. That leaves `base_sha` pinned to the old parent after the backend branch has advanced. On the next edit, autosave posts the old `parent_sha` again, the backend compares it to branch HEAD and returns 409, so ordinary sequential autosaves can populate `conflictState` even when there is no external conflict. This breaks the durable autosave workflow.

### Major

1. **Autosave subscribes to all store changes, not typed-action dispatches.** AC 1 and AC 2 are explicitly scoped to typed-action dispatches. The implementation uses a raw Zustand subscription. Unrelated store changes also synchronously write drafts and reset/schedule the debounce timer: `setDealId`, `setActiveSession`, `setDiagnostics`, `forceCommit`, `reloadFromHead`, promotion state updates, conflict updates. Switching active sessions during a debounce can reset the timer and schedule a commit for the newly active session even if no typed edit happened there. Promotion success triggers the subscription and schedules an autosave as a side effect of changing `deal_id`/`base_sha`, not from a typed edit.

2. **sessionStorage quota/unavailability errors are swallowed without the required warning diagnostic.** The spec risk note says `QuotaExceededError` should surface a `WARNING` diagnostic and continue with backend commit as durability path. Current `setItem` failures are silently ignored.

### Minor

1. **Promotion migration can leave stale stored `base_sha` when called without an active autosave subscription.** `promoteLocalDraft()` copies sessionStorage values from the local key to the real key before updating session `base_sha`. The copied JSON still contains the old local draft base SHA. In the normal subscribed path, the subsequent `set()` happens to trigger the autosave subscriber and overwrite the key with the new base SHA. The migrated value should be internally consistent even if the autosave subscriber is not installed yet.

2. **`promoteLocalDraft()` does not guard against non-local `deal_id`.** The action is named and specified for `local_draft_*`, but it will POST `/deals` for any current `deal_id`. Add a prefix guard with diagnostic or thrown programmer error.

## What Landed Well

- Debounce interval is exactly 2000ms; tests cover single fire, burst coalescing, timer reset.
- Commit payload uses `parent_sha`, `branch`, `JSON.parse(compileToIR(working_tree))`.
- sessionStorage key shape uses root `state.deal_id`: `bma:draft:${deal_id}:${session_id}`.
- Restore and discard branches emit `DRAFT_RESTORED` and `DRAFT_DISCARDED` diagnostics.
- Local draft autosave suppression is present.
- Autosave uses `commitWithConflictHandling`, so 409s flow into `conflictState`.
- Teardown clears pending debounce timer and unsubscribes.

## Verdict Rationale

The implementation is directionally correct for the frontend-only happy path, but AC 4 is not actually integrated with the available backend contract, and the autosave success path cannot support more than one clean autosave without stale-parent conflicts. Those are core workflow failures, not polish issues.

## Sign-off Recommendation

RETURN-FOR-REVISION. Minimum fixes before approval:
- Replace or explicitly block `promoteLocalDraft()` against the real backend contract. If no git-init/create endpoint exists, emit `BLOCKED_ON_BACKEND` diagnostic as the spec requires.
- On successful autosave, update the committed session's `base_sha` to the returned SHA.
- Scope autosave scheduling/sessionStorage writes to typed `dispatch()` calls, not every store mutation.
- Surface warning diagnostics for sessionStorage write failures.
- Add tests for sequential autosaves updating `base_sha`, real promotion failure/blocking behavior, and non-dispatch store updates not triggering autosave.
