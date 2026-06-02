# R1 Review (Pass 2) — `sds-2-document-session-model` fix-pass

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; pass-2 fresh from pass-1 reviewer)
**Date**: 2026-06-02
**Fix-pass under review**: commit `f555b26`
**Pass-1 review**: `studio-document-and-store.sds-2.r1-review-pass1.md`
**Verdict**: APPROVE

## Pass-1 Audit

| ID | Pass-1 Finding | Status | Evidence |
| --- | --- | --- | --- |
| C1 | Real per-session zundo `TemporalState` with `handleSet` / `undo` / `redo` / `pause` / `resume` | CLOSED | `TemporalState<T>` now exposes `handleSet`, `undo`, and `redo` at `session.ts` lines 18-25. `createPerSessionTemporal` creates per-session `past` / `future` stacks plus `paused` state at `useDealStore.ts` lines 46-95. Main and ephemeral sessions each receive their own temporal instance at lines 123 and 183. |
| C2 | Dispatch gated on actual `working_tree` change | CLOSED | `dispatch` captures `oldWorkingTree`, computes `newWorkingTree`, and only calls `handleSet(oldWorkingTree)` when references differ at `useDealStore.ts` lines 135-150. |
| M1 | Strict-TS in `actions.test.ts` | CLOSED | Sibling session uses `mkBranchName(...)` and a full `satisfies TemporalState<DealState>` stub at `actions.test.ts` lines 155-172. |
| M2 | `deleteSession` active-session cleanup | CLOSED | Resets `activeSessionId` to `"main"` when deleting the active session at `useDealStore.ts` lines 228-232. |
| m1 | URL-encode query params | CLOSED | Built with `URLSearchParams` at `useDealStore.ts` lines 166-167. |
| m2 | `createEphemeralSession` `ui_role` narrowed | CLOSED | Argument type now accepts only `ui_role: "preview"` at `useDealStore.ts` lines 36-40. |
| n1 | `clone()` removal skipped | CLOSED | Intentional per fix-pass commit message; the reviewer's "harmless" label was production-only and the test mocks reuse a single Response across calls. |

No PARTIAL or OPEN pass-1 findings remain.

## New Findings

None across Blocking / Critical / Major / Minor / Nit.

## Temporal Semantics Sanity Check

The new `undo` / `redo` stack behavior is coherent: `undo()` pops the previous state from `past`, pushes the current `working_tree` into `future`, and writes the popped state back to the session (`useDealStore.ts` lines 69-80). `redo()` is the inverse (lines 82-93). `pause()` / `resume()` correctly suppress temporal recording because `handleSet` only mutates stacks when `paused` is false (lines 57-67). `undo()` and `redo()` call `storeSet` directly and do not re-enter `dispatch`, so they do not create extra temporal entries.

For sds-4: `handleSet(state)` records the supplied `DealState` as the past entry, not the current post-mutation state. This matches the fix-pass dispatch pattern (passes `oldWorkingTree`) and the sds-4 ticket plan, which expects `pause(); /* mutate */; resume(); handleSet(pre_mutation_state)` to record exactly one entry.

## Type-Safety Check

No new `as any` casts. `satisfies TemporalState<DealState>` used in tests for strict-TS shape check. No new unsafe regressions.

## Verdict Rationale

APPROVE. All pass-1 findings closed cleanly. Manual per-session temporal stack exposes the sanctioned surface (`pause`/`resume`/`handleSet`/`getState`/`undo`/`redo`) with closure-owned per-session isolation; meets AC 4. sds-4 can build on this directly.

## Sign-off Recommendation

APPROVE — proceed to sds-3.
