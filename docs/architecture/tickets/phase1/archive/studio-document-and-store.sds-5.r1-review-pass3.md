# R1 Review (Pass 3) — `sds-5-autosave-and-draft-persistence` fix-pass

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; pass-3, user-authorized after pass-2 RFR)
**Date**: 2026-06-03
**Fix-pass under review**: commit `895024a`
**Pass-2 review**: `studio-document-and-store.sds-5.r1-review-pass2.md`
**Verdict**: APPROVE

## Pass-2 Audit Table

| ID | Severity | Pass-2 Finding | Pass-3 Status | Notes |
|---|---:|---|---|---|
| M1 | Major | Autosave triggered from same-session `working_tree` reference changes, including `reloadFromHead()` | CLOSED | `autosave.ts` now tracks `dispatch_revision` instead of `working_tree` reference identity. `useDealStore.ts` increments `dispatch_revision` only inside `dispatch()` when the active session working tree changes. `reloadFromHead()` mutates `working_tree` via lifecycle `set()` and does not increment the counter, so it no longer schedules autosave. |
| M2 | Major | Empty `deal_id` could write sessionStorage key and call `/deals//commit` | CLOSED | `autosave.ts` guards `!deal_id` before the synchronous sessionStorage write and again inside the debounced backend commit path. Closes both invalid draft-key and invalid backend URL paths. |
| M3 | Major | Successful backend commit advanced in-memory `base_sha` but left sessionStorage draft under old base | CLOSED | Commit success now performs the sessionStorage rewrite and in-memory `base_sha` update in the same `store.setState()` updater. Persisted draft is rewritten with the current `working_tree` and `result.sha`. |
| m1 | Minor | Missing regression test for `reloadFromHead()` false-positive autosave | CLOSED | `autosave.test.ts` adds `test_autosave_does_not_fire_on_reloadFromHead`, which exercises conflict setup, calls `reloadFromHead("main")`, advances timers, and asserts no commit calls occurred. |

## New Findings

None at RFR level.

Residual non-blocking observations:
- `dispatch_revision` is a plain number and can theoretically overflow after `Number.MAX_SAFE_INTEGER`. Nit-level; not a practical R1 concern.
- The autosave success path still assumes the active store context has not changed to another deal while an autosave commit is in flight. Broader race existed before this fix-pass; not introduced by pass-3 changes. May be worth hardening later by checking the committed `deal_id`/session identity before applying success state.
- If the final sessionStorage rewrite fails after an earlier write succeeded, the catch remains silent. Prior write path already reports storage failures, backend autosave remains durable.

## Verdict Rationale

Pass-3 cleanly closes all pass-2 findings:
- Autosave is now keyed off an explicit dispatch signal rather than incidental `working_tree` mutation.
- Blank `deal_id` is guarded before both local draft persistence and backend commit.
- Commit success keeps persisted draft metadata aligned with the advanced `base_sha`.
- The missing `reloadFromHead()` regression test is present and targets the exact previously untested path.

No regressions in the modified files. Commit `895024a` records `vitest: 175 passed` and `pytest: 1529/3/0`.

## Sign-off Recommendation

APPROVE. sds-5 ready to close. The full `studio-document-and-store` todo is ready for the closure protocol.
