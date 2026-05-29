# Structuring Studio Redesign — Phase 0 Architectural Review

**Reviewer**: gpt-5.5-extra-high (independent of implementer)  
**Plan reviewed**: structuring_studio_redesign_ec1d8b3d.plan.md  
**Date**: 2026-05-29  
**Verdict**: RETURN-FOR-REVISION

## Executive summary

- The plan is directionally strong, but Phase 1 cannot open yet because the sequencing makes Phase 1 depend on IR constructs that are not scheduled until Phase 3, especially `WaterfallBranch`, canonical branch consolidation, and multi-target PAC/TAC consolidation.
- The Studio Document contract is under-specified for persistence, migration, import/export, sidecar durability, and cross-view losslessness. Existing storage persists versioned engine IR and unvalidated Studio snapshots, but there is no migration path for the new richer document.
- The IR-evolution section treats several runtime changes as small schema additions. `ComputedAmountNode`, `WaterfallBranch`, `AggregateGroupDef`, and `loss_treatment=NOTIONAL_HOLD` each require explicit engine semantics, validation, fixtures, and compatibility gates.
- The AI architecture has the right high-level separation, but the tool manifest, checker semantics, RAG versioning, provider fallback, and non-convergence path are not yet precise enough to ticket safely.
- The solver and asset-class sections contain contradictions with current code: current solver template UI filters by product family, only one backend template is registered, and the proposed generic `MetricPicker` does not cover PAC schedule building or trigger-threshold tuning without additional domain editors.

## Findings by severity

### Blocking

1. **[B1] Phase 1 canonicalization depends on Phase 3 IR additions.**
   - **Dimension**: Sequencing
   - **Plan section**: `Rule grouping, normalization, and the linter` (lines 800-831); `Implementation sequencing` (lines 1082-1088)
   - **Issue**: Phase 1 includes `rule-canonicalization-linter`, and the linter's second pass emits `WaterfallBranch` quick fixes. `WaterfallBranch` is not scheduled until Phase 3, and it does not exist in the current Pydantic IR (`src/bma_standard_formulas/deals/schemas/ir.py`) or runtime compiler (`src/bma_standard_formulas/deals/runtime.py`). A Phase 1 validator/linter cannot hold canonical branch form while the engine schema cannot parse or run that form.
   - **Recommended fix**: Split Phase 1 canonicalization into `canonicalization-framework` only, with Proposal A-only diagnostics if no schema change is needed. Move `WaterfallBranch` schema/runtime/compiler/validator support before any `SHARED_TRIGGER_BRANCHABLE` quick-fix can ship, or move Proposal C into Phase 1 as a dependency.
   - **Test / acceptance implication**: Add acceptance criteria that Phase 1 diagnostics never emit an action whose resulting document cannot pass Python `DealDefinition.model_validate(...)` and `run_deal(...)`.

2. **[B2] Studio Document persistence and migration are not defined.**
   - **Dimension**: Unenumerated risks
   - **Plan section**: `Studio Document ⊋ Engine IR` (lines 156-170); `e2e-and-cutover` todo (lines 105-106)
   - **Issue**: The plan says the Studio Document persists alongside compiled IR as a sidecar, but current persistence has two distinct paths: canonical `save_deal(...)` writes versioned `DealDefinition` JSON, and `save_studio_ir(...)` writes unvalidated `studio_vN.json` snapshots with an `ir` payload. There is no proposed sidecar schema, migration procedure, versioning policy, or first-open conversion for existing saved deals/sessionStorage drafts.
   - **Recommended fix**: Add a `StudioDocument` persistence subsection before Phase 1: schema version, storage location, migration from `studio_vN.json`, compile artifact contract, rollback behavior, and what happens when only engine IR exists.
   - **Test / acceptance implication**: Require migration tests for existing canonical deal versions, existing studio snapshots with Blockly workspace state, and session draft restore into a Studio Document without dropping opaque IR fields.

