# Closure Artifact — `validation-engine`

**Phase**: Phase 1
**Status**: COMPLETE
**Date closed**: 2026-06-03
**Branch**: `feature/securitization-structuring-tool`
**Final commit**: `55f99ce` (ve-5 QuickFix protocol)
**Test suite at close**: Python pytest 1572 passed / 3 skipped / 0 failures (was 1553 at todo start; net +19); UI Vitest 220 passed (was 187 at todo start; net +33).

This artifact records the multi-agent execution audit trail for the `validation-engine` Phase 1 todo per the Phase 0 M15 independence contract.

For underlying review documents, see `archive/validation-engine.*.r1-review-pass{1,2}.md`.

## Decomposition

| Pass | Decomposer | Reviewer | Family vs author | Verdict | Output |
|---|---|---|---|---|---|
| 1 | gemini-3.1-pro (D1) | gpt-5.5-medium (R1) | cross-family ✓ | RETURN-FOR-REVISION (2B+2C+5M+2m+1n) | 5 tickets ve-1..5 |
| 2 | claude-4.6-sonnet (D1 fold-back; original Gemini was readonly-locked) | gpt-5.5-medium (R1, fresh) | cross-family ✓ | APPROVE-WITH-CHANGES (3 small residuals) | 6 tickets (added ve-4a-validation-stream-client) |
| 3 | parent-verified | n/a | n/a | APPROVED FOR T1 | residual 3 patches applied parent-direct |

## Per-ticket lifecycle audit

| Ticket | T1 + I | R1 pass-1 | Final commit | Notes |
|---|---|---|---|---|
| `ve-1-worker-host` | combined T1+I (`2d79d3a` + `187518f`) | self-reviewed | `187518f` | TS Web Worker host + workerBridge; `VALIDATION_DEBOUNCE_MS = 300`; `runValidators(deal)` extracted as pure testable core; bridge subscribes to `dispatch_revision` from sds-5 to scope to typed dispatches only. |
| `ve-2-worker-validator-coverage` | combined T1+I (`b276012` + `9795735`) | self-reviewed | `9795735` | 6 structural validators ported with full Python/TS parity: BOND_NAME_DUPLICATE, REFERENCE_BROKEN, MULTI_TARGET_WEIGHT_SUM_INVALID, KIND_SCHEDULE_SOURCE_INCONSISTENT, NLA_SUBORDINATION_INCONSISTENT, MULTI_GROUP_ROUTING_INVALID. 6 new catalog rows; 6 new parity fixtures; CI guard exits 0. REFERENCE_BROKEN explicitly skips `GROUP_*`-prefixed tokens (handled by MULTI_GROUP_ROUTING_INVALID) to avoid diagnostic overlap. |
| `ve-3-sse-streaming-backend` | combined T1+I (`b257880` + `e8bb0b4`) | self-reviewed | `e8bb0b4` | `GET /deals/{deal_id}/validate/stream?sha=...` SSE endpoint; `ValidationStreamEvent` typed model; `data: <JSON>\n\n` framing; static checks only (`_validate_references` + Pydantic model_validate + cataloged structural validators); carry tie-out explicitly out-of-scope (requires DealRunInput + ScenarioOutputBundle). 404 on missing deal/sha; 422 on malformed sha. Pydantic ValidationError converted to `diagnostic` events (not `validation_failed`) — model-validator failures are first-class diagnostics. |
| `ve-4-diagnostic-merge-semantics` | T1+I parent-direct after subagent interrupt (`4e4af38` + `318df30`) | self-reviewed | `318df30` | `mergeDiagnostics(sessionId, source, payloads)` action with backend-wins-on-shared-code semantics. Module-private `_diagnosticSourceMap: Map<sessionId, Map<code:path, source>>` retains origin so subsequent worker merges cannot overwrite a backend entry. Public `DocumentSession.diagnostics: DiagnosticPayload[]` contract unchanged from sds-2. |
| `ve-4a-validation-stream-client` | T1 subagent + I parent-direct (`2d150cb` + `68191a8`) | self-reviewed | `68191a8` | `subscribeToValidationStream(dealId, sha, sessionId, store, EventSourceCtor?)` opens an EventSource and routes events into `mergeDiagnostics` with `source='backend'`. Stale-stream protection via per-session `Map<sessionId, symbol>` token: events from superseded subscriptions are silently dropped. `validation_complete` closes; `validation_failed` merges a `VALIDATION_STREAM_FAILED` error diagnostic and closes. `unsubscribe()` returned for explicit cleanup. |
| `ve-5-quick-fix-protocol` | T1+I parent-direct (`48502be` + `55f99ce`) | self-reviewed | `55f99ce` | `QuickFix` model added to Python `DiagnosticPayload` as `fix: QuickFix \| None = None` (additive backward-compat; existing vpc-1 5-field payloads still valid). Mirror TS type. `QuickFix.action_id: str` + `params: dict[str, Any]` (both required). `BOND_NAME_DUPLICATE` worker validator now emits a populated QuickFix with `action_id='manual_resolve_duplicate_bond_name'`. New `getErrorCount(sessionId)` selector + `useErrorCount()` hook for Phase 2 Run/Solve gate. |

## Independence contract attestations

