# R1 Review (Pass 1) — `sds-1-store-foundation-and-deps` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family from claude-4.6-sonnet implementer + Claude parent + gpt codex T1 author)
**Date**: 2026-06-02
**Implementation under review**: commit `0cb3659` (test commit `91525c5`)
**Verdict**: APPROVE-WITH-CHANGES

## Summary
The implementation satisfies the SDS-1 store foundation contract: dependencies are added in `dependencies`, the flat `sessions[id].working_tree` shape is used, the root fields and main `DocumentSession` scaffold are present, the typed dispatcher has the required three-action vocabulary, and the selectors follow the canonical active-session pattern. I found no Blocking, Critical, or Major implementation defects. The remaining issues are test-integrity gaps: the implementation is sound, but a few T1 tests are less direct than the AC text requires.

## Findings

### Blocking
1. None.

### Critical
1. None.

### Major
1. None.

### Minor
1. **AC 2 test fixture is synthetic rather than a real emitted `deal.json`.** The ticket calls for a fixture `deal.json` parsed with `JSON.parse(...) as DealState` to prove the store accepts the Python-emitted IR shape without field renames or transforms. The current T1 test builds a local TypeScript `makeDealFixture()`, stringifies it, and parses it back. That still gives useful structural coverage and the implementation's `emptyDealState()` matches the required `DealDefinitionIR` required fields, but it does not prove compatibility with an actual fixture artifact. Recommendation: in the next pass, update the test to read a real fixture JSON once the fixture path is stable.

2. **AC 4 active-session isolation is not directly exercised with a second session.** The implementation correctly routes every action through `state.sessions[state.activeSessionId].working_tree` and reconstructs only the active session entry. However, the tests only operate with the single `main` session and assert `Object.keys(state.sessions) === ["main"]`; they do not seed an inactive sibling session and prove it is untouched. Recommendation: add a small test-only second session via `setState`, switch `activeSessionId`, dispatch each action, and assert the inactive session's `working_tree` object remains referentially unchanged.

3. **AC 5 selector stability test covers rerender stability, but not unrelated-slice updates.** The selectors themselves use the required canonical pattern and Zustand v5 `Object.is` semantics, so the implementation is correct. The current test verifies references survive a plain rerender; it does not dispatch an unrelated slice update and prove unaffected selector references remain stable. This is a specificity gap only, not a code defect.

4. **The `@ts-expect-error` test validates the `dispatch` union type more than the switch exhaustiveness guard.** The implementation's `const _exhaustive: never = action` default branch is real and will fail TypeScript if a new `DealAction` variant is added without a case. The test line with `@ts-expect-error` is meaningful when `tsc -b` runs because `tsconfig.json` includes `src`, but it checks that an invalid action cannot be passed to `dispatch`; it does not independently mutate the union and prove the default branch catches missing cases. This is acceptable for SDS-1, but the test name slightly overclaims.

### Nit
1. None.

## What landed well
- `zustand` and `zundo` are both in UI `dependencies`; the lockfile resolves real packages (`zundo` 2.3.0 and `zustand` 5.0.14 from the `^5.0.6` range).
- The store uses the pass-2 sanctioned flat shape: `sessions: Record<string, DocumentSession>`, with no `{ state, temporal }` wrapper.
- The initial `main` session has `ui_role: "primary"`, `session_id: "main"`, `branch_name: "main"`, and forward slots for `zundo_history`, `diagnostics`, `validation_target`, and `commit_target`.
- `emptyDealState()` matches the required `DealDefinitionIR` fields and does not rename or add top-level IR fields.
- The action handlers target `state.sessions[state.activeSessionId].working_tree` and do not touch Blockly, `irGenerator.ts`, or `scheduleOverlayMerge.ts`.
- There are no `any` uses. The only `as unknown as RuleNodeIR` cast is the expected `setRulePriority` escape hatch because `RuleNodeIR` does not currently expose `priority`.
- `setDealId(deal_id: string)` is surfaced on the Zustand state and works through `useDealStore.getState().setDealId(...)`.

## Verdict rationale
The implementation is fit to build on: it preserves the SDS-1 flat store shape, keeps SDS-2 additive, and does not introduce legacy coupling or downstream-breaking type drift. The issues are confined to test precision, not runtime behavior or store architecture.

## Sign-off recommendation
APPROVE-WITH-CHANGES — apply Minor fixes during the next implementation pass.

---

## Parent-verify fix-pass applied (2026-06-02)

**Parent agent (Claude Opus 4.7)** applied the 4 Minor fixes directly per the standing orders' Major-only/Minor-only fold-back protocol (no R1 pass-2 dispatched per the cost-discipline budget).

**Fixes**:
- **Minor #1**: deferred to `sds-3-compile-canonical-serialization` (which lands `scripts/emit_canonical_fixtures.py`). A comment was added to `useDealStore.test.ts::test_fixture_deal_json_parses_into_working_tree_without_field_renames` noting this; the synthetic fixture covers the structural shape contract until real `deal.json` artifacts exist on disk.
- **Minor #2**: new test `test_action_dispatch_only_mutates_active_session_not_siblings` in `actions.test.ts` seeds a sibling ephemeral session, dispatches in both directions (active=main → sibling untouched; active=sibling → main untouched), and asserts referential stability of the inactive session's `working_tree`.
- **Minor #3**: new test `test_per_pane_selectors_unchanged_when_other_slices_update` in `selectors.test.ts` mutates `accounts` only and asserts that the `bonds` and `rules` selector references remain stable while `accounts` returns a new reference.
- **Minor #4**: renamed `test_unknown_action_type_fails_compile_via_never_guard` to `test_dispatch_rejects_unknown_action_type_via_discriminated_union` and tightened the comment to accurately describe what the `@ts-expect-error` directive proves vs. the runtime default branch.

**Verification**: 10/10 sds-1 vitest tests pass (8 original + 2 new). UI suite remains green; Python suite unaffected.

**Verdict after parent-verify**: APPROVE — sds-1 ready for sign-off.
