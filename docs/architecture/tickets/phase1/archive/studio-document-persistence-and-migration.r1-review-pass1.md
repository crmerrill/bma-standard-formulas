# R1 Review (Pass 1) — `studio-document-persistence-and-migration` decomposition

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family from gemini-3.1-pro D1 + Claude parent + future Claude implementers)
**Date**: 2026-06-03
**Decomposition under review**: `docs/architecture/tickets/phase1/studio-document-persistence-and-migration.md`
**Verdict**: RETURN-FOR-REVISION

## Summary

The decomposition captures the correct architectural shape: sidecar is minimal, git-tracked, never exported, parse-failure-safe, and legacy AI provenance is kept out of sidecar. However, several acceptance criteria are below the precision bar established by `irvc-1`, `irvc-3`, `irvc-5a`, and the closed `studio-document-and-store` decomposition. The most important issues are exact API/signature pins, exact migration commit metadata pins, exact legacy endpoint enumeration, and a likely mismatch between sidecar `schema_version: int = 1` and the repo's existing string version conventions.

## Findings

### Critical

**C1** — **`sdpm-2` AC 1**: `GitService.commit_deal` extension is under-specified and risks drifting from the landed `sds-0` surface. Current landed signature accepts `commit_target='main'`. AC says only "extended to support sidecar_payload"; allows either extending `commit_deal` or adding `commit_deal_with_sidecar`. Pin the exact signature: `commit_deal(deal_payload, *, author, message, parent_sha=None, commit_target='main', sidecar_payload: dict[str, Any] | bytes | None = None) -> str`. Pin that one commit tree writes both files; preserve `parent_sha` validation against `commit_target`; no separate `commit_deal_with_sidecar` path.

**C2** — **`sdpm-5` AC 3**: legacy FastAPI endpoint deletion list is not exact and cites `POST /deals/{id}/studio` which does not exist. Actual legacy surface backed by the methods named:
- `GET /deals` → `list_studio_deals`
- `GET /deals/{deal_id}` → `load_studio_snapshot`
- `POST /deals` → `save_studio_ir`
- `GET /deals/{deal_id}/solver-presets` → `list_solver_presets`
- `POST /deals/{deal_id}/solver-presets` → `save_solver_preset`

Plus internal helpers (`_ensure_canonical_deal`, `_extract_collateral_risk_settings`) that fall back to `load_studio_snapshot`. Enumerate exact decorators + state whether helpers are removed/replaced/retained.

### Major

**M1** — **`sdpm-1` AC 1**: `schema_version: int = 1` conflicts with repo convention. Engine IR uses `schema_version: str` (values like `"2.0.0"`); manifest uses `schema_version_pin` (string). Recommendation: `schema_version: str = "1.0.0"` for consistency, OR justify the integer choice explicitly.

**M2** — **`sdpm-3` AC 1**: initial commit message not pinned. `irvc-3` pinned `Migrate v1`, `Migrate v2`. Pin author + message: e.g., author `system:migration`, message `Migrate deal.json` (subject) with empty body unless sdpm-4 provenance is present.

**M3** — **`sdpm-4` AC 4**: AI provenance commit-body format not pinned. Pin exact footer:
```
Migrate v{N}

Legacy-Studio-Provenance:
<canonical JSON object, sorted keys, 2-space indent>
```
Pin empty behavior (no provenance → no `Legacy-Studio-Provenance:` section).

**M4** — **`sdpm-4` Dependencies**: should include `irvc-3-legacy-migration` explicitly (sdpm-4 extends the migration window pattern). Currently lists only sdpm-2.

**M5** — **`sdpm-6` AC 2**: pin the public API path `GET /deals/{deal_id}/export?sha={sha}` as well as `export_deal()`. Add API-level regression test `tests/api/routers/test_deals_export_sidecar.py::test_export_endpoint_returns_only_deal_json_and_never_sidecar`.

**M6** — **Mermaid graph**: omits external dependencies for sdpm-4 (irvc-3), sdpm-5 (irvc-3 + sds), sdpm-6 (irvc-5a). Update edges or add a note.

### Minor

**Mi1** — **`sdpm-2`** parse-failure rollback "moved/archived" wording: pin whether `sidecar.broken.json` archival creates a recovery commit OR writes only to working-tree (former changes history on read; latter creates uncommitted dirty state). Pick one and pin.

**Mi2** — **`sdpm-5` AC 1**: pin the full post-cutover `manifest.json` allowed field set exhaustively per irvc-3's bar:
- `deal_id`, `deal_name`, `asset_class`, `schema_version_pin`, `created_at`, `updated_at`
And explicitly reject `studio_current_version`, `studio_versions` (and `solver_presets_library` if solver presets are also being retired).

**Mi3** — **`sdpm-1`** `layout_overrides` shape too open. Pin minimum keys/types: `x: float`, `y: float`, `collapsed: bool | None`.

**Mi4** — **R1 flag for BLOCKED_ON_BACKEND**: classify the follow-on as either an in-scope Phase 1 sibling OR a Phase 2 deferred follow-on.

### Nit

**N1** — **`sdpm-1`** Dependencies says `none`, but graph edge shows `irvc --> sdpm-1`. Internally inconsistent.

**N2** — **`sdpm-3`** scope sentence combines missing `.git/` and missing `sidecar.json` cases; split them.

**N3** — **`sdpm-6`** out-of-scope note: mirror irvc-5a's forbidden-artifact list (`sidecar.json`, `sidecar.broken.json`, `scenarios.json`, `turn_transcripts/`, `discarded_branches/`, `.git/`).

## Master Contract Coverage

Covered (with caveats noted in findings): atomic commit (sdpm-2), parse-failure rollback (sdpm-2), first-open (sdpm-3), legacy migration (sdpm-4), retire transitional fields/APIs (sdpm-5), export hardening (sdpm-6).

Potential missing coverage:
- How sidecar save integrates with the landed `POST /deals/{deal_id}/commit` (sds-0 extension): if sidecar persistence is backend-only, say so; if UI submits `sidecar_payload`, the `CommitRequest` model needs a companion field.
- Whether parse-failure archival creates a commit or dirty working-tree state.

## What Landed Well

- Sidecar boundary architecturally sound, matches Phase 0 B5/M16.
- Ticket order is sensible: schema → persistence → first-open + migration → cleanup → export regression.
- `SIDECAR_LOAD_FAILED` diagnostic message is precise and user-safe.
- `sdpm-5` chooses hard cutover over preserving parallel APIs (right call).

## Verdict Rationale

RETURN-FOR-REVISION. Conceptually correct but not yet implementation-ready at the precision bar. ACs leave too much discretion around `commit_deal` signature, migration commit metadata, route deletion, and version-field conventions. Not architectural blockers; small D1 revision pass should suffice.

## Sign-Off Recommendation

D1 should revise with:
1. Exact `commit_deal(..., sidecar_payload=...)` signature preserving `commit_target`.
2. Sidecar `schema_version` decision pinned (recommend string).
3. Exact first-open commit author + message.
4. Exact legacy AI provenance commit-body format.
5. Exact sdpm-5 endpoint + helper deletion list from current `routers/deals.py`.
6. Explicit external dependency edges (irvc-3, irvc-5a, sds).
7. BLOCKED_ON_BACKEND classification.
8. CommitRequest sidecar_payload extension or backend-only declaration.

After revision: send to R1 pass-2.
