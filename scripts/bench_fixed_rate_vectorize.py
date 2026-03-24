#!/usr/bin/env python3
"""
Benchmark: three approaches for fixed-rate scheduled cashflow generation.

Compares per-loan and cumulative timing for:
  BASELINE:  Current Python for-loop (run_bma_scheduled_cashflow as-is)
  OPTION 1:  Derive all fields from sch_balance_factors output (zero loop)
  OPTION 2:  Vectorized annuity function (numpy-ized, no Python loop)

Also times floating-rate (current loop) as reference.
Validates that all three approaches produce identical results.
"""

from __future__ import annotations

import time
import numpy as np

from bma_standard_formulas import (
    run_bma_scheduled_cashflow,
)
from bma_standard_formulas.scheduled_payments import (
    sch_balance_factors,
)
from bma_standard_formulas.cashflows import (
    BMAScheduledCashflow,
    _annuity_payment,
    _build_rate_vector,
)


# =========================================================================
# OPTION 1:  Derive everything from sch_balance_factors (no loop)
# =========================================================================

def scheduled_from_factors(
    original_balance: float,
    current_balance: float,
    rate_margin: float,
    original_term: int,
    remaining_term: int,
    accrued_interest: float = 0.0,
    loan_id: int = 0,
) -> BMAScheduledCashflow:
    """Fixed-rate path: derive all fields from sch_balance_factors.  Zero Python loops."""
    periods = remaining_term + 1
    loan_age = original_term - remaining_term
    monthly_rate = rate_margin / 12.0
    coupon_pct = np.array([rate_margin * 100.0])

    # sch_balance_factors gives us the full BAL and AM path from origination
    rate_vec = np.concatenate([[0.0], np.full(original_term, coupon_pct[0])])
    _, rates_used, _, am_factors_full, balance_factors_full = sch_balance_factors(
        rate_vec, original_term,
    )
    # Slice to our window: age loan_age .. loan_age + remaining_term
    bal_slice = balance_factors_full[loan_age: loan_age + periods]
    am_slice = am_factors_full[loan_age: loan_age + periods]

    # ending_balance[i] = current_balance * bal_slice[i] / bal_slice[0]
    # This scales the factor path to start at current_balance
    scale = current_balance / bal_slice[0] if bal_slice[0] > 0 else 0.0
    ending_balance = bal_slice * scale

    # beginning_balance: shifted ending_balance
    beginning_balance = np.zeros(periods)
    beginning_balance[1:] = ending_balance[:-1]

    # principal_paid = beginning_balance * am_factor  (am_factor = AF - r)
    principal_paid = np.zeros(periods)
    principal_paid[1:] = beginning_balance[1:] * am_slice[1:]

    # interest_billed = beginning_balance * monthly_rate
    interest_billed = np.zeros(periods)
    interest_billed[1:] = beginning_balance[1:] * monthly_rate

    # interest_paid = min(interest_billed, scheduled_payment)
    # For a standard amortizing loan, interest <= payment always
    interest_paid = interest_billed.copy()

    # scheduled_payment = principal_paid + interest_paid
    scheduled_payment = principal_paid + interest_paid

    # gross_rate = interest_billed / beginning_balance
    with np.errstate(divide="ignore", invalid="ignore"):
        gross_rate = np.where(beginning_balance > 0, interest_billed / beginning_balance, 0.0)

    period = np.arange(periods)
    age = (loan_age + period).astype(float)
    pool_factor = ending_balance / original_balance
    amortized_balance_fraction = bal_slice.copy()

    payment_factor = np.zeros(periods)
    with np.errstate(divide="ignore", invalid="ignore"):
        payment_factor[1:] = np.where(
            beginning_balance[1:] > 0, principal_paid[1:] / beginning_balance[1:], 0.0,
        )

    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(amortized_balance_fraction > 1e-12,
                         pool_factor / amortized_balance_fraction, np.nan)
        survival_factor = np.where(np.isfinite(ratio), ratio, 1.0)

    return BMAScheduledCashflow(
        period=period,
        beginning_balance=beginning_balance,
        scheduled_payment=scheduled_payment,
        payment_factor=payment_factor,
        gross_rate=gross_rate,
        accrued_interest=accrued_interest,
        interest_billed=interest_billed,
        interest_paid=interest_paid,
        principal_paid=principal_paid,
        ending_balance=ending_balance,
        age=age,
        pool_factor=pool_factor,
        amortized_balance_fraction=amortized_balance_fraction,
        survival_factor=survival_factor,
        loan_id=loan_id,
        original_balance=original_balance,
        original_term=original_term,
        remaining_term=remaining_term,
    )


# =========================================================================
# OPTION 2:  Vectorized annuity — build balance path with numpy only
# =========================================================================

