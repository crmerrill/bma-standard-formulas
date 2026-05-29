# Structuring Studio Redesign — Phase 0 Architectural Review, Pass 2

**Reviewer**: gpt-5.5-extra-high, pass 2, independent of plan author
**Plan reviewed**: repo commit `66b2472`; `/Users/crmerrill/.cursor/plans/structuring_studio_redesign_ec1d8b3d.plan.md`
**Prior review path**: `docs/architecture/structuring_studio_redesign_phase0_review.md`
**Date**: 2026-05-29
**Verdict**: **RETURN-FOR-REVISION**

## Executive Summary

- The revision materially improves the plan: most sequencing, IR runtime-contract, solver UX, fixture-scope, Storybook-enforcement, and AI-checker findings from pass 1 were folded back with concrete line-level plan text.
- Phase 1 still should not open. The new Phase 1 foundation is now dominated by a real-git-per-deal persistence model, but the plan does not yet specify the operational contract required to ticket it safely: scale, backup, replication, repo lifecycle, libgit2 fallback, merge strategy, branch garbage collection, and export non-leakage.
- The Studio sidecar contract is internally inconsistent. The plan says the sidecar is DB-only, says `sidecar.json` is tracked by git, says AI provenance lives in commit metadata, but the projection matrix and AI-off contract still mention sidecar AI provenance.
- The IR byte-idempotency invariant is stronger than current code and stronger than the plan's own compile step can support. Current `load_deal(...)` validates through Pydantic migrations, and current `save_deal(...)` emits `model_dump_json(...)`; neither preserves input bytes, absent-vs-default presence, or legacy accepted payload shape.
- The AI writer branch flow remains under-specified at the store boundary. The plan says writer calls mutate the store and validate after each tool call, but preview mode says the persistent store stays at `main` while the branch tip renders read-only. It never states which document validation sees during repair turns.
- Several prior findings are only partially resolved, chiefly `B2`, `B3`, `C3`, `M2`, `M8`, `M11`, and `n1`.
- New findings below are not polish. `B5`, `B6`, and `B7` block Phase 1 ticket decomposition because they affect the first foundation tickets.
- No new user-level open questions are needed; the remaining issues are plan-amendment requirements.

## Audit of Prior Findings

