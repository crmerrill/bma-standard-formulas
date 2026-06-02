# R1 Review (Pass 2) — `studio-document-and-store` decomposition

**Reviewer**: gpt-5.5-extra-high (R1 tier; separate invocation; read-only; pass-2 fresh from pass-1 reviewer)
**Date**: 2026-06-01
**Decomposition under review**: `docs/architecture/tickets/phase1/studio-document-and-store.md` (post-D1-fold-back)
**Pass-1 review**: `docs/architecture/tickets/phase1/studio-document-and-store.r1-review-pass1.md`
**Verdict**: RETURN-FOR-REVISION

## Audit of pass-1 findings

| Finding | Pass-1 category | Pass-2 status | Where it lives now |
|---|---|---|---|
| B1 (commit endpoint extension) | Blocking | PARTIAL | `sds-0-commit-endpoint-extension` AC 1-5; `sds-4` AC 5; `sds-5` AC 1 |
| B2 (createEphemeralSession) | Blocking | CLOSED | `sds-2-document-session-model` AC 3; tests `test_createEphemeralSession_*` |
| C1 (round-trip harness) | Critical | PARTIAL | `sds-3-compile-canonical-serialization` AC 7; files `scripts/emit_canonical_fixtures.py`, `compile.roundtrip.test.ts` |
| C2 (field-order propagation) | Critical | CLOSED | `sds-3` AC 2, 6; tests `test_emit_field_order_*`; CI drift guards |
| C3 (Apply conflict path) | Critical | CLOSED | `sds-4-patch-lifecycle-and-http-integration` AC 2b / AC 3; tests `test_apply_conflict_*` |
| C4 (diagnostics slot) | Critical | CLOSED | `sds-2` AC 1, 5; `diagnostics-types.ts`; tests `test_setDiagnostics_*`, `test_diagnostic_payload_shape_matches_python_envelope` |
| C5 (exactly one zundo entry) | Critical | CLOSED | `sds-4` AC 2a; test `test_apply_success_path_appends_exactly_one_zundo_entry_via_pause_resume` |
| M1 (DocumentSession field precision) | Major | CLOSED | `sds-2` AC 1; tests `test_document_session_type_pins_all_field_shapes_with_literal_precision`, `test_branch_name_brand_rejects_invalid_slug_matches_irvc1_regex` |
| M2 (zundo-per-session architecture) | Major | PARTIAL | `sds-2` AC 4; Risk Note; tests `test_zundo_per_session_instance_isolated_between_sessions`, `test_active_session_switch_does_not_emit_temporal_entry` |
| M3 (DealAction discriminated union) | Major | CLOSED | `sds-1-store-foundation-and-deps` AC 3; tests `test_unknown_action_type_fails_compile_via_never_guard` |
| M4 (DealState structural mirror) | Major | CLOSED | `sds-1` AC 2; tests `test_fixture_deal_json_parses_into_working_tree_without_field_renames` |
| M5 (fixture enumeration) | Major | PARTIAL | `sds-3` AC 7-8; fixture-count parity guard |
| M6 (409 force/reload UX) | Major | CLOSED | `sds-4` AC 5; tests `test_commit_409_conflict_sets_conflictState_*`, `test_forceCommit_*`, `test_reloadFromHead_*` |
| M7 (explicit irvc dependencies) | Major | CLOSED | Mermaid graph edges; `sds-3`, `sds-4`, `sds-5` Dependencies |
| M8 (sessionStorage recovery contract) | Major | CLOSED | `sds-5-autosave-and-draft-persistence` AC 3; tests restore-vs-discard branches |
| M9 (round-trip test path/runtime) | Major | CLOSED | `sds-3` Files affected; `compile.roundtrip.test.ts`; `scripts/emit_canonical_fixtures.py` |
| M10 (multiple ephemeral sessions) | Major | CLOSED | `sds-2` AC 2-4; test `test_multiple_ephemeral_sessions_coexist_with_independent_mutations` |
| m1 (pre-nest main session) | Minor | CLOSED | `sds-1` Scope and AC 2 |
| m2 (positive non-canonicalization test) | Minor | CLOSED | `sds-3` AC 5; test `test_compile_does_not_auto_canonicalize_fragmented_multi_target_rules` |
| m3 (debounce interval) | Minor | CLOSED | `sds-5` AC 1; tests `test_debounced_autosave_fires_single_commit_at_2000ms_*`, `test_action_burst_*` |
| n1 (Mermaid graph irvc edges) | Nit | CLOSED | Mermaid graph includes `irvc -> sds-3`, `irvc -> sds-4`, `irvc -> sds-5`, plus `irvc -> sds-0` |