3. **[B3] The promised lossless inverse for all deterministic modalities is not well-defined.**
   - **Dimension**: Architectural coherence
   - **Plan section**: `The four authoring modalities` (lines 233-258); `Honored "things you like"` (lines 973-979)
   - **Issue**: The plan promises Studio Document ↔ Sheet / Graph / Text losslessness, but the Studio Document contains layout positions, notes, AI provenance, draft scratchwork, selection, and pinned views. The Text pane schema is generated from `ir-types.ts`, which is currently a structural subset of engine IR and has no fields for Studio-only document data. Graph auto-layout vs. user-position overrides are also not specified as a mergeable inverse.
   - **Recommended fix**: Define projection domains explicitly: engine-editable IR, Studio sidecar metadata, view-local layout, and draft scratchwork. State which fields each modality can view, edit, preserve, and round-trip, and define graph layout merge semantics for first-open auto-layout vs. user overrides.
   - **Test / acceptance implication**: Replace the blanket "lossless across all four modalities" claim with testable invariants per field class, including sidecar preservation tests and graph layout override tests.

4. **[B4] Proposals B-E under-enumerate engine-side work and cannot be ticketed as written.**
   - **Dimension**: IR-evolution feasibility
   - **Plan section**: `Land the proposed IR additions` (lines 786-795)
   - **Issue**: The plan lists `ComputedAmountNode`, `WaterfallBranch`, `AggregateGroupDef`, and `loss_treatment` as authoring additions, but each changes runtime execution semantics. Current validation accepts `deal_knobs.source_formulas` as valid sources, current runtime compiles a flat `waterfall_rules` list, current target resolution has no aggregate-group namespace, and `pay_writedown(...)` always decrements bond balance. Without explicit engine acceptance criteria, Phase 3 tickets will either be too large or will ship UI-only shapes that the runtime cannot evaluate.
   - **Recommended fix**: Add one runtime contract subsection per proposal: schema delta, runtime compiler behavior, validation behavior, migration behavior, output/trace changes, and golden fixture coverage.
   - **Test / acceptance implication**: Each proposal needs a backend contract test that validates, runs, and compares a minimal deal before any UI ticket can depend on it.

### Critical

1. **[C1] Canonicalization success criteria are unsafe for semantic preservation.**
   - **Dimension**: IR-evolution feasibility
   - **Plan section**: `Rule grouping, normalization, and the linter` (lines 800-831)
   - **Issue**: `RULE_FRAGMENTATION_CONSOLIDATABLE` only matches consecutive rules with identical `(rule_type, source, payment_style, cap_mode, condition_trigger, group_id)` and different targets. It omits fields that affect behavior today: `max_amount_fixed`, `max_amount_expr`, `condition_expr`, `condition_invert`, `coverage_mode`, `target_weights`, `allow_negative_source`, and source depletion behavior. Consolidating rules can also change observable behavior when target-specific caps or intervening stream mutations exist.
   - **Recommended fix**: Define a formal semantic equivalence predicate for each canonicalization pass, including fields that must match, fields that must be absent, and cases where the linter may suggest but not auto-fix.
   - **Test / acceptance implication**: Add negative tests where visually similar rules must not consolidate, including different `max_amount_expr`, different `condition_expr`, different `coverage_mode`, and intervening `SPLIT_CASH` or reserve rules.

2. **[C2] Phase 2 authoring panes ship before the IR surface they advertise.**
   - **Dimension**: Sequencing
   - **Plan section**: `Spreadsheet pane` (lines 260-271); `Implementation sequencing` (lines 1084-1085)
   - **Issue**: Phase 2 promises Sheet tabs for Calculations and Branches and Graph nodes for Branch/Case, but Phase 3 is where opaque fields and Branch IR actually land. Current `mergeOpaqueIrFields(...)` preserves `calculations`, `deal_state_trigger`, `series_id`, and related fields only as opaque data, and `irGenerator.ts` still emits `deal_knobs: {}` and has no first-class branch/calculation authoring.
   - **Recommended fix**: Move `ir-evolution-surface-opaque` and the Proposal A/B/C minimum schema work ahead of the panes that expose them, or narrow Phase 2 to "current Blockly parity only" with disabled tabs and clear feature flags.
   - **Test / acceptance implication**: Phase 2 acceptance must state which corpus fields are editable vs. read-only/opaque and prove that saving through each pane does not drop current Phase 5-9 fields.

