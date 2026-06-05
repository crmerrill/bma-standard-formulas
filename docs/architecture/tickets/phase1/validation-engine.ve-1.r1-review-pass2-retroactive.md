# R1 Review (Pass 2, retroactive fix-pass) — `ve-1-worker-host`

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family)
**Date**: 2026-06-03
**Fix-pass under review**: T1 `017a3e4`, Fix `478d685`
**Verdict**: APPROVE-WITH-CHANGES

## Summary

The original M1 is fixed for the intended multi-session race: `workerBridge.ts` now captures `sessionId` and a per-session `requestId` at worker `postMessage` time, sends both to the worker, and applies the response to the echoed `sessionId` instead of reading `activeSessionId` at response time.

The stale-response guard is also implemented: each post increments `latestRequestId[sessionId]`, and responses with `requestId < latestRequestId[sessionId]` are dropped.

## Findings

### Major

**M2 — Deleted-session worker responses are not guarded and can write diagnostics to a removed session id.**

The bridge calls `state.setDiagnostics(sessionId, diagnostics)` for a non-stale response without checking whether `state.sessions[sessionId]` still exists. The current `setDiagnostics` implementation does not no-op on missing sessions; it spreads `state.sessions[sessionId]` into a replacement object and writes `[sessionId]: { diagnostics: payloads }`. At runtime, object-spreading `undefined` is a no-op, so this can recreate a malformed session entry containing diagnostics but no `working_tree`, `base_sha`, etc.

`mergeDiagnostics` has the desired missing-session guard, but this worker bridge uses `setDiagnostics`, not `mergeDiagnostics`.

### Minor

**m1 — `latestRequestId` is not cleaned up when sessions are deleted.**

`latestRequestId` is a closure-local record in `createWorkerBridge` and has no deletion hook. It will grow by one key per session id that ever posts validation work during the bridge lifetime.

## Closure Assessment Of Original M1

**CLOSED.** Original M1 was specifically that worker diagnostics could land on whichever session was active at response time. The fix closes that.

## Verdict Rationale

`APPROVE-WITH-CHANGES` because the original M1 is closed and the tests are faithful, but the deleted-session response path is not graceful and can recreate a malformed deleted session. Recommended follow-up: before applying diagnostics, have the bridge or `setDiagnostics` no-op when `sessionId` no longer exists, and add cleanup or a bounded lifecycle for `latestRequestId` entries on session deletion.
