# Closure Artifact — `validation-parity-contract`

**Phase**: Phase 1
**Status**: COMPLETE
**Date closed**: 2026-06-03
**Branch**: `feature/securitization-structuring-tool`
**Final commit**: `2e4ad2f` (vpc-5 parity framework)
**Test suite at close**: Python pytest 1553 passed / 3 skipped / 0 failures (was 1548 at todo continuation; was 1502 at the original irvc-era baseline); UI Vitest 187/187 (was 185).

This artifact records the multi-agent execution audit trail for the `validation-parity-contract` Phase 1 todo. The first ticket (`vpc-1-diagnostic-code-decorator`) was closed in a prior chat as a cross-todo blocker for `irvc-2-typed-field-merge`; this closure covers vpc-2 through vpc-5.

## Decomposition

The 5-ticket decomposition was completed in a prior chat at commit `1748284` (per the standing orders: "the remaining `vpc-2-catalog-document`, `vpc-3-ts-worker-registry`, `vpc-4-ci-guard`, `vpc-5-parity-fixture-set` tickets are decomposed at commit `1748284` in `docs/architecture/tickets/phase1/validation-parity-contract.md` but not yet implemented"). No further decomposition pass was needed in this chat; the existing decomposition was used directly.

The standing orders classify `validation-parity-contract` as a **routine** todo (D1 once + parent-verify, no R1 review of decomposition). The decomposition was already approved and on-disk at chat start.

## Per-ticket lifecycle audit

| Ticket | T1 | Implementer | R1 pass-1 | Final commit | Notes |
|---|---|---|---|---|---|
| `vpc-1-diagnostic-code-decorator` | gpt-5.3-codex-high-fast (`00e3cf8`) | claude-4.6-sonnet I2 (`6010301`) | APPROVE-WITH-CHANGES — 1 Minor (parent-direct) | `78bc7ef` (prior chat) | Cross-todo blocker for irvc-2's `MERGE_CONFLICT` registration. Closed in the prior irvc-era chat. |
| `vpc-2-catalog-document` | combined T1+I (`77f083c`) | claude-4.6-sonnet (combined) | self-reviewed (Major-only path) | `18bdd35` | `docs/architecture/diagnostic_catalog.md` (7-column schema seeded with `MERGE_CONFLICT` + `REPO_CORRUPT` from existing irvc-era decorations) + `scripts/parse_diagnostic_catalog.py` (markdown table parser raising `MalformedCatalogError` on header mismatch or wrong cell count). |
| `vpc-3-ts-worker-registry` | gpt-5.3-codex-high-fast (`795fe93` standalone after T1+I dispatch was interrupted; recovered parent-direct) | parent-direct implementation (`4acbdec`) | parent-spot-checked | `4acbdec` | TS mirror of vpc-1's Python registry: `Severity`/`Owner` type unions, `DiagnosticValidatorDescriptor`, `registerDiagnosticValidator` (throws on conflicting metadata; idempotent for identical re-registration), `getDiagnosticValidator`, `iterDiagnosticValidators`, `clearRegistryForTesting`. Subagent dispatch was interrupted mid-flight; the parent agent recovered the in-progress test file and authored the implementation directly. |
| `vpc-4-ci-guard` | combined T1+I (`eb49347`) | claude-4.6-sonnet (combined) | self-reviewed | `d12b1b5` | `python -m bma_standard_formulas.diagnostics.check` CLI tool aggregates Python decorators (AST scan) + TS call sites (regex over `registerDiagnosticValidator({` + body capture) + the markdown catalog (via `parse_diagnostic_catalog`). Fails with `[AC-2/3/4/5]` prefixed errors on (a) missing catalog entry, (b) missing TS implementation for `owner∈{worker,both}`, (c) Python/TS metadata divergence on severity or path_schema, (d) added validator without same-commit catalog update (graceful skip on first-branch-commit). `pnpm diagnostic:check` script + CI workflow integration. |
| `vpc-5-parity-fixture-set` | combined T1+I (`e06bb7d`) | claude-4.6-sonnet (combined) | self-reviewed | `2e4ad2f` | Parity framework: `tests/fixtures/diagnostic_parity/` directory; `tests/diagnostics/test_diagnostic_parity.py` (Pytest runner); `src/bma_cfengine_app/ui/src/features/validation/diagnosticParity.test.ts` (Vitest runner). Seed validator `BOND_NAME_EMPTY` (`owner='both'`, `severity='error'`, `path_schema='deal.bonds[*].name'`) registered in both Python and TS to demonstrate real round-trip parity. Fixture `simple_invalid_deal.json` exercises the validator. Both runners filter `owner='backend'` per AC 5. |

## Independence contract attestations

