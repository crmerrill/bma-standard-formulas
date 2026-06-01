---
reviewer: R1 (gpt-5.5-extra-high, independent fresh invocation; distinct from D1 and pass-1 R1)
date: 2026-05-29
ticket_set_reviewed: `docs/architecture/tickets/phase1/ir-version-control-foundation.md`
pass_number: 2
verdict: RETURN-FOR-REVISION
---

## Executive Summary

- Pass 2 resolves many pass-1 textual gaps: diagnostic-catalog dependency, export hardening, exact HTTP route contracts, migration commit metadata, branch-name validation, CI/backend fallback coverage, and the oversized `irvc-5` split are substantially improved.
- The pass-1 Blocking findings are **not all genuinely closed**. B1 and B2 are resolved; B3 is only partially resolved because corruption detection is in `irvc-5a`, restore implementation is in `irvc-5b`, and the dependency graph does not force restore to exist before the `REPO_CORRUPT` action/audit path ships.
- A new phase-gate regression was introduced: the ticket set says `irvc-5b` and `irvc-5c` can land in parallel with pane work, but the parent plan's operational design says the full operational contract lands before any pane work begins.
- `irvc-3` still has a real transition hazard: it claims existing `studio_v{N}.json` APIs are preserved, but its manifest-collapse AC removes the manifest fields those APIs currently use.
- The branch API and GC tickets are not yet implementation-ready: slash-containing branch names cannot be addressed by the specified delete route, and branch GC cannot be enforced from the listed files/dependencies.
- Verdict remains **RETURN-FOR-REVISION**. Do not pass to T1 until the dependency graph and acceptance criteria are repaired.

## Audit of Pass-1 Findings

| Finding | Status | Evidence |
|---|---|---|
| B1 — `MERGE_CONFLICT` diagnostic catalog deferral | RESOLVED | `irvc-2` now depends on `validation-parity-contract` and AC 4 requires formal catalog registration via the decorator+guard pattern with a mapped test. |
| B2 — export hardening incomplete | RESOLVED | `irvc-5a` specifies a path-free `export_deal(deal_id, sha)` with literal `git show <sha>:deal.json`, names all forbidden artifacts, and maps a forbidden-artifact seed test. |
| B3 — corruption recovery incomplete | PARTIALLY RESOLVED | Detection is covered in `irvc-5a`, but restore-via-bundle implementation lives in `irvc-5b` with no `irvc-5b → irvc-5a` edge. See C4 below. |
| C1 — `.git/` telemetry AC unmapped | RESOLVED | `irvc-5c` AC 5 + mapped test. |
| C2 — migration exact commit message omitted | RESOLVED | `irvc-3` AC 1 requires `Migrate v{N}` per legacy version with a mapped test asserting author + message sequence + parent chain + final payload equality. |
| C3 — existing `studio_v{N}.json` APIs ambiguous | PARTIALLY RESOLVED | Preservation claim in scope and AC 5, but AC 3's manifest collapse removes fields the existing APIs read. See M15 below. |
| M1 — HTTP API underspecified | RESOLVED WITH NEW ISSUE | Routes/bodies/responses enumerated; but slash-encoding in DELETE route is broken. See M11. |
| M2 — migration file path wrong | RESOLVED | Path corrected to `schemas/migrations/__init__.py`. |
| M3 — `irvc-5` not atomic | RESOLVED | Split into `irvc-5a/b/c`. |
| M4 — locking risk underspecified | RESOLVED | `irvc-1` AC 4 + cross-process test. |
| M5 — `pygit2`/CLI fallback/CI risk | PARTIALLY RESOLVED | CI matrix added; risk-note overclaims wheel-install resilience. See M14. |
| M6 — branch GC policy incomplete | RESOLVED WITH NEW ISSUE | Policy spelled out; but listed files cannot hook Apply/Discard call sites. See M12. |
| M7 — `.git/` size monitoring weak | RESOLVED | `irvc-5c` AC 5 + mapped test. |
| M8 — router collision between `irvc-4` and `irvc-5` | RESOLVED | `irvc-5a` declares `irvc-4` dependency. |
| M9 — future marker syntax unsafe for Python | RESOLVED | Language-correct markers required. |
| M10 — CI integration unspecified | RESOLVED | `irvc-1` CI workflow update + AC 6. |
| m1 — TDD note missing | RESOLVED | Global TDD note at top of file. |
| m2 — branch naming conventions not acceptance-tested | RESOLVED | `irvc-1` AC 5 + mapped test. Minor follow-up: slug grammar not pinned. See n1. |

