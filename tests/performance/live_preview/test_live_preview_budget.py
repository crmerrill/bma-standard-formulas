"""Live preview performance spike (live-preview-perf-spike Phase 1 ticket).

Measures end-to-end engine latency for one debounced base-case run on the
existing fixture deals. Per the plan's targets:

- TARGET_P50_MS = 250
- TARGET_P95_MS = 600

The spike runs the FNR 2006-018 Group 1 fixture (the largest existing real-world
RMBS fixture builder that runs cleanly with `_deal_input_from_repline`: PAC + Z
+ Support, ~10 waterfall rules, single collateral group, 360-period horizon).
The full FNR combined Group 1 + Group 2 deal needs a multi-group input
constructor; that's exercised by `test_fnr_2006_018_combined.py` and is out of
scope for the spike's measurement (single-group is the most representative
keystroke-cadence preview workload).

If targets are met, the always-on preview pattern is viable as-specified.
If not, the spike rejects always-on preview at fixture scale and the plan's
Vision narrative + Phase 4 `live-preview-cashflow` acceptance contract MUST
be amended per Phase 0 fold-back M13 BEFORE `live-preview-cashflow` opens.

Run via: pytest -m slow tests/performance/live_preview/

Marked `slow` so it doesn't run by default in `pytest tests/`.
"""

from __future__ import annotations

import statistics
import time

import pytest

from bma_standard_formulas.deals.runtime import run_deal
from tests.fixtures.fnr_2006_018.deal_definition import (
    build_fnr_2006_018_group_1_deal,
)
from tests.test_fnr_2006_018_parity import _deal_input_from_repline


# Plan targets (ms).
TARGET_P50_MS = 250.0
TARGET_P95_MS = 600.0

# Number of timed iterations per scenario. Higher N → tighter percentile estimates.
ITERATIONS = 20


def _percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile in [0, 1]."""
    if not values:
        return 0.0
    s = sorted(values)
    if q <= 0:
        return s[0]
    if q >= 1:
        return s[-1]
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def _measure_run(deal, run_input, iterations: int = ITERATIONS) -> dict[str, float]:
    """Measure run_deal latency over N iterations. Discards a warm-up run."""
    samples_ms: list[float] = []
    # Warm-up (JIT, caches, etc.).
    run_deal(deal, run_input, scenario_name="warmup")
    for _ in range(iterations):
        t0 = time.perf_counter()
        run_deal(deal, run_input, scenario_name="perf-spike")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        samples_ms.append(elapsed_ms)
    return {
        "n": float(len(samples_ms)),
        "min_ms": min(samples_ms),
        "p50_ms": _percentile(samples_ms, 0.50),
        "p95_ms": _percentile(samples_ms, 0.95),
        "max_ms": max(samples_ms),
        "mean_ms": statistics.mean(samples_ms),
        "stdev_ms": statistics.stdev(samples_ms) if len(samples_ms) > 1 else 0.0,
    }


def _print_stats(label: str, stats: dict[str, float]) -> None:
    print("\n" + "=" * 72)
    print(label)
    print("=" * 72)
    print(f"  n        = {stats['n']:.0f}")
    print(f"  min      = {stats['min_ms']:8.2f} ms")
    print(f"  mean     = {stats['mean_ms']:8.2f} ms (stdev {stats['stdev_ms']:.2f})")
    print(f"  p50      = {stats['p50_ms']:8.2f} ms  (target < {TARGET_P50_MS:.0f} ms)")
    print(f"  p95      = {stats['p95_ms']:8.2f} ms  (target < {TARGET_P95_MS:.0f} ms)")
    print(f"  max      = {stats['max_ms']:8.2f} ms")
    print("=" * 72)
    p50_ok = stats["p50_ms"] < TARGET_P50_MS
    p95_ok = stats["p95_ms"] < TARGET_P95_MS
    if p50_ok and p95_ok:
        print("  VERDICT  = WITHIN BUDGET — always-on preview is viable at this scale.")
    else:
        print(
            "  VERDICT  = OVER BUDGET — see "
            "docs/architecture/tickets/phase1/live-preview-perf-spike.STATUS.md"
        )
    print("=" * 72)


@pytest.mark.slow
def test_live_preview_budget_fnr_2006_018_group_1_baseline() -> None:
    """Baseline: FNR 2006-018 Group 1 at 100 PSA, 360-period horizon.

    Real-world RMBS REMIC fixture. The most representative single-group
    preview workload available in the repo today.
    """
    deal = build_fnr_2006_018_group_1_deal()
    run_input = _deal_input_from_repline(100.0, n_periods=360)
    stats = _measure_run(deal, run_input)
    _print_stats("FNR 2006-018 Group 1 (100 PSA, 360 periods)", stats)
    # Sanity: timings are positive.
    assert stats["p50_ms"] > 0
    assert stats["p95_ms"] >= stats["p50_ms"]


@pytest.mark.slow
def test_live_preview_budget_fnr_2006_018_group_1_zero_psa() -> None:
    """Stress: 0 PSA — full-horizon, no prepay-driven amortization."""
    deal = build_fnr_2006_018_group_1_deal()
    run_input = _deal_input_from_repline(0.0, n_periods=360)
    stats = _measure_run(deal, run_input)
    _print_stats("FNR 2006-018 Group 1 (0 PSA, 360 periods)", stats)
    assert stats["p50_ms"] > 0
    assert stats["p95_ms"] >= stats["p50_ms"]


@pytest.mark.slow
def test_live_preview_budget_fnr_2006_018_group_1_300_psa() -> None:
    """Faster amortization: 300 PSA — shorter effective horizon."""
    deal = build_fnr_2006_018_group_1_deal()
    run_input = _deal_input_from_repline(300.0, n_periods=360)
    stats = _measure_run(deal, run_input)
    _print_stats("FNR 2006-018 Group 1 (300 PSA, 360 periods)", stats)
    assert stats["p50_ms"] > 0
    assert stats["p95_ms"] >= stats["p50_ms"]
