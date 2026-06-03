# R1 Review (Pass 1) — `validation-engine` decomposition

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family from gemini-3.1-pro D1 + Claude parent + future Claude implementers)
**Date**: 2026-06-03
**Decomposition under review**: `docs/architecture/tickets/phase1/validation-engine.md`
**Verdict**: RETURN-FOR-REVISION

## Summary

Directionally right and covers the master contract: worker host, six cheap worker validators, backend authoritative validation, backend-wins merge semantics, quick-fix payloads, Run/Solve error-count selector. Below the irvc-1/irvc-4 specificity bar. Several ACs leave implementers room to pick incompatible contracts, and there's a missing client-ingestion slice between backend SSE and Zustand merge.

## Findings

### Blocking

**B1** — ve-3 SSE stream under-specified vs irvc-4 bar. Pin: exact event schema (`ValidationStreamEvent` or similar); event-name vs data-only events; diagnostic event JSON shape with `event_type` / `source` / `payload: DiagnosticPayload`; terminal events (`validation_complete`, `validation_failed`); close behavior; malformed SHA / missing deal / validation exception responses; explicit "no parent_sha needed (read-only)" note.

**B2** — Missing client-side SSE ingestion slice. ve-3 builds backend; ve-4 builds merge reducer; nothing wires backend events into `mergeDiagnostics(sessionId, 'backend', ...)`. Either expand ve-4 or add `ve-4a-validation-stream-client`. Files under `src/bma_cfengine_app/ui/src/features/validation/`. ACs cover EventSource lifecycle, terminal close, error terminal, stale stream/session protection.

### Critical

**C1** — Store paths wrong. Decomposition mentions `src/bma_cfengine_app/ui/src/store/validationSlice.ts` (lines 33, 127, 159) which doesn't exist. Actual store is at `src/bma_cfengine_app/ui/src/features/deals/store/`. Replace all references; likely affected files are `useDealStore.ts`, `session.ts`, `actions.ts`, optionally `selectors.ts`.

**C2** — ve-5 QuickFix risks breaking vpc-1 `DiagnosticPayload` contract. Pin: additive `fix: QuickFix | None = None` (preferred — backward-compat) OR separate `DiagnosticWithFix` extension. Pin exact `QuickFix` schema (action_id + params), not "e.g.". If additive: AC must state default None and existing 5-field payloads remain valid.

### Major

**M1** — ve-1 AC 3 "e.g., 300ms" not pinned. Pin `VALIDATION_DEBOUNCE_MS = 300`. Add Risk Note for tunability.

**M2** — ve-3 carry tie-out is runtime-only, not static. Existing `compute_carry_tieout` requires `DealRunInput` + `ScenarioOutputBundle`, not just `deal_id` + `sha`. Separate static backend validation (in this endpoint) from runtime deep checks (run-output-dependent; not in this endpoint). Validation SSE runs only `_validate_references` + Pydantic validators + cataloged structural validators.

**M3** — ve-2 should depend directly on `validation-parity-contract`, not just ve-1.

**M4** — ve-4 should depend on `studio-document-and-store` (sds-2 diagnostics slot); ve-5 should depend on sds-1 (typed dispatch surface for QuickFix actions).

**M5** — ve-4 merge needs source-retention model. Currently no way to know which stored diagnostics are worker vs backend on next merge. Pin storage shape: bucket `{worker, backend, merged}` OR wrap as `{source, payload}` UI-side. Don't add `source` to Python `DiagnosticPayload` (vpc-1 contract change).

### Minor

**Mi1** — ve-2 "kind ↔ schedule_contract" too narrow. Existing IR allows PAC/TAC to satisfy via `schedule_contract` OR `schedule_model_type`. Rename to "kind ↔ schedule source consistency" and pin AC.

**Mi2** — Add one sentence in Sequencing Impact explicitly naming `problems-panel` as the visual consumer todo.

### Nit

**N1** — ve-3 mixes NDJSON ("JSON lines") and SSE terminology. Replace with "JSON payloads framed as SSE events" + pinned framing.

## What Landed Well

- Worker/backend split + backend-wins semantics align with plan.
- 6 worker validation areas are the right first coverage set.
- Worker-side quick-fix execution correctly avoided (action intent flows to main thread).
- Run/Solve error-count selector at the data-contract layer; UI deferred to Phase 2.

## Verdict Rationale

Close but not T1-ready. Blocking issue: SSE framing + client ingestion not sufficiently specified for independent backend/frontend/test agents to converge. Critical: wrong store path; QuickFix schema risk.

## Sign-off Recommendation

RETURN-FOR-REVISION. D1 fold-back addressing B1, B2, C1, C2, M1, M2 at minimum. After revision: parent-verify if fixes are mechanical, OR R1 pass-2 if scope expanded for the EventSource client bridge ticket.