| ID | Status | Evidence | Gap if any | Recommended Action |
|---|---|---|---|---|
| B1 | RESOLVED | Plan defers `SHARED_TRIGGER_BRANCHABLE` to Phase 3 in todos lines 24-27, linter text lines 1159-1164, and Phase 1 sequencing lines 1505-1507. | None. | Keep Phase 1 limited to Proposal-A-safe diagnostics. |
| B2 | PARTIALLY RESOLVED | Persistence and migration are now detailed at lines 193-206, with `ir-version-control-foundation` and `studio-document-persistence-and-migration` todos at lines 13-17. Current `deal_store.py` has the old dual path: `save_deal(...)` lines 53-98 and `save_studio_ir(...)` lines 163-209. | The sidecar location/export/versioning story contradicts itself, and git operations are under-specified operationally. | Resolve `B5` and `B7`; then this becomes resolved. |
| B3 | PARTIALLY RESOLVED | The field-class projection matrix exists at lines 432-444. | The matrix conflicts with the "What lives where" table: line 439 puts notes, AI provenance, tags, and scratchwork into sidecar metadata, while lines 169-174 move notes to IR, provenance to git metadata, and scratchwork to the uncommitted working tree. | Rewrite the projection matrix to match the minimized sidecar contract. |
| B4 | RESOLVED | Per-proposal runtime contracts are now explicit for A-E at lines 1061-1133; Proposal E is split at lines 1104-1133. Current `ir.py` still has flat `RuleNode`/`DealDefinition.waterfall_rules` lines 333-425 and current `runtime.py` compiles flat rules at lines 733-784, so the plan correctly treats B-E as real engine work. | None for Phase 0. | Keep backend golden tests as prerequisites. |
| C1 | RESOLVED | Formal consolidation predicates and negative tests are specified at lines 1145-1158. | None. | Keep no-auto-fix outside the predicate. |
| C2 | RESOLVED | Phase 2 explicitly excludes `WaterfallBranch`, `AggregateGroupDef`, and loss-treatment entities until Phase 3 at lines 459 and 1507. | Some diagrams still mention branch nodes; see `m5`. | Clean residual diagram labels. |
| C3 | PARTIALLY RESOLVED | Validation parity contract exists at lines 361-369. | The plan still lets the ticket choose "generator OR guard" at line 368, which defers a core architectural decision for a Phase 1 dependency. | Pick the mechanism, or specify the minimum viable guard contract in enough detail to implement. |
| C4 | RESOLVED | Live preview spike is now a Phase 1 prerequisite with target sizes, latency, cancellation, degraded mode, and fixture path at lines 662-675. | The fallback narrative needs a vision update if the spike rejects always-on preview; see `M13`. | Add the decision gate text from `M13`. |
| C5 | RESOLVED | Tool count and token budget are reconciled at lines 835-854, with a manifest-budget snapshot test. | None. | Keep registry-generated measurement. |
| C6 | RESOLVED | Solver availability moves from filtering to recommendation at lines 969-975 and todos lines 81-84. Current UI still filters by `suitable_for_families` in `SolverTemplateCards.tsx` lines 99-109, so the plan correctly identifies the change. | None. | Implement replacement metadata and UI tests. |
| C7 | RESOLVED | Domain-editor exception for PAC schedules, trigger thresholds, and Z release is specified at lines 1249-1258. | None. | Keep no-IR-leakage acceptance. |
| C8 | RESOLVED | Proposal E is split into WRITEDOWN, NOTIONAL_HOLD, and writeup at lines 1104-1133. Current runtime calls `pay_writedown(...)` against balance at `runtime.py` lines 2825-2833, so the split is justified. | None. | Keep separate golden fixtures. |
| M1 | RESOLVED | Checker inputs now include transcript, compiled IR diff, diagnostics, and structure summary at lines 887-903. | None. | Add adversarial fixtures as planned. |
| M2 | PARTIALLY RESOLVED | Minimum RAG controls are present at lines 946-955. | Governance is explicitly deferred, so ownership, citations, review workflow, and stale-entry policy remain open for AI Phase work. | Add a "must decide before AI writer beta" gate. |
| M3 | RESOLVED | Non-convergence has max repair attempts, branch deletion, failure UI, and partial acceptance at lines 746-759. | Branch/store state remains under-specified; see `C9`. | Resolve `C9`. |
| M4 | RESOLVED | Capability tiers and fallbacks are specified at lines 1386-1402. | None. | Keep substitution logging. |
| M5 | RESOLVED | `MetricRegistry` plus adapters replace the mega-picker at lines 566-575 and 602-615. | None. | Keep adapter size/reuse checks. |
| M6 | RESOLVED | Storybook CI gates are now specified at lines 617-629. | Infra cost/flakiness is not acknowledged; see `M12`. | Add operational limits for screenshot/a11y CI. |
| M7 | RESOLVED | Solver inventory table exists at lines 1274-1290 and correctly notes only `auto_tieout_carry` is registered today. Code confirms only `_auto_tieout_template()` is in `_REGISTERED_TEMPLATES` at `solver_templates.py` lines 156-160. | None. | Keep per-template backend tests. |
| M8 | PARTIALLY RESOLVED | Patch lifecycle is specified at lines 330-339, and solver todo line 82 mentions Apply/Discard/zundo. | The detailed lifecycle says preview is a read-only branch view while zundo is separate; it does not specify how Apply becomes exactly one undoable store transaction or how auto-save treats preview state. | Add store/zundo/commit transaction semantics for Apply and Discard. |
| M9 | RESOLVED | Scenario execution contract is explicit at lines 1308-1317. `scenario_runner.md` confirms batch runner is not implemented at lines 34-45 and 89-95. | None. | Keep scheduled/actual/paired integration tests. |
| M10 | RESOLVED | Fixture classification ticket exists at lines 28-29 and round-trip scope is narrowed at lines 1186-1186. The fixture directory currently contains a small set including FNR, Ford, Verus, GNMA, and CC test packages, not every named prospectus. | None. | Produce `tests/fixtures/STATUS.md`. |
| M11 | PARTIALLY RESOLVED | AI-off contract is detailed at lines 912-923. | Line 919 still says "sidecar's AI provenance slot" despite lines 170 and 198 saying AI provenance lives in git commit metadata, not the sidecar. | Remove sidecar provenance references and define commit-metadata suppression in AI-off mode. |
| m1 | RESOLVED | Plan names canonical endpoint `GET /deals/{id}/solver-templates` and deprecates the slash variant at lines 1274-1276. Current `solver_ux_design.md` still has the old path at lines 185-189, but the plan gives a direct doc update instruction. | None for plan; doc still needs edit during implementation. | Update `solver_ux_design.md` in the relevant ticket. |
| m2 | RESOLVED | Copy migration is split into help, status, diagnostics, and empty-state classes at lines 105-106. Code confirms the status copy in `PropertyPanel.tsx` lines 1029-1034 and help-ish copy at lines 1138-1146 and 1196-1198. | None. | Keep copy-class audit. |
| m3 | RESOLVED | Cutover todo includes stale Blockly-copy audit at lines 107-108. Current stale copy is in `IrPreviewPanel.tsx` lines 58-60. | None. | Keep Playwright copy checks. |
| m4 | RESOLVED | Token enforcement scope and legacy boundary are specified at lines 548-550 and 1534-1535. | None. | Keep Studio-scoped lint. |
| n1 | PARTIALLY RESOLVED | Most text now says five layers, e.g. lines 558-600. | The non-negotiable principles still say "four-layer component catalog" while listing five conceptual layers at line 119. | Replace the remaining "four-layer" wording. |
| n2 | RESOLVED | Cached vs uncached token budget is separated at lines 835-854. | None. | Keep snapshot test. |
| n3 | RESOLVED | CMBS/CLO/Equipment are deferred entirely at lines 1022 and 1534. | None. | Keep unsupported-class behavior explicit. |
| n4 | RESOLVED | Objective checklist is specified at lines 1442-1456. | None. | Require checklist artifact per ticket. |

