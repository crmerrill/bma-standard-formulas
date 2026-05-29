---
reviewer: R1 (gpt-5.5-extra-high, independent agent invocation)
date: 2026-05-29
ticket_set_reviewed: `docs/architecture/tickets/phase1/ir-version-control-foundation.md` (pass 1)
verdict: RETURN-FOR-REVISION
---

## Executive Summary

- The ticket set covers the broad shape of the `ir-version-control-foundation` todo, but it does not yet satisfy the contractual operational design gate.
- The largest blockers are diagnostic-catalog deferral for `MERGE_CONFLICT`, incomplete export/corruption-recovery hardening, and an unmapped `.git/` size telemetry acceptance criterion.
- No Phase 3+ entities (`WaterfallBranch`, `AggregateGroupDef`, `loss_treatment`, `ComputedAmountNode`) were referenced in the ticket set.
- The FastAPI router path referenced by `irvc-4` is correct: `src/bma_cfengine_app/api/routers/deals.py`.
- The migration path in `irvc-3` is incorrect: this repo has `src/bma_standard_formulas/deals/schemas/migrations/__init__.py`, not `src/bma_standard_formulas/deals/migrations.py`.
- All listed test files appear to be new/nonexistent, but `irvc-5` fails the objective test-to-acceptance mapping.

## Completeness Audit

| Requirement | Ticket Coverage | Status | Notes |
|---|---:|---:|---|
| `pygit2` dep + CLI fallback | `irvc-1` | ✓ | Covered, but deployment/wheel risk is not flagged. |
| Python service interface: `commit_deal`, `branch_create`, `branch_delete`, `diff`, `merge_base`, `merge`, `log`, `show`, `branch_list` | `irvc-1`, `irvc-2` | ✓ | All operations are named collectively. Add exact signatures and branch-name validation. |
| Application-level typed field merge with `MERGE_CONFLICT` diagnostic | `irvc-2` | partial | Merge is covered, but diagnostic catalog ownership is deferred. |
| HTTP/SSE API surface for listed endpoints | `irvc-4` | partial | Router path is correct, but endpoint paths/methods are underspecified and branch-list is missing. |
| Legacy `v{N}.json` migration: idempotent, `system:migration`, `Migrate v{N}`, linear chain | `irvc-3` | partial | Linear/idempotent/author covered; exact commit message and compatibility with `studio_v{N}.json` are not. |
| `manifest.json` collapse to non-git metadata | `irvc-3` | ✓ | Field list is explicit. |
| Last-writer-wins UX: 409 + future collaboration markers | `irvc-4` | partial | 409/force covered; marker syntax is unsafe for Python as written. |
| Branch GC: Apply/Discard deletion, 7d retention/redaction, `what-if/*` never auto-GC | `irvc-5` | partial | `what-if/*` exclusion and full retention/prune behavior are missing from AC/tests. |
| Backup/restore via `git bundle` | `irvc-5` | ✓ | Covered by AC/test. |
| Per-repo file locking with bounded timeout | `irvc-1` | ✓ | Covered, but cross-process/single-host risk needs explicit scope and test shape. |
| Export hardening: export cannot reach sidecar/scenarios/transcripts | `irvc-5` | partial | AC only names `.git/` and `sidecar.json`; omits `scenarios.json`, `turn_transcripts/`, and `discarded_branches/`. |
| `git fsck` on load + recovery path | `irvc-5` | partial | Failure detection covered; restore action and audit log are missing. |
| `.git/` size monitoring telemetry | `irvc-5` | partial | AC exists but has no mapped test; weekly p95 alert/budget threshold omitted. |

## Findings

### B1 — Blocking — `irvc-2`

**Issue with evidence:** `irvc-2` emits a placeholder `MERGE_CONFLICT` diagnostic and the ticket explicitly defers formal catalog registration to `validation-parity-contract`. That creates a stable diagnostic code outside the diagnostic catalog lifecycle. The plan requires stable diagnostics to be cataloged and tested, and the ticket's own "Flags for R1 Reviewer" acknowledges the deferral.

