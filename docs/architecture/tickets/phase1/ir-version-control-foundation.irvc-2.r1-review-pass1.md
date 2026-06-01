---
reviewer: R1 (gpt-5.5-extra-high, fresh invocation, readonly)
date: 2026-05-31
ticket: irvc-2-typed-field-merge
implementation_commit: 50dd7a2
verdict: RETURN-FOR-REVISION
---

## Executive Summary
- The core entity-keyed three-way merge implementation satisfies the main happy path and same-field conflict tests for bond/account/fee.
- `MERGE_CONFLICT` is registered through `@diagnostic_code` with `Severity.error`, `Owner.backend`, and is retrievable through `get_diagnostic("MERGE_CONFLICT")`.
- Blocking issue: top-level `DealDefinition` conflicts emit `entity_kind="deal"`, which violates the ticket-pinned AC 5 literal enum.
- Major backend consistency issues remain in successful merge commit creation, especially pygit2 index state and CLI dependence on the current checkout/index.

## Acceptance criteria audit
| AC | Status | Evidence | Notes |
|---|---|---|---|
| 1 — non-overlapping merge | ✓ | `tests/orchestrator/deals/test_merge.py:104`, `src/bma_cfengine_app/orchestrator/deals/merge.py:173` | Same entity, different fields merge field-by-field. |
| 2 — overlapping conflict | ✓ | `tests/orchestrator/deals/test_merge.py:156`, `src/bma_cfengine_app/orchestrator/deals/merge.py:187` | Same entity field conflicts return `DiagnosticPayload`. |
| 3 — typed Pydantic merge | ✓ | `src/bma_cfengine_app/orchestrator/deals/git_service.py:536`, `src/bma_cfengine_app/orchestrator/deals/merge.py:46` | Loads sides with `model_validate_json` and merges model fields, not text diffs. It uses `model_dump(mode="json")` plus `json.dumps`, not `model_dump_json`, but remains typed. |
| 4 — catalog registration | ✓ | `src/bma_cfengine_app/orchestrator/deals/merge.py:17` | Descriptor is registered and retrievable as `MERGE_CONFLICT`. |
| 5 — payload schema | partial | `src/bma_cfengine_app/orchestrator/deals/merge.py:67`, `src/bma_cfengine_app/orchestrator/deals/merge.py:208` | Entity conflicts use the six keys, but root field conflicts produce `entity_kind="deal"`, outside the pinned literal set. |

## Findings

### B1 — Blocking — `src/bma_cfengine_app/orchestrator/deals/merge.py:67`
**Issue + evidence**: AC 5 pins `entity_kind` to exactly seven literals: `bond`, `account`, `fee`, `trigger`, `calculation`, `rule`, `collateral_group`. The implementation merges non-collection `DealDefinition` fields first, and on conflict calls `_build_conflict("deal", "", field_name, ...)`. `_build_conflict` then places that value directly in `payload["entity_kind"]`, so an overlapping edit to `deal_name`, `schema_version`, `asset_class`, `deal_knobs`, etc. returns a `MERGE_CONFLICT` payload outside the public schema.

**Recommended fix**: Do not emit `MERGE_CONFLICT` payloads with `entity_kind="deal"` unless the ticket schema is explicitly expanded. Either constrain this ticket's conflict payloads to the seven entity collections, or introduce a ticket-approved representation for top-level fields and update the pinned schema/tests accordingly.

### Critical
None.

### M1 — Major — `src/bma_cfengine_app/orchestrator/deals/git_service.py:569`
**Issue + evidence**: The pygit2 merge path updates `refs/heads/{into}` and writes `deal.json` to the working tree, but does not update the index. `commit_deal`'s pygit2 path explicitly reads/adds/writes the index after writing `deal.json`; `_merge_pygit2` does not. On a checked-out `into`, this can leave the repository dirty immediately after a successful merge commit.

**Recommended fix**: After writing the merged file, update the index to match the merge commit/worktree, or use a proper checkout/index update flow for the new merge tree.

### M2 — Major — `src/bma_cfengine_app/orchestrator/deals/git_service.py:610`
**Issue + evidence**: The CLI merge path writes merged `deal.json` into the current working tree, runs `git add`, then `git write-tree`. That tree comes from the current checkout/index, not necessarily from `ours_sha`/`into`. If `into` is not the currently checked-out branch, or if the per-deal repo gains other tracked files like `manifest.json`/transcripts, the merge commit can accidentally include the wrong tree state.

**Recommended fix**: Build the merge tree from `ours_sha` explicitly, replacing only `deal.json` with the merged blob. A temporary index via `GIT_INDEX_FILE` plus `git read-tree <ours_sha>`/`git update-index --cacheinfo ...` would avoid coupling correctness to the caller's checkout.

### Minor
None.

### Nit
None.

## Verdict justification
RETURN-FOR-REVISION. The implementation is close, but AC 5 is a pinned public contract and the current code can return an invalid `MERGE_CONFLICT` payload. The backend merge commit consistency issues should also be fixed before this lands, so pygit2 and CLI remain behaviorally equivalent.