## New Findings

### C4 — Critical — `irvc-5a`, `irvc-5b`

**Issue + evidence.** Pass-1 B3 is only textually closed. `irvc-5a` promises that on fsck failure the system emits `REPO_CORRUPT` with a "Restore from latest backup" action and audit-log entries for "restore attempt initiated, and restore result". The restore implementation, however, lives in `irvc-5b`. The dependency graph does NOT include an `irvc-5b → irvc-5a` edge; both depend only on `irvc-3`, and `irvc-5a` is explicitly labeled "Immediate-deploy-safety prerequisite; must land before any production traffic" while `irvc-5b` is labeled "can land in parallel with pane work". If `irvc-5a` ships first (as the sequencing requires), the diagnostic surfaces a "Restore" action that has no backing function and the restore-result audit log is unreachable. The parent plan binds these together as one operational contract.

**Recommended fix.** Either (a) add a graph edge `irvc-5b → irvc-5a` and re-label `irvc-5b` as deploy-blocking, or (b) move the `restore_deal` function (not the CLI scripts) into `irvc-5a` so the diagnostic action has a real implementation in the same PR; keep the bundle-creation CLI in `irvc-5b`.

**Test/acceptance implication.** Add an `irvc-5a` test that asserts the `REPO_CORRUPT` diagnostic action invokes restore-via-bundle end-to-end (seed bundle → corrupt repo → trigger fsck → assert restore succeeds and audit log records detection + attempt + success).

### M11 — Major — `irvc-4`

**Issue + evidence.** `DELETE /deals/{id}/branches/{name}` cannot represent the branch names the system actually uses. `irvc-1` AC 5 specifies branches with slashes — `ai/turn-{slug}`, `solver/run-{slug}`, `what-if/{slug}`. FastAPI default path-param matchers do not match `/`, so `DELETE /deals/d1/branches/ai/turn-foo` will not route to the handler without either URL-encoding to `%2F` (often rejected by intermediaries by default) or declaring the param as `{name:path}`.

**Recommended fix.** Make the route explicit: either `DELETE /deals/{id}/branches/{name:path}` (and document URL-decoding expectations), or change to `POST /deals/{id}/branches/delete` with the branch name in the body. Apply the same fix to any other path that accepts a `{name}` segment.

**Test/acceptance implication.** Add endpoint contract tests for each branch namespace.

### M12 — Major — `irvc-5c`

**Issue + evidence.** `irvc-5c` AC 1 requires ephemeral branches to be deleted *immediately on Apply (after squash-merge) or Discard*. The only file the ticket modifies is `operational.py`, and its only dependency is `irvc-3`. The Apply path lives in `irvc-4` (merge endpoint); the merge primitive lives in `irvc-2`; the Discard call site (branch-delete endpoint) lives in `irvc-4`. Without modifying the merge endpoint or the branch-delete endpoint — and without depending on `irvc-4` — `irvc-5c` cannot wire immediate post-Apply or post-Discard deletion. The AC is structurally unsatisfiable from the listed files.

**Recommended fix.** Add `irvc-4` as a dependency for `irvc-5c`, list the router file in Files affected, and re-scope AC 1 to specify exactly which call sites invoke the GC hook (merge endpoint on success → `gc_branch_after_apply(branch)`; branch-delete endpoint on success → `gc_branch_after_discard(branch)`).

**Test/acceptance implication.** `test_ephemeral_branches_deleted_on_apply_discard` must call the API endpoints, not call `operational.py` directly.

### M13 — Major — `irvc-5b`, `irvc-5c` (phase-gate regression)

**Issue + evidence.** The Sequencing Impact section says `irvc-5b` and `irvc-5c` "can land in parallel with pane work". The parent plan's operational design subsection is explicit that the operational contract lands "before any pane work begins". Pane tickets depend on the version-control foundation; allowing two of its tickets to slip in parallel opens the door to pane work landing without backup, restore, branch GC, PII redaction, or `.git/` size telemetry in place.

