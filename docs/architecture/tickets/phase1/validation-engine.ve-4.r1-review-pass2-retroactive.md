# R1 Review (Pass 2, retroactive fix-pass) — `ve-4-diagnostic-merge-semantics`

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family)
**Date**: 2026-06-03
**Fix-pass under review**: T1 `ae6fd20`, Fix `099f8c9`
**Verdict**: APPROVE-WITH-CHANGES

## Summary

The lifecycle fix for original M1 is implemented correctly: `deleteSession` cleans up per-session provenance, `setDiagnostics` clears/rebuilds provenance, and the test-only reset hook gives tests a complete reset path for module-private state.

One checklist item is not satisfied: `getDiagnosticSourceMapForTesting()` returns the raw internal `Map`, so it is not a read-only inspector.

## Findings

### M1 — Test inspector exposes mutable internal map

`getDiagnosticSourceMapForTesting()` is documented as test-only, but it returns `_diagnosticSourceMap` directly. A caller can mutate the live module-private map with `.set()`, `.delete()`, `.clear()`, or by mutating nested session maps.

It should return a read-only snapshot, for example a cloned `Map<string, ReadonlyMap<string, Source>>`, a plain serialized object, or narrowly scoped query helpers such as `hasDiagnosticSourceMapEntryForTesting(sessionId)`.

Severity: minor/test-surface issue. It does not reopen the original production lifecycle bug.

## Checklist Assessment

1. `deleteSession` cleanup: Pass.
2. `setDiagnostics(sid, [])` empty case: Pass.
3. `setDiagnostics(sid, payloads)` non-empty case: Pass. Re-seeds with `"worker"` provenance.
4. `resetDiagnosticSourceMapForTesting()`: Pass. Test-only.
5. `getDiagnosticSourceMapForTesting()`: Fail. Returns the live raw `Map`.
6. T1 fidelity: Pass. All three tests would fail before fix.
7. Missing source-map entry on `deleteSession`: Pass. `Map.delete` no-ops gracefully.
8. `setDiagnostics` key consistency: Pass. Uses `${p.code}:${p.path}`.

## Closure Assessment

Original M1: **CLOSED**.

## Verdict Rationale

APPROVE-WITH-CHANGES because the requested lifecycle behavior is correct, the T1 tests have real pre-fix failure fidelity, and the edge cases check out. Before full approval, make `getDiagnosticSourceMapForTesting()` a read-only snapshot or replace it with narrower read-only test query helpers.
