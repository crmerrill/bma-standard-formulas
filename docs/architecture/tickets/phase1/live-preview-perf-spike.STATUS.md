# Live Preview Performance Spike — STATUS

**Phase 1 ticket**: `live-preview-perf-spike`
**Status**: COMPLETE
**Date**: 2026-06-03
**M13 decision-gate outcome**: **ALWAYS-ON PREVIEW IS VIABLE** at the largest existing real-world fixture (FNR 2006-018 Group 1, 360-period horizon). No Vision-narrative amendment required.

## Targets (per plan §"Performance spike — Phase 1 prerequisite")

| Metric | Target | Source |
|---|---:|---|
| p50 latency | < 250 ms | plan line 715 |
| p95 latency | < 600 ms | plan line 715 |
| Cancellation latency | preempt before next debounced mutation | plan line 716 |
| Degraded-mode UI | "Preview paused — keep editing; results stale at hh:mm:ss" | plan line 717 |
| Coalescing semantics | concrete when keystroke cadence exceeds budget | plan line 716 |

## Measurements

Measured on commodity dev hardware (Apple M-series, Python 3.12). Each scenario runs `bma_standard_formulas.deals.runtime.run_deal` 20 iterations after a warm-up. The benchmark module is `tests/performance/live_preview/test_live_preview_budget.py`; CI runs it via `pytest -m slow`.

### FNR 2006-018 Group 1 — multi-group RMBS, ~10 waterfall rules, 360 periods

| Scenario | n | min | mean | **p50** | **p95** | max |
|---|---:|---:|---:|---:|---:|---:|
| 100 PSA (base case) | 20 | 190.33 ms | 224.57 ms (σ 32.52) | **230.91 ms** ✓ | **290.18 ms** ✓ | 304.07 ms |
| 0 PSA (full horizon stress) | 20 | 185.96 ms | 219.65 ms (σ 22.27) | **228.24 ms** ✓ | **248.42 ms** ✓ | 250.86 ms |
| 300 PSA (fast amortization) | 20 | 177.96 ms | 210.89 ms (σ 24.84) | **219.01 ms** ✓ | **234.87 ms** ✓ | 268.52 ms |

✓ = within target. **All three scenarios are within both p50 and p95 targets**.

The 100 PSA p95 at 290 ms is the closest to the budget edge; this is the scenario most likely to fail on slower hardware. The 0 PSA scenario has a tighter p95 (248 ms) because no prepay-driven cashflow variability shortens the horizon prematurely.

### Out of measurement scope

- **200-rule synthetic auto ABS**: not generated for this spike. The existing fixtures don't include one, and the FNR 2006-018 Group 1 measurement establishes the in-budget viability for the largest real-world fixture available. Synthetic large-fixture stress can be added as a follow-on if/when a 200-rule fixture is authored (e.g., for a Phase 4 stress-test corpus).
- **Multi-group combined deal**: the FNR 2006-018 combined Group 1 + Group 2 deal needs `GroupedCollateralInput` construction (not the single-group `_deal_input_from_repline`). It runs in `test_fnr_2006_018_combined.py` but isn't included in this spike's run loop. A follow-on can extend the benchmark to the combined deal once the multi-group input helper is factored for benchmark use.
- **CC master trust with PFA/IFA**: no real CC master-trust fixture exists in the repo today (`cc_series_test` is a synthetic minimal fixture). The named research-only entries (Capital One COMET, Chase Issuance Trust) are RAG corpus only per `tests/fixtures/STATUS.md`; no measurement runs against them.

## Cancellation behavior

The Python engine's `run_deal()` is a synchronous call. Cancellation in this layer is **not preemptive** — once `run_deal` starts, it runs to completion. Cancellation must be implemented at the caller layer (the validation Web Worker host or the live-preview UI controller) by:

1. Debouncing dispatch (already established at 300 ms via `VALIDATION_DEBOUNCE_MS` from `ve-1`).
2. On a new typed dispatch arriving while a preview run is in flight, the caller logically discards the in-flight result when it returns (the result is associated with a stale `dispatch_revision` from `sds-5`).
3. The caller does NOT attempt to interrupt the running Python call — it just lets it finish and ignores the output.

This is a **coalescing-with-late-discard** strategy, not active preemption. Given the measured p50/p95, this is acceptable: the in-flight run completes within budget, so the discarded work is bounded.

If a future fixture exceeds budget on a single run, active preemption (e.g., via subprocess + signal-based cancellation, or a worker-pool architecture) will be needed; this is **out of scope for Phase 1**. Phase 4 `live-preview-cashflow` may revisit if larger fixtures appear.

## Degraded-mode UI contract

Even though always-on preview is viable at the measured scale, the `live-preview-cashflow` Phase 4 ticket MUST still implement the degraded-mode UI per the plan, because:

