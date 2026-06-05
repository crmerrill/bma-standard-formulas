# R1 Review (Pass 1, retroactive) — `vpc-3-ts-worker-registry` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family; RETROACTIVE)
**Date**: 2026-06-03
**Implementation under review**: commit `4acbdec` (test commit `795fe93`)
**Verdict**: APPROVE-WITH-CHANGES

## Findings

1. **Identical-metadata re-registration is documented as a no-op, but it can update the registered descriptor.**
   In `src/bma_cfengine_app/ui/src/features/validation/diagnosticRegistry.ts`, `registerDiagnosticValidator` checks conflicts only for `severity`, `pathSchema`, and `owner`, then always calls `REGISTRY.set(desc.code, desc)`. If a caller re-registers the same `code` with identical metadata but a different `fn`, the stored validator is replaced. That contradicts the implementation comment and the expected checklist behavior that identical metadata should be a no-op.
   Recommendation: return the existing descriptor immediately after confirming metadata matches, or include `fn` identity in the duplicate conflict policy if replacement is intended.

2. **`clearRegistryForTesting` is exported from the production module.**
   The underlying `REGISTRY` Map is module-private and no Map reference leaks. However, `clearRegistryForTesting()` is publicly exported from the same module and can mutate global registry state outside tests. This is not an AC blocker, but it is a real escape hatch.

## Checklist

- **AC 1**: Pass. `Severity` is `"error" | "warning" | "info"`; `Owner` is `"worker" | "backend" | "both"`. `DiagnosticPayload` matches Python envelope including optional `fix`.
- **AC 2**: Pass. `registerDiagnosticValidator({ code, severity, pathSchema, owner, fn })` adds descriptor and returns it.
- **AC 3**: Pass. `getDiagnosticValidator(code)` returns the registered descriptor or `undefined`.
- **AC 4**: Pass. Conflicts in `severity`, `pathSchema`, or `owner` throw.
- **Idempotent re-registration**: Needs change. Same descriptor is harmless, but same metadata with a different `fn` overwrites — not a true no-op.
- **Module-private registry**: Mostly pass. `REGISTRY` is module-private; the exported `clearRegistryForTesting` is the only mutation leak.
- **Type safety**: Pass. No `any` casts and no unsafe `as` assertions.

## Test Review

The T1 commit covers the required ACs and the happy-path idempotent case. It does not cover the edge case where a duplicate code is re-registered with identical metadata but a different `fn`.

## Required Change Before Full Approval

Update `registerDiagnosticValidator` so identical-metadata duplicate registration is a true no-op, and add a test that re-registers the same code with identical metadata but a different function and verifies the original descriptor remains registered.
