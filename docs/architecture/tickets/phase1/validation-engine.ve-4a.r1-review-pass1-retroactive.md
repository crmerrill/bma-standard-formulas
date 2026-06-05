# R1 Review (Pass 1, retroactive) — `ve-4a-validation-stream-client` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family; RETROACTIVE)
**Date**: 2026-06-03
**Implementation under review**: commit `68191a8` (test commit `2d150cb`)
**Verdict**: APPROVE-WITH-CHANGES

## Findings

1. **Lifecycle cleanup gap after terminal events**
   `validation_complete` and `validation_failed` call `close()`, but `close()` only closes the EventSource; it does not clear `_activeSubscriptions` for the active `sessionId`. `unsubscribe()` does clear the active token, but a normal successful/failed terminal stream can leave a stale token in the module-private map until the same session subscribes again.

   This is not a core AC failure for AC 1-6, but it is a memory/lifecycle issue. It also means a mocked or unusual EventSource that invokes `onmessage` after terminal close would still pass `isStillActive()`.

   Recommended change: have terminal close clear the active token when it still belongs to this subscription, or have `close()` optionally perform active-token cleanup.

2. **Test teardown does not clear `_activeSubscriptions`**
   Tests use `vi.restoreAllMocks()` in `beforeEach`, but `_activeSubscriptions` is module-private and not reset directly.

   Recommended change: either export a test-only reset helper, expose active-count only under test, or structure tests so every subscription is unsubscribed/terminal cleanup clears the token.

## Acceptance Criteria Review

- **AC 1: opens EventSource** — Pass. `subscribeToValidationStream(dealId, sha, sessionId, store, EventSourceCtor?)` constructs `/deals/${dealId}/validate/stream?sha=...`.
- **AC 2: diagnostic merge dispatch** — Pass.
- **AC 3: validation_complete closes** — Pass.
- **AC 4: validation_failed merges error + closes** — Pass.
- **AC 5: returns unsubscribe()** — Pass.
- **AC 6: stale-stream protection** — Pass. The per-session symbol token correctly causes newer subscriptions for the same `sessionId` to supersede older streams.

## EventSource Edge Cases

- **Malformed / non-JSON SSE data** — Handled defensively via `try/catch` around `JSON.parse`.
- **Unknown JSON event shapes** — Benignly ignored.
- **Reconnect behavior** — No custom reconnect logic. Relies on native EventSource automatic reconnection until terminal event or unsubscribe.

## T1 Test Review

The T1 tests cover the main AC paths. Coverage gap: tests do not assert cleanup of `_activeSubscriptions` after terminal events, and do not directly test malformed/non-JSON `MessageEvent.data`.