## New Findings

### B5. Sidecar, provenance, and export contracts are internally inconsistent

- **Severity**: Blocking
- **Dimension**: Architectural coherence / Unenumerated risks
- **Plan section + lines**: Overview line 3; "What lives where" lines 162-176; persistence lines 193-203; projection matrix lines 432-444; AI-off lines 912-920.
- **Issue**: The plan has at least four incompatible sidecar stories:
  - line 3 and lines 162-176 say the sidecar is minimal and DB-only;
  - line 198 says `sidecar.json` is tracked by git so rollback follows IR rollback;
  - line 170 says AI provenance lives in git commit metadata, not sidecar;
  - line 439 says sidecar metadata includes per-entity notes, AI provenance, tags, and scratchwork;
  - line 919 says the "sidecar's AI provenance slot" stays empty in AI-off mode.

  This cannot be ticketed safely. It affects persistence, export, rollback, AI-off behavior, migration, and security review.
- **Recommended fix**: Choose one contract and propagate it everywhere. Minimum acceptable contract: sidecar fields, storage location, whether it is git-tracked or DB-versioned, export exclusion mechanism, AI provenance location, AI-off suppression behavior, and migration mapping from legacy `studio_v{N}.json`.
- **Test/acceptance implication**: Add tests proving export contains only `deal.json`; sidecar load failure does not affect IR; AI-off creates no AI commit metadata or sidecar provenance; and legacy provenance migrates exactly once to the chosen location.

### B6. The byte-identical IR round-trip invariant is not implementable as written

- **Severity**: Blocking
- **Dimension**: IR-evolution feasibility / Architectural coherence
- **Plan section + lines**: Todos line 12; compile step lines 178-182; IR idempotency lines 208-224.
- **Issue**: The plan requires byte-identical round-trip over every fixture and even preserves absent-vs-null/default presence at lines 214-215. But line 180 says compile "canonicalizes ordering" and "applies multi-target consolidation," which directly contradicts lines 210-216 and 228-230 saying no transformation and no implicit canonicalization. Current code also cannot preserve bytes: `load_deal(...)` parses JSON and calls `DealDefinition.model_validate(migrate_deal_payload(payload))` in `deal_store.py` lines 121-122, and `save_deal(...)` serializes the Pydantic model with `model_dump_json(indent=2)` at lines 78-83. That path loses original formatting, key order outside model declaration, absent-vs-default presence, and legacy pre-migration input form.
- **Recommended fix**: Either weaken the invariant to semantic/stable-canonical JSON equality after explicit migration, or specify a raw-JSON AST/presence-map store that preserves unknown accepted shapes and absent/null/default provenance. Also remove "applies multi-target consolidation" from the compile step unless it is explicitly user-triggered.
- **Test/acceptance implication**: Round-trip tests must distinguish three cases: raw imported bytes preserved before migration, migration commit produces deterministic canonical bytes, and post-migration save-without-edit is byte-identical to the previous committed `deal.json`.

