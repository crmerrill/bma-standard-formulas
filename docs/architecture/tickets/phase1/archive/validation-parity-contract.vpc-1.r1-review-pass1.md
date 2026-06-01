---
reviewer: R1 (gpt-5.5-extra-high, fresh invocation, readonly)
date: 2026-05-30
ticket: vpc-1-diagnostic-code-decorator
implementation_commit: 6010301
verdict: APPROVE-WITH-CHANGES
---

## Executive Summary
- AC 1-6 are satisfied by the implementation and mapped by the T1 tests.
- Public exports match the requested API surface exactly.
- Scope is respected: no IR/schema, catalog doc, markdown parser, CI guard, TS registry, or validator migration leakage observed.
- Source location capture uses `inspect.getsourcefile` / `inspect.getsourcelines` with graceful fallback.
- One Minor hygiene issue remains: the module-level mutable registry lacks an explicit import-time/thread-safety note.

## Acceptance criteria audit
| AC | Status | Evidence | Notes |
|---|---|---|---|
| 1 — enums | ✓ | `src/bma_standard_formulas/diagnostics/payload.py:11-20`, `tests/diagnostics/test_payload.py:15-16` | `Severity` is exactly `error/warning/info`; `Owner` is exactly `worker/backend/both`; both inherit `(str, enum.Enum)`. |
| 2 — payload | ✓ | `src/bma_standard_formulas/diagnostics/payload.py:23-28`, `tests/diagnostics/test_payload.py:18-53` | Exactly five fields; `payload` uses `Field(default_factory=dict)`; invalid severity is tested via `ValidationError`. |
| 3 — decorator | ✓ | `src/bma_standard_formulas/diagnostics/decorator.py:12-23`, `tests/diagnostics/test_decorator.py:45-98` | Signature is keyword-only for `severity`, `path_schema`, `owner`; non-`Severity` / non-`Owner` are rejected with `TypeError`. |
| 4 — descriptor | ✓ | `src/bma_standard_formulas/diagnostics/registry.py:19-26`, `src/bma_standard_formulas/diagnostics/decorator.py:31-38` | Frozen dataclass with exactly six fields; qualname and `(file, line)` are populated from the decorated function. |
| 5 — registry | ✓ | `src/bma_standard_formulas/diagnostics/registry.py:29-50`, `tests/diagnostics/test_registry.py:56-84` | `_REGISTRY` is module-private and keyed by code; lookup, iteration, missing lookup, and duplicate registration behavior match the contract. |
| 6 — path_schema | ✓ | `src/bma_standard_formulas/diagnostics/decorator.py:31-38`, `tests/diagnostics/test_decorator.py:73-87` | Decorator stores path schemas as provided and accepts `.field`, `[*]`, and `[id_var]` patterns without validation. |

## Findings

### Blocking
None.

### Critical
None.

### Major
None.

### Minor

### m1 — Minor — `src/bma_standard_formulas/diagnostics/registry.py:29`
**Issue + evidence**: `_REGISTRY` is a module-level mutable dict, which is acceptable for this v1 contract because diagnostics register at import time, but the implementation does not document that concurrency assumption.

**Recommended fix**: Add a brief module docstring sentence or nearby comment explaining that registry mutation is intended for import-time validator registration, not runtime concurrent mutation.

### Nit
None.

## Verdict Justification
Threshold applied: zero Blocking, zero Critical, zero Major. The implementation is mergeable after or alongside the Minor hygiene change, so the verdict is `APPROVE-WITH-CHANGES`.

## Parent fix-pass + verification (2026-05-30)

The Minor finding (m1) was applied directly by the parent agent rather than dispatching a fresh implementer subagent for a single-sentence docstring change (cost discipline). The expanded module docstring at `src/bma_standard_formulas/diagnostics/registry.py:1-12` now documents the import-time-mutation contract: `_REGISTRY` is populated by `@diagnostic_code` decorations during module import, lookups are thread-safe afterward, and production code must not mutate the registry at runtime. Tests use the existing `_clean_registry` autouse fixture pattern explicitly noted in the docstring.

Targeted suite (`tests/diagnostics/`): 4 passed in 0.13s. Full suite (`tests/`): 1438 passed, 3 skipped, 0 failures — no regressions from the docstring change.

m1 is now CLOSED. Ticket merged.