3. **[C3] The TypeScript validation engine mirror is under-scoped.**
   - **Dimension**: Architectural coherence
   - **Plan section**: `Validation engine + Problems Panel` (lines 179-198)
   - **Issue**: The plan says the TS worker mirrors `_validate_references`, model validators, and runtime-only checks. The Python validator includes ordered split-stream discovery, source-formula names from `deal_knobs.source_formulas`, group-token mixing, coverage-mode constraints, trigger calculation refs, PAC/TAC/Z invariants, and multi-group consistency. Hand-copying this into TS without a generated contract will drift quickly.
   - **Recommended fix**: Specify a validation contract generator or golden diagnostic suite shared between Python and TS. Separate cheap structural checks in the worker from authoritative backend diagnostics streamed through SSE.
   - **Test / acceptance implication**: Add parity tests that run the same invalid deals through Python validation and TS worker validation and assert stable diagnostic codes/paths for the overlapping subset.

4. **[C4] Live preview performance has no measured fast-path budget.**
   - **Dimension**: Unenumerated risks
   - **Plan section**: `Live cashflow preview` (lines 456-466)
   - **Issue**: The plan proposes a 300 ms debounce and cancellation for every store mutation, but the runtime is Python-backed and current deal execution can involve 360 periods, multi-group flows, calculations, triggers, and per-loan paired artifacts. There is no evidence that a 200-rule auto ABS deal can run at keystroke cadence or that cancellation can preempt work before the next mutation arrives.
   - **Recommended fix**: Add a performance spike before live preview implementation with target deal sizes, measured p50/p95 runtime, cancellation latency, worker/server queueing behavior, and a degraded mode when the fast path exceeds budget.
   - **Test / acceptance implication**: Require a performance test fixture for a large synthetic auto ABS and a grouped RMBS deal; preview must coalesce edits and surface stale/canceled status rather than blocking typing.

5. **[C5] The AI context budget and tool count claims are inconsistent with the enumerated toolbox.**
   - **Dimension**: AI architecture
   - **Plan section**: `The IR-construction toolbox` (lines 538-610); `Lean context strategy` (lines 612-623)
   - **Issue**: The plan estimates "~300 tools at ~25 tokens each = ~8K tokens", but the plan enumerates roughly 38 primitive tools, 9 macros, and 6 prospectus-pattern tools. Either the manifest is materially larger than specified, or the cost model is overestimated/hand-waved. Prompt caching also depends on a stable prefix, but the plan does not define how the mutable document summary and diagnostics are separated from the cached manifest.
   - **Recommended fix**: Replace the estimate with a generated manifest budget from the actual tool registry and specify the prompt layout: cached static prefix, uncached document summary, uncached RAG, uncached diagnostics.
   - **Test / acceptance implication**: Add an AI pipeline acceptance test that snapshots the manifest token count and fails if it exceeds the intended budget without an explicit update.

6. **[C6] Asset-class "defaults, not gates" is contradicted by current solver filtering and template metadata.**
   - **Dimension**: Asset-class scope
   - **Plan section**: `Asset-class affordances` (lines 680-700); `Solver redesign` (lines 907-913)
   - **Issue**: The plan says solver template availability is not driven by asset class. Current `SolverTemplateCards.tsx` filters visible templates by `suitable_for_families`, and `ProductFamily` currently covers only `AGENCY`, `PRIME_JUMBO`, `NON_QM_QRM`, `CRT`, and `ANY`, not the full Day-1 asset-class registry. This is an availability gate, not just a default ordering.
   - **Recommended fix**: Change the plan to require ordering/prominence only, with all templates visible through "show all" or search. Update template metadata to distinguish `recommended_for` from `allowed_for`.
   - **Test / acceptance implication**: Add UI tests proving an unconventional template remains accessible for a mismatched detected asset class.

