# R1 Review (Pass 1) — `sds-2-document-session-model` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family from claude-4.6-opus implementer + Claude parent + gpt codex T1 author)
**Date**: 2026-06-02
**Implementation under review**: commit `ae78456` (test commit `5eb5955`)
**Verdict**: RETURN-FOR-REVISION

## Summary

The implementation lands the flat `sessions[id].working_tree` shape, branded `BranchName` constructor, root `deal_id` HTTP URLs, per-session diagnostics slot, and main-session delete protection. However, the core AC 4 zundo contract is not satisfied: `zundo_history` is a minimal manual counter-like object, not a per-session temporal instance with usable undo/redo/future semantics, and the dispatch interception records history after every `DealAction` dispatch rather than only verified `working_tree` mutations. There is also a strict-TS compatibility issue left in an existing store test after tightening `DocumentSession`.

## Findings

### Blocking
None.

### Critical

1. **AC 4 — `zundo_history` is not a real per-session zundo/temporal instance and cannot support undo/redo semantics.** `session.ts` defines a local `TemporalState<T>` with only `getState`, `pause`, and `resume`, and `useDealStore.ts` creates instances with no-op `pause`/`resume` and a permanently empty `futureStates` array. There is no `undo`, `redo`, `handleSet`, or equivalent mechanism, and the implementation does not use zundo's `temporal(...)` middleware or a manual substitute with the same operational surface promised by the ticket risk note. This means downstream undo/redo consumers cannot actually operate on `sessions[activeSessionId].zundo_history`, and sds-4's pause/resume batching expectations will be a no-op. References: `src/bma_cfengine_app/ui/src/features/deals/store/session.ts` lines 18-22; `src/bma_cfengine_app/ui/src/features/deals/store/useDealStore.ts` lines 46-53, 107-119.

2. **AC 4 — temporal entries are appended unconditionally after dispatch instead of only for confirmed `working_tree` mutations.** The dispatch wrapper always appends `previousWorkingTree` into the active session's history after `applyAction`, regardless of whether `result.sessions` exists or whether the active session's `working_tree` actually changed. Today the public `DealAction` vocabulary mostly mutates `working_tree`, but the existing invalid-action runtime test path and any future non-working-tree action routed through `dispatch` would still emit a temporal entry. The AC is explicit that only `working_tree` mutations add temporal entries, while session switching and diagnostics do not. References: `src/bma_cfengine_app/ui/src/features/deals/store/useDealStore.ts` lines 93-123; `src/bma_cfengine_app/ui/src/features/deals/store/actions.ts` lines 78-83.

### Major

1. **Type quality — tightening `DocumentSession` appears to leave `actions.test.ts` non-strict-compatible.** `DocumentSession.branch_name` and `commit_target` are now `BranchName`, and `zundo_history` is now `TemporalState<DealState>`, but `actions.test.ts` still seeds a sibling session with raw string branch names and `zundo_history: null`. Because `tsconfig.json` includes all `src` files under `strict: true`, this should fail type-checking unless tests are excluded by an external runner configuration not visible in the changed files. References: `src/bma_cfengine_app/ui/src/features/deals/store/actions.test.ts` lines 153-166.

2. **Forward compatibility — `deleteSession` can leave `activeSessionId` dangling when deleting the active ephemeral session.** The action removes non-main sessions but does not update `activeSessionId` if the deleted session is active. The next `dispatch` then dereferences `state.sessions[sessionId]` without a guard and will crash. References: `src/bma_cfengine_app/ui/src/features/deals/store/useDealStore.ts` lines 95-99, 201-204.

### Minor

1. **AC 3 / HTTP robustness — `createEphemeralSession` does not URL-encode query parameters.** Reference: `src/bma_cfengine_app/ui/src/features/deals/store/useDealStore.ts` lines 138-140.

2. **Type quality — `createEphemeralSession` allows `ui_role: "primary"` for ephemeral sessions.** The action's parameter accepts `"primary" | "preview"` but ephemeral sessions are conceptually preview-only. References: `src/bma_cfengine_app/ui/src/features/deals/store/useDealStore.ts` lines 36-40, 125-158.

### Nit

1. **Unneeded `clone()` on the show response.** `showRes.clone().json()` is harmless but unnecessary. Reference: `src/bma_cfengine_app/ui/src/features/deals/store/useDealStore.ts` line 144.

## What Landed Well

- AC 1: `BranchName` is branded, raw strings rejected at compile time, `mkBranchName` matches the irvc-1 slug grammar.
- AC 2 satisfied: flat store shape, no wrapper.
- AC 3 substantially satisfied: HTTP URLs use `state.deal_id`; partial-record-on-failure prevention; main untouched.
- AC 5 satisfied: `DiagnosticPayload` matches Python envelope; `setDiagnostics` atomic per-session.
- AC 6 satisfied for main protection.

## Verdict Rationale

RETURN-FOR-REVISION because the central per-session zundo contract is not implemented to the level required by AC 4. The current tests prove isolated past-state counts, but not usable temporal behavior, pause/resume semantics, redo/future behavior, or a compatible handle surface for sds-4 batching.

## Sign-off Recommendation

RETURN-FOR-REVISION — fix AC 4 zundo and dispatch interception; tighten strict-TS in actions.test.ts; fix active-session deletion behavior; tighten createEphemeralSession ui_role; URL-encode query params; remove unneeded clone(). Then R1 pass-2.