def scheduled_vectorized_annuity(
    original_balance: float,
    current_balance: float,
    rate_margin: float,
    original_term: int,
    remaining_term: int,
    accrued_interest: float = 0.0,
    loan_id: int = 0,
) -> BMAScheduledCashflow:
    """Fixed-rate path: vectorize the annuity formula.  No Python loop."""
    periods = remaining_term + 1
    loan_age = original_term - remaining_term
    monthly_rate = rate_margin / 12.0

    period = np.arange(periods)
    age = (loan_age + period).astype(float)

    # For fixed rate: level payment from original terms
    if monthly_rate <= 0:
        fixed_payment = original_balance / original_term
    else:
        fixed_payment = original_balance * monthly_rate / (1 - (1 + monthly_rate) ** (-original_term))

    # Vectorized balance path via recurrence:
    #   ending_balance[i] = ending_balance[i-1] * (1 + r) - payment
    #   = current_balance * (1+r)^i - payment * ((1+r)^i - 1) / r
    # This is a closed-form for the balance at period i with constant rate + payment.
    if monthly_rate > 0:
        periods_vec = np.arange(periods)  # 0, 1, 2, ...
        compound = (1 + monthly_rate) ** periods_vec
        # ending_balance at period i (after i payments):
        # B(i) = B(0)*(1+r)^i - P*((1+r)^i - 1)/r
        ending_balance = current_balance * compound - fixed_payment * (compound - 1.0) / monthly_rate
    else:
        ending_balance = current_balance - fixed_payment * np.arange(periods)
    ending_balance = np.maximum(ending_balance, 0.0)

    beginning_balance = np.zeros(periods)
    beginning_balance[1:] = ending_balance[:-1]

    interest_billed = np.zeros(periods)
    interest_billed[1:] = beginning_balance[1:] * monthly_rate

    scheduled_payment_arr = np.zeros(periods)
    scheduled_payment_arr[1:] = np.minimum(fixed_payment, beginning_balance[1:] + interest_billed[1:])

    interest_paid = np.minimum(interest_billed, scheduled_payment_arr)
    principal_paid = scheduled_payment_arr - interest_paid

    with np.errstate(divide="ignore", invalid="ignore"):
        gross_rate = np.where(beginning_balance > 0, interest_billed / beginning_balance, 0.0)

    pool_factor = ending_balance / original_balance

    payment_factor = np.zeros(periods)
    with np.errstate(divide="ignore", invalid="ignore"):
        payment_factor[1:] = np.where(
            beginning_balance[1:] > 0, principal_paid[1:] / beginning_balance[1:], 0.0,
        )

    # BAL path via sch_balance_factors (needed for survival_factor)
    coupon_pct = np.array([rate_margin * 100.0])
    rate_vec_full = np.concatenate([[0.0], np.full(original_term, coupon_pct[0])])
    _, _, _, _, balance_factors_full = sch_balance_factors(rate_vec_full, original_term)
    amortized_balance_fraction = balance_factors_full[loan_age: loan_age + periods]

    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(amortized_balance_fraction > 1e-12,
                         pool_factor / amortized_balance_fraction, np.nan)
        survival_factor = np.where(np.isfinite(ratio), ratio, 1.0)

    return BMAScheduledCashflow(
        period=period,
        beginning_balance=beginning_balance,
        scheduled_payment=scheduled_payment_arr,
        payment_factor=payment_factor,
        gross_rate=gross_rate,
        accrued_interest=accrued_interest,
        interest_billed=interest_billed,
        interest_paid=interest_paid,
        principal_paid=principal_paid,
        ending_balance=ending_balance,
        age=age,
        pool_factor=pool_factor,
        amortized_balance_fraction=amortized_balance_fraction,
        survival_factor=survival_factor,
        loan_id=loan_id,
        original_balance=original_balance,
        original_term=original_term,
        remaining_term=remaining_term,
    )


# =========================================================================
# Benchmark runner
# =========================================================================

def _percentiles(arr: np.ndarray) -> str:
    return (
        f"min={arr.min():.3f}  p50={np.percentile(arr, 50):.3f}  "
        f"p95={np.percentile(arr, 95):.3f}  p99={np.percentile(arr, 99):.3f}  "
        f"max={arr.max():.3f} ms"
    )


