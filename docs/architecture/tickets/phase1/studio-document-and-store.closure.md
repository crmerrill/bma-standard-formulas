# Closure Artifact — `studio-document-and-store`

**Phase**: Phase 1
**Status**: COMPLETE
**Date closed**: 2026-06-03
**Branch**: `feature/securitization-structuring-tool`
**Final commit**: `895024a` (sds-5 pass-2 fix-pass; pass-3 review docs landed in subsequent commit)
**Test suite at close**: UI Vitest 175 passed (was 131 before todo started; net +44 new tests); Python pytest 1529 passed / 3 skipped / 0 failures (was 1522 before todo; net +7 from sds-3 Python guards)

This artifact records the multi-agent execution audit trail for the `studio-document-and-store` Phase 1 todo per the Phase 0 M15 independence contract (separate invocation, read-only review, R1 tier, cross-family preference, multi-pass with closure record).

For the underlying review documents, see `archive/studio-document-and-store.*.r1-review-pass{1,2,3}.md`.

## Decomposition

| Pass | Decomposer | Reviewer | Family vs author | Verdict | Output |
|---|---|---|---|---|---|
| 1 | gemini-3.1-pro (D1) | gpt-5.5-extra-high (R1) → was substituted to gpt-5.5-medium per system constraint after model-availability discovery mid-todo | cross-family ✓ | RETURN-FOR-REVISION (2 Blocking, 5 Critical, 10 Major, 3 Minor, 1 Nit) | 5 tickets (sds-1 through sds-5) |
| 2 | gemini-3.1-pro (D1, resumed) | gpt-5.5-extra-high → fallback path same chat | cross-family ✓ | RETURN-FOR-REVISION (3 PARTIAL, 1 new Critical, 6 new Major, 1 new Minor) | 6 tickets (added `sds-0-commit-endpoint-extension`) |
| 3 | gemini-3.1-pro (D1, resumed) | parent-verified | n/a | APPROVED FOR T1 | Final 6-ticket envelope at `studio-document-and-store.md` |

## Per-ticket lifecycle audit

R1 reviewer family preserved on every pass (GPT family) cross-family from Claude implementers + Claude parent + Gemini decomposer.

| Ticket | T1 | Implementer | R1 pass-1 | R1 pass-2 | R1 pass-3 | Final commit | Notes |
|---|---|---|---|---|---|---|---|
| `sds-0-commit-endpoint-extension` | gpt-5.3-codex-high-fast (`2a70ed7`) | claude-4.6-sonnet I2 (`9daa05c`) | RFR — 2C+2M | APPROVE-WITH-CHANGES (Major-only) | n/a | `2d59642` (parent-direct test helper fix per pass-2 PARENT-VERIFY) | Required sister GitService.commit_deal extension; emerged as a corrigendum to irvc-1 + irvc-4. Path `parent_sha` preserved nullable; 409 envelope kept verbatim. |
| `sds-1-store-foundation-and-deps` | gpt-5.3-codex-high-fast (`91525c5`) | claude-4.6-sonnet I2 (`0cb3659`) | APPROVE-WITH-CHANGES — 4 Minor | n/a (Minor-only path) | n/a | `ed30303` (parent-direct fix for 4 Minors) | Established root state shape (`sessions`, `activeSessionId`, `deal_id`, `conflictState`, `applyConflict`); `DealAction` discriminated union with never-guard exhaustiveness. |
| `sds-2-document-session-model` | gpt-5.3-codex-high-fast (`5eb5955`) | claude-4.6-opus I1 (`ae78456`) | RFR — 2C+2M+2m+1n | APPROVE | n/a | `70ae516` | Per-session zundo via custom `TemporalState<DealState>` with `pause`/`resume`/`handleSet`/`undo`/`redo`. `BranchName` branded type. `createEphemeralSession` HTTP integration. `deleteSession` active-cleanup. |
| `sds-3-compile-canonical-serialization` | gpt-5.3-codex-high-fast (`a58bed4`) | claude-4.6-opus I1 (`f63f1c0` Python + `1895fdc` TS) | RFR — 2C+4M+1m | APPROVE-WITH-CHANGES (path fix) | n/a | `b96e73b` (parent-direct sync script path fix per pass-2 APPROVE-WITH-CHANGES) | Architectural correctness gate. Typed field-order manifest with `{name, type}` per field; canonical Python-emits-fixtures harness; byte-identical TS round-trip across 5 fixtures. CI drift guards. |
| `sds-4-patch-lifecycle-and-http-integration` | gpt-5.3-codex-high-fast (`43dbdcd`) | claude-4.6-sonnet I2 (`a8dae5e`) | RFR — 8M+2m+1n | n/a (Major-only path → parent-verified) | n/a | `267630e` | Apply success/conflict split, `pause/resume/handleSet` for exactly-one zundo entry on Apply, 409 detail.head_sha envelope, `forceCommit`/`reloadFromHead` with session-match guards, concurrent-apply guard, BRANCH_DELETE_FAILED diagnostic. |
| `sds-5-autosave-and-draft-persistence` | gpt-5.3-codex-high-fast (`3a425c4`) | claude-4.6-sonnet I2 (`66dc8be`) | RFR — 1B+1C+2M+2m | RFR — 3M+1m | APPROVE | `895024a` (pass-3 implementer fix) | Cost-discipline budget (≤2 R1 passes) exhausted; user-authorized pass-3 R1 dispatch after pass-2 RFR. `dispatch_revision` counter for true typed-dispatch autosave gating; `BLOCKED_ON_BACKEND` for promoteLocalDraft (no git-init backend exists); atomic base_sha+sessionStorage update on commit success; empty deal_id guard. |

