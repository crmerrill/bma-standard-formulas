#!/usr/bin/env python
"""
Profile pool aggregation strategies.

Compares the current _aggregate_actual implementation against four
alternatives for summing FLOW fields across 10k BMAActualCashflow objects.

The stock/ratio reconstruction step (_reconstruct_stocks_and_ratios) is
identical for all approaches and is excluded from the comparison — we're
only benchmarking the FLOW field summation, which is where the strategies
diverge.

Strategies:
  current   Per-field Python loops: for each of N_FIELDS (~18), loop over all
            constituents, np.pad each array, np.stack into (n_periods,
            n_constituents), np.sum(axis=1).

  accum_A   Per-constituent accumulation: one Python loop over constituents;
            inner Python loop over fields; in-place acc[j, :m] += arr.
            No intermediate stacks, no np.pad.

  accum_B   Per-constituent, vectorized per-cf: one Python loop over
            constituents; build (n_fields, m) matrix from all fields at once
            with np.array([...]), then acc[:, :m] += mat.

  stack_3d  Build one 3D array (n_constituents, n_fields, n_periods) in a
            single list comprehension, then np.sum(axis=0).

  reduce    Per-field, but use np.add.reduce on a pre-extracted list instead
            of np.stack + np.sum.  Avoids one intermediate allocation per field.
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import numpy as np

from bma_standard_formulas.engine import Loan, RateIndex, run_actual_portfolio
from bma_standard_formulas.formulas import (
    generate_smm_curve_from_psa,
    generate_sda_curve,
    cdr_to_mdr_vector,
    BMAActualCashflow,
    FieldKind,
)
from bma_standard_formulas.formulas.cashflows import fields_by_kind

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

N_LOANS      = 10_000
N_RUNS       = 7      # timing repetitions per strategy (report median)
ORIGINAL_TERM = 360
ORIGINAL_BALANCE = 350_000.0
ASOF_DATE = date(2026, 3, 1)
RNG_SEED  = 42

FIXTURES      = Path(__file__).parent.parent / "tests" / "fixtures"
SOFR_HIST_CSV = FIXTURES / "SOFR_historical.csv"
SOFR_FWD_CSV  = FIXTURES / "03032026_SOFR3M_FWD.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    return d.replace(year=y, month=m % 12 + 1, day=min(d.day, 28))


def _approx_balance(original: float, coupon_pct: float, orig_term: int, age: int) -> float:
    if age == 0:
        return original
    r = coupon_pct / 1200.0
    if r == 0.0:
        return original * (1 - age / orig_term)
    rem = orig_term - age
    return original * (1 - (1 + r) ** (-rem)) / (1 - (1 + r) ** (-orig_term))


def _time_runs(fn, n_runs: int) -> np.ndarray:
    """Run fn() n_runs times, return array of elapsed seconds."""
    times = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return np.array(times)


def _report(label: str, times_s: np.ndarray, baseline_s: float) -> None:
    med = np.median(times_s)
    speedup = baseline_s / med
    print(f"  {label:<14}  median={med:.3f}s  min={times_s.min():.3f}s  "
          f"max={times_s.max():.3f}s  vs baseline: {speedup:.2f}x")


# ---------------------------------------------------------------------------
# Alternative aggregation strategies (FLOW fields only)
# ---------------------------------------------------------------------------

def _flow_fields_current(cfs: list[BMAActualCashflow]) -> dict[str, np.ndarray]:
    """Current implementation: per-field loops + np.stack + np.sum."""
    n = max(len(cf.period) for cf in cfs)
    return {
        f.name: np.sum(
            np.stack([
                np.pad(getattr(cf, f.name), (0, n - len(cf.period)), constant_values=0)
                for cf in cfs
            ], axis=1),
            axis=1,
        )
        for f in fields_by_kind(BMAActualCashflow, FieldKind.FLOW)
    }


def _flow_fields_accum_a(cfs: list[BMAActualCashflow]) -> dict[str, np.ndarray]:
    """Alt A: per-constituent accumulation, inner Python loop over fields."""
    n = max(len(cf.period) for cf in cfs)
    flow_field_names = [f.name for f in fields_by_kind(BMAActualCashflow, FieldKind.FLOW)]
    n_fields = len(flow_field_names)
    acc = np.zeros((n_fields, n), dtype=np.float64)
    for cf in cfs:
        m = len(cf.period)
        for j, name in enumerate(flow_field_names):
            acc[j, :m] += getattr(cf, name)
    return {flow_field_names[j]: acc[j] for j in range(n_fields)}


def _flow_fields_accum_b(cfs: list[BMAActualCashflow]) -> dict[str, np.ndarray]:
    """Alt B: per-constituent accumulation, vectorized per constituent.
    Builds (n_fields, m) matrix from all fields at once, then acc[:, :m] += mat.
    """
    n = max(len(cf.period) for cf in cfs)
    flow_field_names = [f.name for f in fields_by_kind(BMAActualCashflow, FieldKind.FLOW)]
    n_fields = len(flow_field_names)
    acc = np.zeros((n_fields, n), dtype=np.float64)
    for cf in cfs:
        m = len(cf.period)
        mat = np.array([getattr(cf, name) for name in flow_field_names], dtype=np.float64)
        acc[:, :m] += mat
    return {flow_field_names[j]: acc[j] for j in range(n_fields)}


def _flow_fields_stack_3d(cfs: list[BMAActualCashflow]) -> dict[str, np.ndarray]:
    """Alt C: build one 3D array (n_constituents, n_fields, n_periods), sum axis=0."""
    n = max(len(cf.period) for cf in cfs)
    flow_field_names = [f.name for f in fields_by_kind(BMAActualCashflow, FieldKind.FLOW)]
    # Build (n_constituents, n_fields, n_periods)
    stack = np.array([
        [np.pad(getattr(cf, name), (0, n - len(cf.period)), constant_values=0)
         for name in flow_field_names]
        for cf in cfs
    ], dtype=np.float64)
    summed = stack.sum(axis=0)  # (n_fields, n_periods)
    return {flow_field_names[j]: summed[j] for j in range(len(flow_field_names))}


def _flow_fields_reduce(cfs: list[BMAActualCashflow]) -> dict[str, np.ndarray]:
    """Alt D: per-field, use np.add.reduce on pre-padded list (no stack allocation)."""
    n = max(len(cf.period) for cf in cfs)
    return {
        f.name: np.add.reduce([
            np.pad(getattr(cf, f.name), (0, n - len(cf.period)), constant_values=0)
            for cf in cfs
        ])
        for f in fields_by_kind(BMAActualCashflow, FieldKind.FLOW)
    }


# ---------------------------------------------------------------------------
# flow_matrix strategy helpers
# ---------------------------------------------------------------------------
#
# The _flow_matrix proposal pre-packs all FLOW fields into a (n_flow, n_periods)
# matrix at BMAActualCashflow construction (in __post_init__), so that pool
# aggregation can do one matrix-add per constituent instead of n_flow scalar
# slice-adds per constituent.
#
# Here we profile this idea WITHOUT modifying production code:
#   _pack_flow_matrices   simulates the __post_init__ pre-packing cost
#   _flow_fields_from_matrices  simulates the aggregation cost
#
# This lets us answer: does the aggregation speedup outweigh the construction
# overhead paid on every single cashflow generation (not just on aggregation)?
# ---------------------------------------------------------------------------

def _pack_flow_matrices(
    cfs: list[BMAActualCashflow],
    flow_field_names: list[str],
) -> list[np.ndarray]:
    """Build (n_flow, m) matrix for each cashflow — simulates __post_init__ overhead.

    This is the cost we'd pay at *construction* time for every loan in the portfolio,
    not just during aggregation.  Each matrix is contiguous float64, shape (n_fields, m).
    """
    return [
        np.array([getattr(cf, name) for name in flow_field_names], dtype=np.float64)
        for cf in cfs
    ]


def _flow_fields_from_matrices(
    matrices: list[np.ndarray],
    flow_field_names: list[str],
) -> dict[str, np.ndarray]:
    """Aggregation using pre-packed matrices: one numpy op per constituent."""
    n = max(mat.shape[1] for mat in matrices)
    n_fields = len(flow_field_names)
    acc = np.zeros((n_fields, n), dtype=np.float64)
    for mat in matrices:
        m = mat.shape[1]
        acc[:, :m] += mat
    return {flow_field_names[j]: acc[j] for j in range(n_fields)}


# ---------------------------------------------------------------------------
# Setup: generate real cashflows
# ---------------------------------------------------------------------------

def generate_cashflows() -> list[BMAActualCashflow]:
    print("  Loading SOFR...", end="", flush=True)
    sofr_hist = RateIndex.from_csv(SOFR_HIST_CSV)
    sofr_fwd  = RateIndex.from_csv(SOFR_FWD_CSV, date_col="ResetDate", rate_col="Rate")
    sofr      = RateIndex.merge(sofr_hist, sofr_fwd, name="SOFR")
    print(f" {len(sofr):,} obs")

    rng          = np.random.default_rng(RNG_SEED)
    ages         = rng.integers(0, 121, size=N_LOANS)
    is_arm       = rng.random(size=N_LOANS) < 0.5
    coupon_fixed = rng.uniform(6.5, 8.5, size=N_LOANS)
    arm_spread   = rng.uniform(1.25, 2.25, size=N_LOANS)
    psa_speeds   = rng.integers(80, 221, size=N_LOANS)

    sda_cdr   = generate_sda_curve(100.0, ORIGINAL_TERM)
    mdr_curve = cdr_to_mdr_vector(sda_cdr)
    sev_curve = np.full(ORIGINAL_TERM + 1, 0.35)

    loans: list[Loan] = []
    smm_curves: dict[int, np.ndarray] = {}
    for i in range(N_LOANS):
        age     = int(ages[i])
        rem     = ORIGINAL_TERM - age
        orig_dt = _add_months(ASOF_DATE, -age)
        coupon  = float(arm_spread[i]) if is_arm[i] else float(coupon_fixed[i])
        cur_bal = _approx_balance(ORIGINAL_BALANCE, coupon, ORIGINAL_TERM, age)
        next_reset = (
            date(ASOF_DATE.year, 1, 1)
            if is_arm[i] and ASOF_DATE.month > 1
            else (date(ASOF_DATE.year - 1, 1, 1) if is_arm[i] else None)
        )
        loans.append(Loan(
            loan_id=i + 1, origination_date=orig_dt, asof_date=ASOF_DATE,
            original_balance=ORIGINAL_BALANCE, current_balance=cur_bal,
            rate_margin=coupon, original_term=ORIGINAL_TERM, remaining_term=rem,
            servicing_fee=0.25,
            first_payment_date=_add_months(orig_dt, 1).replace(day=1),
            reset_frequency=12 if is_arm[i] else 0,
            index_type="SOFR" if is_arm[i] else None,
            next_reset_date=next_reset,
        ))
        smm_curves[i + 1] = generate_smm_curve_from_psa(int(psa_speeds[i]), ORIGINAL_TERM)

    print(f"  Generating {N_LOANS:,} actual cashflows...", end="", flush=True)
    t0 = time.perf_counter()
    portfolio = run_actual_portfolio(
        loans, smm_curves=smm_curves, mdr_curves=mdr_curve,
        severity_curves=sev_curve, rate_index=sofr, flush=False,
    )
    gen_s = time.perf_counter() - t0

    # Extract raw BMAActualCashflow list from _pending
    cfs = [c for c in portfolio._pending if isinstance(c, BMAActualCashflow)]
    print(f" done ({gen_s:.2f}s)")
    return cfs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 72)
    print("SETUP: generating real cashflows")
    print("=" * 72)
    cfs = generate_cashflows()
    n = max(len(cf.period) for cf in cfs)
    print(f"\n  {len(cfs):,} cashflows  |  max periods: {n}  "
          f"|  FLOW fields: {len(list(fields_by_kind(BMAActualCashflow, FieldKind.FLOW)))}")

    flow_field_names = [f.name for f in fields_by_kind(BMAActualCashflow, FieldKind.FLOW)]

    # Warm up each strategy once before timing
    print("\n  Warming up all strategies...")
    _flow_fields_current(cfs)
    _flow_fields_accum_a(cfs)
    _flow_fields_accum_b(cfs)
    _flow_fields_stack_3d(cfs)
    _flow_fields_reduce(cfs)
    matrices = _pack_flow_matrices(cfs, flow_field_names)
    _flow_fields_from_matrices(matrices, flow_field_names)
    print("  Done.\n")

    # ---------------------------------------------------------------------------
    # Verify correctness: all alternatives must match current
    # ---------------------------------------------------------------------------
    print("=" * 72)
    print("CORRECTNESS CHECK (all strategies vs current)")
    print("=" * 72)
    ref    = _flow_fields_current(cfs)
    fm_result = _flow_fields_from_matrices(matrices, flow_field_names)
    checks = [
        ("accum_A",      _flow_fields_accum_a(cfs)),
        ("accum_B",      _flow_fields_accum_b(cfs)),
        ("stack_3d",     _flow_fields_stack_3d(cfs)),
        ("reduce",       _flow_fields_reduce(cfs)),
        ("flow_matrix",  fm_result),
    ]
    all_ok = True
    for label, result in checks:
        mismatches = [
            f for f in ref
            if not np.allclose(ref[f], result[f], rtol=1e-12, atol=1e-12)
        ]
        status = "PASS" if not mismatches else f"FAIL ({mismatches})"
        print(f"  {label:<14}  {status}")
        if mismatches:
            all_ok = False

    if not all_ok:
        print("\n  WARNING: correctness failures detected — timing results may be misleading")

    # ---------------------------------------------------------------------------
    # Timing — aggregation only (apples-to-apples comparison)
    # ---------------------------------------------------------------------------
    print()
    print("=" * 72)
    print(f"TIMING — AGGREGATION ONLY  ({N_RUNS} runs each, reporting median)")
    print("=" * 72)
    print("  (flow_matrix uses pre-built matrices; pack cost measured separately below)")
    print()

    strategies = [
        ("current",      lambda: _flow_fields_current(cfs)),
        ("accum_A",      lambda: _flow_fields_accum_a(cfs)),
        ("accum_B",      lambda: _flow_fields_accum_b(cfs)),
        ("stack_3d",     lambda: _flow_fields_stack_3d(cfs)),
        ("reduce",       lambda: _flow_fields_reduce(cfs)),
        ("flow_matrix",  lambda: _flow_fields_from_matrices(matrices, flow_field_names)),
    ]

    results: dict[str, np.ndarray] = {}
    for label, fn in strategies:
        print(f"  timing {label}...", end="", flush=True)
        results[label] = _time_runs(fn, N_RUNS)
        print(f" median={np.median(results[label]):.3f}s")

    baseline = float(np.median(results["current"]))
    print()
    print(f"  {'Strategy':<14}  {'median':>8}  {'min':>8}  {'max':>8}  {'vs baseline':>12}")
    print(f"  {'-'*14}  {'--------':>8}  {'--------':>8}  {'--------':>8}  {'------------':>12}")
    for label, times in results.items():
        med = np.median(times)
        ratio = baseline / med
        marker = " ← baseline" if label == "current" else (
            f" ← {ratio:.2f}x {'faster' if ratio > 1 else 'slower'}"
        )
        print(f"  {label:<14}  {med:>7.3f}s  {times.min():>7.3f}s  "
              f"{times.max():>7.3f}s  {ratio:>11.2f}x{marker}")

    # ---------------------------------------------------------------------------
    # Timing — flow_matrix construction overhead
    # ---------------------------------------------------------------------------
    # Pre-packing matrices happens once per cashflow generation, not once per
    # aggregation.  We need to know whether the pack cost exceeds the aggregation
    # savings vs accum_A, since in production it is always paid.
    # ---------------------------------------------------------------------------
    print()
    print("=" * 72)
    print(f"TIMING — flow_matrix CONSTRUCTION OVERHEAD  ({N_RUNS} runs)")
    print("=" * 72)
    print("  Measuring time to pre-pack all flow fields into (n_flow, m) matrices")
    print("  for all 10k cashflows.  This cost is paid at construction time, NOT")
    print("  during aggregation — so it adds to the generation budget, not the")
    print("  aggregation budget.")
    print()

    pack_times = _time_runs(lambda: _pack_flow_matrices(cfs, flow_field_names), N_RUNS)
    pack_med   = float(np.median(pack_times))

    accum_a_med   = float(np.median(results["accum_A"]))
    flow_mat_med  = float(np.median(results["flow_matrix"]))
    agg_savings   = accum_a_med - flow_mat_med   # how much faster flow_matrix is vs accum_A in agg

    print(f"  Pack time (median):                   {pack_med:.3f}s")
    print(f"  Pack time (min):                      {pack_times.min():.3f}s")
    print()
    print(f"  Aggregation savings vs accum_A:       {agg_savings:.4f}s  "
          f"({'faster' if agg_savings > 0 else 'slower'} in agg step)")
    net = pack_med - agg_savings
    verdict = (
        f"net COST of {net:.4f}s per portfolio"
        if net > 0
        else f"net SAVING of {-net:.4f}s per portfolio"
    )
    print(f"  Net (pack - agg savings):             {net:+.4f}s  →  {verdict}")
    print()
    print("  Total cost breakdown:")
    print(f"    accum_A total (no pre-pack):        {accum_a_med:.3f}s  (agg only)")
    print(f"    flow_matrix total (pack + agg):     {pack_med + flow_mat_med:.3f}s")
    ratio_total = accum_a_med / (pack_med + flow_mat_med)
    print(f"    accum_A vs flow_matrix total:       {ratio_total:.2f}x  "
          f"({'accum_A faster' if ratio_total > 1 else 'flow_matrix faster'} end-to-end)")

    # ---------------------------------------------------------------------------
    # Memory estimate
    # ---------------------------------------------------------------------------
    print()
    print("=" * 72)
    print("MEMORY ESTIMATE (peak intermediate allocations)")
    print("=" * 72)
    n_fields = len(flow_field_names)
    per_field_mb   = N_LOANS * n * 8 / 1e6
    stack_3d_mb    = N_LOANS * n_fields * n * 8 / 1e6
    accum_mb       = n_fields * n * 8 / 1e6
    per_cf_mat_mb  = n_fields * n * 8 / 1e6          # one (n_fields, n) matrix resident per cf
    all_cf_mats_mb = N_LOANS * n_fields * 170 * 8 / 1e6  # all pre-packed (avg ~170 periods/cf)
    print(f"  current     peak per field stack: {per_field_mb:.1f} MB  "
          f"× {n_fields} fields = {per_field_mb * n_fields:.1f} MB total (sequential)")
    print(f"  stack_3d    single 3D allocation: {stack_3d_mb:.1f} MB  (all at once)")
    print(f"  accum_A/B   running accumulator:  {accum_mb:.2f} MB  (plus per-cf matrix in accum_B)")
    print(f"  flow_matrix per-cf matrix (live): {per_cf_mat_mb:.2f} MB  (temp, discarded each iter)")
    print(f"  flow_matrix if stored on object:  {all_cf_mats_mb:.1f} MB  "
          f"({N_LOANS:,} × {n_fields} fields × ~170 periods × 8B)")


if __name__ == "__main__":
    main()