**Recommended fix:** Either make `irvc-2` depend on `validation-parity-contract`, or include the minimal diagnostic catalog entry, backend owner metadata, and tests in `irvc-2` itself. Do not land a placeholder diagnostic code that another ticket must later legitimize.

**Test/acceptance implication:** Add a test asserting `MERGE_CONFLICT` is registered with severity/path schema/owner, and that merge-conflict output conforms to that diagnostic contract.

### B2 — Blocking — `irvc-5`

**Issue with evidence:** Export hardening is incomplete. The operational contract says `export_deal(deal_id, sha)` must literally have no path to `.git/`, `sidecar.json`, `scenarios.json`, `turn_transcripts/`, or `discarded_branches/`. `irvc-5` AC 1 only tests `.git/` and `sidecar.json`.

**Recommended fix:** Rewrite AC 1 to require a narrow function signature and construction-by-`git show <sha>:deal.json`, with no user-controlled path argument. Name all forbidden artifacts.

**Test/acceptance implication:** Expand `test_export_deal_isolates_deal_json` to seed `.git/`, `sidecar.json`, `scenarios.json`, `turn_transcripts/`, and `discarded_branches/`, then prove none can be selected or returned.

### B3 — Blocking — `irvc-5`

**Issue with evidence:** Corruption recovery is incomplete. The plan requires `git fsck --no-progress` on every load, `REPO_CORRUPT`, a "Restore from latest backup" action, and an audit log. `irvc-5` only requires raising a specific exception on fsck failure.

**Recommended fix:** Add explicit restore-via-bundle behavior and audit-log requirements to scope and AC.

**Test/acceptance implication:** Add tests for fsck failure surfacing `REPO_CORRUPT`, restore from latest bundle, and audit log entries for detection, attempted restore, and restore result.

### C1 — Critical — `irvc-5`

**Issue with evidence:** AC 5 says "A size monitoring telemetry function measures `.git/` size per deal," but the test plan maps only AC 1 through AC 4. This is an objective checklist failure: unmapped acceptance criterion.

**Recommended fix:** Add a test mapping for AC 5.

**Test/acceptance implication:** Add `tests/orchestrator/deals/test_operational.py::test_git_size_telemetry_reports_count_objects_budget` or equivalent.

### C2 — Critical — `irvc-3`

**Issue with evidence:** Migration acceptance omits the required exact commit message `Migrate v{N}`. The parent todo explicitly requires one commit per legacy version with author `system:migration` and message `Migrate v{N}`.

**Recommended fix:** Add the exact commit-message requirement to AC 1.

**Test/acceptance implication:** Extend `test_legacy_migration_creates_linear_history` to assert author, message sequence, parent chain, and final `deal.json` equals the latest legacy version.

### C3 — Critical — `irvc-3`

**Issue with evidence:** The ticket says it "explicitly does NOT migrate `studio_v{N}.json`," but current backend behavior is centered on `save_studio_ir`, `load_studio_snapshot`, `list_studio_deals`, and router normalization. Replacing `deal_store.py` without a compatibility bridge risks breaking existing Studio API behavior before `studio-document-persistence-and-migration` lands.

**Recommended fix:** Clarify the boundary: either preserve current `studio_v{N}.json` APIs unchanged until the sidecar ticket, or define a compatibility shim and tests. Do not leave current router callers ambiguous.

**Test/acceptance implication:** Add regression tests for existing `GET /deals/{id}`, `POST /deals`, run/solve load paths, and canonical-sync behavior during the transition.

### M1 — Major — `irvc-4`

**Issue with evidence:** The HTTP API is too underspecified for frontend consumption. AC 1 names operations, but not concrete paths, methods, request bodies, response shapes, query params, or SSE endpoint shape. It also omits `branch_list` even though the service interface includes it.

