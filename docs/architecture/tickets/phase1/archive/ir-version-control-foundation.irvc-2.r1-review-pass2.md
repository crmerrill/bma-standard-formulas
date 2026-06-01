---
reviewer: R1 (gpt-5.5-extra-high, fresh invocation, readonly, pass 2)
date: 2026-06-01
ticket: irvc-2-typed-field-merge
fix_pass_commit: ca39844
verdict: APPROVE
---

## Executive Summary
- B1 is closed: top-level `DealDefinition` conflicts no longer emit `MERGE_CONFLICT` with `entity_kind="deal"`; they resolve to the target-side value.
- M1 is closed: the pygit2 path creates the merge commit on `into` and checks out the merge tree when `into` is the current branch, keeping worktree/index aligned.
- M2 is closed: the CLI path now builds the merge tree from `ours_sha` through a temporary index and lands it with `update-ref`.
- The fix-pass touched only docs, `merge.py`, `git_service.py`, and merge tests; no IR/schema, FastAPI, migration, `print`, or `shell=True` regression was found.
- Original entity-level AC 1-4 behavior remains intact by inspection: entity collection conflicts still use the pinned seven-kind payload path.

## Pass-1 finding verification
| Finding | Status | Evidence (file:line) | Test |
|---|---|---|---|
| B1 — top-level entity_kind="deal" | CLOSED | `src/bma_cfengine_app/orchestrator/deals/merge.py:59-73` now handles non-collection fields and, on `_CONFLICT`, assigns `merged = o_val` instead of calling `_build_conflict`; `_build_conflict` is only reached from collection/entity paths at `src/bma_cfengine_app/orchestrator/deals/merge.py:133-156` and `src/bma_cfengine_app/orchestrator/deals/merge.py:192-195`, whose `entity_kind` values come from `_ENTITY_COLLECTIONS` at `src/bma_cfengine_app/orchestrator/deals/merge.py:33-41`. | `tests/orchestrator/deals/test_merge.py:211-272` parametrizes pygit2/CLI, creates divergent `deal_name` edits, asserts the result is not a `DiagnosticPayload`, and asserts target value `"name-from-branch-a"` wins. |
| M1 — pygit2 index not updated | CLOSED | `src/bma_cfengine_app/orchestrator/deals/git_service.py:561-573` builds the merge tree from `ours_commit.tree` with merged `deal.json` and creates a two-parent commit on `refs/heads/{into}`; `src/bma_cfengine_app/orchestrator/deals/git_service.py:575-582` detects when HEAD is already `into` and calls `repo.checkout_tree(merge_commit.tree)` plus `repo.state_cleanup()`. Because HEAD is already symbolic to `refs/heads/{into}`, the `create_commit` target ref update makes an explicit `set_head` unnecessary in this path. | Exercised by `tests/orchestrator/deals/test_merge.py:211-272` for the successful checked-out-`into` path under pygit2 and CLI. Status cleanliness is verified by inspection of the checkout-tree update path rather than a dedicated `git status` assertion. |
| M2 — CLI tree from current checkout | CLOSED | `src/bma_cfengine_app/orchestrator/deals/git_service.py:614-629` writes the merged blob, creates a temporary `GIT_INDEX_FILE`, runs `read-tree` from `ours_sha`, updates only `deal.json` with `update-index --cacheinfo`, and writes that tree; `src/bma_cfengine_app/orchestrator/deals/git_service.py:630-631` cleans the temp index with `Path.unlink(missing_ok=True)`; `src/bma_cfengine_app/orchestrator/deals/git_service.py:640-648` uses `commit-tree` with `-p ours_sha` and `-p theirs_sha`, preserves `Merge branch '{branch}' into '{into}'`, and lands it via `update-ref`. | `tests/orchestrator/deals/test_merge.py:275-325` parametrizes pygit2/CLI, leaves `what-if/throwaway` checked out, merges into `main`, asserts `main:deal.json` has the merged result, asserts `main` points at the merge SHA, and asserts the checked-out branch remains unchanged. |

## New findings introduced by the fix-pass
None.

## Verdict justification
APPROVE. Every pass-1 finding is closed, and the fix-pass did not introduce any new Blocking, Critical, Major, Minor, or Nit findings under the requested scope.
