# Phase 1 hand-off — `ir-version-control-foundation` complete, paused before next todo

**Date paused**: 2026-06-01
**Branch**: `feature/securitization-structuring-tool`
**Last commit**: `5d2a9ef` (`fix(irvc-5c): close R1 pass-2 SSE squash-bypass + sign off`)
**Test suite**: 1502 passed, 3 skipped, 0 failures (baseline at chat start: 1426; net +76 new tests)

## What's done

### Phase 1 todo `ir-version-control-foundation` — COMPLETE

All seven irvc tickets merged with full TDD lifecycle (T1 → I → R1 → fix-pass → R1 pass-2 or parent-verify):

| Ticket | Final commit | Notes |
|---|---|---|
| `irvc-1-core-git-service` | `52771d3` | Includes user-approved follow-up hardening of CLI log parser (NUL field separators via `git log -z` instead of SOH delimiters). |
| `irvc-2-typed-field-merge` | `cb35a1a` | `MERGE_CONFLICT` registered via vpc-1 catalog. |
| `irvc-3-legacy-migration` | `df7ba80` | Versioned `load_deal(deal_id, version=N)` round-trips for both migration commits AND normal saves; first-open migration wrapped in per-deal `_migration_lock`. |
| `irvc-4-http-api` | `a113572` | Eight HTTP endpoints + SSE merge stream + 409 LWW with `force=true` bypass. |
| `irvc-5a-export-and-fsck` | `1c2948a` | `export_deal(deal_id, sha)` is path-free by construction; `_fsck_on_init` runs at every `GitService` construction (memoized); `restore_deal` uses atomic `.git.old` swap with rollback. |
| `irvc-5b-backup-restore` | `59d2c6f` | Backup CLI strict-glob match (no substring collisions); missing-deal exits with clear stderr error. |
| `irvc-5c-branch-gc-and-telemetry` | `5d2a9ef` | **Cross-cutting decision (Path B)**: `GitService.merge` gained `squash` parameter; router defaults `squash=True` for `ai/turn-*` and `solver/run-*` to honor Phase 0 C11's "squash on Apply" contract. Both `POST /merge` and `GET /merge/stream` SSE route apply squash + GC for ephemeral branches. |

### Phase 1 todo `validation-parity-contract` — partial

| Ticket | Status |
|---|---|
| `vpc-1-diagnostic-code-decorator` | ✅ Merged at `78bc7ef`. Cross-todo blocker for `irvc-2` was satisfied. |
| `vpc-2-catalog-document` | ⏳ Decomposed at `1748284`, not yet implemented. |
| `vpc-3-ts-worker-registry` | ⏳ Decomposed at `1748284`, not yet implemented. |
| `vpc-4-ci-guard` | ⏳ Decomposed at `1748284`, not yet implemented. |
| `vpc-5-parity-fixture-set` | ⏳ Decomposed at `1748284`, not yet implemented. |

The remaining vpc tickets are not on any other Phase 1 todo's critical path EXCEPT `validation-engine` (which depends on the full vpc surface). Driving them through is mostly routine work.

## What's NOT done — Phase 1 todos still pending

Per `~/.cursor/plans/structuring_studio_redesign_ec1d8b3d.plan.md` line 1567, Phase 1 also includes:

- `design-system-and-tokens` (routine)
- `studio-document-and-store` (architecturally heavy)
- `studio-document-persistence-and-migration` (architecturally heavy)
- `validation-engine` (architecturally heavy, depends on full vpc)
- `rule-canonicalization-framework` (architecturally heavy)
- `corpus-fixture-status` (routine)
- `problems-panel` (routine)
- `live-preview-perf-spike` (routine, Phase-4-decision gate per M13)
- `visual-design-language` (routine)

## Architectural decisions made during this session

1. **irvc-1 R1 pass-2 M1 PARTIAL → user-approved hardening fix**: Switched CLI log parser from SOH (`\x01`) record delimiter to git's canonical `git log -z` with NUL field separators. Found a latent bug — git accepts SOH bytes in commit subjects, so the prior parser was vulnerable to malformed output for any commit with a SOH in its subject.

2. **irvc-5c R1 pass-1 C1 → user-approved Path B**: Squash-on-Apply contract (Phase 0 C11) was added to `GitService.merge` itself rather than being papered over by post-merge history rewrites in irvc-5c's GC hook. The router defaults `squash=True` for `ai/turn-*`/`solver/run-*` namespaces; `squash=False` is the default for general-purpose merges so the irvc-2 primitive's contract is unchanged for non-ephemeral callers.

3. **irvc-5c R1 pass-2 → parent-direct fix**: Pass-2 found a sibling-endpoint miss (`GET /merge/stream` SSE bypassed the squash logic). Treated as tactical (5-line fix in routers/deals.py), not a ticket-spec flaw, so applied directly + parent-verified rather than spawning another R1/implementer pair.

## R1 review artifacts on disk

For audit trail and any future cross-ticket review, all R1 reviews are in:
- `docs/architecture/tickets/phase1/ir-version-control-foundation.r1-review-pass1.md` (decomposition pass-1)
- `docs/architecture/tickets/phase1/ir-version-control-foundation.r1-review-pass2.md` (decomposition pass-2)
- `docs/architecture/tickets/phase1/ir-version-control-foundation.irvc-1.r1-review-pass1.md`
- `docs/architecture/tickets/phase1/ir-version-control-foundation.irvc-1.r1-review-pass2.md`
- `docs/architecture/tickets/phase1/ir-version-control-foundation.irvc-2.r1-review-pass1.md`
- `docs/architecture/tickets/phase1/ir-version-control-foundation.irvc-2.r1-review-pass2.md`
- `docs/architecture/tickets/phase1/ir-version-control-foundation.irvc-3.r1-review-pass1.md`
- `docs/architecture/tickets/phase1/ir-version-control-foundation.irvc-4.r1-review-pass1.md`
- `docs/architecture/tickets/phase1/ir-version-control-foundation.irvc-5a.r1-review-pass1.md`
- `docs/architecture/tickets/phase1/ir-version-control-foundation.irvc-5a.r1-review-pass2.md`
- `docs/architecture/tickets/phase1/ir-version-control-foundation.irvc-5b.r1-review-pass1.md`
- `docs/architecture/tickets/phase1/ir-version-control-foundation.irvc-5c.r1-review-pass1.md`
- `docs/architecture/tickets/phase1/ir-version-control-foundation.irvc-5c.r1-review-pass2.md`
- `docs/architecture/tickets/phase1/validation-parity-contract.vpc-1.r1-review-pass1.md`

## Outstanding work captured separately

None. The fix-passes in this session each closed the corresponding R1 findings; no deferred items.

## Resumption prompt for the next chat

Drop the same standing-orders prompt (Phase 1 Autonomous Execution) into a fresh chat. The new parent agent will pick up by:

1. Reading the five sources of truth at the top of the standing orders.
2. Running `git log --oneline -10` to confirm the irvc todo close (last commits `5d2a9ef`, `b06f10f`, `a3a695f`).
3. Reading this hand-off doc to understand state.
4. Choosing the next todo from the eleven-todo Phase 1 list. Options the user has not yet ruled out:
   - Finish `validation-parity-contract` (drive vpc-2/3/4/5 — mostly routine).
   - Move to `studio-document-and-store` (architecturally heavy; depends on irvc work which is now merged).
   - Move to `design-system-and-tokens` (routine; cheap; visual-foundation work).
   - Move to `live-preview-perf-spike` (routine; gates Phase 4 decision).
5. Confirming with the user before driving a new architecturally-heavy todo, OR proceeding autonomously on routine work per the standing orders.
