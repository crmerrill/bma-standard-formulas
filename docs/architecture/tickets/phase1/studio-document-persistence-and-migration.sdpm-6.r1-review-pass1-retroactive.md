# R1 Review (Pass 1, retroactive) — `sdpm-6-export-hardening-regression` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family; RETROACTIVE)
**Date**: 2026-06-03
**Implementation under review**: commit `5f5df01` (test-only)
**Verdict**: APPROVE

## Findings

No Blocking, Critical, or Major issues found.

### Minor

- The API-layer regression plants only `sidecar.json` and `sidecar.broken.json`, while the orchestrator-layer regression plants the wider forbidden set: `scenarios.json`, `turn_transcripts/`, and `discarded_branches/`. Because the API response is asserted equal to canonical `deal.json`, this still proves omission by behavior, but the fixture does not independently plant every forbidden artifact at the API layer.
- Neither new regression explicitly covers symlink artifacts in the working tree. This is acceptable for `sdpm-6` because `export_deal()` never walks the working tree; it calls `service.show(sha, "deal.json")` with a literal path.
- Input validation remains delegated to git/repo errors. Future API hardening could add explicit 404/400 tests for nonexistent deals and SHAs.

## Checklist Assessment

- AC 1 is covered. `tests/orchestrator/deals/test_operational_export_sidecar.py::test_export_deal_strictly_excludes_sidecar_and_broken_archives` asserts `export_deal()` returns exactly `service.show(sha, "deal.json")`.
- AC 2 is covered. `tests/api/routers/test_deals_export_sidecar.py::test_export_endpoint_returns_only_deal_json_and_never_sidecar` asserts `GET /api/deals/{deal_id}/export?sha=...` returns the canonical `deal.json` payload and excludes sidecar sentinels.
- Forbidden artifacts are actually planted in the orchestrator test: `sidecar.json`, `sidecar.broken.json`, `scenarios.json`, `turn_transcripts/`, and `discarded_branches/`. `.git/` exists by virtue of the seeded git-backed deal repo.
- Both layers covered: direct orchestrator call and public FastAPI endpoint.
- The "no production change needed" claim is verified. `export_deal(deal_id, sha)` is path-free and returns only `service.show(sha, "deal.json")`.

## Residual Risk

The residual risks are around broader API ergonomics and future regression depth, not the core export isolation guarantee. Since the production implementation is already hardcoded to the canonical git object path `deal.json`, working-tree sidecars, broken sidecars, scenario files, transcript directories, discarded branches, and `.git/` contents are unreachable through this export path by construction.
