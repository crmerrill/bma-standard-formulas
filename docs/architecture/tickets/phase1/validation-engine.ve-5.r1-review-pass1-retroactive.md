# R1 Review (Pass 1, retroactive) — `ve-5-quick-fix-protocol` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family; RETROACTIVE)
**Date**: 2026-06-03
**Implementation under review**: commit `55f99ce` (test commit `48502be`)
**Verdict**: APPROVE-WITH-CHANGES

## Findings

1. **Forward-compat gap: emitted `manual_resolve_*` QuickFix is not a registered `DealAction`.**

   `ve-5` AC 1 says `QuickFix.action_id` should match a registered `DealAction` `type`, but the implemented exemplar emits:
   - `action_id: "manual_resolve_duplicate_bond_name"`

   The current `DealAction` union only includes:
   - `addBond`, `setBondKind`, `setRulePriority`

   I found no quick-fix/action registry that Phase 2 Problems Panel can use to validate `manual_resolve_duplicate_bond_name`. As implemented, `action_id` is effectively free-form. That may be acceptable if `manual_resolve_*` is intentionally a non-dispatchable UI instruction, but it should be formalized before Phase 2 consumes it.

   Recommended change: either register `manual_resolve_duplicate_bond_name` in a QuickFix registry with explicit semantics, or change the emitted QuickFix to use an actual dispatchable `DealAction` type.

## Checklist Review

- **AC 1 Python model**: Pass. `QuickFix` added as Pydantic model with `action_id: str` and `params: dict[str, Any]`; `DiagnosticPayload.fix: QuickFix | None = None` is additive.
- **AC 1 backward compatibility**: Pass. Existing 5-field payloads still validate because `fix` defaults to `None`.
- **AC 1 TypeScript mirror**: Pass with path note. `QuickFix` and `fix?: QuickFix` added in `diagnostics-types.ts`, not the spec-listed `validation/types.ts`. Consistent with repo's existing import path.
- **AC 2 worker QuickFix emission**: Pass. `BOND_NAME_DUPLICATE` emits a populated `fix` object.
- **AC 3 `getErrorCount(sessionId)`**: Pass. Counts `severity === "error"`; returns `0` for missing sessions.
- **AC 3 `useErrorCount()` hook**: Pass by inspection. Test coverage focuses on `getErrorCount`; not direct hook-specific coverage.
- **QuickFix schema required fields**: Pass. Python `params` has no default; both fields required.
- **vpc-1 schema test update**: Necessary as written.

## Residual Risk

The only material concern is semantic, not structural: Phase 2 needs a stable way to know whether a QuickFix is dispatchable, manually resolvable, or invalid. Without a registry or a discriminated action contract, the `action_id` field is syntactically typed but not operationally validated.