7. **[C7] Solver Level 2 is not expressive enough for the listed Day-1 templates.**
   - **Dimension**: Solver UX
   - **Plan section**: `Level 2 — Graphical builder` (lines 843-893); `Templates Day 1` (lines 907-913)
   - **Issue**: The `[Scope] ▸ [Property] ▸ [Operator] ▸ [Value(s)]` picker can express yield/WAL/CE targets, but "Build a PAC schedule" needs speed bands, support-bond selection, derivation model, stale provenance, and schedule-band editing. "Tune trigger thresholds" needs trigger-specific threshold schedules, cure periods, rolling windows, and polarity. Those require domain editors, not just metric targets and constraints.
   - **Recommended fix**: Amend Level 2 to allow template-specific domain editors composed under the same no-IR-leakage rules, especially `ScheduleBandEditor`, `RateOrScheduleEditor`, and trigger-threshold editors.
   - **Test / acceptance implication**: Add walkthrough acceptance tests for "Build a PAC schedule" and "Tune trigger thresholds" that never expose raw `metric_path`, `knob_path`, or JSON.

8. **[C8] `loss_treatment=NOTIONAL_HOLD` and writeup semantics are not implementable as a small runtime tweak.**
   - **Dimension**: IR-evolution feasibility
   - **Plan section**: `Proposal E — BondDef.loss_treatment` (lines 790-795)
   - **Issue**: `waterfall_ir_design.md` says `NOTIONAL_HOLD` keeps balance unchanged and accumulates a deferred amount, while current `pay_writedown(...)` always reduces `bond_balance`. Implementing `NOTIONAL_HOLD`, writeup, and missed coupon recovery requires new ledgers, output columns, and rule behavior, not just reading a bond enum inside `PAY_WRITEDOWN`.
   - **Recommended fix**: Split Proposal E into `WRITEDOWN` first, then `NOTIONAL_HOLD/deferred amount`, then `writeup_enabled/PAY_WRITEUP`, each with runtime and output contracts.
   - **Test / acceptance implication**: Add golden tests showing future interest accrues on reduced balance for `WRITEDOWN` and full notional for `NOTIONAL_HOLD`, plus output assertions for deferred amount/writeup.

### Major

1. **[M1] Checker-on-transcript is not a substitute for compiled IR review.**
   - **Dimension**: AI architecture
   - **Plan section**: `Checker semantics` (lines 656-665)
   - **Issue**: Reviewing tool calls is useful, but it is not strictly stronger than IR review. A tool may have the right name and plausible but wrong arguments; a macro may decompose incorrectly; a later tool call may undo an earlier correct call. The checker cannot catch those unless it sees the compiled diff and diagnostics.
   - **Recommended fix**: Require checker input to include the tool transcript, compiled IR diff summary, validation diagnostics, and a plain-language structure summary.
   - **Test / acceptance implication**: Add adversarial checker fixtures where the correct Layer-3 tool is called with wrong thresholds, missing branch cases, or swapped bond names.

2. **[M2] RAG corpus ownership and versioning are missing.**
   - **Dimension**: AI architecture
   - **Plan section**: `RAG corpus` (lines 674-679)
   - **Issue**: The corpus entries include canonical tool-call sequences, but the plan does not say who curates them, how citations are verified, or how entries migrate when tools are renamed or argument schemas change.
   - **Recommended fix**: Add corpus governance: owner, review workflow, schema version, tool-version lockfile, migration command, and stale-entry CI.
   - **Test / acceptance implication**: CI should validate every corpus tool sequence against current Zod schemas and fail on renamed or removed tools.

3. **[M3] Writer self-correction lacks a non-convergence path.**
   - **Dimension**: AI architecture
   - **Plan section**: `Pipeline shape` (lines 490-536); `Multi-turn conversation pattern` (lines 641-654)
   - **Issue**: The writer receives diagnostics after every tool call, but there is no turn cap, rollback boundary, or user-facing "could not converge" state. A bad prompt or incompatible prospectus excerpt could loop through validation errors.
   - **Recommended fix**: Define max repair attempts, checkpoint rollback, partial-draft handling, and the exact UI state when the AI gives up.
   - **Test / acceptance implication**: Add tests for repeated diagnostic failures and verify the document is unchanged unless the user accepts a valid patch.

