# R1 Review (Pass 2, retroactive fix-pass) — `ve-4a-validation-stream-client`

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family)
**Date**: 2026-06-03
**Fix-pass under review**: T1 `4d5bd39`, Fix `9a70455`
**Verdict**: APPROVE

## Summary

The fix-pass closes both original Pass-1 findings.

The new test-only helpers are explicitly marked `@internal Test-only`, are named with `_ForTesting`, and are only referenced by `validationStreamClient.test.ts`. The production implementation now centralizes active-token cleanup through `clearActiveToken()`, which only deletes the session entry if the current map value still equals this subscription's token.

## Findings

No findings.

Checklist verification:
- `_getActiveSubscriptionsForTesting()` and `_resetActiveSubscriptionsForTesting()` are clearly demarcated as test-only and are not used outside tests.
- `clearActiveToken()` correctly checks `_activeSubscriptions.get(sessionId) === subscriptionToken` before deleting, so it cannot clobber a newer superseding subscription.
- `terminalClose()` calls `close()` first, then `clearActiveToken()`. Under normal EventSource/browser event semantics, no asynchronous `onmessage` can interleave between those synchronous statements; late messages after terminal cleanup fail `isStillActive()`.
- Both `validation_complete` and `validation_failed` handlers call `terminalClose()`, not raw `close()`.
- `unsubscribe()` now uses the same `clearActiveToken()` helper, then calls `close()`.
- The new terminal-cleanup tests would have failed against the pre-fix code because `validation_complete` / `validation_failed` previously called only `close()`, leaving `_activeSubscriptions.has(SESSION_ID)` true.
- Superseded-terminal edge case is handled: stale stream messages fail the leading `isStillActive()` guard before reaching terminal handling, and `clearActiveToken()` itself also refuses to delete if the map now belongs to a newer token.

## Closure Assessment

- Pass-1 Finding 1, lifecycle cleanup gap after terminal events: **CLOSED**.
- Pass-1 Finding 2, test teardown does not clear `_activeSubscriptions`: **CLOSED**.

## Verdict Rationale

Approve. The fix addresses the stale active-subscription map entry without weakening stale-stream protection, shares cleanup logic between terminal events and unsubscribe, and adds regression tests that directly cover the previously missing behavior.
