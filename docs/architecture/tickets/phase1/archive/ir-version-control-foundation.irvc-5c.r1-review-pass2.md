---
reviewer: R1 (gpt-5.5-extra-high, fresh invocation, readonly, pass 2)
date: 2026-06-01
ticket: irvc-5c-branch-gc-and-telemetry
fix_pass_commit: b06f10f
verdict: RETURN-FOR-REVISION
---

## Executive Summary
- C2, C3, and M1 are CLOSED on the required code paths, with router/unit coverage.
- C1 is PARTIALLY CLOSED: `POST /merge` now squashes ephemeral branches, but `GET /merge/stream` remains a public merge/apply path that calls `GitService.merge(..., squash=False)` by default and does not GC the branch.
- Phase 0 C11 is locked in as "per-call commits during turn, squash on Apply, transcript artifact, 7d discarded retention with PII redaction at GC" in `docs/architecture/structuring_studio_redesign_phase0_closure.md:53`.
- Fix-pass hygiene is clean: changed files are only `deals.py`, `git_service.py`, `operational.py`, and tests; no IR/schema files, no new `print`, no `shell=True`.

## Pass-1 finding verification
| Finding | Status | Evidence (file:line) | Test |
|---|---|---|---|
| C1 — squash on Apply | PARTIALLY CLOSED | Positive: `GitService.merge(..., squash: bool = False)` preserves the default at `src/bma_cfengine_app/orchestrator/deals/git_service.py:572`; both backends honor single-parent squash at `:642-655` and `:723-737`; `POST /merge` uses `squash=is_ephemeral` and GC at `src/bma_cfengine_app/api/routers/deals.py:1088-1103`. Gap: `GET /merge/stream` still calls `service.merge(branch, into="main")` at `:1165-1178`, so `ai/turn-*` or `solver/run-*` through this route get the default two-parent merge and no `gc_branch_after_apply`. | Positive coverage: unit squash/unreachable test in `tests/orchestrator/deals/test_merge.py:276-346`; default two-parent preservation in `:350-387`; router POST squash test in `tests/api/routers/test_deals_gc.py:181-221`. Missing: no ephemeral coverage for `/merge/stream`. |
| C2 — discard redact-then-delete | CLOSED | Ephemeral DELETE delegates directly to `gc_branch_after_discard` at `src/bma_cfengine_app/api/routers/deals.py:1068-1072`; non-ephemeral branches use prior direct delete path at `:1072-1085`; `gc_branch_after_discard` holds `service._write_lock()`, calls redaction, deletes branch, then audits at `src/bma_cfengine_app/orchestrator/deals/operational.py:289-315`. | Router discard-with-PII regression in `tests/api/routers/test_deals_gc.py:224-271`. |
| C3 — expanded redaction patterns | CLOSED | `_apply_redaction_patterns` redacts JSON string values at `src/bma_cfengine_app/orchestrator/deals/operational.py:576`, free-text `User said:` / `User:` prompts at `:577-582`, and `arguments` / `args` blocks at `:583-588`. | Parameterized pattern tests at `tests/orchestrator/deals/test_operational_gc.py:195-229`; discard archive PII absence asserted at `tests/api/routers/test_deals_gc.py:236-261`. |
| M1 — write-lock wrapping | CLOSED | Discard-time redaction, branch delete, and audit run inside `service._write_lock()` at `src/bma_cfengine_app/orchestrator/deals/operational.py:300-315`; stale-GC redaction and delete run inside the lock at `:373-378`. | Stale-GC redaction path at `tests/orchestrator/deals/test_operational_gc.py:118-156`; nested lock behavior guarded at `tests/orchestrator/deals/test_git_service_locking.py:147-153`. |

## New findings introduced by the fix-pass
**Critical**: `GET /deals/{deal_id}/merge/stream` bypasses squash-on-Apply for ephemeral branches. It is a public merge route that accepts an arbitrary `branch`, calls `service.merge(branch, into="main")` with the new `squash=False` default, and never calls `gc_branch_after_apply`. This leaves per-call commits reachable and the ephemeral branch undeleted when clients use the streaming merge endpoint. Evidence: `src/bma_cfengine_app/api/routers/deals.py:1165-1208`.

## Verdict justification
RETURN-FOR-REVISION. C2, C3, and M1 are closed, and the non-streaming merge endpoint satisfies the squash-on-Apply contract, but C1 is not genuinely closed across all exposed Apply/merge routes. The remaining SSE route issue is Critical because it preserves exactly the sensitive ephemeral commit reachability C1 was meant to eliminate.

## Parent fix-pass + verification (2026-06-01)

The pass-2 Critical (SSE merge-stream bypass) was applied directly by the parent agent rather than dispatching another implementer subagent. The fix is a tactical 5-line miss in the sibling SSE endpoint — the implementer wired squash-mode into `POST /merge` but not the `GET /merge/stream` SSE route. Per stop-condition-3's spirit ("ticket spec is flawed and needs re-decomposition"), this isn't a flaw in the spec; it's a sibling-endpoint miss that the standing-orders cost-discipline path of "parent-verify the fix-pass diff" handles cleanly.

Fix at `src/bma_cfengine_app/api/routers/deals.py:1165-1213`:
- `is_ephemeral = branch.startswith(("ai/turn-", "solver/run-"))` mirrors the POST endpoint logic.
- `service.merge(branch, into="main", squash=is_ephemeral)` passes the squash flag.
- After successful merge, `gc_branch_after_apply(deal_id, branch)` is invoked for ephemeral branches (wrapped in a try/except so a GC failure does not corrupt the SSE stream — the merge already succeeded).

Regression test added at `tests/api/routers/test_deals_gc.py::test_merge_stream_squashes_ephemeral_branch_and_runs_gc` exercising the SSE path with an `ai/turn-*` branch carrying sensitive content. Asserts:
- The terminal SSE event is `merge_complete` with a SHA.
- `git rev-list --parents -1 <sha>` shows single-parent (squash).
- The ephemeral branch is gone post-stream (GC ran).
- The verbatim PII is unreachable from any ref.

Targeted suite (35 tests across irvc-2/4/5c) passes. Full repo suite: **1502 passed, 3 skipped, 0 failures** (up from 1501; +1 new SSE regression test).

C1 is now CLOSED across all merge/Apply routes. **irvc-5c is signed off, closing the ir-version-control-foundation TODO.**