4. **[M4] Multi-agent workflow hard-codes model availability.**
   - **Dimension**: Unenumerated risks
   - **Plan section**: `Roles and model selection` (lines 997-1011)
   - **Issue**: The workflow prescribes specific models for ticket authoring, implementation, review, and sign-off. The plan does not define substitutions for rate limits, deprecations, provider outages, or regulated environments where some model families are unavailable.
   - **Recommended fix**: Convert model names into capability tiers and approved fallback lists, with a rule that cross-family review is required but exact models are configurable.
   - **Test / acceptance implication**: Ticket workflow acceptance should not depend on one named model being available.

5. **[M5] `MetricPicker` is overloaded as a reuse proof.**
   - **Dimension**: Architectural coherence
   - **Plan section**: `MetricPicker as the canonical reuse example` (lines 412-423)
   - **Issue**: The same picker is assigned to solver targets, trigger editing, compare diffs, calculation builder, and AI argument hints. Those surfaces have materially different type systems: trigger expressions need rolling windows and polarity, compare needs run/structure axes, and calculation building needs expression composition. Forcing all of them through one component risks a brittle mega-component.
   - **Recommended fix**: Define a shared typed metric registry and smaller adapters per surface, rather than one canonical picker implementation for every use.
   - **Test / acceptance implication**: Component acceptance should test shared registry behavior separately from surface-specific UI.

6. **[M6] Storybook enforcement is asserted but not wired to CI.**
   - **Dimension**: Unenumerated risks
   - **Plan section**: `Storybook is required, not optional` (lines 425-435)
   - **Issue**: The plan says missing stories fail review, but there is no CI hook or story coverage rule. Reviewer enforcement alone is weak, especially when reviews are delegated to AI subagents.
   - **Recommended fix**: Add a Phase 1 CI requirement: story existence check for Layer 1/2/3 components, Storybook build, and visual/a11y smoke tests where feasible.
   - **Test / acceptance implication**: A component added under the catalog without a story should fail CI.

7. **[M7] Solver template scope is understated relative to current implementation.**
   - **Dimension**: Solver UX
   - **Plan section**: `Templates Day 1` (lines 907-913)
   - **Issue**: The backend has solver-template endpoints, but current registration exposes only `Balance the deal`. The plan lists nine Day-1 templates and says PRESETS migrate one-by-one, but it does not specify backend ownership, template-by-template dependencies, or which existing raw-spec fixtures must continue to work.
   - **Recommended fix**: Add a solver-template inventory table with current status, backend owner, required solver primitives, required UI editor, and acceptance tests.
   - **Test / acceptance implication**: Each template needs a Python unit test that resolves a `SolverSpec` and a Playwright journey from Level 1 through Apply/Discard.

8. **[M8] Apply/Discard, auto-save, and undo stack interactions are undefined.**
   - **Dimension**: Solver UX
   - **Plan section**: `Result presentation` (lines 898-905); `Reactive store with typed actions` (lines 173-177)
   - **Issue**: Solver results default to Discard, while the store auto-saves and zundo records mutations. The plan does not state whether a solver result is a pending patch outside the store, a draft branch in the store, or an undoable action after Apply.
   - **Recommended fix**: Define patch lifecycle states: proposed, previewed, applied, discarded. State when auto-save writes them and how undo/redo treats apply/discard.
   - **Test / acceptance implication**: Add tests that Discard leaves persisted Studio Document unchanged and Apply creates exactly one undoable store transaction.

