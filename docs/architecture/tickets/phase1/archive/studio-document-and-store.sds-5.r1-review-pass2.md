# R1 Review (Pass 2) — `sds-5-autosave-and-draft-persistence` fix-pass

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; pass-2 fresh from pass-1 reviewer)
**Date**: 2026-06-03
**Fix-pass under review**: commit `9559eea`
**Pass-1 review**: `studio-document-and-store.sds-5.r1-review-pass1.md`
**Verdict**: RETURN-FOR-REVISION

## Pass-1 Audit Table

| ID | Severity | Status | Notes |
|---|---:|---|---|
| B1 | Blocking | CLOSED | `promoteLocalDraft()` rejects non-local IDs, appends a `BLOCKED_ON_BACKEND` error diagnostic for `local_draft_*`, avoids the incompatible `/deals` backend contract, and throws. |
| C1 | Critical | CLOSED | Successful autosave advances `sessions[activeSessionId].base_sha = result.sha` after `commitWithConflictHandling()` resolves. Sequential autosave regression covered. |
| M1 | Major | PARTIAL | The fix prevents `setDealId`, `setDiagnostics`, and same-session `setActiveSession` from scheduling autosave. However, autosave still fires on any same-active-session `working_tree` reference change, including `reloadFromHead()` (lifecycle.ts:243-253). |
| M2 | Major | CLOSED | `sessionStorage.setItem()` failures append `SESSIONSTORAGE_WRITE_FAILED` warning diagnostic. |
| m1 | Minor | CLOSED | Migration consistency moot under `BLOCKED_ON_BACKEND`. |
| m2 | Minor | CLOSED | `promoteLocalDraft()` guards non-`local_draft_` IDs before any backend or state mutation. |

## New Findings (introduced by pass-1 fix)

### Major

1. **Autosave still schedules for non-typed same-session `working_tree` changes.** `autosave.ts:117-127` treats `currentWorkingTree !== prevWorkingTree && sameSession` as the trigger. Current typed actions are immutable so this fires for every typed `dispatch()` — but it's broader than typed dispatch. `reloadFromHead()` mutates the same session's `working_tree` in `lifecycle.ts:243-253`; if that session is active, the subscription synchronously writes a draft and schedules a backend autosave even though the change came from conflict recovery.

2. **Empty `deal_id` autosave to invalid URL.** Initial state has `deal_id: ""` (`useDealStore.ts:142`). Storage key built unconditionally from `deal_id` (`autosave.ts:130`); backend commit only checks `local_draft_` prefix (`autosave.ts:176`). If `subscribeAutosave()` is installed before a real deal ID is set and the user dispatches, this can create an empty-ID sessionStorage key and call `commitWithConflictHandling("", ...)` producing `/deals//commit`.

3. **`base_sha` advancement non-atomic with sessionStorage.** Each typed change writes sessionStorage immediately with the session's current `base_sha` (`autosave.ts:131-139`). After backend commit success, only in-memory `base_sha` is updated (`autosave.ts:191-203`); sessionStorage draft entry is not rewritten. Edit-while-commit-in-flight scenario can leave sessionStorage holding a newer working_tree under the OLD base_sha; on crash, restore discards as stale.

### Minor

1. **M1 regression test gap.** `test_autosave_does_not_fire_on_setActiveSession_or_setDealId_or_setDiagnostics` covers metadata changes but not the current false-positive path: same-active-session `working_tree` updates outside `dispatch()`, especially `reloadFromHead()`.

## Verdict Rationale

The fix-pass closes the original backend promotion blocker, the straightforward sequential `base_sha` self-conflict, the quota diagnostic, and the non-local promotion guard. However, one original Major remains only partially closed because the autosave trigger is still inferred from `working_tree` reference changes rather than typed dispatches. New Major autosave correctness gaps surfaced: empty `deal_id` can still autosave to an invalid backend URL, and `base_sha` advancement is not persisted atomically with the sessionStorage draft.

## Sign-off Recommendation

RETURN-FOR-REVISION. Pass-3 should:
- Add empty-`deal_id` guard before sessionStorage draft writes and debounced backend commits.
- Replace reference-comparison autosave trigger with a true typed-dispatch signal (revision counter incremented only by `dispatch()`).
- On autosave success, update sessionStorage atomically with the advanced `base_sha`.
- Add tests for empty `deal_id`, `reloadFromHead()` not scheduling autosave, and edit-while-commit-in-flight crash recovery.