### B7. The real-git-per-deal foundation is not operationally ticket-safe

- **Severity**: Blocking
- **Dimension**: Unenumerated risks
- **Plan section + lines**: Todo line 14; IR version control lines 232-269; flow lines 271-321.
- **Issue**: The revision elevates git from an implementation idea to a Phase 1 prerequisite, but the operational envelope is missing. It does not specify expected number of deal repos, repo directory lifecycle, backup/restore, multi-region replication, object-store compatibility, branch/tag retention, garbage collection, corruption recovery, CI/test isolation, repository locking, or how `.git` metadata is protected from export and tenant leakage. It names `pygit2` as default at lines 238-241, but `pyproject.toml` current dependencies lines 28-35 do not include any git library, and libgit2 is a native dependency with packaging implications on local dev, CI, and deployment. The merge strategy is deferred between JSON merge driver and application-level merge at lines 260-265 even though Phase 1 depends on it.
- **Recommended fix**: Add a Phase 1 operational design subsection before ticketing: dependency decision and install story, repo-per-deal scale assumptions, backup/restore contract, lock/concurrency contract, GC/retention policy, export hardening, merge strategy chosen for v1, and rollback/corruption playbook. Prefer application-level typed merge over `gitattributes` JSON merge driver unless the plan can prove driver installation and server execution are portable.
- **Test/acceptance implication**: Add integration tests for concurrent saves, branch create/delete/GC, export excluding `.git` and sidecar, restore from backup, and fallback from `pygit2` to CLI in an environment without libgit2.

### C9. AI writer branch flow does not specify which store state validation sees

- **Severity**: Critical
- **Dimension**: AI architecture
- **Plan section + lines**: AI writer todo line 58; version flow lines 273-280; patch lifecycle lines 330-339; pipeline lines 717-744; non-convergence lines 746-759.
- **Issue**: The plan says each AI tool call mutates the Studio Document store and validation runs after every action. It also says each AI turn commits passing calls to `ai/turn-{id}` and that preview mode renders the branch tip in a read-only view while the persistent store remains at `main` HEAD. It never defines the active mutable document for repair turn 3. If validation runs against `main`, the writer never sees cumulative AI work. If validation runs against the branch working tree, the store is no longer simply "persistent store remains at main." If there is a separate branch-scoped store, its lifecycle and merge into main are missing.
- **Recommended fix**: Define `DocumentSession` or equivalent: branch name, base SHA, working tree state, validation target, commit target, and UI rendering mode. State explicitly that AI writer repair validates against the ephemeral branch tip plus the latest uncommitted tool action, while `main` store remains untouched until Apply.
- **Test/acceptance implication**: Add tests for a three-tool AI repair sequence where tool 3 depends on tool 1; validation must see cumulative branch state and `main` must remain unchanged until Apply.

### C10. Diagnostic catalog generator/guard is still a deferred architecture decision

- **Severity**: Critical
- **Dimension**: Architectural coherence
- **Plan section + lines**: Validation parity lines 361-369; validation todos lines 19-23.
- **Issue**: The plan says "Either a generator emits a TS catalog from Pydantic validators, OR a pre-commit guard fails..." at line 368. These are materially different architectures. A generator from Pydantic validators is non-trivial because validators contain Python code, conditional paths, and formatted messages. A guard is cheaper but only enforces documentation, not parity. The ticket cannot estimate scope or acceptance until this is chosen.
- **Recommended fix**: Pick guard-first as v1 unless the plan can specify an actual generator design. Define exact guard inputs, required catalog fields, how Python validators declare diagnostic codes, and how TS worker ownership is checked.
- **Test/acceptance implication**: Add a failing test where a new Python diagnostic code without catalog entry fails CI; add parity fixtures only for codes marked `owner=worker` or `owner=both`.

### C11. Commit-per-tool-call and discarded-branch retention are not bounded

- **Severity**: Critical
- **Dimension**: AI architecture / Unenumerated risks
- **Plan section + lines**: AI writer todo line 58; AI flow lines 273-280; non-convergence lines 752-759.
- **Issue**: Every validated writer tool call becomes a commit. Long prospectus sessions, macro decomposition, and repair loops can create large commit graphs per deal. The plan says discarded branch commit blobs "can be retained" in `discarded_branches/` with default 7 days at line 756, but it does not define size caps, PII/prompt retention policy, GC, audit access, or whether tool-call transcripts embedded in commit messages survive branch deletion. This is a storage, privacy, and UX issue.
- **Recommended fix**: Define commit squashing/compaction rules, branch archive retention limits, maximum commits per AI turn, commit-message redaction policy, and GC schedule. Consider one commit per accepted AI turn plus internal transcript artifacts, rather than one permanent commit per tool call.
- **Test/acceptance implication**: Add tests that discarded AI branches are inaccessible after retention expiry, git GC does not remove applied history, and export never includes discarded transcripts.