**Recommended fix.** Strike the "can land in parallel with pane work" language. Mark all three operational tickets (`irvc-5a/b/c`) as deploy-blocking and add an explicit gate: no pane ticket opens until `irvc-5a/b/c` are merged.

**Test/acceptance implication.** Sequencing-level only.

### M14 — Major — `irvc-1`

**Issue + evidence.** The risk note says "The CLI fallback guarantees operational safety if wheel installation fails in a specific environment", but AC 1 makes `pygit2` a standard dependency. Standard dependencies fail at install, not at import — if pip cannot build a `pygit2` wheel, the application package cannot install at all. The fallback only saves a successful install whose `import pygit2` later fails at runtime.

**Recommended fix.** Choose one: (a) make `pygit2` an optional extra (`pyproject.toml [project.optional-dependencies]` per existing `numba` / `fred` precedent) and have `GitService` import it lazily; or (b) keep `pygit2` standard but rewrite the risk note and add a CI matrix entry that installs without the pygit2 extra and runs the full suite to prove the CLI fallback is exercised by package consumers.

**Test/acceptance implication.** Replace the implicit "wheel install can fail safely" claim with explicit coverage.

### M15 — Major — `irvc-3`

**Issue + evidence.** AC 3 rewrites `manifest.json` to exactly six fields. AC 5 simultaneously requires `save_studio_ir`, `load_studio_snapshot`, `list_studio_deals` to be preserved UNCHANGED. Today those functions read and write `studio_current_version` and `studio_versions` on the manifest. The two ACs are contradictory.