**Recommended fix:** Replace operation names with exact routes, e.g. `GET /deals/{id}/branches`, `POST /deals/{id}/branch`, `DELETE /deals/{id}/branches/{name}`, `GET /deals/{id}/diff?a_sha=&b_sha=`, `GET /deals/{id}/show?sha=&path=deal.json`, etc.

**Test/acceptance implication:** Split `test_git_read_endpoints` into endpoint-specific contract tests, including branch list and response schemas.

### M2 — Major — `irvc-3`

**Issue with evidence:** File path specificity is wrong. The ticket references `src/bma_standard_formulas/deals/migrations.py`, but the migration module exists at `src/bma_standard_formulas/deals/schemas/migrations/__init__.py`.

**Recommended fix:** Correct the file path and state whether the git migration belongs in the schema migration package or in orchestrator persistence. Prefer keeping filesystem/git migration in orchestrator code and reusing `migrate_deal_payload` from the existing schema migration package.

**Test/acceptance implication:** Tests should import the real module path and prove schema payload migration still runs before `DealDefinition.model_validate`.

### M3 — Major — `irvc-5`

**Issue with evidence:** `irvc-5` is not atomic. It bundles export security, fsck/recovery, backup/restore, branch GC, PII redaction, and size telemetry across service and API code. That is too much for a single review pass/sign-off.

**Recommended fix:** Split into smaller tickets, for example: export+fsck recovery, backup/restore bundle scripts, and branch GC+size telemetry.

**Test/acceptance implication:** Each split ticket should have its own focused acceptance criteria and failure-mode tests.

### M4 — Major — `irvc-1`

**Issue with evidence:** Locking risk is under-specified. The plan assumes single-host backend and cross-process safety via file/libgit2 locks, with cross-host locking out of scope. The ticket only says "concurrent write lock prevents race conditions" and flags timeout tuning.

**Recommended fix:** Add explicit single-host scope, cross-process locking requirement, reads lock-free behavior, and cross-host out-of-scope note.

**Test/acceptance implication:** `test_concurrent_writes_timeout` should use separate processes or independent repository handles, not only threads.

### M5 — Major — `irvc-1`

**Issue with evidence:** `pygit2` wheel availability is not flagged. The project requires Python `>=3.12` and advertises Python 3.13; `pygit2`/libgit2 packaging can fail on constrained CI or deployment targets.

**Recommended fix:** Add a risk note and CI acceptance: install/test on supported Python versions, and force the CLI fallback path when `pygit2` import or repository open fails.

**Test/acceptance implication:** Add a test that simulates `ImportError`/libgit2 unavailable and proves the same operation interface works via CLI.

### M6 — Major — `irvc-5`

**Issue with evidence:** Branch GC policy is incomplete. The ticket does not require `what-if/*` branches to be excluded from auto-GC, and it does not fully capture "preserve discarded branch artifacts for 7d, redact PII at GC time, then prune."

**Recommended fix:** Add explicit AC for `what-if/*` never auto-GC and for discarded-branch retention/prune semantics.

**Test/acceptance implication:** Add tests for applied branch deletion, discarded branch deletion, old non-applied branch redaction, `what-if/*` preservation, and prune timing.

### M7 — Major — `irvc-5`

**Issue with evidence:** `.git/` size monitoring is weaker than the operational contract. The plan requires weekly `git count-objects -v`, p95 per-tenant alerting, and default threshold behavior. The ticket only says "measures `.git/` size per deal."

**Recommended fix:** Add job cadence, count-objects source, tenant p95 aggregation, and alert threshold to AC.

**Test/acceptance implication:** Add tests for telemetry payload shape and threshold crossing behavior.

### M8 — Major — `irvc-4`, `irvc-5`

**Issue with evidence:** Dependency graph has a router collision risk. Both `irvc-4` and `irvc-5` modify `src/bma_cfengine_app/api/routers/deals.py`, but `irvc-5` does not depend on `irvc-4`.

**Recommended fix:** Either move `irvc-5` export endpoint work into `irvc-4`, or make `irvc-5` depend on `irvc-4` for router modifications. If `irvc-5` remains independent, keep it service-only until the API ticket lands.