### M12. Storybook CI cost and flakiness are unacknowledged

- **Severity**: Major
- **Dimension**: Unenumerated risks
- **Plan section + lines**: Storybook CI lines 617-629.
- **Issue**: The plan mandates story existence, Storybook build, axe scan, and screenshot regression for core variants. It does not specify CI time budget, browser/OS matrix, image artifact storage, screenshot thresholding, font rendering stabilization, OKLCH/color-management handling, or flake triage. Screenshot regression is especially prone to false positives across text rendering and color spaces.
- **Recommended fix**: Add an infra contract: one pinned browser, pinned fonts, deterministic theme tokens, screenshot threshold, artifact retention, quarantine process, and which stories are screenshot-tested versus axe/build-only.
- **Test/acceptance implication**: CI acceptance should include a measured max runtime and documented artifact path/retention.

### M13. Live-preview rejection path conflicts with the stated vision

- **Severity**: Major
- **Dimension**: Architectural coherence / Sequencing
- **Plan section + lines**: Vision/reference apps lines 130-136; live-preview spike lines 662-675.
- **Issue**: The plan's Vision sells Observable/Hex-style instant propagation and calls live preview the biggest UX leap at lines 650-660, but the spike may reject always-on preview at lines 669-675. If it rejects, the plan does not say whether Phase 4 still satisfies the redesign vision, whether an on-demand preview is acceptable, or which user journeys change.
- **Recommended fix**: Add a decision gate: if the spike rejects always-on preview, amend the Vision and Phase 4 acceptance before opening `live-preview-cashflow`.
- **Test/acceptance implication**: The spike deliverable must include either performance evidence for always-on preview or revised UX acceptance for on-demand/degraded preview.

### M14. "Every primitive callable" is not reconciled with CC-specific defaults

- **Severity**: Major
- **Dimension**: Asset-class scope
- **Plan section + lines**: Principles lines 121 and 956-976; toolbox lines 780-793.
- **Issue**: The plan says every primitive is callable in every asset class, but tools like `add_principal_funding_account(...)` and `add_trigger_excess_spread(...)` are explicitly CC-specific at lines 783 and 792. That may be fine, but the plan does not distinguish "callable" from "well-defaulted outside its home class." A manual structurer or AI writer can call a CC-specific tool in Auto ABS and silently get CC assumptions like rolling three-month excess spread or controlled-accumulation minimum schedules.
- **Recommended fix**: Add metadata per tool: `available_for=ALL`, `recommended_for`, `requires_explicit_args_outside`, and `cross_class_warning`. CC-specific helpers should require explicit non-CC confirmations or route to generic primitives.
- **Test/acceptance implication**: Add tests that calling CC-specific primitives in non-CC classes produces info diagnostics and does not inject hidden CC defaults without explicit arguments.

### M15. Phase 0 independence is tier-based, not identity/family protected

- **Severity**: Major
- **Dimension**: Unenumerated risks
- **Plan section + lines**: Phase 0 lines 1478-1490; capability tiers lines 1386-1402.
- **Issue**: The per-ticket workflow requires cross-family review from the implementer, but Phase 0 only says an independent `gpt-5.5-extra-high` agent reviews the plan. It does not require a different parent chat, different model family from the plan author, or explicit evidence that the plan author and reviewer are not the same agent lineage. The current review instruction relies on process outside the plan.
- **Recommended fix**: Add Phase 0-specific independence criteria: reviewer must be a separate agent invocation, transcript linked, no plan-edit permissions, and either cross-family from plan author or explicitly logged single-family exception.
- **Test/acceptance implication**: Phase 0 closure artifact should include reviewer identity, model/tier, and independence attestation.

### M16. Scenario storage is outside the field-class and persistence model

