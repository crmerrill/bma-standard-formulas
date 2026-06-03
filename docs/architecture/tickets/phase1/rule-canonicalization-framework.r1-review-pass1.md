# R1 Review (Pass 1) — `rule-canonicalization-framework` decomposition

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family from gemini-3.1-pro D1 + Claude parent + future Claude implementers)
**Date**: 2026-06-03
**Decomposition under review**: `docs/architecture/tickets/phase1/rule-canonicalization-framework.md`
**Verdict**: APPROVE-WITH-CHANGES (parent-verified)

## Summary

The decomposition is structurally sound and tracks the Phase 0 master contract: equivalence predicate, fragmentation detector, opt-in QuickFix mutation, info-only interleaved detector, negative tests, and round-trip semantic equivalence are all present. It correctly keeps compile-to-IR unchanged and defers `SHARED_TRIGGER_BRANCHABLE` to Phase 3. The remaining issues are contract-pinning gaps against the irvc-1 specificity bar and the just-closed validation/catalog surfaces — tactical, not architectural.

## Findings

### Critical

**C1** — rcf-2 missing catalog row ACs for `RULE_FRAGMENTATION_CONSOLIDATABLE`. Pin severity (warning), owner (both), exact path schema, exact message template, quick-fix mapping (`canonicalize_consolidate_rule_run`), and same-commit catalog requirement. The vpc-4 CI guard fails without this.

**C2** — rcf-4 missing catalog row ACs for `INTERLEAVED_RULES_FACTORABLE`. Pin severity (info), owner (both), exact path schema, exact message template, quick-fix column ("Manual review only"), and force `fix = null` (NOT manual_resolve_*) since this is info-only.

**C3** — rcf-5 cashflow equivalence oracle not specific enough. Pin: per-period, per-bond cashflow vector equality on the engine's serialized output fields; exact comparison for deterministic decimal/currency outputs; tolerance `abs <= 1e-9 / rel <= 1e-12` for any floats; period count + bond IDs + cashflow field set MUST be identical post-fix.

### Major

**M1** — rcf-3 missing explicit dependency on `studio-document-and-store` (sds-1 DealAction discriminated union; sds-5 dispatch revision for autosave commit attribution).

**M2** — rcf-3 typed-action shape underspecified. Pin: `CanonicalizeConsolidateRuleRunAction = { type: 'canonicalizeConsolidateRuleRun'; payload: { start_index: number; end_index: number } }`, included in `DealAction`, exhaustively handled, mutates only active session's `working_tree.waterfall_rules`. Pin invalid-range behavior (out-of-bounds, start>=end, non-consolidatable current run): no-op + warning diagnostic.

**M3** — rcf-5 fixture coverage should be STATUS.md-driven, not hardcoded. Replace "load the 5 known fixtures" with "load every fixture classified STRUCTURAL or QUANTITATIVE GOLDEN in `tests/fixtures/STATUS.md`; assert minimum set includes the 5 named fixtures."

**M4** — rcf-2 diagnostic payload schema not pinned beyond `fix`. Add: `payload: { start_index, end_index, rule_ids: string[], source: string, target_count: number }`. `path` uses the same range contract as catalog.

### Minor

**Mi1** — rcf-1 "mutates the shared source" needs local definition. Pin: an intervening rule mutates the shared source if any of (a) `to_targets` contains the source, (b) the rule's `source` aliases via group routing to the shared source.

**Mi2** — rcf-4 should explicitly say it's a heuristic info-only visibility detector (not a safe-consolidation claim).

**Mi3** — rcf-4 out-of-scope: also explicitly mention SHARED_TRIGGER_BRANCHABLE belongs to Phase 3 `branch-canonicalization-after-waterfall-branch`.

### Nit

**N1** — rcf-2 prefer `canonicalizationValidators.ts` module pattern (matching `structuralValidators.ts` from ve-2): module-level `registerDiagnosticValidator(...)` call; worker imports module so registration runs before `iterDiagnosticValidators()` is called. Avoid implying `workerBridge.ts` owns registration.

## What Landed Well

- Phase 0 B6 preserved: canonicalization opt-in only; compile-to-IR unmodified.
- Equivalence predicate field list pinned tightly to avoid false positives.
- Master contract coverage complete (predicate → detector → QuickFix action → info-only → tests).
- Worker-hosted via `iterDiagnosticValidators()` aligns with ve-1.

## Verdict Rationale

Structural shape is right; sequencing is right; no architectural rework needed. The findings are AC-level contract pins that the irvc-1 specificity bar requires. Parent-direct fold-back is appropriate.

## Sign-off Recommendation

APPROVE-WITH-CHANGES. Parent applies the 3C+4M+3m+1n folds directly; no R1 pass-2 needed since findings are tactical.

---

## Parent-verify fold-back applied (2026-06-03)

(See follow-up file edits.)