**B1 PARTIAL**: `sds-0` correctly adds the missing endpoint-level concept (`payload` + `branch`) and makes `sds-4` / `sds-5` depend on it, but it does not close cleanly against the landed backend. `sds-0` AC 4 says the endpoint passes `commit_target=branch` to `GitService.commit_deal(...)`, while the landed `GitService.commit_deal` signature has no `commit_target` / branch parameter and writes `refs/heads/main`. `sds-0` Files affected only list `src/bma_cfengine_app/api/routers/deals.py` plus endpoint tests, so the required service-level branch-target extension is out of scope even though the AC requires it. This keeps the pass-1 Blocking finding partially open: committing a supplied payload to an ephemeral branch is still not implementable by following the ticket as written.

**C1 / M5 PARTIAL**: The fold-back picks the right high-level mechanism (Python emits canonical fixtures; Vitest reads them), and it enumerates the current minimum fixture set. However, the repo's current fixture directories are builder-based (`tests/fixtures/fnr_2006_018/deal_definition.py`, plus `ginniemae_2025_203`, `verus_2024_9`, `cc_series_test`, `ford_2024_c` package builders) and there are currently no `tests/fixtures/*/deal.json` files. `sds-3` AC 7 says `scripts/emit_canonical_fixtures.py` handles directories "exporting a `DealDefinition`" or containing `deal.json`, but the Vitest contract still reads each `<fixture>/deal.json`, and the parity guard counts only `deal.json` vs `deal.canonical.json`. The ticket must explicitly say whether the emitter materializes `<fixture>/deal.json` for builder-based fixtures, or whether the TS test reads a generated source artifact with a different name. As written, the explicit minimum fixtures can produce `deal.canonical.json` without a corresponding `deal.json`, making the round-trip harness under-specified.

**M2 PARTIAL**: The fold-back sanctions option (a), which is the right architectural choice. The remaining issue is store-shape consistency. `sds-2` AC 1 says `DocumentSession` exactly includes `zundo_history: TemporalState<DealState>`, AC 2 says the store holds `sessions: Record<string, DocumentSession>`, while AC 4 says the store shape is `sessions: Record<string, { state: DocumentSession; temporal: TemporalState<DealState> }>` or equivalent. That gives implementers two incompatible access patterns (`sessions[id].working_tree` vs `sessions[id].state.working_tree`, `zundo_history` vs `temporal`) across `sds-1` selectors/actions and `sds-2` tests. The observable isolation tests are good, but the decomposition should pick one concrete shape or explicitly update all selectors/actions/tests to the wrapper shape.

## New findings introduced by the fold-back

### Critical

1. **(sds-0, AC 4; Files affected)** — The commit endpoint extension requires a `GitService` API extension but does not scope it. The landed service writes commits to `refs/heads/main`; `sds-0` AC 4 calls for `commit_target=branch`, which does not exist. Add `src/bma_cfengine_app/orchestrator/deals/git_service.py` to Files affected, extend `commit_deal(..., commit_target: str = "main")` or an equivalent branch-target parameter, and add service-level tests proving non-main branch commits advance only the target branch. Without this, `sds-0` cannot satisfy its own ephemeral-branch commit AC.

### Major

