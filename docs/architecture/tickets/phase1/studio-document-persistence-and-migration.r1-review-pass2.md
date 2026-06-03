# R1 Review (Pass 2) — `studio-document-persistence-and-migration` decomposition fold-back

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; pass-2 fresh from pass-1 reviewer)
**Date**: 2026-06-03
**Decomposition under review**: `docs/architecture/tickets/phase1/studio-document-persistence-and-migration.md` (post-fold-back)
**Pass-1 review**: `studio-document-persistence-and-migration.r1-review-pass1.md`
**Verdict**: APPROVE-WITH-CHANGES

## Pass-1 Audit Table

| ID | Status | Evidence |
|---|---|---|
| C1 | CLOSED | sdpm-2 pins exact `commit_deal` signature with `sidecar_payload`; CommitRequest extended with forwarding behavior. |
| C2 | PARTIAL | AC 3 enumerates exact 5 decorators + helper rewiring. But sdpm-5 user journey still says `POST /deals/{id}/studio` (non-existent route). |
| M1 | CLOSED | `schema_version: str = "1.0.0"`. |
| M2 | CLOSED | First-open commit metadata pinned. |
| M3 | CLOSED | AI provenance footer format pinned exactly. |
| M4 | CLOSED | sdpm-4 deps include irvc-3-legacy-migration. |
| M5 | CLOSED | sdpm-6 pins both `export_deal()` and `GET /deals/{deal_id}/export?sha={sha}` plus regression test. |
| M6 | CLOSED | Mermaid graph adds external edges. |
| Mi1 | PARTIAL | Fold-back picks "working tree only" for parse-failure archival, but then says "next successful save commit will include sidecar.broken.json in the commit tree." Internally ambiguous. |
| Mi2 | CLOSED | sdpm-5 pins exhaustive manifest field set + rejection list. |
| Mi3 | CLOSED | layout_overrides inner shape pinned. |
| Mi4 | CLOSED | BLOCKED_ON_BACKEND classified as deferred Phase 2. |
| N1 | CLOSED | irvc → sdpm-1 graph edge removed; sdpm-1 deps remain none. |
| N2 | CLOSED | sdpm-3 scope split. |
| N3 | CLOSED | sdpm-6 out-of-scope mirrors irvc-5a forbidden-artifact list. |

## New Findings

### Major

**P2-M1** — sdpm-2 AC 3: broken-sidecar archival lifecycle is internally ambiguous. Text says working-tree only, but also says next successful save commit will include sidecar.broken.json. Pick one and pin the lifecycle. Recommendation: **read-time local only** (sidecar.broken.json is NOT committed; the next successful save with valid sidecar overwrites/deletes the local broken file) — keeps history clean and avoids permanent recovery-artifact pollution.

### Minor

**P2-m1** — sdpm-5 user journey still cites `POST /deals/{id}/studio` (the pass-1 C2 wrong endpoint). Replace with one of the real deleted routes (e.g., `POST /deals`) or a table-driven "each legacy route returns 404" journey.

## Master Contract Coverage

All Phase 0 / master obligations covered.

## Verdict Rationale

APPROVE-WITH-CHANGES. The fold-back closes substantive pass-1 precision gaps. Two small residual issues remain — both narrow doc patches, parent-verify path appropriate.

## Sign-off Recommendation

Apply two narrow patches:
1. sdpm-2 AC 3: pin sidecar.broken.json as read-time local only (not committed).
2. sdpm-5 user journey: replace POST /deals/{id}/studio with POST /deals (real deleted route).

After: APPROVE for T1.

---

## Parent-verify patches applied (2026-06-03)

**Parent agent (Claude Opus 4.7)** applied both residual patches per the APPROVE-WITH-CHANGES recommendation (no R1 pass-3 dispatched per arch-heavy protocol's parent-verify-the-third-pass guidance).

**Verdict after parent-verify**: APPROVE — sdpm decomposition ready for T1 on sdpm-1.
