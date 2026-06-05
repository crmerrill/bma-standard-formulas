# R1 Review (Pass 2, retroactive fix-pass) — `live-preview-perf-spike`

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family)
**Date**: 2026-06-03
**Fix-pass under review**: T1 `81de38e`, Fix `99400cd`
**Verdict**: APPROVE-WITH-CHANGES

## Summary

The fix-pass closes the three required R1 changes:
- Budget assertions are now unconditional in all three PSA benchmark scenarios.
- Default pytest runs now exclude `slow` tests via `pyproject.toml`.
- `STATUS.md` now has a dedicated `## Follow-on tickets` section naming the required fixture-scale gaps.

The only remaining caveat is CI enforcement strength: `.github/workflows/ci.yml` adds the requested `slow-bench` job, but it is `continue-on-error: true`, so it is informational rather than merge-blocking.

## Findings

1. **CI slow benchmark is non-blocking by design.**

   `.github/workflows/ci.yml` adds `slow-bench` and runs `python -m pytest -m slow tests/performance/ -v --tb=short`. However, the job has `continue-on-error: true`. This avoids noisy merge failures from GitHub runner variance, but it also means a real budget regression will not fail the PR check.

   Recommendation: keep this as APPROVE-WITH-CHANGES unless the R1 requirement intended a strict CI gate. A better long-term guard would use repeated samples or multi-run median/percentile smoothing, then make the job blocking once variance is characterized.

## Closure Assessment

- **Budget enforcement**: CLOSED. Each PSA scenario asserts `p50_ms < TARGET_P50_MS` and `p95_ms < TARGET_P95_MS`. No environment variable gating.
- **Default-suite exclusion**: CLOSED. `addopts = ["-m", "not slow"]` in `pyproject.toml`. No conftest/setup.cfg/Makefile override found.
- **CI workflow**: PARTIALLY-CLOSED. `slow-bench` job added but `continue-on-error: true`.
- **STATUS.md follow-on section**: CLOSED. Lists 200-rule synthetic auto ABS, multi-group RMBS combined deal, CC master trust with PFA/IFA.
- **Meta-tests**: CLOSED. `test_status_md_follow_on_items_named` verifies named items, not just heading.
- **Edge case: continue-on-error / variance**: PARTIALLY-CLOSED. Tradeoff documented; smoothing mechanism would be stronger.

## Verdict Rationale

APPROVE-WITH-CHANGES: the required file-level remediations are present and the original R1 issues are substantially closed. The remaining change is policy-level: decide whether the slow benchmark must be a strict merge gate.