1. Slower hardware (older laptops, virtualized cloud dev environments) may exceed budget on the same fixture.
2. Future fixtures (200+ rule synthetic auto ABS, multi-group combined deals) may exceed budget.

The degraded-mode contract is:

- When the most recent preview run exceeded `TARGET_P95_MS = 600 ms` (computed over a rolling window of recent runs), the dock shows: **"Preview paused — keep editing; results stale at hh:mm:ss"** with the wall-clock time of the last successful preview.
- The dock NEVER blocks input. The user can keep editing; the dock will resume when latency recovers.
- An explicit "Run preview" button appears in the Inspector dock that triggers an on-demand preview, ignoring the budget gate.

This contract is forward-compatible with Phase 4. The current Phase 1 measurement does not require triggering degraded mode in normal use.

## Coalescing semantics when keystroke cadence exceeds budget

When typed dispatches arrive faster than the preview run can complete (i.e., > 1 dispatch per `p50_ms`):

1. The 300 ms debounce already coalesces bursts. Only the **last** dispatch in a burst triggers a preview run.
2. If a typed dispatch arrives WHILE a preview run is in flight, the new dispatch is queued; the in-flight run completes and its output is **discarded** (logically — by checking `dispatch_revision` from sds-5).
3. The next preview run starts immediately after the discarded run completes (no additional debounce).

This is acceptable per the measurement — the worst case is one wasted run per coalesced burst. The user perceives it as "preview catches up after typing settles."

## Performance regression test

The benchmark at `tests/performance/live_preview/test_live_preview_budget.py` is the regression-testable budget per the plan's deliverable list. It is marked `@pytest.mark.slow` so it does NOT run by default in `pytest tests/`. CI runs it on every PR/push to `main` via the `slow-bench` job:

```bash
pytest -m slow tests/performance/ -v --tb=short
```

The `slow-bench` CI job is set to `continue-on-error: true` because GitHub Actions runners have higher variance than dev hardware. The job is informational: a consistent budget failure over multiple runs (or local reproduction) is the authoritative signal for a regression. To make timing failures gate the merge, set `continue-on-error: false` in `.github/workflows/ci.yml`.

The benchmark asserts hard budget failures on `p50 >= 250 ms` or `p95 >= 600 ms`. These assertions are unconditional — the tests are `@pytest.mark.slow` and excluded from the default suite, so they only run when explicitly invoked with `-m slow`.

## Follow-on tickets

The following fixture-scale gaps are unresolved and tracked for Phase 1 closure or Phase 2 spillover. The M13 always-on viability verdict applies only to the measured FNR 2006-018 Group 1 scale; these gaps represent the next measurement tier before Phase 4 `live-preview-cashflow` acceptance.

1. **200-rule synthetic auto ABS** — no large-rule-count auto ABS fixture exists in the repo. A 200-rule synthetic fixture should be authored (e.g., for a Phase 4 stress-test corpus) and added to `tests/performance/live_preview/` with the same p50/p95 budget assertions.

2. **Multi-group RMBS combined deal** — the FNR 2006-018 combined Group 1 + Group 2 deal runs in `test_fnr_2006_018_combined.py` but uses a multi-group input constructor that isn't factored for the benchmark loop. A follow-on should extend the benchmark to the combined deal once the multi-group input helper (`GroupedCollateralInput` path) is available for direct benchmark invocation.

3. **CC master trust with PFA/IFA** — no real CC master-trust fixture exists (`cc_series_test` is a synthetic minimal fixture). Capital One COMET and Chase Issuance Trust are RAG corpus only (per `tests/fixtures/STATUS.md`); no measurement run is possible until a CC master-trust deal builder is authored with PFA/IFA waterfall rules.

These items do not block Phase 1 closure (the M13 verdict stands for the measured scale), but they should be triaged and assigned before the Phase 4 `live-preview-cashflow` ticket opens.

## Decision-gate (M13) summary

Per Phase 0 fold-back M13:

> If the spike rejects always-on preview at fixture scale, the Vision and Phase 4 acceptance contracts are amended as part of the spike's deliverable, NOT silently absorbed by the implementation ticket.

**The spike does NOT reject always-on preview.** All three measured scenarios on the largest existing real-world fixture are within both p50 and p95 targets. No Vision-narrative amendment is required. Phase 4 `live-preview-cashflow` may proceed with the always-on contract as-specified.

If a future fixture (e.g., the synthetic 200-rule auto ABS or a Phase 3 multi-group combined deal at full horizon) breaks budget on representative dev hardware, the spike's verdict can be re-litigated in a follow-on ticket. The benchmark at `tests/performance/live_preview/` is the authoritative regression check for that re-litigation.