1. **(sds-3, AC 7-8)** — Builder fixtures are not materialized for the Vitest round-trip harness. Current fixture coverage is builder-based, not `deal.json`-based. The emitter must either write both `<fixture>/deal.json` and `<fixture>/deal.canonical.json` for builder fixtures, or the TS round-trip test must consume an explicitly generated source artifact. The parity guard should cover the explicit builder fixture set as well as discovered `deal.json` fixtures.

2. **(sds-1, AC 2; sds-3 dependency graph)** — `sds-1` introduces a hidden forward dependency on `sds-3` by requiring an exhaustive structural assertion "against the Python-emitted field-order manifest from `sds-3`, deferred there." `sds-1` is Layer 0 and unblocks `sds-2`; `sds-3` depends on `sds-2`. Move that exhaustive manifest-based assertion to `sds-3`, or add a separate pre-`sds-1` manifest ticket. `sds-1` should not have a test contract that cannot pass until a downstream ticket lands.

3. **(sds-0, AC 1; landed irvc-4 surface)** — `sds-0` says existing `CommitRequest.parent_sha: str` is unchanged, but the landed irvc-4 endpoint has already fixed `parent_sha` to `str | None = None`. If implementers follow the decomposition literally, they can regress the irvc-4 nullable-parent fix. AC 1 should preserve the landed field exactly: `parent_sha: str | None = None`.

4. **(sds-0, AC 3 / AC 5; sds-4 AC 5)** — The 409 response field is renamed to `current_head_sha`, but legacy irvc-4 returns FastAPI `detail.head_sha` and `sds-0` AC 5 requires byte-identical legacy behavior when `payload` and `branch` are omitted. Either preserve `detail.head_sha` and have the UI client read that field, or include a backward-compatible envelope that keeps existing tests passing while adding `current_head_sha`. As written, `sds-0` AC 3 and AC 5 conflict.

5. **(sds-2 / sds-5, missing store field)** — `deal_id` is used by `createEphemeralSession` HTTP calls, autosave commit URLs, sessionStorage keys, and `local_draft_*` promotion, but no ticket pins where `deal_id` lives in the store. `DocumentSession` does not include `deal_id`, and `useDealStore` ACs only mention `sessions` and `activeSessionId`. Add a root store field such as `deal_id: string` plus initialization/update semantics, or explicitly include `deal_id` in the session model if local drafts are session-scoped. This must be pinned before `sds-5` AC 3-4 can be implemented unambiguously.

6. **(sds-2, AC 1 / AC 4; sds-1 selectors)** — The per-session zundo fold-back leaves incompatible access paths. Pick one shape: either `sessions: Record<string, DocumentSession>` where `DocumentSession.zundo_history` is the temporal handle, or `sessions: Record<string, { state: DocumentSession; temporal: TemporalState<DealState> }>` and update all earlier selectors/actions to use `.state.working_tree`. The current "or equivalent" clause is too loose for a multi-ticket decomposition where earlier tests will compile against a concrete shape.

### Minor

1. **(sds-0, AC 2)** — The serialization sentence is internally redundant: "writes `json.dumps(payload, ...)` (using ... `model_dump_json(indent=2)`)". The AC should say the endpoint validates with `DealDefinition.model_validate(payload)` and commits the exact UTF-8 bytes of `validated.model_dump_json(indent=2)` (or the current Pydantic canonical serializer). That avoids implementers accidentally double-serializing or using Python `json.dumps` ordering instead of Pydantic's output.

## Verdict rationale

The fold-back substantially improves the decomposition and closes most pass-1 findings at the right level of precision. However, the pass-1 Blocking commit-endpoint finding is only partially closed because `sds-0` requires a backend service capability that is not scoped, and the round-trip harness still has an input-materialization gap for the actual builder-based fixture set. These are spec defects, not implementation nits, so this pass cannot approve the ticket set for T1.

## Sign-off recommendation

RETURN-FOR-REVISION — Blocking/Critical findings still open: fix `sds-0` by explicitly extending `GitService.commit_deal` for branch-target commits and preserving landed irvc-4 compatibility, and fix `sds-3` by materializing or otherwise explicitly sourcing builder-based fixtures for the Vitest round-trip harness.