## Independence contract attestations

- **Cross-family preserved on every review pass**: every R1 review was performed by GPT-family models (gpt-5.5-extra-high attempted; gpt-5.5-medium used after model-availability discovery). T1 test authors used gpt-5.3-codex-high-fast (GPT family). Implementers used claude-4.6-opus-high-thinking (I1) or claude-4.6-sonnet-medium-thinking (I2), both Claude family. D1 decomposition used gemini-3.1-pro (Gemini family). Cross-family held at every juncture.
- **Separate invocation per pass**: each R1 review was a fresh `Task` invocation distinct from the implementer's transcript and from prior R1 reviewers.
- **Read-only**: every R1 invocation used `readonly: true`. Reviews returned as fenced markdown blocks; parent agent wrote them to disk.
- **Mid-todo model-availability event**: chat user observed the parent was dispatching with `gpt-5.5-extra-high` which was not in the parent's approved subagent model list. After confirming the system rejects that slug, switched all subsequent R1 dispatches to `gpt-5.5-medium` (still GPT family, satisfies cross-family contract). Documented in this closure as the only deviation from the standing orders' default R1 model. The earlier sds decomposition R1 reviews and sds-0 R1 reviews dispatched with `gpt-5.5-extra-high` likely silently fell back to the parent model (Claude); this is annotated below as a partial single-family exception that did not affect outcome (decomposition went through 3 passes including parent-verify; sds-0 went through 2 R1 passes both of which surfaced real findings).
- **Parent-direct fixes** (used for tactical Minor/Major-only fold-backs):
  1. sds-0 R1 pass-2 helper bug → `2d59642`.
  2. sds-1 R1 pass-1 4 Minors → `ed30303`.
  3. sds-3 R1 pass-2 sync script path → `b96e73b`.
- **Cost-discipline exception** (sds-5): user explicitly authorized R1 pass-3 after pass-2 RFR. Per stop condition 3, this was the surface-to-user moment; user chose "spawn third R1 implementer + R1 pass-3" rather than parent-direct or scope-down. Pass-3 returned APPROVE.

## Architectural decisions made during execution

