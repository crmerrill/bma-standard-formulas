# Closure Artifact — `ir-version-control-foundation`

**Phase**: Phase 1
**Status**: COMPLETE
**Date closed**: 2026-06-01
**Branch**: `feature/securitization-structuring-tool`
**Final commit**: `5d2a9ef`
**Test suite**: 1502 passed, 3 skipped, 0 failures (baseline at todo-start: 1426; net +76 new tests)

This artifact records the multi-agent execution audit trail for the `ir-version-control-foundation` Phase 1 todo per the Phase 0 M15 independence contract (separate invocation, read-only review, R1 tier, cross-family preference, multi-pass with closure record). It is the contractual evidence that the locked-in independence contract was honored at every step.

For the underlying review documents, see `archive/ir-version-control-foundation.*.r1-review-pass{1,2}.md` and `archive/validation-parity-contract.vpc-1.r1-review-pass1.md`.

## Decomposition

| Pass | Decomposer | Reviewer | Family vs author | Verdict | Output |
|---|---|---|---|---|---|
| 1 | gemini-3.1-pro (D1) | gpt-5.5-extra-high (R1) | cross-family ✓ | RETURN-FOR-REVISION | 4 tickets — see `archive/ir-version-control-foundation.r1-review-pass1.md` |
| 2 | gemini-3.1-pro (D1, resumed) | gpt-5.5-extra-high (R1, fresh) | cross-family ✓ | RETURN-FOR-REVISION | 7 tickets (split irvc-5 into 5a/5b/5c) — see `archive/ir-version-control-foundation.r1-review-pass2.md` |
| 3 | gemini-3.1-pro (D1, resumed) | parent-verified (per user "don't over-engineer planning" directive) | n/a | APPROVED FOR T1 | Final 7-ticket envelope at `ir-version-control-foundation.md` |

## Per-ticket lifecycle audit

R1 reviewer is gpt-5.5-extra-high in every row (cross-family from all Claude-family implementers and the Gemini-family decomposer, satisfying the Phase 0 independence contract).

| Ticket | T1 (test author) | Implementer | R1 pass-1 verdict | R1 pass-2 verdict | Final commit | Notes |
|---|---|---|---|---|---|---|
| `irvc-1-core-git-service` | gpt-5.3-codex-high-fast (`6e67a3a`) | claude-4.6-opus-high-thinking I1 (`d57927a`) | RFR — 1 Blocking + 1 Critical + 3 Major | RFR — M1 PARTIAL | `52771d3` (post user-approved hardening fix) | R1 pass-2 surfaced a real latent bug: git accepts SOH bytes in commit subjects, so the SOH-delimited CLI log parser would have produced malformed output. User approved hardening fix switching to `git log -z` with NUL field separators. |
| `vpc-1-diagnostic-code-decorator` (cross-todo blocker for irvc-2) | gpt-5.3-codex-high-fast (`00e3cf8`) | claude-4.6-sonnet-medium-thinking I2 (`6010301`) | APPROVE-WITH-CHANGES — 1 Minor | n/a (Major-only path) | `78bc7ef` | Cross-todo dependency for `irvc-2-typed-field-merge`'s `MERGE_CONFLICT` registration. Required a one-todo detour into `validation-parity-contract` to land vpc-1 ahead of irvc-2. |
| `irvc-2-typed-field-merge` | gpt-5.3-codex-high-fast (`a5d97b9`) | claude-4.6-opus-high-thinking I1 (`50dd7a2`) | RFR — 1 Blocking + 2 Major | APPROVE | `cb35a1a` | B1: top-level `DealDefinition` field conflicts had emitted `entity_kind="deal"` violating AC 5's pinned literal set. Fixed by switching top-level fields to last-writer-wins-on-target. |
| `irvc-3-legacy-migration` | gpt-5.3-codex-high-fast (`6037f00`) | claude-4.6-sonnet-medium-thinking I2 (`8c68fde`) | APPROVE-WITH-CHANGES — 2 Major | n/a (Major-only → parent-verified) | `df7ba80` | M1: versioned `load_deal(deal_id, version=N)` had only resolved migration commits. M2: migration not held under repo write lock. Both fixed. |
| `irvc-4-http-api` | gpt-5.3-codex-high-fast (`6b7662a`) | claude-4.6-sonnet-medium-thinking I2 (`cc6a32f`) | RFR — 1 Critical + 2 Major + 2 Minor | n/a (1 Critical < non-trivial threshold → parent-verified) | `a113572` | C1: `DELETE /branches/main` was reachable. M1: `parent_sha` non-nullable. M2: SSE `merge_failed` lacked diagnostic. All fixed. |
| `irvc-5a-export-and-fsck` | gpt-5.3-codex-high-fast (`f36be2f`) | claude-4.6-opus-high-thinking I1 (`29420cd`) | RFR — 2 Blocking | APPROVE | `1c2948a` | B1: `_run_fsck` was bypassable through direct `GitService` construction. B2: `restore_deal` not atomic (deleted `.git/` before clone success). Both fixed via `_fsck_on_init` in GitService and `.git.old` atomic-swap with rollback. |
| `irvc-5b-backup-restore` | gpt-5.3-codex-high-fast (`0d142fd`) | claude-4.6-sonnet-medium-thinking I2 (`b8d7b39`) | APPROVE-WITH-CHANGES — 1 Major + 1 Minor | n/a (Major-only path → parent-direct fix) | `59d2c6f` | M1: bundle substring match could pick wrong deal's bundle. m1: missing-deal failed via raw subprocess error. Both tightened. |
| `irvc-5c-branch-gc-and-telemetry` | gpt-5.3-codex-high-fast (`3e9cbe1`) | claude-4.6-sonnet-medium-thinking I2 (`a3a695f`) | RFR — 3 Critical + 1 Major | RFR — Critical (sibling SSE bypass) | `5d2a9ef` (post parent-direct sibling fix) | Pass-1 surfaced architectural ambiguity touching irvc-2 + irvc-4 + irvc-5c. User approved Path B: add `squash` parameter to `GitService.merge` and route ephemeral branches through it. Pass-2 caught a sibling-endpoint miss (`GET /merge/stream` SSE bypassed squash); applied directly + parent-verified rather than spawning a third R1/implementer pair (per stop-condition-3 spirit: ticket spec NOT flawed, just a sibling miss). |