**Test/acceptance implication:** Avoid two independent tickets adding adjacent route contracts without shared API tests.

### M9 — Major — `irvc-4`

**Issue with evidence:** Future-work marker syntax is unsafe as written for Python. The parent plan examples use `// FUTURE: ...`, but `irvc-4` modifies a Python router where `//` is not a comment.

**Recommended fix:** Specify language-correct comments while preserving the grep-able marker, e.g. `# FUTURE: collaboration - replace last-writer-wins with three-way merge UI when collaboration lands`.

**Test/acceptance implication:** Add or reference a marker-lint test that accepts Python `# FUTURE:` and TypeScript `// FUTURE:` forms.

### M10 — Major — `irvc-1`, `irvc-3`, `irvc-4`, `irvc-5`

**Issue with evidence:** CI integration is not specified. The ticket set introduces git CLI dependency, pygit2/libgit2 dependency, filesystem locks, subprocess fallback, and bundle/fsck commands, but no ticket says how CI will provide and exercise both backends.

**Recommended fix:** Add CI notes to `irvc-1` or a shared acceptance item: verify `git` CLI availability, run pygit2 backend tests, run forced-CLI fallback tests, and run operational command tests.

**Test/acceptance implication:** The backend test suite must exercise both backends in CI, not only local developer machines.

### m1 — Minor — all tickets

**Issue with evidence:** The test plans list concrete new test files and do not merely say "run existing tests," which satisfies the main TDD shape. However, none of the ticket test plans explicitly states "write these failing tests before implementation."

**Recommended fix:** Add a one-line TDD note to the ticket set or each ticket: "These tests are authored first and must fail before implementation."

**Test/acceptance implication:** No new test case required, but it makes the TDD gate auditable.

### m2 — Minor — `irvc-1`, `irvc-4`, `irvc-5`

**Issue with evidence:** Branch naming conventions are not acceptance-tested. The parent contract names `main`, ephemeral `ai/turn-*` and `solver/run-*`, and persistent `what-if/*`.

**Recommended fix:** Add branch-name validation and tests either in `GitService` or in the API layer.

**Test/acceptance implication:** Tests should reject invalid branch names/path traversal and preserve the three allowed namespaces.

## Specific Recommendations

1. Add diagnostic catalog ownership for `MERGE_CONFLICT` to `irvc-2`, or make `irvc-2` depend on `validation-parity-contract`.
2. Expand `irvc-5` export AC/tests to prove only `deal.json` is reachable and all sidecar/scenario/transcript/discarded artifacts are unreachable by construction.
3. Expand `irvc-5` corruption recovery AC/tests to include restore from latest bundle and audit logging.
4. Add a mapped test for `irvc-5` AC 5 `.git/` size telemetry.
5. Amend `irvc-3` migration AC/tests to assert exact `Migrate v{N}` commit messages.
6. Correct the migration file path to `src/bma_standard_formulas/deals/schemas/migrations/__init__.py`, or move git migration logic explicitly into orchestrator persistence.
7. Define the compatibility behavior for existing `studio_v{N}.json` APIs while `studio-document-persistence-and-migration` is not yet landed.
8. Make `irvc-4` enumerate exact HTTP/SSE route contracts, including branch list.
9. Split `irvc-5` into smaller operational tickets, or sharply narrow its scope so one PR can be reviewed and signed off safely.
10. Add lock/pygit2/CLI fallback/CI risk notes and cross-process tests.
11. Resolve the router dependency collision between `irvc-4` and `irvc-5`.

## Approval Gate

RETURN-FOR-REVISION. Flip to APPROVE only when:

- All Blocking findings B1-B3 are fixed in the ticket text.
- Critical findings C1-C3 have explicit AC/test coverage.
- Major findings M1-M10 are resolved or intentionally re-scoped with clear ticket boundaries.
- The completeness audit has no `partial` or `✗` rows for contractual Phase 1 operational requirements.
- The dependency graph is updated to reflect router/API sequencing and diagnostic-catalog sequencing.
