# R1 Review (Pass 1, retroactive) — `live-preview-perf-spike` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family; RETROACTIVE)
**Date**: 2026-06-03
**Implementation under review**: commit `277c573` (test commit `6b8f594`)
**Verdict**: APPROVE-WITH-CHANGES

## Findings

1. **Budget regression is not actually enforced.**
   `tests/performance/live_preview/test_live_preview_budget.py` measures p50/p95, but only asserts positive timing and `p95 >= p50`. The STATUS doc explicitly says hard budget assertions are deferred. That means the committed benchmark is measurement-capable, but not yet a regression guard for `p50 < 250 ms` / `p95 < 600 ms`.

2. **`slow` marker does not keep the benchmark out of default pytest runs by itself.**
   The benchmark is marked `@pytest.mark.slow`, and `pyproject.toml` registers the marker, but there is no default `addopts = -m "not slow"` or equivalent. Current CI runs `python -m pytest tests/ -v`, so these slow benchmarks would run in the default suite unless CI/test invocation changes.

3. **Fixture-scale gap is acknowledged, but still a real budget risk.**
   The plan asked for largest fixtures: synthetic 200-rule auto ABS, multi-group RMBS, and CC master trust with PFA/IFA. The implementation measured only FNR 2006-018 Group 1: single group, ~10 waterfall rules, 360 periods. STATUS clearly documents the missing fixture classes. However, the M13 "always-on viable" verdict is only proven for the largest existing single-group real fixture, not for the full plan target scale.

## Checklist Assessment

- **Run-size targets**: Partial. Measured only FNR 2006-018 Group 1, not the 200-rule auto ABS, combined multi-group RMBS, or CC master trust.
- **Latency budget**: Pass for measured fixture. Reported p50/p95 are within budget for 100/0/300 PSA.
- **Cancellation behavior**: Pass with caveat. STATUS correctly documents coalescing-with-late-discard via `dispatch_revision`, not active preemption.
- **Degraded-mode UI contract**: Pass. STATUS specifies "Preview paused — keep editing; results stale at hh:mm:ss", non-blocking editing, resume behavior, and an explicit "Run preview" affordance.
- **Performance fixture committed / slow marker**: Partial. Fixture is committed and marked `slow`, but slow is not excluded by default in current pytest config.
- **M13 decision gate**: Pass with scope caveat. STATUS records "ALWAYS-ON PREVIEW IS VIABLE" — verdict applies to the measured FNR Group 1 scale.
- **Fixture-scale gap**: Acknowledged. Should be tracked as follow-on.

## Required Changes Before Full Approval

- Make the performance benchmark fail on budget regression, at least when intentionally run via `pytest -m slow tests/performance/live_preview/`.
- Ensure slow benchmarks do not run in the default suite.
- Add or document a concrete follow-on ticket for the full fixture-scale benchmark gap.
