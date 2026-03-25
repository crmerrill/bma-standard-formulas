#!/usr/bin/env python
"""
Profile: 10,000-loan portfolio — cashflow generation + aggregation.

Measures end-to-end wall-clock time using the engine layer (Loan objects,
RateIndex, run_actual_portfolio).  Loans are a 50/50 mix of fixed-rate and
annual ARM, with varying seasoning (ages 0–120 months).  Floating-rate loans
reset annually against real SOFR data (historical 2018–2026 merged with
the forward curve through 2036).

Timing sections:
  1. Setup       — load SOFR fixtures, merge, build assumption curves, create loans
  2. Generation  — run_actual_portfolio (scheduled + actual per loan, then aggregate)
  3. Realization — pool and pass-through cashflow field access (lazy evaluation)
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import numpy as np

from bma_standard_formulas.engine import (
    Loan,
    RateIndex,
    run_actual_portfolio,
)
from bma_standard_formulas.formulas import (
    generate_smm_curve_from_psa,
    generate_sda_curve,
    cdr_to_mdr_vector,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

N_LOANS          = 10_000
ORIGINAL_TERM    = 360          # 30-year mortgages
ORIGINAL_BALANCE = 350_000.0   # $ face value at origination

ARM_FRACTION     = 0.50         # fraction of loans that are floating-rate ARM
PSA_MIN, PSA_MAX = 80, 220      # per-loan PSA speed range
SDA_SPEED        = 100.0        # % SDA for shared default curve
SEVERITY         = 0.35         # loss severity fraction (shared)

ASOF_DATE = date(2026, 3, 1)    # valuation / reporting date

RNG_SEED = 42

FIXTURES      = Path(__file__).parent.parent / "tests" / "fixtures"
SOFR_HIST_CSV = FIXTURES / "SOFR_historical.csv"
SOFR_FWD_CSV  = FIXTURES / "03032026_SOFR3M_FWD.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _approx_current_balance(original_balance: float, coupon_pct: float,
                             original_term: int, age: int) -> float:
    """Scheduled balance factor × original face — standard amortisation."""
    if age == 0:
        return original_balance
    r = coupon_pct / 1200.0
    if r == 0.0:
        return original_balance * (1 - age / original_term)
    rem = original_term - age
    bal_factor = (1 - (1 + r) ** (-rem)) / (1 - (1 + r) ** (-original_term))
    return original_balance * bal_factor


def _add_months(d: date, n: int) -> date:
    """Advance a date by n months, clamping day to 28 to avoid month-end errors."""
    m = d.month - 1 + n
    y = d.year + m // 12
    mo = m % 12 + 1
    return d.replace(year=y, month=mo, day=min(d.day, 28))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    rng = np.random.default_rng(RNG_SEED)

    # =========================================================================
    # 1. SETUP
    # =========================================================================
    print("=" * 72)
    print("1. SETUP")
    print("=" * 72)
    t_setup = time.perf_counter()

    # --- SOFR: historical (daily 2018–2026) merged with forward (monthly 2026–2036)
    t0 = time.perf_counter()
    sofr_hist = RateIndex.from_csv(SOFR_HIST_CSV, name="SOFR_HIST")
    sofr_fwd  = RateIndex.from_csv(
        SOFR_FWD_CSV, date_col="ResetDate", rate_col="Rate", name="SOFR_FWD"
    )
    # Forward takes precedence on any overlap at the splice point
    sofr = RateIndex.merge(sofr_hist, sofr_fwd, name="SOFR")
    sofr_ms = (time.perf_counter() - t0) * 1e3
    print(f"\n  SOFR index: {len(sofr):,} obs  "
          f"({sofr.dates[0]} → {sofr.dates[-1]})  [{sofr_ms:.1f} ms]")

    # --- Age-indexed assumption curves (length 361: index 0 = origination)
    # Using age-indexed curves means a single array works for all seasoning levels;
    # actual_cashflow_from_loan slices the correct [age : age + remaining_term + 1]
    # window automatically.
    curve_len = ORIGINAL_TERM + 1
    t0 = time.perf_counter()
    sda_cdr   = generate_sda_curve(SDA_SPEED, ORIGINAL_TERM)  # % CDR, age-indexed
    mdr_curve = cdr_to_mdr_vector(sda_cdr)                    # decimal MDR
    sev_curve = np.full(curve_len, SEVERITY)
    curves_ms = (time.perf_counter() - t0) * 1e3
    print(f"  SDA {SDA_SPEED:.0f}% MDR + {SEVERITY:.0%} severity (age-indexed, len={curve_len})"
          f"  [{curves_ms:.1f} ms]")

    # --- Create 10k Loan objects
    t0 = time.perf_counter()
    ages         = rng.integers(0, 121, size=N_LOANS)        # seasoning months [0, 120]
    is_arm       = rng.random(size=N_LOANS) < ARM_FRACTION
    coupon_fixed = rng.uniform(6.5, 8.5, size=N_LOANS)       # % full coupon (fixed loans)
    arm_spread   = rng.uniform(1.25, 2.25, size=N_LOANS)     # % spread over SOFR (ARM loans)
    psa_speeds   = rng.integers(PSA_MIN, PSA_MAX + 1, size=N_LOANS)

    loans: list[Loan] = []
    smm_curves: dict[int, np.ndarray] = {}

    for i in range(N_LOANS):
        age     = int(ages[i])
        rem     = ORIGINAL_TERM - age
        orig_dt = _add_months(ASOF_DATE, -age)
        coupon  = float(arm_spread[i]) if is_arm[i] else float(coupon_fixed[i])
        cur_bal = _approx_current_balance(ORIGINAL_BALANCE, coupon, ORIGINAL_TERM, age)

        # ARM loans reset annually; as-of March 2026, last reset was Jan 2026
        next_reset = (
            date(ASOF_DATE.year, 1, 1) if ASOF_DATE.month > 1
            else date(ASOF_DATE.year - 1, 1, 1)
        ) if is_arm[i] else None

        # First payment is the 1st of the month after origination (standard US mortgage
        # convention: payment due the 1st, covering the prior month's interest).
        first_pmt = _add_months(orig_dt, 1).replace(day=1)

        loans.append(Loan(
            loan_id            = i + 1,
            origination_date   = orig_dt,
            asof_date          = ASOF_DATE,
            original_balance   = ORIGINAL_BALANCE,
            current_balance    = cur_bal,
            rate_margin        = coupon,    # % — full coupon for fixed, spread for ARM
            original_term      = ORIGINAL_TERM,
            remaining_term     = rem,
            servicing_fee      = 0.25,      # 25 bps
            first_payment_date = first_pmt,
            reset_frequency    = 12 if is_arm[i] else 0,
            index_type         = "SOFR" if is_arm[i] else None,
            next_reset_date    = next_reset,
        ))

        # Per-loan PSA SMM curve (age-indexed)
        smm_curves[i + 1] = generate_smm_curve_from_psa(int(psa_speeds[i]), ORIGINAL_TERM)

    loan_ms = (time.perf_counter() - t0) * 1e3
    n_arm   = int(is_arm.sum())
    n_fixed = N_LOANS - n_arm
    print(f"  {N_LOANS:,} loans: {n_fixed:,} fixed-rate, {n_arm:,} ARM  [{loan_ms:.1f} ms]")
    print(f"  PSA: {PSA_MIN}–{PSA_MAX}% per-loan  |  "
          f"Fixed coupons: {coupon_fixed.min():.2f}–{coupon_fixed.max():.2f}%  |  "
          f"ARM spreads: {arm_spread.min():.2f}–{arm_spread.max():.2f}% over SOFR")

    print(f"\n  SETUP TOTAL:  {time.perf_counter() - t_setup:.3f} s")

    # =========================================================================
    # 2. CASHFLOW GENERATION + AGGREGATION
    # =========================================================================
    print()
    print("=" * 72)
    print("2. CASHFLOW GENERATION + AGGREGATION  (run_actual_portfolio)")
    print("=" * 72)

    # Warm-up: one throwaway call to trigger any lazy initialisation
    run_actual_portfolio(
        [loans[0]],
        smm_curves=smm_curves[loans[0].loan_id],
        mdr_curves=mdr_curve,
        severity_curves=sev_curve,
        rate_index=sofr,
    )
    print("\n  Warm-up complete.\n")

    # Time the full run at increasing loan counts to show scaling
    milestone_sizes = [100, 500, 1_000, 2_500, 5_000, 7_500, N_LOANS]
    milestone_times: dict[int, float] = {}
    portfolio = None

    for n in milestone_sizes:
        t0 = time.perf_counter()
        portfolio = run_actual_portfolio(
            loans[:n],
            smm_curves=smm_curves,
            mdr_curves=mdr_curve,
            severity_curves=sev_curve,
            rate_index=sofr,
            flush=False,
        )
        milestone_times[n] = time.perf_counter() - t0

    total_gen_s = milestone_times[N_LOANS]

    print(f"  {'Loans':>8}   {'Total (s)':>10}   {'ms / loan':>10}")
    print(f"  {'--------':>8}   {'----------':>10}   {'----------':>10}")
    for n in milestone_sizes:
        t_s = milestone_times[n]
        print(f"  {n:>8,}   {t_s:>10.3f}   {1e3*t_s/n:>10.3f}")

    print(f"\n  GENERATION TOTAL ({N_LOANS:,} loans):  {total_gen_s:.3f} s  "
          f"({1e3*total_gen_s/N_LOANS:.3f} ms/loan avg)")
    print(f"  Portfolio constituents:            {portfolio.n_constituents:,}")

    # =========================================================================
    # 3. REALIZATION  (lazy evaluation: pool aggregation + waterfall)
    # =========================================================================
    print()
    print("=" * 72)
    print("3. REALIZATION  (pool aggregation + pass-through cashflows)")
    print("=" * 72)

    t_real = time.perf_counter()

    # First access to .pool triggers _aggregate_actual (the expensive step)
    t0 = time.perf_counter()
    pool = portfolio.pool
    pool_s = time.perf_counter() - t0

    # All further .pool field accesses are cached — should be near-zero
    t0 = time.perf_counter()
    _ = pool.period
    _ = pool.perf_bal
    _ = pool.act_am
    _ = pool.vol_prepay
    _ = pool.new_def
    _ = pool.fcl
    _ = pool.svc_billed
    _ = pool.prin_recov
    cached_s = time.perf_counter() - t0

    # Pass-through / waterfall fields
    t0 = time.perf_counter()
    _ = portfolio.pt_principal
    _ = portfolio.pt_interest
    pt_cf = portfolio.pt_cashflow
    _ = portfolio.gross_cashflow
    _ = portfolio.svc_cashflow
    waterfall_s = time.perf_counter() - t0

    total_real_s = time.perf_counter() - t_real

    print(f"\n  Pool aggregation (_aggregate_actual):  {pool_s:.3f} s")
    print(f"  Pool field access (all, cached):       {cached_s:.6f} s")
    print(f"  Waterfall / pass-through:              {waterfall_s:.3f} s")
    print(f"  REALIZATION TOTAL:                     {total_real_s:.3f} s")
    print(f"\n  Pool periods:         {len(pool.period)}")
    print(f"  pt_cashflow total:    ${pt_cf.sum():>15,.0f}")

    # =========================================================================
    # SUMMARY
    # =========================================================================
    total_setup_s = (sofr_ms + curves_ms + loan_ms) / 1e3
    total_e2e     = total_setup_s + total_gen_s + total_real_s
    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"  Setup (SOFR + curves + loans):      {total_setup_s:>8.3f} s")
    print(f"    SOFR load + merge:                {sofr_ms/1e3:>8.3f} s")
    print(f"    Assumption curves:                {curves_ms/1e3:>8.3f} s")
    print(f"    Loan object creation:             {loan_ms/1e3:>8.3f} s")
    print(f"  Generation ({N_LOANS:,} loans):         {total_gen_s:>8.3f} s  "
          f"({1e3*total_gen_s/N_LOANS:.3f} ms/loan)")
    print(f"  Realization (pool + waterfall):     {total_real_s:>8.3f} s")
    print(f"  ─────────────────────────────────────────")
    print(f"  Total end-to-end:                   {total_e2e:>8.3f} s")


if __name__ == "__main__":
    main()