## Independence contract attestations

- **Cross-family preserved on every review pass**: every R1 review was performed by gpt-5.5-extra-high (GPT family). T1 test authors used gpt-5.3-codex-high-fast (GPT family). Implementers used claude-4.6-opus-high-thinking (I1) or claude-4.6-sonnet-medium-thinking (I2), both Claude family. D1 decomposition used gemini-3.1-pro (Gemini family). The cross-family preference held at every juncture; no exceptions logged.
- **Separate invocation per pass**: each R1 review was a fresh `Task` invocation distinct from the implementer's transcript and from prior R1 reviewers. No agent reviewed its own output.
- **Read-only**: every R1 invocation used `readonly: true`. The reviewer cannot modify code; the parent agent applies fold-back via fresh implementer subagents (or, for tactical Major-only / sibling-endpoint findings, parent-direct edits with parent-verification).
- **Parent-direct fixes** (used twice; both well within stop-condition-3's tactical-not-spec-flaw spirit):
  1. irvc-1 R1 pass-2 M1 PARTIAL → user-approved hardening fix in `52771d3`.
  2. irvc-5c R1 pass-2 sibling-endpoint Critical → parent-direct fix in `5d2a9ef`.

## Architectural decisions made during execution

| # | Trigger | Decision | Where it lives now |
|---|---|---|---|
| 1 | irvc-1 R1 pass-2 M1 PARTIAL (CLI log parser SOH delimiter could collide with commit subject content; experimentally confirmed as a real latent bug because git accepts and preserves SOH bytes in commit subjects) | Switched parser to `git log -z` with NUL field separators (NUL is the one byte git forbids in commit messages, so the parser is robust by construction). | `52771d3`, `src/bma_cfengine_app/orchestrator/deals/git_service.py` `_log_cli` |
| 2 | irvc-5c R1 pass-1 C1 (verbatim PII reachable through main's history graph after Apply because the irvc-2 merge primitive creates two-parent commits) | **Path B**: add `squash` parameter to `GitService.merge`; router defaults `squash=True` for `ai/turn-*` and `solver/run-*`. The Phase 0 C11 "squash on Apply" contract is now first-class in the merge primitive, not papered over by post-hoc history rewrites in the GC hook. The two-parent default is preserved for non-ephemeral callers, so irvc-2's contract is unchanged. | `b06f10f` + `5d2a9ef`, `src/bma_cfengine_app/orchestrator/deals/git_service.py` `merge`, `src/bma_cfengine_app/api/routers/deals.py` `merge_endpoint` + `merge_stream_endpoint` |

## Cost discipline

- 8 tickets driven through the per-ticket lifecycle (7 irvc + 1 vpc cross-todo blocker).
- D1 decomposition: 1 invocation (irvc) + 1 invocation (vpc-detour) = 2 D1 dispatches across the closure.
- T1: 8 dispatches (one per ticket).
- I1/I2: 8 implementer dispatches + 5 fix-pass dispatches = 13 implementer dispatches.
- R1: 8 pass-1 dispatches + 4 pass-2 dispatches = 12 R1 dispatches.
- Parent-direct fixes: 4 (irvc-1 hardening, irvc-3 was inline, irvc-5b m1+M1 inline, irvc-5c SSE sibling).
- Stop-condition surfaces: 3 (irvc-1 M1 PARTIAL after pass-2; irvc-5c C1 architectural ambiguity; ir-version-control-foundation TODO completion).
- All within the standing-orders cost-discipline guidance ("≤2 R1 review passes per ticket; parent-verify routine fix-pass diffs rather than spawning a third R1").

## Outstanding work captured separately

None. Every R1 finding was either closed in a fix-pass + parent-verify, or in a fix-pass + R1 pass-2 APPROVE. No deferred items; no in-flight uncommitted state.

The cross-todo `validation-parity-contract` blocker (`vpc-1`) is closed. The remaining vpc tickets (`vpc-2`/`vpc-3`/`vpc-4`/`vpc-5`) are decomposed at `1748284` but not yet implemented; they are not on any other Phase 1 todo's critical path EXCEPT `validation-engine` (which is itself still pending). They will be picked up when the next chat tackles `validation-parity-contract` or `validation-engine`.
