# R1 Review (Pass 1) — `sdpm-2-git-persistence-and-rollback` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family from claude-4.6-opus implementer + Claude parent + gpt codex T1 author)
**Date**: 2026-06-03
**Implementation under review**: commit `df50a10` (test commit `b9e2656`)
**Verdict**: RETURN-FOR-REVISION

## Summary

The main sidecar persistence shape landed: `commit_deal` has the requested `sidecar_payload` keyword, both pygit2 and CLI paths include `sidecar.json` in the commit tree when supplied, `load_deal` now returns deal + sidecar + diagnostics, and the HTTP commit request forwards `sidecar_payload`. AC 3 is incomplete: `sidecar.broken.json` is written on parse failure, but no successful save path removes/overwrites it, and the CLI main path doesn't actively prevent a staged broken file from committing.

## Findings

### Major

**M1** — AC 3 broken-sidecar lifecycle is incomplete. `_load_sidecar_from_commit` writes `sidecar.broken.json` to the working tree on parse failure, but no save path removes or overwrites it before a later successful save. Spec: "The next successful save with a valid sidecar overwrites or removes the local broken file from the working tree before committing." After a user repairs the sidecar, the stale local `sidecar.broken.json` persists, misleading later debugging.

**M2** — AC 3 "MUST NOT be committed" not enforced on CLI main path. The CLI main-branch path uses `git add deal.json` + optional `git add sidecar.json` + `git commit` without explicitly excluding `sidecar.broken.json`. If the file was already staged by another tool or manual `git add .`, the next commit can include it. Recommendation: `git rm --cached --ignore-unmatch sidecar.broken.json` before the CLI commit.

### Minor

**m1** — Broken archive write not lock-protected or atomic. `_load_sidecar_from_commit` writes `sidecar.broken.json` directly with `write_bytes` outside the `GitService` write lock. Should use temp file + `os.replace`, ideally coordinated with the repo-level write lock.

**m2** — Sidecar diagnostics dropped at production call sites. `_ensure_canonical_deal`, `deal_run_service`, `deal_solver_service` only take `[0]` from the new tuple and discard the diagnostics list. AC 4 says the failure diagnostic is surfaced; production paths today don't preserve it. Either document scope or add UI propagation.

## What Landed Well

- `commit_deal` signature exactly per spec; both backends write `sidecar.json` atomically.
- Omitting `sidecar_payload` preserves existing tracked `sidecar.json` from the parent tree (backward compat).
- `load_deal` reads `sidecar.json`, validates, returns empty default on missing/invalid, emits exact `SIDECAR_LOAD_FAILED` message.
- `CommitRequest.sidecar_payload` forwarded to service.
- Tests parametrized over pygit2 + CLI.

## Verdict Rationale

AC 3 uses MUST-level language and the gaps are small + testable. Return for revision rather than approve with advisory notes.

## Sign-off Recommendation

RETURN-FOR-REVISION → parent-verify path (Major-only, no R1 pass-2).

---

## Parent-verify fix-pass applied (2026-06-03)

(See follow-up commit.)
