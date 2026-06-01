---
reviewer: R1 (gpt-5.5-extra-high, fresh invocation, readonly)
date: 2026-06-01
ticket: irvc-5c-branch-gc-and-telemetry
implementation_commit: a3a695f
verdict: RETURN-FOR-REVISION
---

*Note: this artifact was written to disk after the fact (during ir-version-control-foundation closure cleanup). The original review was consumed live during the irvc-5c lifecycle, drove the fix-pass at `b06f10f` (and the subsequent SSE-bypass fix at `5d2a9ef`), and was the basis for the architectural decision to add a `squash` parameter to `GitService.merge` (Path B per user direction). This reconstruction preserves the audit trail per the Phase 0 M15 independence contract.*

## Executive Summary
- T1 maps AC 1-5 to tests, and the implementation adds the requested public entry points with stable callable signatures.
- AC 1, 2, 4, and 5 are mostly implemented, with router wiring limited to the intended GC hooks.
- AC 3 is not satisfied: Apply/Discard paths can leave verbatim PII in reachable or recoverable git history, and the redaction regex does not remove non-JSON verbatim prompts.
- The destructive `commit-tree` / `update-ref` rewrite path is not protected by the repo write lock, creating a race with merge/delete writers.
- Verdict is `RETURN-FOR-REVISION` because the PII-retention issues are Critical.

## Acceptance criteria audit

