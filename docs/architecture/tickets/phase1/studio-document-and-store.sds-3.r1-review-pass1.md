# R1 Review (Pass 1) — `sds-3-compile-canonical-serialization` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family from claude-4.6-opus implementer + Claude parent + gpt codex T1 author)
**Date**: 2026-06-02
**Implementation under review**: commits `f63f1c0` (Python) + `1895fdc` (TS), test commit `a58bed4`
**Verdict**: RETURN-FOR-REVISION

## Summary

The happy-path implementation is close: `compileToIR(working_tree: DealState): string` exists, the Python field-order emitter walks the current nested model graph, the two checked-in field-order manifests are currently byte-identical, and the TS round-trip test pins byte identity for the five named fixtures.

I would not sign off yet. Several acceptance-criterion guardrails are either missing from CI or narrower than the spec requires. The most important risks are stale manifest handling, unguarded vendored-copy drift, fixture parity/auto-extension gaps, and TS-side numeric/default semantics that are not derived from the Pydantic schema.

## Findings

### Critical

1. **`compileToIR` silently serializes fields missing from the manifest instead of failing.** AC 2 requires fields absent from the manifest to fail compilation with a clear error. The implementation only throws when the whole model entry is missing. If a known model gains a new field and the manifest is stale, `serializeModel` appends the unknown key after the manifest-ordered keys (`compile.ts` lines 88-95). That defeats the runtime safety mechanism requested by AC 2. Recommendation: make unknown fields a hard error for manifest-backed models with a message naming the model and missing field. Add a unit test that injects an extra field and expects `compileToIR` to throw.

2. **CI drift/parity guardrails required by AC 6-8 are not wired.** The ticket explicitly requires CI to run `emit_field_order.py --check`, `emit_canonical_fixtures.py --check`, a vendored-copy diff guard, and a fixture-count parity guard. The current workflow only runs `pytest tests/` with no UI/Vitest run, no `--check` invocations, no vendored-copy diff. `tests/scripts/test_emit_field_order.py::test_emitter_walks_all_nested_models_and_records_declaration_order` calls the emitter in write mode, so a stale Python source manifest can be regenerated during pytest before assertions inspect it. Without explicit CI `--check` or git diff check, pytest alone can mask committed generated-artifact drift. Recommendation: add CI steps for the two `--check` commands, byte comparison between the two `field_order.json` paths, parity invocation, and the UI test suite.

### Major

1. **Fixture parity is one-directional and not invoked by `--check`.** `assert_fixture_count_parity` only computes `missing = deal_dirs - canonical_dirs` (`emit_canonical_fixtures.py` lines 117-125). A stale extra `deal.canonical.json` without a matching `deal.json` passes. The script `main()` also does not call parity in `--check` mode at lines 128-136. The test only covers the missing-canonical case (`tests/scripts/test_emit_canonical_fixtures.py` lines 154-162). Recommendation: check both set differences, call parity from `main()` in `--check`, and add a failure test for canonical-without-source.

2. **Round-trip coverage is fixed to five fixture names and does not auto-extend.** `compile.roundtrip.test.ts` uses a hardcoded `FIXTURES_UNDER_TEST` list at lines 18-24 with `shouldIncludeFixture` filter at lines 40-44. A sixth fixture under `tests/fixtures/*/deal.json` is invisible to the TS byte-identity test. Recommendation: discover fixture directories from the filesystem, assert the required five names are present, and run round-trip assertions for every discovered `deal.json`.

3. **`schedule_contract` numeric formatting is a TS heuristic, not Pydantic semantics.** The TS serializer decides whether all non-`period` `schedule_contract` values should be float-formatted by scanning for any fractional value in the array (`compile.ts` lines 155-171). After `JSON.parse`, TS cannot distinguish `100` vs `100.0`, so a schedule whose values were all integer-valued floats in Python can drift from `100.0` to `100`. Real forward-compat risk for autosave and new fixtures. Recommendation: avoid heuristic reconstruction; extend the generated manifest with per-field scalar type information.

4. **Numeric/default serialization duplicates schema semantics in TS.** Hardcoded `FLOAT_FIELDS`, `FLOAT_ARRAY_FIELDS`, `LIST_CHILD_MODEL`, `RATE_OR_SCHEDULE_FIELDS`, `RAW_DICT_INT_KEYS` blocks in `compile.ts` lines 8-69 duplicate Pydantic annotation info. A new float field added to Pydantic + included in `field_order.json` will still serialize incorrectly in TS unless someone updates the hardcoded TS metadata. One concrete type mismatch: `TriggerNode.threshold_schedule` is `list[float] | None` in Python but `LIST_CHILD_MODEL` maps it to `RateScheduleEntry`, so integer-valued threshold floats would emit as `1` rather than `1.0`. Recommendation: generate schema/type metadata alongside field order; add a generated drift test that proves every Pydantic float/list-of-float field is represented in TS metadata.

### Minor

1. **Vendoring is currently manual.** The two `field_order.json` copies are byte-identical now, but no sync script, package script, pre-commit hook, or CI guard enforces the copy relationship. Recommendation: add a named sync command/script and a CI `diff --no-index` guard.

## What Landed Well

- AC 1 satisfied: `compileToIR(working_tree: DealState): string` exists.
- Python field-order emitter walks the nested BaseModel graph via annotations.
- Source and vendored manifests are byte-identical at HEAD.
- List order preserved in serializer.
- No-canonicalization behavior pinned against `fnr_2006_018`.
- Canonical fixture emitter handles builder materialization and passthrough.
- Round-trip test does direct byte comparison to `deal.canonical.json` plus second-compile idempotency.

## Verdict Rationale

The implementation proves the current five fixtures can pass byte-identical serialization, but the ticket is explicitly a correctness gate. The missing CI guardrails and stale-manifest behavior mean future schema changes can drift silently. The TS serializer also relies on hand-maintained type/default knowledge that is not derived from the Pydantic source of truth, which is fragile for sds-4/sds-5 and Phase 3 schema growth.

## Sign-off Recommendation

RETURN-FOR-REVISION. Re-review after:
1. `compileToIR` rejects manifest-unknown fields.
2. CI runs generated-artifact checks, vendored-copy sync checks, parity checks, and Vitest.
3. Fixture discovery auto-extends beyond the five named fixtures while enforcing the required five.
4. Numeric/default metadata is either generated from Pydantic or guarded by tests strong enough to catch schema drift.
