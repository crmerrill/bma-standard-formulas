# R1 Review (Pass 1, retroactive) — `ve-4-diagnostic-merge-semantics` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family; RETROACTIVE)
**Date**: 2026-06-03
**Implementation under review**: commit `318df30` (test commit `4e4af38`)
**Verdict**: APPROVE-WITH-CHANGES

## Findings

### M1 — `_diagnosticSourceMap` is not reset or cleaned up

The implementation adds a module-private `_diagnosticSourceMap` keyed by `sessionId -> Map<code:path, source>`, but it is not cleared when the Zustand store is reset via `useDealStore.setState(useDealStore.getInitialState(), true)` and is not cleaned up when `deleteSession(sessionId)` removes a non-main session.

Impact:
- Tests that reset store state with `getInitialState()` do not reset the source map.
- Deleted sessions leave source-map entries behind for the lifetime of the module.
- If a session's diagnostics are replaced or cleared through `setDiagnostics`, the source map can still remember an old backend entry and cause later worker merges for the same `(code, path)` to be skipped.

Recommended change:
- Clear `_diagnosticSourceMap.delete(sessionId)` inside `deleteSession` for non-main sessions.
- Add a test-only/internal reset hook or incorporate source-map cleanup into whatever reset path tests use.
- Consider whether `setDiagnostics(sessionId, payloads)` should also reset/rebuild that session's source map.

## Checklist

1. **AC 1**: Pass. `mergeDiagnostics(sessionId, source, payloads)` exposed with `source: "worker" | "backend"`.
2. **AC 2**: Pass. Backend payloads upsert over worker payloads; once source map records `"backend"`, later worker payloads for that key are skipped.
3. **AC 3**: Pass. Existing diagnostics whose keys are not in the incoming merge set are carried forward.
4. **Module-private source map**: Needs change. Map is module-private and shaped as requested, but not reset by `getInitialState()` and not cleaned up on session deletion.
5. **Public `DiagnosticPayload` schema unchanged**: Pass.
6. **Concurrent merge race**: Acceptable. Zustand `set` synchronous in normal frontend execution.
7. **Test coverage**: Mostly. Test covers `worker -> backend -> worker` and asserts backend persists. But `beforeEach` does not reset `_diagnosticSourceMap`, so suite can leak provenance between tests.

## Summary

Core backend-wins merge behavior implemented correctly for AC 1-3, public payload contract intact. Source-map lifecycle cleanup needed before considering VE-4 fully merge-ready.