9. **[M9] Scenario step overstates current runner support.**
   - **Dimension**: Sequencing
   - **Plan section**: `Scenarios step` (lines 919-929)
   - **Issue**: Current docs say multi-scenario execution is a user-code loop and proposed batch runner is not implemented. Current backend can bridge runsetup refs and rejects raw JSON `PAIRED` collateral over HTTP. The plan's scenario matrix needs a concrete adapter contract rather than "integrates with existing scheduled / actual / paired runner shapes."
   - **Recommended fix**: Add a scenarios execution contract: how matrix columns become `DealRunInput`, how runsetup refs are selected, what modes are allowed from browser JSON, and how paired artifacts are regenerated.
   - **Test / acceptance implication**: Add integration tests for scheduled, actual, and paired scenarios from the UI matrix through `/deals/{id}/runs`.

10. **[M10] Corpus round-trip testing promise exceeds available fixtures.**
    - **Dimension**: IR-evolution feasibility
    - **Plan section**: `RAG corpus` (lines 674-679); `Rule grouping, normalization, and the linter` (lines 827-831)
    - **Issue**: `waterfall_ir_design.md` enumerates many deals, but the test fixture directory currently contains only a subset, and several are structural placeholders with TODOs for quantitative extraction. `tests/test_fnr_2006_018_decrement_table.py` is a strong quantitative anchor, but Ford, Verus, and GNMA fixtures explicitly defer full tie-out.
    - **Recommended fix**: Distinguish "structural fixture", "quantitative golden fixture", and "research-only corpus entry" in the plan.
    - **Test / acceptance implication**: Canonicalization round-trip tests should state which deals are required on Day 1 and should not claim every named prospectus has executable golden coverage until fixtures exist.

11. **[M11] AI-off mode needs a stronger isolation contract.**
    - **Dimension**: AI architecture
    - **Plan section**: `Provider routing` (lines 666-672)
    - **Issue**: The plan says AI can be globally toggled off, but the deterministic toolbox is also used as the "same typed-action pipeline" for manual edits. It is unclear whether disabling AI disables only remote model calls or hides/rejects the entire AI pane, RAG indexing, provenance writes, and provider configuration loading.
    - **Recommended fix**: Add an AI-off contract: no network calls, no provider keys required, toolbox remains available to deterministic UI paths, AI provenance is not created, and disabled UI explains why.
    - **Test / acceptance implication**: Add a test that app boot and manual authoring work with AI env vars absent.

### Minor

1. **[m1] Plan and docs use inconsistent solver-template endpoint paths.**
   - **Dimension**: Solver UX
   - **Plan section**: `Templates Day 1` (lines 907-913)
   - **Issue**: The plan correctly names `GET /deals/{id}/solver-templates`, and current API implements that path. `solver_ux_design.md` still documents `GET /deals/{id}/solver/templates`.
   - **Recommended fix**: Update the plan fold-back or referenced doc to state the canonical endpoint path and deprecate the slash variant.
   - **Test / acceptance implication**: API docs and frontend client tests should reference one path.

2. **[m2] PropertyPanel hint-text citations are mostly correct but one cited range is status copy.**
   - **Dimension**: Architectural coherence
   - **Plan section**: `validation-help-system` todo (lines 102-103)
   - **Issue**: `PropertyPanel.tsx` lines 1138-1146 and 1196-1198 are inline explanatory hints, but lines 1029-1034 are a dynamic tape-collateral status message. Treating all of these as "stray hint text" risks migrating operational status copy into help bubbles.
   - **Recommended fix**: Split migration targets into help text, status text, warning diagnostics, and empty states.
   - **Test / acceptance implication**: Help registry tests should assert preconditions for help text only; status copy remains in stateful UI components or diagnostics.

3. **[m3] Current IR preview empty-state copy is stale.**
   - **Dimension**: Sequencing
   - **Plan section**: `e2e-and-cutover` todo (lines 105-106)
   - **Issue**: `IrPreviewPanel.tsx` still tells users to "Drag a Deal block" and "Add Bonds in Bond Definitions", while current Blockly architecture removed those concepts. The redesign cutover should include stale-copy audit, not just component deletion.
   - **Recommended fix**: Add stale copy audit to Phase 6 polish/cutover acceptance.
   - **Test / acceptance implication**: Playwright copy checks should reject legacy Blockly instructions in the new workbench.

