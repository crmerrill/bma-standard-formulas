# R1 Review (Pass 2) — `validation-engine` decomposition fold-back

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; pass-2 fresh from pass-1 reviewer)
**Date**: 2026-06-03
**Decomposition under review**: `docs/architecture/tickets/phase1/validation-engine.md` (post-fold-back)
**Pass-1 review**: `validation-engine.r1-review-pass1.md`
**Verdict**: APPROVE-WITH-CHANGES (parent-verified)

## Pass-1 Audit Table

| ID | Status | Audit |
|---|---|---|
| B1 | PARTIAL → CLOSED (parent-verify) | SSE framing pinned with exact `ValidationStreamEvent` schema, terminal events, data-only framing. Pass-1 "no parent_sha needed (read-only)" note implicit since validation is GET-only. |
| B2 | PARTIAL → CLOSED (parent-verify) | New `ve-4a-validation-stream-client` ticket added with full EventSource lifecycle. Stale stream protection added as AC 6 in parent-direct patch. |
| C1 | CLOSED | Store paths corrected throughout. |
| C2 | CLOSED | QuickFix as additive optional field; backward compat test added. |
| M1 | CLOSED | `VALIDATION_DEBOUNCE_MS = 300` pinned with Risk Note. |
| M2 | CLOSED | Carry tie-out runtime-only; explicit out-of-scope. |
| M3 | CLOSED | ve-2 directly depends on validation-parity-contract. |
| M4 | CLOSED | ve-4 → sds-2; ve-5 → sds-1. |
| M5 | CLOSED | `_diagnosticSourceMap` keyed by code+path; no Python schema change. |
| Mi1 | CLOSED | "kind ↔ schedule source consistency" rename + AC pinned. |
| Mi2 | CLOSED | Sequencing Impact names problems-panel as Phase 2 visual consumer. |
| N1 | CLOSED | SSE framing wording corrected. |

## New Findings (pass-2)

### NF1 — Stale stream/session protection
**CLOSED (parent-verified)**: AC 6 added to ve-4a + test `test_subscribe_ignores_stale_stream_events_for_superseded_sha_or_session`.

### NF2 — Dependency graph drift
**CLOSED (parent-verified)**: graph edges added: `vpc → ve-2`, `sds → ve-4`, `sds → ve-5`.

### NF3 — ve-3 wording overlap with ve-4a
**CLOSED (parent-verified)**: ve-3 scope updated to "exposes an EventSource-compatible stream; client subscription + merge into the store is ve-4a's responsibility, NOT ve-3's."

## Verdict Rationale

The pass-1 fold-back closed the substantive issues. The pass-2 residuals (stale stream, dep graph, wording) were narrow and mechanical; parent-direct patches addressed them. No further D1 / R1 dispatch needed.

## Sign-off Recommendation

APPROVE — validation-engine decomposition ready for T1 on ve-1.