def main() -> None:
    N = 10_000
    OB = 250_000.0
    OT = 360
    RT = 360
    RM = 0.06  # 6% fixed rate

    print("=" * 72)
    print(f"Benchmark: fixed-rate scheduled CF generation ({N:,} loans, {OT}-period)")
    print("=" * 72)

    # --- Warm-up ---
    run_bma_scheduled_cashflow(OB, OB, RM * 100, OT, RT, loan_id=0)
    scheduled_from_factors(OB, OB, RM, OT, RT, loan_id=0)
    scheduled_vectorized_annuity(OB, OB, RM, OT, RT, loan_id=0)

    # --- Validate equivalence ---
    print("\nValidating equivalence (single loan)...")
    baseline = run_bma_scheduled_cashflow(OB, OB, RM * 100, OT, RT, loan_id=1)
    opt1     = scheduled_from_factors(OB, OB, RM, OT, RT, loan_id=1)
    opt2     = scheduled_vectorized_annuity(OB, OB, RM, OT, RT, loan_id=1)

    for name, alt in [("Option 1 (factors)", opt1), ("Option 2 (vec annuity)", opt2)]:
        eb_ok = np.allclose(baseline.ending_balance, alt.ending_balance, atol=1e-4)
        ib_ok = np.allclose(baseline.interest_billed, alt.interest_billed, atol=1e-4)
        pp_ok = np.allclose(baseline.principal_paid, alt.principal_paid, atol=1e-4)
        sp_ok = np.allclose(baseline.scheduled_payment, alt.scheduled_payment, atol=1e-4)
        pf_ok = np.allclose(baseline.pool_factor, alt.pool_factor, atol=1e-8)
        eb_maxdiff = np.max(np.abs(baseline.ending_balance - alt.ending_balance))
        print(f"  {name}: eb={eb_ok} ib={ib_ok} pp={pp_ok} sp={sp_ok} pf={pf_ok}  "
              f"(max |eb diff| = {eb_maxdiff:.2e})")

    # --- BASELINE: current loop ---
    print(f"\n--- BASELINE (current Python loop) ---")
    times = np.empty(N)
    t_total = time.perf_counter()
    for i in range(N):
        t0 = time.perf_counter()
        run_bma_scheduled_cashflow(OB, OB, RM * 100, OT, RT, loan_id=i + 1)
        times[i] = (time.perf_counter() - t0) * 1e3
    baseline_total = time.perf_counter() - t_total
    print(f"  Total:    {baseline_total:.3f} s   ({1e3 * baseline_total / N:.3f} ms/loan)")
    print(f"  Per-loan: {_percentiles(times)}")

    # --- OPTION 1: derive from balance factors ---
    print(f"\n--- OPTION 1 (derive from sch_balance_factors, zero loop) ---")
    times1 = np.empty(N)
    t_total = time.perf_counter()
    for i in range(N):
        t0 = time.perf_counter()
        scheduled_from_factors(OB, OB, RM, OT, RT, loan_id=i + 1)
        times1[i] = (time.perf_counter() - t0) * 1e3
    opt1_total = time.perf_counter() - t_total
    print(f"  Total:    {opt1_total:.3f} s   ({1e3 * opt1_total / N:.3f} ms/loan)")
    print(f"  Per-loan: {_percentiles(times1)}")

    # --- OPTION 2: vectorized annuity ---
    print(f"\n--- OPTION 2 (vectorized annuity formula, zero loop) ---")
    times2 = np.empty(N)
    t_total = time.perf_counter()
    for i in range(N):
        t0 = time.perf_counter()
        scheduled_vectorized_annuity(OB, OB, RM, OT, RT, loan_id=i + 1)
        times2[i] = (time.perf_counter() - t0) * 1e3
    opt2_total = time.perf_counter() - t_total
    print(f"  Total:    {opt2_total:.3f} s   ({1e3 * opt2_total / N:.3f} ms/loan)")
    print(f"  Per-loan: {_percentiles(times2)}")

    # --- FLOATING RATE reference ---
    print(f"\n--- FLOATING RATE (current loop, for reference) ---")
    timesf = np.empty(N)
    t_total = time.perf_counter()
    for i in range(N):
        idx = np.full(RT, 0.05) + np.linspace(0, 0.02, RT) * (i % 7) / 7
        t0 = time.perf_counter()
        run_bma_scheduled_cashflow(OB, OB, (idx + RM) * 100, OT, RT, loan_id=i + 1)
        timesf[i] = (time.perf_counter() - t0) * 1e3
    float_total = time.perf_counter() - t_total
    print(f"  Total:    {float_total:.3f} s   ({1e3 * float_total / N:.3f} ms/loan)")
    print(f"  Per-loan: {_percentiles(timesf)}")

    # --- Summary ---
    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"  {'Approach':<45} {'Total':>8}  {'ms/loan':>8}  {'Speedup':>8}")
    print(f"  {'-'*45} {'-'*8}  {'-'*8}  {'-'*8}")
    print(f"  {'Baseline (Python loop, fixed rate)':<45} {baseline_total:>7.3f}s  {1e3*baseline_total/N:>7.3f}   {'1.0x':>8}")
    print(f"  {'Option 1 (sch_balance_factors, no loop)':<45} {opt1_total:>7.3f}s  {1e3*opt1_total/N:>7.3f}   {baseline_total/opt1_total:>7.1f}x")
    print(f"  {'Option 2 (vectorized annuity, no loop)':<45} {opt2_total:>7.3f}s  {1e3*opt2_total/N:>7.3f}   {baseline_total/opt2_total:>7.1f}x")
    print(f"  {'Floating rate (Python loop, reference)':<45} {float_total:>7.3f}s  {1e3*float_total/N:>7.3f}   {baseline_total/float_total:>7.1f}x")


if __name__ == "__main__":
    main()