4. **[m4] Color-token scope needs a migration boundary.**
   - **Dimension**: Architectural coherence
   - **Plan section**: `Color system` (lines 315-360); `Anti-patterns the reviewer rejects` (lines 437-450)
   - **Issue**: The plan says no hardcoded colors outside tokens, but current CSS and Blockly code have hardcoded hex values, including scrollbar colors and block palette colors. Deleting Blockly files handles some of this, but global CSS and existing shared UI need a migration rule.
   - **Recommended fix**: Add "new/changed studio code only" vs. "whole UI migration" scope and a lint rule for the selected boundary.
   - **Test / acceptance implication**: If whole-UI migration is intended, add stylelint or custom lint enforcement; otherwise scope the review rule to new Studio components.

### Nits / suggestions

1. **[n1] Layer numbering is internally inconsistent.**
   - **Dimension**: Architectural coherence
   - **Plan section**: `Four-layer component catalog` (lines 368-410)
   - **Issue**: The principle says four layers, but the catalog names Layer 0 through Layer 4, which is five layers.
   - **Recommended fix**: Rename it to "five-layer catalog" or fold workbench surfaces outside the catalog.
   - **Test / acceptance implication**: None.

2. **[n2] AI token-budget wording is confusing.**
   - **Dimension**: AI architecture
   - **Plan section**: `Lean context strategy` (lines 612-623)
   - **Issue**: The plan says total per-call budget is 10-14K and net live tokens are under 6K. That is plausible only if the manifest is cached and isolated, but the prose reads like both are simultaneously the turn size.
   - **Recommended fix**: Separate "context window tokens", "billable uncached input tokens", and "cacheable prefix tokens."
   - **Test / acceptance implication**: None beyond [C5].

3. **[n3] CMBS/CLO/Equipment placeholder defaults need less product assertion.**
   - **Dimension**: Asset-class scope
   - **Plan section**: `Per-class default profiles` (lines 746-749)
   - **Issue**: "CMBS conventions are closer to non-agency RMBS" may be defensible for some waterfall concepts, but it is too broad for a placeholder pack that has not been researched in the plan.
   - **Recommended fix**: Say placeholders expose generic primitives with no class-specific recommendations until research and engine support land.
   - **Test / acceptance implication**: Opening an unsupported class should show generic authoring, not class-specific confidence.

4. **[n4] The "principal-Google standard" review phrase is imprecise.**
   - **Dimension**: Unenumerated risks
   - **Plan section**: `Multi-agent execution workflow` (lines 993-1049)
   - **Issue**: The review rubric is strong on severity labels but weak on reproducible criteria. Two AI reviewers may disagree about "composition over duplication" without objective checks.
   - **Recommended fix**: Turn subjective review phrases into checklists: component reuse search, story presence, token lint, a11y checks, test-to-acceptance mapping.
   - **Test / acceptance implication**: Review output should include a checklist artifact per ticket.

## Findings by dimension

1. **Architectural coherence**
   - [B3]: Cross-view losslessness is not defined for Studio-only sidecar fields.
   - [C3]: The TS validator mirror needs a generated or golden-tested contract with Python.
   - [M5]: `MetricPicker` should be a shared registry plus adapters, not one universal component.
   - [m2]: Hint-text migration should distinguish help, status, warning, and empty-state copy.
   - [m4]: Token enforcement needs an explicit migration boundary.
   - [n1]: The component catalog is described as four layers but lists five.

2. **IR-evolution feasibility**
   - [B4]: Proposals B-E need explicit runtime/compiler/validator contracts.
   - [C1]: Canonicalization quick-fixes can change semantics unless equivalence is formalized.
   - [C8]: `loss_treatment` requires new ledgers and output semantics beyond a small enum.
   - [M10]: Fixture coverage is not yet broad enough for the claimed corpus-wide round-trip tests.

3. **AI architecture**
   - [C5]: Tool-count and context-budget claims need measurement from the actual manifest.
   - [M1]: Transcript review should be paired with compiled IR diff review.
   - [M2]: RAG corpus ownership and migration are missing.
   - [M3]: Writer non-convergence needs a bounded failure path.
   - [M11]: AI-off mode needs a no-network/no-provider-key isolation contract.
   - [n2]: Token-budget wording should separate cached vs. uncached tokens.

