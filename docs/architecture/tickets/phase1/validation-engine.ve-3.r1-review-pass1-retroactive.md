# R1 Review (Pass 1, retroactive) — `ve-3-sse-streaming-backend` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family; RETROACTIVE)
**Date**: 2026-06-03
**Implementation under review**: commit `e8bb0b4` (test commit `b257880`)
**Verdict**: APPROVE-WITH-CHANGES

## Findings

### Required Change

1. `IR_VALIDATION_ERROR` is emitted as a first-class diagnostic but is not cataloged.
   - `stream_validation()` converts `pydantic.ValidationError` into `DiagnosticPayload(code="IR_VALIDATION_ERROR", ...)`.
   - I did not find `IR_VALIDATION_ERROR` in `docs/architecture/diagnostic_catalog.md`.
   - The decision to treat model-validator failures as diagnostics is sound, but the emitted diagnostic code should be registered/cataloged like the rest of the diagnostic surface. Otherwise this creates a hidden diagnostic code outside the catalog contract.
   - Recommended fix: add `IR_VALIDATION_ERROR` to the diagnostic catalog, and preferably register it through the diagnostics registry/decorator mechanism.

## Checklist Review

1. AC 1: Pass.
   - `GET /deals/{deal_id}/validate/stream?sha=<sha>` is exposed.
   - Malformed SHA validated before constructing `StreamingResponse`.
   - Missing deal and missing SHA/object raised as `HTTPException(404)` before streaming begins.

2. AC 2: Pass.
   - Static backend validation executed via hardcoded structural validators plus `DealDefinition.model_validate()`.
   - `_validate_references` covered because it is a `DealDefinition` model validator.
   - Runtime/output-dependent carry tie-out explicitly excluded.
   - Minor caveat: the structural validator list is hardcoded.

3. AC 3: Pass with required cataloging change above.
   - `ValidationStreamEvent` pinned with `event_type`, optional `payload`, optional `error`.
   - SSE framing is `data: <JSON>\n\n` with no `event:` lines.

4. AC 4: Pass. Generator yields `validation_complete` after success; unexpected exceptions yield `validation_failed`. Tests assert exactly one terminal event and no events after.

## Pydantic ValidationError Decision

Converting `Pydantic ValidationError` into `diagnostic` events is the right contract shape. Once `IR_VALIDATION_ERROR` is cataloged, the distinction is sound:

- `diagnostic`: deal content is invalid or structurally suspicious.
- `validation_complete`: validation ran to completion, even if diagnostics were emitted.
- `validation_failed`: validator infrastructure failed unexpectedly.

## Error Handling

Pre-stream HTTP handling is correct: 422 on malformed SHA, 404 on missing deal/SHA.

## Streaming Gotchas

No blocking issue. Backpressure: handled by ASGI. Client disconnect: no explicit disconnect check, acceptable for this finite stream. Keep-alive: no heartbeats — acceptable for current static checks.

## Test Review

The T1 tests cover ACs well. Missing but recommended: 422 for malformed SHA, 404 for missing deal/SHA before stream starts, optional assertion that no `event:` lines are present.