| AC | Status | Evidence | Notes |
|---|---|---|---|
| 1 — Apply/Discard hooks | partial | `src/bma_cfengine_app/api/routers/deals.py:1068`, `:1087`, `src/bma_cfengine_app/orchestrator/deals/operational.py:274` | Router hooks are wired only for `ai/turn-*` / `solver/run-*`. However `gc_branch_after_discard` does not itself delete; the router deletes first and the hook only audits. |
| 2 — 7d retention GC | ✓ | `src/bma_cfengine_app/orchestrator/deals/operational.py:308` | `retention_days` defaults to 7 and stale ephemeral branches are selected by tip commit timestamp. |
| 3 — PII redaction | ✗ | `src/bma_cfengine_app/orchestrator/deals/operational.py:358`, `:480`, `src/bma_cfengine_app/api/routers/deals.py:1097` | Redaction is only invoked in stale GC. Apply/Discard do not redact before branch deletion/merge reachability changes, and non-JSON prompt text is not scrubbed. |
| 4 — what-if/* never GC'd | ✓ | `src/bma_cfengine_app/orchestrator/deals/operational.py:339` | Stale GC only processes `ai/turn-*` and `solver/run-*`; router hooks also skip `what-if/*`. |
| 5 — size telemetry | ✓ | `src/bma_cfengine_app/orchestrator/deals/operational.py:565` | Runs `git count-objects -v`, aggregates `p95_bytes`, handles empty result, and emits `logger.warning` with threshold metadata. |

## Findings

### C1 — Critical — `src/bma_cfengine_app/api/routers/deals.py:1097`
**Issue + evidence**: The Apply path merges first, then calls `gc_branch_after_apply`, which only deletes the branch ref. `GitService.merge` creates a real merge commit with the ephemeral branch tip as the second parent (`src/bma_cfengine_app/orchestrator/deals/git_service.py:633`, `:708`). That means branch-unique commits, including their original commit messages, remain reachable through `main` after branch deletion. This fails AC 3 and the operational design's squash-on-Apply / PII-redaction intent.

**Recommended fix**: Redact or squash before the branch tip becomes reachable from `main`. Prefer making Apply a squash-style merge for ephemeral branches, or rewrite the ephemeral branch under the repo write lock before merge and ensure `main` references only sanitized commits. Add a regression test that commits a sensitive tool-call message on `ai/turn-*`, applies it, deletes the branch, and asserts `git log --all --format=%B` contains no verbatim prompt/arg values.

### C2 — Critical — `src/bma_cfengine_app/api/routers/deals.py:1071`
**Issue + evidence**: The Discard endpoint deletes the branch before calling `gc_branch_after_discard`; the hook then only writes an audit record (`src/bma_cfengine_app/orchestrator/deals/operational.py:289`). No redaction or redacted archive happens on this path, and after deletion the branch can no longer be rewritten by the chosen `commit-tree` / `update-ref` approach. The original objects may be unreachable from refs, but they remain in `.git/` until pruning and are not replaced with the required redacted summary.

**Recommended fix**: Move ephemeral discard ownership into `gc_branch_after_discard`: under the write lock, rewrite/archive redacted messages first, then delete the branch, then audit. The router should delegate to that hook instead of deleting first for ephemeral branches.

### C3 — Critical — `src/bma_cfengine_app/orchestrator/deals/operational.py:550`
**Issue + evidence**: `_apply_redaction_patterns` only rewrites JSON string pairs matching `"key": "value"`. It does not remove verbatim user prompts outside JSON, even though the T1 stale-GC fixture includes a `User said: 'Please add...'` line (`tests/orchestrator/deals/test_operational_gc.py:129`). The archived `redacted_messages.txt` is built from this partially redacted message (`src/bma_cfengine_app/orchestrator/deals/operational.py:522`), so it can preserve the exact user prompt.

**Recommended fix**: Parse the expected tool-call transcript format and emit a purpose-built sanitized summary, e.g. `(model, tool_name, arg_shape)`, rather than trying to redact arbitrary commit text in place. At minimum, remove known prompt fields and `User said:` style free-text sections before writing either git commits or archive files.

### M1 — Major — `src/bma_cfengine_app/orchestrator/deals/operational.py:417`
**Issue + evidence**: The destructive rewrite path uses raw `git log`, `git commit-tree`, and `git update-ref` subprocesses without holding `GitService._write_lock`. Meanwhile merge and branch deletion serialize via that lock (`src/bma_cfengine_app/orchestrator/deals/git_service.py:180`, `:400`, `:580`). A concurrent merge/delete can race with redaction and leave either stale refs or reachable unredacted commits.

**Recommended fix**: Expose a small GitService transaction/helper for operational rewrites, or implement the redaction/delete flow in GitService itself. Use `git update-ref refs/heads/<branch> <new_tip> <old_tip>` so the rewrite fails if the branch moved during redaction.

### Minor
None.

### Nit
None.

## Verdict justification
RETURN-FOR-REVISION. The implementation has multiple Critical AC 3 failures around PII retention in git history, so it must return for revision. C1 in particular is architecturally rooted in the irvc-2 merge primitive (two-parent commits leave ephemeral history reachable from main); resolving it cleanly requires extending the merge primitive itself with a squash mode rather than papering over the issue with post-hoc history rewrites in irvc-5c's GC hook.

## Disposition (resolved by `b06f10f` + `5d2a9ef`)

- **C1**: Resolved per **Path B** (user-approved): added `squash` parameter to `GitService.merge`, router defaults `squash=True` for `ai/turn-*` and `solver/run-*`. Both `POST /merge` and `GET /merge/stream` SSE route honor squash + GC for ephemeral branches.
- **C2**: Resolved by routing the DELETE endpoint through `gc_branch_after_discard` for ephemeral branches; the GC hook now holds the GitService write lock and redacts-then-deletes-then-audits.
- **C3**: Resolved by expanding `_apply_redaction_patterns` to scrub JSON values, free-text `User said:` / `User:` prompts, and `arguments:` / `args=` blocks.
- **M1**: Resolved by wrapping both the discard-time and stale-GC redaction paths in `service._write_lock()`.

R1 pass-2 (see `archive/ir-version-control-foundation.irvc-5c.r1-review-pass2.md`) verified C2/C3/M1 closed and surfaced one additional Critical (sibling SSE bypass) that the parent agent applied directly per stop-condition-3's tactical-not-spec-flaw spirit. Final commit `5d2a9ef`.