4. **Asset-class scope**
   - [C6]: Current solver template filtering is an availability gate.
   - [n3]: Placeholder class defaults should avoid unsupported product assertions.

5. **Solver UX**
   - [C7]: Level 2 needs domain-specific editors for PAC schedules and trigger thresholds.
   - [M7]: Nine Day-1 templates need an inventory and backend acceptance plan.
   - [M8]: Apply/Discard must be reconciled with auto-save and undo.
   - [m1]: Solver-template endpoint naming should be made consistent.

6. **Sequencing**
   - [B1]: Phase 1 linter depends on Phase 3 `WaterfallBranch`.
   - [C2]: Phase 2 surfaces advertise fields that are not authorable until Phase 3.
   - [M9]: Scenario matrix depends on runner/orchestrator contracts that are only partially implemented.
   - [m3]: Cutover needs stale-copy acceptance, not just component replacement.

7. **Unenumerated risks**
   - [B2]: Studio Document migration and sidecar durability are unspecified.
   - [C4]: Live preview performance and cancellation need measured budgets.
   - [M4]: Model-specific multi-agent workflow needs capability-based fallbacks.
   - [M6]: Storybook requirements need CI enforcement.
   - [n4]: AI reviewer rubric needs objective checks.

## Recommendations for the plan author (fold-back guidance)

1. Amend `Implementation sequencing` so Phase 1 does not emit or require IR constructs scheduled for Phase 3. Either move Proposal A/C foundations earlier or narrow Phase 1 to validation infrastructure only.
2. Add a `StudioDocument persistence and migration` subsection with schema, sidecar storage, versioning, first-open import, export behavior, provenance durability, and existing snapshot migration.
3. Replace blanket "lossless round-trip across all modalities" with a field-class matrix: engine IR, sidecar metadata, view layout, AI provenance, scratchwork, selection, and scenarios.
4. Expand `IR evolution required` with per-proposal runtime contracts and split Proposal E into separate ledgers/semantics tickets.
5. Tighten `Rule grouping, normalization, and the linter` with formal equivalence predicates, negative examples, and quick-fix preconditions.
6. Add a `Validation parity contract` covering Python vs. TS diagnostics, generated schemas, stable diagnostic codes, and backend SSE authority.
7. Add a live-preview performance spike before implementation, with explicit run-size targets and fallback UI when preview cannot keep up.
8. Revise the AI section with actual tool counts, manifest versioning, RAG governance, checker inputs that include compiled IR diffs, non-convergence handling, and AI-off isolation.
9. Revise asset-class template behavior from filtering/gating to ordering/recommendation, and add tests for cross-class template access.
10. Expand Solver Level 2 to allow template-specific domain editors while preserving the no-raw-IR rule.
11. Add CI enforcement for Storybook, component catalog updates, token usage, and story presence.
12. Add a parity checklist for feature-flag cutover: current Blockly journeys, opaque field preservation, solver template migration, run/solve/cancel, Analysis page read-only rendering, stale-copy audit, and e2e coverage.

## Open questions for the user

1. Should Studio Document sidecars be exported with a deal when sent to a counterparty, or is export intentionally engine IR only with AI provenance stripped?
2. Is Blockly parity sufficient for Phase 2, or must Phase 2 author all fields currently preserved by `mergeOpaqueIrFields(...)`?
3. Should the AI RAG corpus be treated as product data requiring human approval, citations, and versioned migrations, or as developer test fixtures?
4. Are CMBS, CLO, and Equipment intended to be openable as generic unsupported deals on Day 1, or should the UI steer users away until researched profiles exist?
5. During long-running solves or cashflow runs, should the Studio Document be editable with snapshot isolation, or locked until the run finishes?
6. Is single-user multi-tab editing a supported scenario for the redesign, or is last-writer-wins acceptable until collaboration is in scope?