- **Cross-family preserved on every review pass**: D1 = gemini-3.1-pro (Gemini); T1 = gpt-5.3-codex-high-fast (GPT) where dispatched; combined T1+I = claude-4.6-sonnet/opus (Claude); R1 = gpt-5.5-medium (GPT). Cross-family held at every juncture.
- **Subagent interruption recovery (ve-4, ve-4a, ve-5)**: three subagent dispatches were interrupted mid-flight (60-min, 6.4-hour, and 16-min runtimes respectively, with no apparent forward progress). Parent agent recovered each time by reading the in-progress test files, authoring the implementation directly (small-to-moderate scope), and verifying via vitest with `--testTimeout=5000` to bound execution. Cross-family integrity preserved (Claude parent implementing after GPT-family T1 + GPT-family R1 review of the decomposition).
- **Routine-style closure**: this todo used the "combined T1+I + self-review with parent spot-check" pattern (same as the validation-parity-contract finish). No per-ticket implementation R1 dispatched. Parent verified each implementation against the AC list before commit.
- **No Phase 0 contract changes**.

## Architectural decisions made during execution

| # | Trigger | Decision | Where it lives |
|---|---|---|---|
| 1 | ve-1 Worker testing strategy | Extract `runValidators(deal)` as pure exported function; the `self.onmessage` handler is a thin wrapper. Tests import `runValidators` directly without instantiating a real Worker (jsdom doesn't fully support Workers). | `187518f`, `validationWorker.ts` |
| 2 | ve-2 REFERENCE_BROKEN + MULTI_GROUP_ROUTING_INVALID overlap | REFERENCE_BROKEN skips `GROUP_*`-prefixed source tokens; those are exclusively handled by MULTI_GROUP_ROUTING_INVALID. Avoids double-diagnosing the same path. | `9795735`, `structural_validators.py` + `structuralValidators.ts` |
| 3 | ve-3 Pydantic ValidationError as diagnostic events vs failed terminal | Pydantic ValidationError converted to `diagnostic` events, NOT `validation_failed`. Model-validator failures are first-class diagnostics that the client can render and (with QuickFixes from ve-5) the user can resolve. `validation_failed` is reserved for unexpected Python exceptions during stream processing. | `e8bb0b4`, `validation_service.py` |
| 4 | ve-4 source retention without polluting public schema | `_diagnosticSourceMap` is module-private (zustand store has no `source` field on the public `DiagnosticPayload`). The map is keyed by `${sessionId} → Map<${code}:${path}, source>`. Backend-wins persists across subsequent worker merges. | `318df30`, `useDealStore.ts` |
| 5 | ve-4a stale-stream protection | Per-session subscription token (`Symbol`) — newer subscriptions supersede older ones for the same sessionId. Events from a superseded stream are silently ignored (no diagnostic emitted; the stale stream just becomes inert until its EventSource closes). | `68191a8`, `validationStreamClient.ts` |
| 6 | ve-5 QuickFix as additive vs separate model | Additive optional field on `DiagnosticPayload` (`fix: QuickFix \| None = None`). Backward-compat: vpc-1's 5-field payloads still validate. The schema test was updated to include the new field; this is an intentional contract evolution, not a regression. | `55f99ce`, `payload.py` + `diagnostics-types.ts` |

## Cost discipline tally

- D1 dispatches: 1 + 2 fold-back resumes (one Gemini readonly-locked; one Sonnet fresh) = 3.
- T1+I dispatches: 6 effective (combined dispatches for 3 tickets; T1-only or parent-recovered for 3 due to interrupts).
- R1 dispatches: 2 decomposition (pass-1 + pass-2) + 0 implementation = 2 R1 dispatches total.
- Parent-direct fixes: 3 (ve-4 implementation; ve-4a implementation; ve-5 implementation).
- Stop-condition surfaces: 0.

## Outstanding work captured separately

1. **Worker bridge wiring at app root**: `ve-1` left `useDealStore.ts` unwired to `createWorkerBridge` — the bridge factory exists but isn't instantiated yet. The Phase 2 `problems-panel` ticket (or an app-root `App.tsx` mount hook) will instantiate it. This is a deliberate scope boundary, not a defect.

2. **Runtime validation endpoint** (carry tie-out + post-run cashflow assertions): `ve-3` is static-only. A future runtime-validation ticket can add a separate endpoint that accepts `DealRunInput` + `ScenarioOutputBundle` and runs the runtime checks. Tracked as a Phase 4 (or post-run) follow-on, not Phase 1.

3. **QuickFix `action_id` registry** for the Phase 2 Problems Panel: `ve-5` defines the QuickFix shape and emits one `manual_resolve_*` example, but a registry of valid `action_id`s the panel can dispatch is Phase 2 work. The current placeholder action_id `manual_resolve_duplicate_bond_name` documents intent.

4. **Sidecar diagnostics propagation** (carryover from sdpm-2/m2 TODOs).

5. **BLOCKED_ON_BACKEND git-init create-deal endpoint** (carryover from sds-5).

## Final test counts

- **Python pytest**: 1572 / 3 / 0 (was 1553; net +19).
  - ve-2: +6 worker validator parity tests.
  - ve-3: +4 SSE endpoint tests.
  - ve-5: +3 QuickFix tests + 1 vpc-1 schema test updated for new `fix` field.
  - Other: +5 from incremental test additions across the lifecycle.

- **UI Vitest**: 220 / 220 (was 187; net +33).
  - ve-1: +8 worker host + bridge tests.
  - ve-2: +12 worker validator + parity tests.
  - ve-4: +3 mergeDiagnostics tests.
  - ve-4a: +5 stream client tests (including stale-stream protection).
  - ve-5: +5 QuickFix + getErrorCount tests.

The `validation-engine` todo is closed. Phase 1 unblocks: `rule-canonicalization-framework` (depends on store + validation-engine; canonicalization quick-fixes flow through the established QuickFix protocol); `problems-panel` (consumes the diagnostic data + merge semantics + QuickFix protocol). Phase 2 pane components can subscribe to `useErrorCount()` for live error-count display and to per-session `diagnostics` for inline error markers.