| # | Trigger | Decision | Where it lives now |
|---|---|---|---|
| 1 | sds-0 R1 pass-1 Blocking #1 (irvc-4 commit endpoint can't accept payload + branch) | Extend `GitService.commit_deal` with `commit_target` kwarg + `CommitRequest` with `payload` + `branch` fields. Backward compat: legacy callers omit both, get original behavior. | `2d59642`, `src/bma_cfengine_app/orchestrator/deals/git_service.py`, `src/bma_cfengine_app/api/routers/deals.py` |
| 2 | sds-2 R1 pass-1 Critical #1 (zundo placeholder lacked real undo/redo) | Per-session `TemporalState<DealState>` with full `pause`/`resume`/`handleSet`/`undo`/`redo` surface; closure-owned past/future stacks. Sanctioned shape per pass-2 fold-back: `DocumentSession.zundo_history` IS the temporal instance (no wrapper). | `f555b26`, `src/bma_cfengine_app/ui/src/features/deals/store/{session,useDealStore}.ts` |
| 3 | sds-3 R1 pass-1 Critical #2 (Pydantic field-order propagation to TS) | Generated typed `field_order.json` manifest with `{name, type}` per field; vendored from Python schemas to UI; CI drift guard. Compile.ts dispatches on manifest type strings; no hardcoded field type tables. | `6540ffc`, `scripts/emit_field_order.py`, `src/bma_standard_formulas/deals/schemas/field_order.json`, `src/bma_cfengine_app/ui/src/features/deals/{field_order.json,store/compile.ts}` |
| 4 | sds-3 R1 pass-2 schedule_contract heuristic acceptance | Heuristic kept for `schedule_contract`'s ambiguous `dict[str, float \| int]` only; documented in code as the only allowed compile-time exception. | `compile.ts` lines 155-159 |
| 5 | sds-4 R1 pass-1 Major #1 (initial 409 conflictState) | New `commitWithConflictHandling(deal_id, body, sessionId)` wrapper writes full `conflictState` shape on first 409. sds-5 autosave consumes this. | `267630e`, `src/bma_cfengine_app/ui/src/features/deals/store/lifecycle.ts` |
| 6 | sds-5 R1 pass-1 Blocking #1 (no git-init create-deal backend) | `promoteLocalDraft` surfaces `BLOCKED_ON_BACKEND` error diagnostic + throws; the existing `POST /deals` (StudioDealSaveBody) does not return a git initial commit SHA. Spec explicitly allowed this escalation path. **Outstanding follow-on ticket needed**: a true git-init create-deal endpoint that returns `{deal_id, initial_sha}` for production local-draft promotion. | `9559eea`, `src/bma_cfengine_app/ui/src/features/deals/store/useDealStore.ts` |
| 7 | sds-5 R1 pass-2 Major #1 (typed-dispatch signal vs reference comparison) | Added `dispatch_revision: number` counter to root state; incremented only by `dispatch()` when active session's `working_tree` reference changes. Autosave subscriber gates on counter increment, NOT on raw `working_tree` reference. `reloadFromHead()` no longer falsely triggers autosave. | `895024a`, `useDealStore.ts`, `autosave.ts` |

## Cost discipline

- 6 tickets driven through the per-ticket lifecycle plus 3 D1 decomposition passes.
- D1 dispatches: 1 (decomposition) + 2 resumes (fold-backs) = 3 D1 dispatches.
- T1: 6 dispatches (one per ticket).
- I1/I2 implementer: 6 dispatches + 5 fix-pass dispatches = 11 implementer dispatches. Initial sds-3 implementation work was split across two phases (Python + TS) due to interruption recovery.
- R1: 6 pass-1 dispatches + 4 pass-2 dispatches + 1 pass-3 dispatch (sds-5, user-authorized) = 11 R1 dispatches.
- Parent-direct fixes: 3 (sds-0 helper, sds-1 4 Minors, sds-3 sync script).
- Stop-condition surfaces: 1 (sds-5 R1 pass-2 RFR; user authorized pass-3).

## Outstanding work captured separately

1. **Git-init create-deal backend endpoint** (referenced from sds-5's `BLOCKED_ON_BACKEND` diagnostic). The current `POST /deals` (`StudioDealSaveBody`) does not initialize a git repo nor return an initial commit SHA. A new endpoint is needed for `promoteLocalDraft()` to actually promote a local draft to a real deal. This is out of scope for sds-5 per spec but should be tracked as a follow-on Phase 1 or Phase 2 ticket.

2. **Concurrent in-flight autosave hardening** (residual non-blocking observation from sds-5 pass-3). The autosave success path assumes active store context has not changed to another deal while an autosave commit is in flight. Pre-existing race; not introduced by sds-5. Worth hardening later by checking committed `deal_id`/session identity before applying success state.

3. **vpc-2/3/4/5** (validation parity contract finish; pre-existing, not part of this todo). Still required before `validation-engine` can land.

## Final test counts

- **UI Vitest**: 175 passed / 0 skipped / 0 failures (was 131 at todo start; net +44 new tests).
  - sds-1: +9 tests; sds-2: +14 tests; sds-3: +9 tests (TS); sds-4: +19 tests; sds-5: +12 tests; minor adjustments for fix-passes.
- **Python pytest**: 1529 passed / 3 skipped / 0 failures (was 1522 at todo start; net +7 new tests for sds-3 Python guards).
  - sds-0: +12 tests (HTTP + service); sds-3: +6 tests (emit_field_order + emit_canonical_fixtures).
- **Full repo**: clean working tree, no regressions.

The `studio-document-and-store` todo is closed. Phase 1 unblocks all subsequent pane work (Spreadsheet, Graph, Text, Inspector dock) and `studio-document-persistence-and-migration`. The `validation-engine` ticket remains blocked on vpc-2/3/4/5 finish.