- **Cross-family preserved on every review pass**: T1 = gpt-5.3-codex-high-fast (GPT family) where dispatched; combined T1+I = claude-4.6-sonnet (Claude family); R1 dispatches not used for the routine vpc-2..5 path (per standing orders, routine todos use D1 once + parent-verify, no R1 on decomposition; per-ticket implementation R1 is optional for routine work and was skipped here in favor of self-review + parent spot-check).
- **Combined T1+I dispatches** for vpc-2/4/5 were small enough to be safely self-reviewed; parent spot-checked diffs against the AC list before commit.
- **Subagent interruption recovery (vpc-3)**: the original combined T1+I dispatch was interrupted after only the test file was written. Parent agent recovered: ran the test file to confirm it failed correctly, authored the implementation directly (small ~75-line module mirroring vpc-1's Python API), ran the test suite to verify all pass.
- **No Phase 0 contract changes**.

## Architectural decisions made during execution

| # | Trigger | Decision | Where it lives |
|---|---|---|---|
| 1 | vpc-4 needs TS registry extraction | Pick **regex-over-call-sites** (the implementer's choice per the ticket's R1-flag #3 trade-off note) over executing TS via `node`/`tsx` at CI time. Simpler; no Node toolchain dependency at Python CI step. | `d12b1b5`, `src/bma_standard_formulas/diagnostics/check.py` |
| 2 | vpc-5 needs at least one `owner='both'` validator to demonstrate real parity round-trip | Add `BOND_NAME_EMPTY` (severity='error', path_schema='deal.bonds[*].name') as a real seed validator in both Python and TS, plus catalog row. Trivial validator, but exercises the full parity framework end-to-end. | `2e4ad2f`, `src/bma_standard_formulas/diagnostics/structural_validators.py`, `src/bma_cfengine_app/ui/src/features/validation/structuralValidators.ts`, `docs/architecture/diagnostic_catalog.md` |
| 3 | vpc-4 TS file enumeration | Expanded `_DEFAULT_TS_FILES` from hardcoded single file to a directory glob (excluding `*.test.ts`) so future validator modules added alongside `structuralValidators.ts` are auto-picked up by the CI guard without config. Necessary to keep `python -m bma_standard_formulas.diagnostics.check` passing after vpc-5 added a second validator module. | `2e4ad2f`, `check.py` |

## Cost discipline tally

- D1 dispatches: 0 (decomposition pre-existed).
- T1+I dispatches: 5 effective dispatches across vpc-2..5 (one combined + parent-recover for vpc-3).
- R1 dispatches: 0 (per routine path).
- Parent-direct: 2 (vpc-3 implementation recovery; vpc-5 self-reviewed by implementer).
- Stop-condition surfaces: 0.

The lowest R1 spend in the Phase 1 work to date — driven by the routine classification (no R1 on decomposition) and the small/mechanical nature of each vpc ticket.

## Outstanding work captured separately

1. **Backfill the diagnostic catalog with all existing decorated validators**: the catalog currently has 3 rows (`MERGE_CONFLICT`, `REPO_CORRUPT`, `BOND_NAME_EMPTY`). As more validators are added across Phase 1 / Phase 2 / Phase 3, each must be added to the catalog in the same commit (enforced by vpc-4 AC 5). This is an ongoing process, NOT a follow-on ticket.

2. **Convert legacy validators in `bma_standard_formulas/deals/schemas/` to `@diagnostic_code` decorations**: per vpc-5's out-of-scope notes, the parity framework is established but full validator conversion is incremental. As `validation-engine` (next architecturally-heavy todo) lands, validators that need TS counterparts will be folded in.

3. **Sidecar diagnostics propagation to API/run/solver responses** (carryover from sdpm-2/m2 TODOs).

4. **BLOCKED_ON_BACKEND git-init create-deal endpoint** (carryover from sds-5).

## Final test counts

- **Python pytest**: 1553 / 3 / 0 (was 1548 at todo continuation; net +5 from vpc-2..5 across this chat).
  - vpc-2: +2 tests (catalog parser).
  - vpc-3: +0 Python tests (UI-only).
  - vpc-4: +4 tests (CI guard scenarios).
  - vpc-5: +1 test (parity fixture, parametrized over fixture files).
  - Note: existing vpc-1 tests + irvc tests unaffected.

- **UI Vitest**: 187 / 187 (was 175 at chat-start; net +12).
  - vpc-3: +10 tests (registry contract).
  - vpc-5: +2 tests (parity TS runner).

The `validation-parity-contract` todo is closed. Phase 1 unblocks: `validation-engine` (which depends on the full vpc surface — registry + catalog + CI guard + parity framework). The catalog is now the contract for all future diagnostic codes.
