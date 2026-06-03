# R1 Review (Pass 2) — `sds-3-compile-canonical-serialization` fix-pass

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; pass-2 fresh from pass-1 reviewer)
**Date**: 2026-06-02
**Fix-pass under review**: commit `6540ffc`
**Pass-1 review**: `studio-document-and-store.sds-3.r1-review-pass1.md`
**Verdict**: APPROVE-WITH-CHANGES (parent-verified)

## Pass-1 Audit Table

| Finding | Status | Verification |
|---|---|---|
| C1: `compileToIR` rejects manifest-unknown fields | CLOSED | `serializeModel` builds a manifest field set and throws for any present key not in that model's manifest at `compile.ts` lines 70-80. Regression coverage in `test_compile_rejects_field_not_in_manifest` at `compile.test.ts` lines 294-303. Always-on. |
| C2: CI drift/parity guards | CLOSED | CI runs `python scripts/emit_field_order.py --check`, `python scripts/emit_canonical_fixtures.py --check`, vendored manifest diff guard, Python tests, and Vitest in a separate UI job at `.github/workflows/ci.yml` lines 39-69. Fixture parity is invoked inside canonical `--check` at lines 139-142 of the emitter. |
| M1: Bidirectional parity guard + orphan-canonical test | CLOSED | `assert_fixture_count_parity` computes both `missing_canonical` and `orphan_canonical` at `emit_canonical_fixtures.py` lines 117-133. Tests cover both cases at `test_emit_canonical_fixtures.py` lines 154-175. |
| M2: Auto-extending fixture discovery + minimum-set assertion | CLOSED | `discoverFixtures` reads directories under `tests/fixtures` and filters to entries containing `deal.json` at `compile.roundtrip.test.ts` lines 27-32. Required five fixtures asserted at lines 19-25 and 65-73. Round-trip runs for every discovered fixture at lines 76-94. |
| M3: `schedule_contract` handling | CLOSED | Heuristic kept and documented as the only allowed serializer heuristic at `compile.ts` lines 155-159. `period` preserved as int via `SCHEDULE_CONTRACT_INT_KEYS`. |
| M4: Per-field type metadata replaces hardcoded TS blocks | CLOSED | Old hardcoded per-field tables removed. `field_order.json` now stores `{name, type}` entries; `compile.ts` dispatches from manifest type strings. Remaining hardcoded logic is the documented `schedule_contract` exception, not a per-field type table. |
| m1: Vendoring sync script + CI diff guard | CLOSED (parent-verified) | The CI diff guard is present at `.github/workflows/ci.yml` lines 45-46. Pass-2 found the `sync:field-order` script's relative path was wrong (`../../../` instead of `../../`); parent-applied tactical patch corrects this. Verified by running `npm run sync:field-order` post-patch and confirming the vendored copy still matches the source manifest byte-for-byte. |

## New Findings

### Minor

1. **`sync:field-order` script's relative path was wrong.** From `src/bma_cfengine_app/ui/`, `../../../` resolves to the repo root, but the source manifest lives at `src/bma_standard_formulas/...`. The correct path is `../../bma_standard_formulas/...`. Parent-applied fix; verified by running the script and confirming byte-equality to the source.

## Additional Audit Notes

- The typed manifest emitter handles current `DealDefinition` graph edge cases: `Annotated` aliases unwrapped at `emit_field_order.py` lines 86-89; `Literal` represented at lines 91-92; `Union` and PEP 604 unions at lines 94-98; `Optional` normalized; default-factory fields included via `model.model_fields`.
- Generated metadata captures representative Pydantic cases correctly: `Dollars`/`Rate` aliases → `float`; `RateOrSchedule | None` → `Union[float, list[RateScheduleEntry], None]`; `schedule_contract` → `list[dict[str, Union[float, int]]]`; `threshold_schedule` → `Optional[list[float]]`.
- Non-fixture top-level CSV files skipped by both paths.

## Verdict Rationale

The fix-pass closes the substantive pass-1 correctness concerns: stale manifest fields fail compilation, CI has the necessary guards, fixture parity is bidirectional, round-trip coverage auto-extends, and type formatting is manifest-driven. Only the broken sync-script path remained — fixed by parent in a tactical patch.

## Sign-off Recommendation

APPROVE — sds-3 closed; proceed to sds-4.

---

## Parent-verify patch applied (2026-06-02)

**Parent agent (Claude Opus 4.7)** corrected the `sync:field-order` script path in `src/bma_cfengine_app/ui/package.json` from `../../../bma_standard_formulas/...` to `../../bma_standard_formulas/...`. Verified:
- `cd src/bma_cfengine_app/ui && npm run sync:field-order` succeeds.
- `diff -q ../../bma_standard_formulas/deals/schemas/field_order.json src/features/deals/field_order.json` shows no difference.