- **Severity**: Major
- **Dimension**: Architectural coherence
- **Plan section + lines**: Field matrix lines 432-444; sidecar minimization lines 162-176; scenarios lines 1298-1317.
- **Issue**: Line 1306 says scenarios are "Stored as part of the Studio Document (UI-only) AND mirrored to the engine's run-input format." The field-class matrix does not include scenarios, and the sidecar is supposedly only layout overrides plus UI preferences. If scenarios are UI-only, they cannot live in the engine IR; if they are part of the Studio Document, persistence/export/versioning must classify them.
- **Recommended fix**: Add a `ScenarioSet` field class: storage location, export behavior, git/sidecar status, versioning, and round-trip invariant. Decide whether scenario sets are internal sidecar data, separate run-setup entities, or IR-adjacent but non-exported committed files.
- **Test/acceptance implication**: Add tests proving scenario edits persist, are included/excluded from export according to contract, and are pinned to run `commit_id`.

### m5. Phase 2 diagrams still advertise branch UI before branch IR exists

- **Severity**: Minor
- **Dimension**: Sequencing
- **Plan section + lines**: Structure diagram lines 405-421; spreadsheet/graph descriptions lines 446-467; Phase 2 clarification lines 459 and 1507.
- **Issue**: The plan correctly says Branches do not exist in Phase 2, but the diagram and pane descriptions still list Branches, Branch, and Case nodes without consistently marking them Phase 3. This reintroduces ambiguity for ticket authors.
- **Recommended fix**: Annotate Branch/Case/AggregateGroup in diagrams as "Phase 3+" or remove them from Phase 2 descriptions.
- **Test/acceptance implication**: Phase-dependency checklist should fail Phase 2 tickets that include Branch/Case UI.

### n5. One residual phrase still says solver templates are filtered by asset class

- **Severity**: Nit
- **Dimension**: Asset-class scope
- **Plan section + lines**: Honored feedback table lines 1372-1380.
- **Issue**: Line 1376 says solver templates are "filtered by asset class," contradicting lines 969-975 and 1274-1276, which correctly require recommendation ordering rather than filtering.
- **Recommended fix**: Replace "filtered by asset class" with "ordered by asset-class recommendation."
- **Test/acceptance implication**: None beyond `C6`.

## Findings by Dimension

| Dimension | Findings |
|---|---|
| Architectural coherence | `B3` partially resolved; `C3` partially resolved; `M8` partially resolved; `B5`; `B6`; `C10`; `M13`; `M16`; `n1`; `m5` |
| IR-evolution feasibility | `B6`; prior `B4`, `C1`, and `C8` are resolved but depend on preserving their backend-test gates |
| AI architecture | `M2` partially resolved; `M11` partially resolved; `C9`; `C11` |
| Asset-class scope | `M14`; `n5`; prior `C6` and `n3` are resolved |
| Solver UX | `M8` partially resolved; prior `C7`, `M7`, and `m1` are resolved |
| Sequencing | `m5`; prior `B1`, `C2`, and `M9` are resolved |
| Unenumerated risks | `B2` partially resolved; `B7`; `C11`; `M12`; `M15` |

## Recommendations for Fold-Back

1. Rewrite the Studio sidecar contract once, consistently: fields, storage location, git/DB status, export exclusion, provenance location, AI-off behavior, and migration mapping.
2. Resolve the byte-idempotency contradiction by either weakening the invariant to canonical post-migration JSON or specifying a raw-byte/presence-preserving store architecture.
3. Add an operational design for real-git-per-deal before Phase 1: dependency, scale, backup/restore, locking, merge strategy, export hardening, retention, and GC.
4. Define branch-scoped document sessions for AI and solver proposals, including which store validation sees and how Apply/Discard interact with zundo and auto-save.
5. Pick the diagnostic catalog enforcement mechanism for v1; do not leave generator-vs-guard to the implementation ticket.
6. Add commit graph and discarded-branch retention limits, including prompt/tool-call metadata redaction and GC.
7. Add Storybook CI operational limits: pinned browser/fonts, thresholds, artifact retention, flake policy, and runtime budget.
8. Add a live-preview spike decision gate that amends the vision and Phase 4 acceptance if always-on preview is rejected.
9. Add tool metadata that distinguishes universal availability from class-specific defaults, especially for CC-specific primitives.
10. Classify ScenarioSet persistence in the field-class matrix and export/versioning model.
11. Add Phase 0-specific independence criteria to the multi-agent workflow.
12. Clean residual wording: remaining "four-layer" phrase, Branch/Case Phase 2 diagram leakage, and "filtered by asset class" phrasing.

## Open Questions for the User

None. The six prior open questions have been answered in the revised plan. The remaining work is plan correction, not user direction.
