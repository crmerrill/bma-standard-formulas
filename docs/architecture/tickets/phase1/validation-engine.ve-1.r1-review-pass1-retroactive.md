# R1 Review (Pass 1, retroactive) — `ve-1-worker-host` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family; RETROACTIVE)
**Date**: 2026-06-03
**Implementation under review**: commit `187518f` (test commit `2d79d3a`)
**Verdict**: APPROVE-WITH-CHANGES

## Findings

### Major

**M1 — Worker responses are applied to the active session at response time, not the session that was validated.**

`workerBridge.ts` posts `state.sessions[state.activeSessionId].working_tree`, but the response handler later calls `useStore.getState()` and writes diagnostics to whatever `activeSessionId` is current at that moment. If the user switches sessions between worker invocation and response, diagnostics can be written to the wrong `DocumentSession`.

This does not invalidate the core worker-host implementation, but it is a correctness gap around AC 4's "updates the `DocumentSession` diagnostics slot." The bridge should capture the `sessionId` sent with each validation request and route the returned diagnostics to that same session, ideally with a request token/revision guard to avoid stale responses overwriting newer diagnostics.

## Acceptance Criteria Review

**AC 1: TS Web Worker instantiated; hosts validation registry — PASS.**

`workerBridge.ts` constructs a real module worker using `new Worker(new URL("./validationWorker.ts", import.meta.url), { type: "module" })`. `validationWorker.ts` imports `structuralValidators` for registration side effects and calls `iterDiagnosticValidators()`.

**AC 2: worker receives serialized `working_tree`; executes registered validators — PASS.**

The bridge posts `{ deal: session.working_tree }`. The worker calls `runValidators(e.data.deal)` and executes every descriptor returned by `iterDiagnosticValidators()`.

**AC 3: 300ms debounce; bursts produce exactly one invocation; timer reset — PASS.**

`VALIDATION_DEBOUNCE_MS = 300` is exported. On every `dispatch_revision` change, the bridge clears the existing timer and schedules a new one. The T1 test covers five mutations within the debounce window.

**AC 4: worker returns `DiagnosticPayload[]`; main thread updates diagnostics — PASS WITH MAJOR FOLLOW-UP.**

The worker returns `{ diagnostics: DiagnosticPayload[] }`, and the bridge calls `setDiagnostics(...)`. The basic data path is present. The session-attribution issue in M1 should be fixed.

## Additional Checklist

**`runValidators` separation — CLEAN.** Extracting `runValidators(deal)` as a pure exported function is a good separation.

**Production Worker construction — PASS.** The `new Worker(new URL(...))` pattern is appropriate.

**Worker bridge wiring — DELIBERATE GAP, TRACKED.** `useDealStore.ts` is not wired to instantiate `createWorkerBridge` on app mount. The closure document explicitly records this as outstanding work.

**Memory/state — PASS.** The worker does not accumulate per-run validation state. The bridge cleanup clears any pending timer, unsubscribes from the store, terminates the worker.

## Test Review

The T1 tests cover the main contract: registered validator execution, `DiagnosticPayload[]` shape, 300ms constant, burst debounce behavior, single-mutation debounce, unchanged-revision no-op.

Residual test gap: no test covers session switching or stale response routing between post and worker response.

## Verdict Rationale

No Blocking or Critical findings. The session-attribution race is a Major follow-up because it can misplace diagnostics in multi-session use, but it does not require returning the implementation wholesale.