**Recommended fix.** Pick one: (a) keep `studio_current_version` and `studio_versions` in the manifest until `studio-document-persistence-and-migration` migrates them out (add to AC 3's allow-list as "transitional"), or (b) move studio version tracking into a separate file in *this* ticket and align AC 5 to the new storage location.

**Test/acceptance implication.** Add an inverse test asserting AC 3 by enumerating manifest keys and rejecting anything outside the allowed set.

### M16 — Major — `irvc-5a`

**Issue + evidence.** AC 4 requires `git fsck --no-progress` on deal load but does not say which load path runs fsck. Today there are at least three load entry points: `load_deal`, `load_studio_snapshot`, and `_ensure_canonical_deal`. If fsck only runs on the canonical path, a corrupt repo opened first via the studio API silently bypasses the check.

**Recommended fix.** Specify the exact integration point(s) and recommend: run fsck once per process per deal (memoized) at the first git-touching call regardless of entry point.

**Test/acceptance implication.** Split `test_fsck_detects_corruption` into one sub-test per entry point.

### M17 — Major — `irvc-2`, `irvc-4`

**Issue + evidence.** `irvc-4` AC 1 specifies `MergeResult(status=..., sha=..., diagnostic=...)` but neither `irvc-2` nor `irvc-4` enumerates the `diagnostic` payload schema. T1 cannot write a contract test for the SSE stream or merge response without that schema pinned.

**Recommended fix.** Either (a) add an AC to `irvc-2` pinning the `MERGE_CONFLICT` diagnostic shape (entity_kind, entity_id, field_path, ours_value, theirs_value, ancestor_value at minimum), or (b) explicitly defer to `validation-parity-contract` with a hard dependency on the specific sub-ticket that lands the schema.

**Test/acceptance implication.** Add `test_merge_conflict_payload_schema_is_stable`.

### m3 — Minor — `irvc-3`

**Issue + evidence.** AC 4 says `migrate_deal_payload` is called BEFORE `model_validate`, but there's no negative regression proving the order matters.

**Recommended fix.** Add a fixture 1.x payload that fails `model_validate` directly but passes after migration.

### m4 — Minor — `irvc-4`

**Issue + evidence.** SSE `MergeProgressEvent` has no schema enumerated.

**Recommended fix.** Add a small Pydantic model spec: required fields, terminal events, stream-closure guarantee.

### m5 — Minor — `irvc-1`

**Issue + evidence.** AC 4 references "single-host, cross-process per-repo advisory lock" but does not specify lock file location or reentrancy semantics.

**Recommended fix.** Pin the lock file path and reentrancy semantics.

### n1 — Nit — `irvc-1`

**Issue + evidence.** AC 5 references `{slug}` without defining a grammar.

**Recommended fix.** Pin grammar, e.g., `[a-z0-9][a-z0-9-]{0,63}`.

### n2 — Nit — `irvc-5c`

**Issue + evidence.** Once M12 is fixed, the Flags-for-Reviewer note "irvc-5c is service-only" becomes false.

**Recommended fix.** Update Flags-for-Reviewer after M12 fix.

## Completeness Audit

The contractual Phase 1 operational requirements are individually mentioned across the ticket set, but several resolve as **partial** when checked against integration sequencing and the actual code surface:

| Operational requirement | Status | Open issue |
|---|---|---|
| `pygit2` dep + CLI fallback (test suite runs both) | ✓ | M14 risk-note overclaim (does not block) |
| Service interface (commit, branches, diff, merge_base, merge, log, show, branch_list) | ✓ | — |
| Typed-field merge with registered `MERGE_CONFLICT` | ✓ | M17 payload schema pinning |
| HTTP / SSE API surface | partial | M11 slash-encoding; m4 SSE event schema |
| Legacy `v{N}.json` migration with `system:migration` + `Migrate v{N}` | ✓ | — |
| `manifest.json` collapse to non-git metadata | partial | M15 contradicts preserved studio APIs |
| Last-writer-wins UX (409 + future markers) | ✓ | — |
| Branch GC: Apply/Discard delete, 7d retention, redaction, `what-if/*` never auto-GC | partial | M12 not wireable from listed files/deps |
| Backup / restore via `git bundle` | partial | C4 restore-action call site without dep |
| Per-repo file locking, 5s timeout, cross-process | ✓ | m5 lock-file path/reentrancy (minor) |
| Export hardening (only `deal.json`; forbidden artifacts unreachable) | ✓ | — |
| `git fsck` on load + recovery path + audit log | partial | C4 + M16 |
| `.git/` size monitoring (weekly p95, 100 MB threshold) | ✓ | — |
| Operational contract lands BEFORE pane work | partial | M13 phase-gate language regression |

Four `partial` rows remain. The completeness audit does **not** pass cleanly.

## Specific Recommendations

To flip the verdict, apply each of the following in the ticket text:

1. Close B3 properly. Add a graph edge `irvc-5b → irvc-5a` (or move `restore_deal` into `irvc-5a`) and add a corrupt-repo → diagnostic → restore-from-bundle round-trip test. (C4)
2. Fix the branch DELETE route to `{name:path}` or POST-with-body, and add per-namespace deletion tests. (M11)
3. Wire branch GC to Apply/Discard. Add `irvc-4` as dependency, list router file in Files affected, restate AC 1 to name call sites, rewrite the test to exercise endpoints. (M12, n2)
4. Strike "can land in parallel with pane work" from `irvc-5b/5c`; add explicit gate that no pane ticket opens until `irvc-5a/b/c` are merged. (M13)
5. Reconcile `pygit2` install-failure semantics: move to optional extras or rewrite risk note + add CI matrix entry. (M14)
6. Resolve `manifest.json` vs. studio APIs contradiction: keep transitional fields, or move studio version tracking out in *this* ticket. (M15)
7. Specify which load paths run fsck (recommended: per-process memoized at first git-touching call); split fsck test by entry point. (M16)
8. Pin `MERGE_CONFLICT` payload schema in `irvc-2` or via specific sub-ticket dependency. (M17)
9. Pin slug grammar in `irvc-1` AC 5. (n1)
10. Add negative migration-order test. (m3)
11. Specify SSE event schema. (m4)
12. Specify lock-file location and reentrancy. (m5)

## Approval Gate

Verdict: **RETURN-FOR-REVISION**. Flip to **APPROVE** only when ALL of the following are true:

- The Critical finding C4 is closed in the dependency graph AND a corrupt-repo → restore-via-bundle round-trip test is mapped.
- All Major findings M11, M12, M13, M14, M15, M16, M17 are resolved in ticket text, with corresponding test plan updates.
- The Completeness Audit table has no `partial` or `✗` rows for the contractual Phase 1 operational requirements.
- Pass-1 findings B3 and C3 are upgraded from PARTIALLY RESOLVED to RESOLVED by the same edits above.
- Minor findings m3, m4, m5 and Nit n1 are either applied or explicitly deferred with a Phase-1 follow-up ticket ID written into the ticket file.

If the next revision satisfies the above, pass to T1 (test author). Until then, do not unblock implementation.
