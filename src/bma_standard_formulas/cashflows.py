# Requires Python 3.12+
# Uses native type hints: list[x], tuple[x, y], X | None (PEP 585, PEP 604)
"""
BMA mortgage cashflow calculations (BMA Section C.3).

This module computes monthly cashflows for mortgage loans and pools. It implements
the BMA (Bond Market Association) standard formulas used in residential mortgage-
backed securities (RMBS).

Two main types of cashflows:
  1. Scheduled cashflows: "What if" scenario with no prepayments or defaults.
     Represents the planned amortization of the loan over its life.

  2. Actual cashflows: Realistic scenario with prepayments (borrowers paying off
     early) and defaults. Used for modeling expected bond cashflows.

All arrays are indexed by period. Period 0 is the "as-of" state (starting balance);
period 1 is the first payment month, period 2 the second, etc.

Reference: BMA_FORMULAS.md, Section C.3 (SF-18 to SF-19).
"""
from __future__ import annotations

import warnings
import numpy as np
from dataclasses import dataclass, field, fields

from bma_standard_formulas.scheduled_payments import (
    sch_balance_factor_fixed_rate,
    sch_balance_factors,
)

try:
    import pandas as pd
except ImportError:
    pd = None  # optional: to_dataframe() and __repr__ fall back when missing

__version__ = "0.3.1"


# =============================================================================
# Helpers
# =============================================================================

def _annuity_payment(balance: float, monthly_rate: float, remaining_term: int) -> float:
    """Level payment for a loan: balance * r / (1 - (1+r)^-M). Returns balance/M when r=0."""
    if remaining_term <= 0:
        return 0.0
    if monthly_rate <= 0:
        return balance / remaining_term
    return balance * monthly_rate / (1 - (1 + monthly_rate) ** (-remaining_term))


def _build_rate_vector(
    index: float | np.ndarray,
    rate_margin: float,
    original_term: int,
    remaining_term: int,
) -> tuple[np.ndarray, bool]:
    """
    Build the annual rate vector (decimal) for periods 1..remaining_term.

    Similar to sch_payment_factor_vector / sch_balance_factors:
    - index=0 or len 1: fixed rate (rate = index + rate_margin for all periods)
    - index vector: floating rate, oldest first; extended backward with oldest,
      forward with newest if shorter than remaining_term

    Returns:
        (monthly_rate: length remaining_term+1, monthly_rate[0]=0),
        is_fixed: True if fixed rate (constant)
    """
    index_arr = np.asarray(index, dtype=float)
    if index_arr.ndim == 0:
        rate_scalar = float(index_arr)
        if rate_scalar < 0 or rate_margin < 0:
            raise ValueError("index and rate_margin must be >= 0")
        full_rate = rate_scalar + rate_margin
        return np.concatenate([[0.0], np.full(remaining_term, full_rate / 12.0)]), True
    if len(index_arr) == 0:
        raise ValueError("index cannot be empty when array-like")
    if np.any(index_arr < 0) or rate_margin < 0:
        raise ValueError("all index values and rate_margin must be >= 0")
    coupon_vec = index_arr + rate_margin
    coupons_given = len(coupon_vec)
    if coupons_given == 1:
        return np.concatenate([[0.0], np.full(remaining_term, float(coupon_vec[0]) / 12.0)]), True
    if coupons_given >= remaining_term:
        rates = np.concatenate([[0.0], np.asarray(coupon_vec[:remaining_term], dtype=float) / 12.0])
        return rates, False
    oldest = float(coupon_vec[0])
    newest = float(coupon_vec[-1])
    loan_age = original_term - remaining_term
    backward_fill = max(0, loan_age - coupons_given)
    if backward_fill > 0:
        warnings.warn(
            f"index has {coupons_given} rates but {loan_age} historical periods needed. "
            f"Extending oldest rate backwards for {backward_fill} period(s).",
            UserWarning,
        )
    forward_fill = max(0, remaining_term - coupons_given - backward_fill)
    full_annual = np.concatenate([
        np.full(backward_fill, oldest),
        np.asarray(coupon_vec, dtype=float),
        np.full(forward_fill, newest),
    ])[:remaining_term]
    monthly = np.concatenate([[0.0], full_annual / 12.0])
    return monthly, False


def _reconstruct_stocks_and_ratios(
    n: int,
    perf_bal_0: float,
    fcl_0: float,
    new_def: np.ndarray,
    vol_prepay: np.ndarray,
    act_am: np.ndarray,
    am_def: np.ndarray,
    exp_am: np.ndarray,
    exp_int: np.ndarray,
    lost_int: np.ndarray,
    act_int: np.ndarray,
    svc_fee: np.ndarray,
    prin_recov: np.ndarray,
    prin_loss: np.ndarray,
    sch_am: np.ndarray,
    adb: np.ndarray,
    age_weighted: np.ndarray,
) -> "BMAActualCashflow":
    """Vectorized stock rollforward and ratio derivation for BMAActualCashflow operations."""
    period = np.arange(n)

    # --- Reconstruct stocks via vectorized cumsum ---
    perf_bal = np.empty(n)
    perf_bal[0] = perf_bal_0
    if n > 1:
        perf_bal[1:] = perf_bal_0 - np.cumsum(new_def[1:] + vol_prepay[1:] + act_am[1:])
    np.maximum(perf_bal, 0.0, out=perf_bal)

    fcl = np.empty(n)
    fcl[0] = fcl_0
    if n > 1:
        fcl[1:] = fcl_0 + np.cumsum(new_def[1:] - adb[1:] - am_def[1:])
    np.maximum(fcl, 0.0, out=fcl)

    # --- Derive ratios ---
    with np.errstate(divide="ignore", invalid="ignore"):
        # MDR = new_def / prior perf_bal
        mdr = np.zeros(n)
        if n > 1:
            mdr[1:] = np.where(perf_bal[:-1] > 1e-12, new_def[1:] / perf_bal[:-1], 0.0)

        # SMM = vol_prepay / (prior perf_bal * scheduled survival factor)
        smm = np.zeros(n)
        if n > 1:
            sched_surv = np.where(sch_am[:-1] > 1e-12, sch_am[1:] / sch_am[:-1], 0.0)
            denom = perf_bal[:-1] * sched_surv
            smm[1:] = np.where(denom > 1e-12, vol_prepay[1:] / denom, 0.0)

        # Gross rate = exp_int / (prior perf_bal + prior fcl) since exp_int uses gross coupon
        # Net rate = (exp_int - svc_fee) / (prior perf_bal + prior fcl)
        gross_rate = np.zeros(n)
        net_rate = np.zeros(n)
        if n > 1:
            bal_prev = perf_bal[:-1] + fcl[:-1]
            gross_rate[1:] = np.where(bal_prev > 1e-12, exp_int[1:] / bal_prev, 0.0)
            net_rate[1:] = np.where(bal_prev > 1e-12, (exp_int[1:] - svc_fee[1:]) / bal_prev, 0.0)

        # Age = perf_bal-weighted average (age_weighted / perf_bal)
        age = np.where(perf_bal > 1e-12, age_weighted / perf_bal, 0.0)

    # --- Verify interest identity ---
    if n > 1:
        if not np.allclose(act_int[1:], exp_int[1:] - lost_int[1:], rtol=0, atol=1e-5):
            warnings.warn("act_int != exp_int - lost_int after combining (tolerance 1e-5)")

    return BMAActualCashflow(
        period=period,
        perf_bal=perf_bal,
        new_def=new_def,
        fcl=fcl,
        sch_am=sch_am,
        exp_am=exp_am,
        vol_prepay=vol_prepay,
        am_def=am_def,
        act_am=act_am,
        exp_int=exp_int,
        lost_int=lost_int,
        act_int=act_int,
        svc_fee=svc_fee,
        prin_recov=prin_recov,
        prin_loss=prin_loss,
        adb=adb,
        mdr=mdr,
        smm=smm,
        gross_rate=gross_rate,
        net_rate=net_rate,
        age=age,
    )


def compare_arrays(bma_array: np.ndarray, test_array: np.ndarray,
                   rtol: float = 1e-9, atol: float = 1e-10) -> tuple[bool, float, int]:
    """
    Compare two numeric arrays for near-equality (used in BMA compliance tests).

    Returns (all_close, max_rel_diff, worst_period). all_close is True if arrays
    match within rtol (relative) and atol (absolute) for every element.
    """
    min_len = min(len(bma_array), len(test_array))
    bma = bma_array[:min_len]
    test = test_array[:min_len]
    with np.errstate(divide='ignore', invalid='ignore'):
        rel_diff = np.abs(bma - test) / np.maximum(np.abs(bma), atol)
        rel_diff = np.where(np.isfinite(rel_diff), rel_diff, 0.0)
    max_rel_diff = np.max(rel_diff)
    worst_period = np.argmax(rel_diff)
    all_close = np.allclose(bma, test, rtol=rtol, atol=atol)
    return all_close, max_rel_diff, worst_period


# =============================================================================
# Scheduled Cashflows: Amortization with No Prepayments or Defaults
# =============================================================================

@dataclass(frozen=True, slots=True)
class BMAScheduledCashflow:
    """
    A python dataclass object designed to encapsulate the monthly scheduled cashflow for 
    a single loan (no prepayments, no defaults).

    Each field in the dataclass is a 1D array of length (remaining_term + 1). Index i corresponds
    to period i. Period 0 is the initial state; periods 1, 2, 3... are payment months.

    Dollar amounts (balances, payments):
      - beginning_balance: Loan balance at start of the period (before payment).
      - ending_balance: Loan balance at end of the period (after principal payment).
      - scheduled_payment: Total P&I payment (principal + interest) for the period.
      - interest_billed: Interest due for the period (beginning_balance * monthly_rate).
      - interest_paid: Interest portion of the payment (may be capped by payment).
      - principal_paid: Principal portion of the payment (= scheduled - interest_paid).

    Key identity (must hold for each period): ending_balance = beginning_balance - principal_paid.

    Ratios and factors (used when pooling loans):
      - pool_factor: Remaining principal as fraction of original face. E.g. 0.95 means 95% of
        original balance remains. Used to aggregate loans into a pool.
      - gross_rate: Interest rate (interest_billed / beginning_balance). Annualized.
      - age: Loan age in months at each period. When combining cashflows, we use the
        ending_balance-weighted average age per period.
      - payment_factor: BMA C.3 amortization factor [1 − SCH AM(i)/SCH AM(i−1)] = 1 − BAL[i]/BAL[i−1].
        Used in ACT AM, EXP AM, AM DEF (SF-18). Uses BAL path (amortized_balance_fraction), not pool factor.
      - amortized_balance_fraction: BAL = scheduled balance as fraction of par (no prepays). Used for payment_factor.
      - bal_path_is_estimated: True if BAL path was estimated (e.g. floating rate with partial index).
      - bal_path_note: Optional note when bal_path_is_estimated (e.g. historical rates extended backward).

    A no-arg constructor BMAScheduledCashflow() creates an empty (single period, all zeros)
    cashflow, so you can do empty.add_cashflows(cf1, cf2, ...) to pool cashflows.
    """
    period: np.ndarray = field(default_factory=lambda: np.arange(1))
    beginning_balance: np.ndarray = field(default_factory=lambda: np.zeros(1))
    scheduled_payment: np.ndarray = field(default_factory=lambda: np.zeros(1))
    payment_factor: np.ndarray = field(default_factory=lambda: np.zeros(1))  # BMA C.3: 1 - SCH AM(i)/SCH AM(i-1)
    gross_rate: np.ndarray = field(default_factory=lambda: np.zeros(1))  # interest_billed / beginning_balance
    accrued_interest: float = 0.0  # as-of accrued, unpaid (e.g. for settlement); may become vector later
    interest_billed: np.ndarray = field(default_factory=lambda: np.zeros(1))
    interest_paid: np.ndarray = field(default_factory=lambda: np.zeros(1))
    principal_paid: np.ndarray = field(default_factory=lambda: np.zeros(1))
    ending_balance: np.ndarray = field(default_factory=lambda: np.zeros(1))
    age: np.ndarray = field(default_factory=lambda: np.zeros(1))  # loan age (months); when pooling, combined = weighted by ending_balance
    pool_factor: np.ndarray = field(default_factory=lambda: np.zeros(1))
    amortized_balance_fraction: np.ndarray = field(default_factory=lambda: np.zeros(1))  # BAL = scheduled path
    survival_factor: np.ndarray = field(default_factory=lambda: np.zeros(1))  # F/BAL; 1.0 when F=BAL, <1 when prepaid
    bal_path_is_estimated: bool = False
    bal_path_note: str = ""

    def __post_init__(self) -> None:
        """Make all ndarray fields read-only so the instance is immutable after creation."""
        for f in fields(self):
            arr = getattr(self, f.name)
            if isinstance(arr, np.ndarray):
                arr.flags.writeable = False  # prevents in-place mutation (e.g. arr[i] = x)

    def __add__(self, other: BMAScheduledCashflow) -> BMAScheduledCashflow:
        """Combine two cashflows: self + other (e.g. cf1 + cf2). See add_cashflows()."""
        return self.add_cashflows(other)

    def __sub__(self, other: BMAScheduledCashflow) -> BMAScheduledCashflow:
        """Subtract one cashflow from another: self - other. See subtract_cashflows()."""
        return self.subtract_cashflows(other)

    def __mul__(self, scalar: float) -> BMAScheduledCashflow:
        """Scale all dollar amounts by scalar (e.g. cf * 2.0 doubles balances)."""
        return self.scale_by(scalar)

    def __rmul__(self, scalar: float) -> BMAScheduledCashflow:
        """Scale all dollar amounts by scalar (e.g. 2.0 * cf)."""
        return self.scale_by(scalar)

    def __truediv__(self, scalar: float) -> BMAScheduledCashflow:
        """Scale all dollar amounts by 1/scalar (e.g. cf / 2.0 halves balances)."""
        if scalar == 0:
            raise ValueError("division by zero")
        return self.scale_by(1.0 / scalar)

    def add_cashflows(self, *cfs: BMAScheduledCashflow) -> BMAScheduledCashflow:
        """
        Combine this cashflow with others into one pooled cashflow.

        Use this when you have several loans and want to see the combined monthly
        balances and payments as if they were a single pool. Example: loan A (self)
        has $100k balance (100 months left), loan B has $50k (50 months left); the
        combined cashflow shows $150k total for periods 0..50, then $100k for 51..100.

        Alignment:
          - Cashflows may have different lengths (different remaining terms).
          - All align on period 0 (the as-of / initial state).
          - Shorter cashflows contribute zeros for periods beyond their maturity
            (the loan has paid off).
          - Combined period vector is 0, 1, 2, ..., max(periods across all cfs).

        Pool factor, gross rate, and age are recomputed from the combined totals.
        Raises ValueError if the combined balances fail
        ending_balance = beginning_balance - principal_paid (within floating-point tolerance).
        """
        all_cfs = (self,) + cfs
        if len(all_cfs) == 1:
            return self

        n = max(len(cf.period) for cf in all_cfs)
        period = np.arange(n)

        # --- Step 1: Align and sum dollar amounts ---
        # pad: append zeros for periods beyond each cf's maturity (loan paid off).
        # stack(axis=1): put each loan's array as a column; result shape (rows: n_periods, columns: n_loans).
        # sum(axis=1): add across loans (columns); result shape (rows: n_periods,).
        beginning_balance = np.sum(np.stack([np.pad(cf.beginning_balance, (0, n - len(cf.beginning_balance)), constant_values=0) for cf in all_cfs], axis=1), axis=1)
        scheduled_payment = np.sum(np.stack([np.pad(cf.scheduled_payment, (0, n - len(cf.scheduled_payment)), constant_values=0) for cf in all_cfs], axis=1), axis=1)
        interest_billed = np.sum(np.stack([np.pad(cf.interest_billed, (0, n - len(cf.interest_billed)), constant_values=0) for cf in all_cfs], axis=1), axis=1)
        interest_paid = np.sum(np.stack([np.pad(cf.interest_paid, (0, n - len(cf.interest_paid)), constant_values=0) for cf in all_cfs], axis=1), axis=1)
        principal_paid = np.sum(np.stack([np.pad(cf.principal_paid, (0, n - len(cf.principal_paid)), constant_values=0) for cf in all_cfs], axis=1), axis=1)
        ending_balance = np.sum(np.stack([np.pad(cf.ending_balance, (0, n - len(cf.ending_balance)), constant_values=0) for cf in all_cfs], axis=1), axis=1)

        # --- Step 2: Verify balance identity ---
        # For each period: ending_balance must equal beginning_balance - principal_paid.
        # Skip period 0 (it's the initial state; beginning_balance is 0 there).
        # atol=1e-5 ($0.00001 = 0.001 cents): allows for floating-point rounding when summing many loans.
        balance_check = beginning_balance[1:] - principal_paid[1:]
        if not np.allclose(balance_check, ending_balance[1:], rtol=0, atol=1e-5):
            raise ValueError("Combined cashflow fails balance check: beginning_balance - principal_paid != ending_balance")

        # --- Step 3: Compute pool factor for the combined pool ---
        # Each loan's original face = ending_balance[0] / pool_factor[0]. All cfs have period 0.
        combined_original_face = 0.0
        for cf in all_cfs:
            if len(cf.period) > 0 and cf.pool_factor[0] > 0:
                combined_original_face += cf.ending_balance[0] / cf.pool_factor[0]
        if combined_original_face <= 0:
            raise ValueError("Combined original face is non-positive; cannot compute pool factor")

        pool_factor = ending_balance / combined_original_face
        amortized_balance_fraction = pool_factor.copy()  # combined pool: F=BAL when all no-prepay
        with np.errstate(divide="ignore", invalid="ignore"):
            survival_factor = np.where(amortized_balance_fraction > 0, pool_factor / amortized_balance_fraction, 0.0)

        # --- Step 4: Payment factor = BMA C.3 amortization factor [1 - SCH AM(i)/SCH AM(i-1)] ---
        payment_factor = np.zeros(n)
        payment_factor[1:] = 1.0 - np.where(pool_factor[:-1] > 0, pool_factor[1:] / pool_factor[:-1], 0.0)

        # --- Step 5: Gross rate and weighted-average age ---
        with np.errstate(divide="ignore", invalid="ignore"):
            gross_rate = np.where(beginning_balance > 0, interest_billed / beginning_balance, 0.0)
            age_weighted_sum = np.sum(np.stack([np.pad(cf.age * cf.ending_balance, (0, n - len(cf.period)), constant_values=0) for cf in all_cfs], axis=1), axis=1)
            age = np.where(ending_balance > 0, age_weighted_sum / ending_balance, 0.0)

        accrued_interest = sum(cf.accrued_interest for cf in all_cfs)
        bal_path_is_estimated = any(getattr(cf, "bal_path_is_estimated", False) for cf in all_cfs)
        bal_path_note = "; ".join(
            n for cf in all_cfs for n in [getattr(cf, "bal_path_note", "")] if n
        )
        return type(self)(
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
            bal_path_is_estimated=bal_path_is_estimated,
            bal_path_note=bal_path_note,
        )

    def subtract_cashflows(self, other: BMAScheduledCashflow) -> BMAScheduledCashflow:
        """
        Subtract another cashflow from this one (e.g. pool minus a tranche).

        Returns self - other for all balance and payment fields. Cashflows may
        have different lengths; they align on period 0, with zeros for periods
        beyond each cashflow's maturity. Pool factor, gross rate, age recomputed.
        """
        n = max(len(self.period), len(other.period))
        period = np.arange(n)
        # --- Step 1: Align and subtract dollar amounts ---
        beginning_balance = np.pad(self.beginning_balance, (0, n - len(self.period)), constant_values=0) - np.pad(other.beginning_balance, (0, n - len(other.period)), constant_values=0)
        scheduled_payment = np.pad(self.scheduled_payment, (0, n - len(self.period)), constant_values=0) - np.pad(other.scheduled_payment, (0, n - len(other.period)), constant_values=0)
        interest_billed = np.pad(self.interest_billed, (0, n - len(self.period)), constant_values=0) - np.pad(other.interest_billed, (0, n - len(other.period)), constant_values=0)
        interest_paid = np.pad(self.interest_paid, (0, n - len(self.period)), constant_values=0) - np.pad(other.interest_paid, (0, n - len(other.period)), constant_values=0)
        principal_paid = np.pad(self.principal_paid, (0, n - len(self.period)), constant_values=0) - np.pad(other.principal_paid, (0, n - len(other.period)), constant_values=0)
        ending_balance = np.pad(self.ending_balance, (0, n - len(self.period)), constant_values=0) - np.pad(other.ending_balance, (0, n - len(other.period)), constant_values=0)

        # --- Step 2: Verify balance identity ---
        # ending_balance must equal beginning_balance - principal_paid for each period. atol=1e-5 ($0.00001 = 0.001 cents).
        if not np.allclose(beginning_balance[1:] - principal_paid[1:], ending_balance[1:], rtol=0, atol=1e-5):
            raise ValueError("Result fails balance check: beginning_balance - principal_paid != ending_balance")

        # --- Step 3: Compute pool factor for the result ---
        # Pool factor = remaining balance / original face. For subtract, original face = ending_balance[0].
        original_face = ending_balance[0] if ending_balance[0] > 0 else 1.0  # guard against divide by zero
        pool_factor = np.where(original_face > 0, ending_balance / original_face, 0.0)
        amortized_balance_fraction = pool_factor.copy()
        with np.errstate(divide="ignore", invalid="ignore"):
            survival_factor = np.where(amortized_balance_fraction > 0, pool_factor / amortized_balance_fraction, 0.0)

        # --- Step 4: Payment factor = BMA C.3 amortization factor [1 - SCH AM(i)/SCH AM(i-1)] ---
        payment_factor = np.zeros(n)
        payment_factor[1:] = 1.0 - np.where(pool_factor[:-1] > 0, pool_factor[1:] / pool_factor[:-1], 0.0)

        # --- Step 5: Gross rate and age ---
        with np.errstate(divide="ignore", invalid="ignore"):
            gross_rate = np.where(beginning_balance > 0, interest_billed / beginning_balance, 0.0)
            age_numer = np.pad(self.age * self.ending_balance, (0, n - len(self.period)), constant_values=0) - np.pad(other.age * other.ending_balance, (0, n - len(other.period)), constant_values=0)
            age = np.where(ending_balance > 0, age_numer / ending_balance, 0.0)

        accrued_interest = self.accrued_interest - other.accrued_interest
        bal_path_is_estimated = getattr(self, "bal_path_is_estimated", False) or getattr(other, "bal_path_is_estimated", False)
        bal_path_note = "; ".join(n for n in [getattr(self, "bal_path_note", ""), getattr(other, "bal_path_note", "")] if n)
        return type(self)(
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
            bal_path_is_estimated=bal_path_is_estimated,
            bal_path_note=bal_path_note,
        )

    def scale_by(self, scalar: float) -> BMAScheduledCashflow:
        """
        Scale all dollar amounts (balances, payments) by a constant.

        Example: cf.scale_by(2.0) doubles every balance and payment. Pool factor,
        gross rate, and age are unchanged (they are ratios, not dollar amounts).
        """
        # Dollar amounts: multiply by scalar. Ratios/factors: copy unchanged (no scaling).
        return type(self)(
            period=self.period.copy(),
            beginning_balance=self.beginning_balance * scalar,
            scheduled_payment=self.scheduled_payment * scalar,
            payment_factor=self.payment_factor.copy(),
            gross_rate=self.gross_rate.copy(),
            accrued_interest=self.accrued_interest * scalar,
            interest_billed=self.interest_billed * scalar,
            interest_paid=self.interest_paid * scalar,
            principal_paid=self.principal_paid * scalar,
            ending_balance=self.ending_balance * scalar,
            age=self.age.copy(),
            pool_factor=self.pool_factor.copy(),
            amortized_balance_fraction=self.amortized_balance_fraction.copy(),
            survival_factor=self.survival_factor.copy(),
            bal_path_is_estimated=self.bal_path_is_estimated,
            bal_path_note=self.bal_path_note,
        )

    def to_dataframe(self):
        """
        Return a pandas DataFrame with each field as a column.

        Useful for inspection in a REPL or export to CSV. Requires pandas.
        """
        if pd is None:
            raise ImportError("pandas is required for to_dataframe(); pip install pandas")
        # One column per field; arrays share the same index (period)
        return pd.DataFrame({
            "period": self.period,
            "beginning_balance": self.beginning_balance,
            "scheduled_payment": self.scheduled_payment,
            "payment_factor": self.payment_factor,
            "gross_rate": self.gross_rate,
            "accrued_interest": np.full(len(self.period), self.accrued_interest),
            "interest_billed": self.interest_billed,
            "interest_paid": self.interest_paid,
            "principal_paid": self.principal_paid,
            "ending_balance": self.ending_balance,
            "age": self.age,
            "pool_factor": self.pool_factor,
            "amortized_balance_fraction": self.amortized_balance_fraction,
            "survival_factor": self.survival_factor,
        })

    def __repr__(self) -> str:
        """Display as pandas DataFrame when pandas installed; otherwise compact text table."""
        try:
            return repr(self.to_dataframe())
        except ImportError:
            return self._repr_fallback()

    def _repr_fallback(self) -> str:
        """Compact text table when pandas is not installed (fallback for repr)."""
        n = len(self.period)
        head = min(5, n)                       # show first 5 rows
        tail = min(2, max(0, n - head - 1))   # show last 2 rows; avoid overlap with head
        lines = [
            f"BMAScheduledCashflow({n} periods)",
            "period  beginning_balance  ending_balance  gross_rate  accrued_interest  interest_billed  principal_paid  interest_paid",
        ]

        def row(i: int) -> str:
            period = self.period[i]
            beginning_balance = self.beginning_balance[i]
            ending_balance = self.ending_balance[i]
            gross_rate = self.gross_rate[i]
            accrued_interest = self.accrued_interest
            interest_billed = self.interest_billed[i]
            principal_paid = self.principal_paid[i]
            interest_paid = self.interest_paid[i]
            return f"{period:6}  {beginning_balance:17.2f}  {ending_balance:14.2f}  {gross_rate:9.4f}  {accrued_interest:16.2f}  {interest_billed:14.2f}  {principal_paid:14.2f}  {interest_paid:13.2f}"

        for i in range(head):
            lines.append(row(i))
        if tail and head + tail < n:
            lines.append("  ...")
        for i in range(n - tail, n) if tail else []:
            lines.append(row(i))
        return "\n".join(lines)


# =============================================================================
# Scheduled Cashflow Runner
# =============================================================================

def run_bma_scheduled_cashflow(
    original_balance: float,
    current_balance: float,
    rate_margin: float,
    original_term: int,
    remaining_term: int,
    index: float | np.ndarray = 0.0,
    accrued_interest: float = 0.0,
    servicing_fee: float = 0.0
) -> BMAScheduledCashflow:
    """
    Generate the scheduled amortization for a single loan (no prepays, no defaults).

    This is the "what if" scenario: what would the monthly payments and balances
    be if the borrower pays exactly on schedule until maturity? Used as the base
    for actual cashflows (which apply prepayment and default assumptions).

    Fixed vs floating:
    - Fixed rate (index=0 or len 1): Level payment computed from original_balance,
      original_term, and (index + rate_margin). Applied every period.
    - Floating rate (index vector): Payment recomputed each period from
      beginning_balance, remaining_term, and (index + rate_margin) for that period.

    Args:
        original_balance: Original loan amount (face value at origination), in dollars.
        current_balance: Current outstanding balance (for aged loans that have made payments).
        rate_margin: Annual rate margin as decimal (e.g. 0.08 for 8%). Added to index.
        original_term: Original loan term in months (e.g. 360 for 30-year).
        remaining_term: Months left to maturity (e.g. 300 if 60 months have passed).
        index: Index rates (decimal), default 0 = fixed. Scalar or 1D array (oldest first).
              Extended backward with oldest, forward with newest if too short.
        accrued_interest: Accrued but unpaid interest (optional).
        servicing_fee: Annual servicing fee as decimal (e.g. 0.0025 for 25 bps).

    Returns:
        BMAScheduledCashflow with arrays for each period (period 0 = initial, 1..N = payment months).

    Raises:
        ValueError: If any input fails validation (e.g. original_balance <= 0).
    """
    if original_balance <= 0:
        raise ValueError("original_balance must be positive")
    if original_term <= 0:
        raise ValueError("original_term must be positive")
    if remaining_term < 0:
        raise ValueError("remaining_term must be >= 0")
    if accrued_interest < 0:
        raise ValueError("accrued_interest must be >= 0")
    if servicing_fee < 0:
        raise ValueError("servicing_fee must be >= 0")

    periods = remaining_term + 1  # period 0 = initial state, 1..remaining_term = payment months
    loan_age = original_term - remaining_term

    # --- Rate setup: scalar for fixed, vector for floating ---
    index_arr = np.asarray(index, dtype=float)
    is_fixed = np.all(index_arr == 0)
    if is_fixed:
        monthly_rate = rate_margin / 12.0
        fixed_level_payment = _annuity_payment(original_balance, monthly_rate, original_term)
    else:
        monthly_rate, _ = _build_rate_vector(index, rate_margin, original_term, remaining_term)

    # --- Amortization loop: compute the F path (actual balance trajectory) ---
    # Starts from current_balance which may be < scheduled balance if prepaid.
    # Fixed: level payment from original terms. Floating: recompute each period.
    period = np.arange(periods)
    beginning_balance = np.zeros(periods)
    scheduled_payment = np.zeros(periods)
    gross_rate = np.zeros(periods)
    interest_billed = np.zeros(periods)
    interest_paid = np.zeros(periods)
    principal_paid = np.zeros(periods)
    ending_balance = np.zeros(periods)
    age = np.zeros(periods, dtype=float)
    age[:] = loan_age + period
    ending_balance[0] = current_balance

    for i in range(1, periods):
        beginning_balance[i] = ending_balance[i - 1]
        if is_fixed:
            interest_billed[i] = beginning_balance[i] * monthly_rate
            scheduled_payment[i] = fixed_level_payment
        else:
            interest_billed[i] = beginning_balance[i] * monthly_rate[i]
            scheduled_payment[i] = _annuity_payment(beginning_balance[i], monthly_rate[i], remaining_term - i + 1)
        scheduled_payment[i] = min(scheduled_payment[i], beginning_balance[i] + interest_billed[i])
        interest_paid[i] = min(interest_billed[i], scheduled_payment[i])
        principal_paid[i] = scheduled_payment[i] - interest_paid[i]
        ending_balance[i] = beginning_balance[i] - principal_paid[i]
        gross_rate[i] = interest_billed[i] / beginning_balance[i] if beginning_balance[i] > 0 else 0.0

    # --- BMA factor tracking ---
    # pool_factor (F) = actual balance / original face — from the amortization loop above.
    # payment_factor = principal / beginning_balance — BMA C.3 amortization factor per period.
    pool_factor = ending_balance / original_balance
    payment_factor = np.zeros(periods)
    with np.errstate(divide="ignore", invalid="ignore"):
        payment_factor[1:] = np.where(
            beginning_balance[1:] > 0, principal_paid[1:] / beginning_balance[1:], 0.0,
        )

    # amortized_balance_fraction (BAL) = scheduled balance as fraction of par (no-prepay path).
    # Computed via sch_balance_factors from origination, then sliced to our window.
    # For floating with partial index, historical rates are extended backward (estimated).
    coupon_vec = np.atleast_1d(index_arr + rate_margin) * 100.0
    bal_path_is_estimated = not is_fixed and max(0, loan_age - len(coupon_vec)) > 0
    if bal_path_is_estimated:
        bal_path_note = (
            f"BAL path estimated: floating rate with partial index "
            f"({len(coupon_vec)} rates, {max(0, loan_age - len(coupon_vec))} historical periods extended backward)"
        )
    elif is_fixed:
        bal_path_note = f"BAL path exact: fixed rate {rate_margin * 100:.4f}%"
    else:
        bal_path_note = f"BAL path exact: floating rate with full index ({len(coupon_vec)} rates)"
    amortized_balance_fraction = (
        sch_balance_factors(coupon_vec, original_term, remaining_term)[3]
        [loan_age : loan_age + periods]
    )

    # survival_factor = F / BAL. Equals 1.0 when current_balance = scheduled balance (no prepay).
    # When current_balance < scheduled (prepaid start), survival < 1 and stays constant.
    # At maturity both F and BAL → 0; use 1.0 as the limit (tolerance handles float residuals).
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(amortized_balance_fraction > 1e-12, pool_factor / amortized_balance_fraction, np.nan)
        survival_factor = np.where(np.isfinite(ratio), ratio, 1.0)

    # Construct immutable cashflow; __post_init__ will set arrays read-only
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
        bal_path_is_estimated=bal_path_is_estimated,
        bal_path_note=bal_path_note,
    )


# =============================================================================
# Actual Cashflows: Prepayments and Defaults Applied
# =============================================================================

@dataclass(frozen=True, slots=True)
class BMAActualCashflow:
    """
    Monthly actual cashflow with prepayments and defaults applied.

    Unlike BMAScheduledCashflow, this models real-world behavior: borrowers may
    prepay (pay off early) or default (stop paying). Each field is a 1D array
    of length (periods + 1), indexed by period.

    Field order follows BMA SF-18 table so DataFrames read left-to-right:

      - perf_bal: PERF BAL — Performing Balance (stock)
      - new_def: NEW DEF — New Defaults (flow)
      - fcl: FCL — Foreclosure pipeline (stock)
      - sch_am: SCH AM — Scheduled balance path (stock)
      - exp_am: EXP AM — Expected Amortization (flow)
      - vol_prepay: VOL PREPAY — Voluntary Prepayments (flow)
      - am_def: AM DEF — Amortization from Defaults (flow)
      - act_am: ACT AM — Actual Amortization (flow)
      - exp_int: EXP INT — Expected Interest, gross (flow)
      - lost_int: LOST INT — Interest lost to defaults (flow)
      - act_int: ACT INT — Actual Interest, gross (flow)
      - svc_fee: Servicing fee in dollars (flow)
      - prin_recov: PRIN RECOV — Principal Recovery (flow)
      - prin_loss: PRIN LOSS — Principal Loss (flow)
      - adb: ADB — Amortized Default Balance (stock)
      - mdr: MDR — Monthly Default Rate (ratio)
      - smm: SMM — Monthly Prepayment Rate (ratio)
      - gross_rate: Gross coupon rate, monthly (ratio)
      - net_rate: Net pass-through rate, monthly (ratio)
      - age: Loan age in months (ratio)
    """
    period: np.ndarray
    perf_bal: np.ndarray
    new_def: np.ndarray
    fcl: np.ndarray
    sch_am: np.ndarray
    exp_am: np.ndarray
    vol_prepay: np.ndarray
    am_def: np.ndarray
    act_am: np.ndarray
    exp_int: np.ndarray
    lost_int: np.ndarray
    act_int: np.ndarray
    svc_fee: np.ndarray
    prin_recov: np.ndarray
    prin_loss: np.ndarray
    adb: np.ndarray
    mdr: np.ndarray
    smm: np.ndarray
    gross_rate: np.ndarray
    net_rate: np.ndarray
    age: np.ndarray

    def __post_init__(self) -> None:
        for f in fields(self):
            arr = getattr(self, f.name)
            if isinstance(arr, np.ndarray):
                arr.flags.writeable = False

    def __add__(self, other: BMAActualCashflow) -> BMAActualCashflow:
        return self.add_cashflows(other)

    def __sub__(self, other: BMAActualCashflow) -> BMAActualCashflow:
        return self.subtract_cashflows(other)

    def __mul__(self, scalar: float) -> BMAActualCashflow:
        return self.scale_by(scalar)

    def __rmul__(self, scalar: float) -> BMAActualCashflow:
        return self.scale_by(scalar)

    def __truediv__(self, scalar: float) -> BMAActualCashflow:
        if scalar == 0:
            raise ValueError("division by zero")
        return self.scale_by(1.0 / scalar)

    def add_cashflows(self, *cfs: BMAActualCashflow) -> BMAActualCashflow:
        """Combine actual cashflows: sum flows, reconstruct stocks, derive ratios."""
        all_cfs = (self,) + cfs
        if len(all_cfs) == 1:
            return self
        n = max(len(cf.period) for cf in all_cfs)

        def _pad_sum(attr: str) -> np.ndarray:
            return np.sum(np.stack([
                np.pad(getattr(cf, attr), (0, n - len(cf.period)), constant_values=0)
                for cf in all_cfs
            ], axis=1), axis=1)

        # Sum flows
        new_def = _pad_sum("new_def")
        vol_prepay = _pad_sum("vol_prepay")
        act_am = _pad_sum("act_am")
        am_def = _pad_sum("am_def")
        exp_am = _pad_sum("exp_am")
        exp_int = _pad_sum("exp_int")
        lost_int = _pad_sum("lost_int")
        act_int = _pad_sum("act_int")
        svc_fee = _pad_sum("svc_fee")
        prin_recov = _pad_sum("prin_recov")
        prin_loss = _pad_sum("prin_loss")
        # Sum stocks (period 0 initial + full arrays for sch_am, adb)
        sch_am = _pad_sum("sch_am")
        adb = _pad_sum("adb")
        perf_bal_0 = sum(cf.perf_bal[0] for cf in all_cfs)
        fcl_0 = sum(cf.fcl[0] for cf in all_cfs)
        # Weighted-average age
        age_weighted = np.sum(np.stack([
            np.pad(cf.age * cf.perf_bal, (0, n - len(cf.period)), constant_values=0)
            for cf in all_cfs
        ], axis=1), axis=1)

        return _reconstruct_stocks_and_ratios(
            n, perf_bal_0, fcl_0, new_def, vol_prepay, act_am, am_def, exp_am,
            exp_int, lost_int, act_int, svc_fee, prin_recov, prin_loss,
            sch_am, adb, age_weighted,
        )

    def subtract_cashflows(self, other: BMAActualCashflow) -> BMAActualCashflow:
        """Subtract actual cashflows: subtract flows, reconstruct stocks, derive ratios."""
        n = max(len(self.period), len(other.period))

        def _pad_sub(attr: str) -> np.ndarray:
            return (np.pad(getattr(self, attr), (0, n - len(self.period)), constant_values=0)
                    - np.pad(getattr(other, attr), (0, n - len(other.period)), constant_values=0))

        new_def = _pad_sub("new_def")
        vol_prepay = _pad_sub("vol_prepay")
        act_am = _pad_sub("act_am")
        am_def = _pad_sub("am_def")
        exp_am = _pad_sub("exp_am")
        exp_int = _pad_sub("exp_int")
        lost_int = _pad_sub("lost_int")
        act_int = _pad_sub("act_int")
        svc_fee = _pad_sub("svc_fee")
        prin_recov = _pad_sub("prin_recov")
        prin_loss = _pad_sub("prin_loss")
        sch_am = _pad_sub("sch_am")
        adb = _pad_sub("adb")
        perf_bal_0 = self.perf_bal[0] - other.perf_bal[0]
        fcl_0 = self.fcl[0] - other.fcl[0]
        age_weighted = (
            np.pad(self.age * self.perf_bal, (0, n - len(self.period)), constant_values=0)
            - np.pad(other.age * other.perf_bal, (0, n - len(other.period)), constant_values=0)
        )

        return _reconstruct_stocks_and_ratios(
            n, perf_bal_0, fcl_0, new_def, vol_prepay, act_am, am_def, exp_am,
            exp_int, lost_int, act_int, svc_fee, prin_recov, prin_loss,
            sch_am, adb, age_weighted,
        )

    def scale_by(self, scalar: float) -> BMAActualCashflow:
        """Scale actual cashflows: multiply flows and initial stocks, reconstruct, derive ratios."""
        n = len(self.period)
        return _reconstruct_stocks_and_ratios(
            n,
            self.perf_bal[0] * scalar,
            self.fcl[0] * scalar,
            self.new_def * scalar,
            self.vol_prepay * scalar,
            self.act_am * scalar,
            self.am_def * scalar,
            self.exp_am * scalar,
            self.exp_int * scalar,
            self.lost_int * scalar,
            self.act_int * scalar,
            self.svc_fee * scalar,
            self.prin_recov * scalar,
            self.prin_loss * scalar,
            self.sch_am * scalar,
            self.adb * scalar,
            self.age * self.perf_bal * scalar,
        )

    def to_dataframe(self):
        if pd is None:
            raise ImportError("pandas is required for to_dataframe(); pip install pandas")
        return pd.DataFrame({f.name: getattr(self, f.name) for f in fields(self)})

    def __repr__(self) -> str:
        try:
            return repr(self.to_dataframe())
        except ImportError:
            return self._repr_fallback()

    def _repr_fallback(self) -> str:
        n = len(self.period)
        head = min(5, n)
        tail = min(2, max(0, n - head - 1))
        lines = [
            f"BMAActualCashflow({n} periods)",
            "period   perf_bal     act_am  vol_prepay    new_def     act_int   prin_loss",
        ]
        def row(i: int) -> str:
            return (f"{self.period[i]:6}  {self.perf_bal[i]:9.2f}  {self.act_am[i]:9.2f}"
                    f"  {self.vol_prepay[i]:10.2f}  {self.new_def[i]:9.2f}"
                    f"  {self.act_int[i]:10.2f}  {self.prin_loss[i]:9.2f}")
        for i in range(head):
            lines.append(row(i))
        if tail and head + tail < n:
            lines.append("  ...")
        for i in range(n - tail, n) if tail else []:
            lines.append(row(i))
        return "\n".join(lines)


# =============================================================================
# Actual Cashflow Runner
# =============================================================================

def run_bma_actual_cashflow(
    scheduled_cf: BMAScheduledCashflow,
    smm_curve: np.ndarray,
    mdr_curve: np.ndarray,
    severity_curve: np.ndarray,
    severity_lag: int = 12,
    coupon: float = 0.08,
    servicing_fee: float = 0.0,
    pi_advanced: bool = True,
    months_to_liquidation: int = 12,
) -> BMAActualCashflow:
    """
    Apply prepayment and default assumptions to a scheduled cashflow.

    Args:
        scheduled_cf: Scheduled cashflow from run_bma_scheduled_cashflow.
        smm_curve: Monthly prepayment rate (0-1). E.g. 0.01 = 1% SMM per month.
        mdr_curve: Monthly default rate on performing balance. E.g. 0.001 = 0.1% MDR.
        severity_curve: Loss severity per dollar defaulted (0-1). E.g. 0.20 = 20% loss.
        severity_lag: Months from default to recovery (BMA default 12).
        coupon: Annual gross interest rate as decimal (e.g. 0.095 for 9.5%).
        servicing_fee: Annual servicing fee as decimal (e.g. 0.005 for 50bps).
        pi_advanced: True if P&I advanced (interest continues to accrue during foreclosure).
        months_to_liquidation: MDR forced to 0 in final N months (no new defaults near maturity).

    Returns:
        BMAActualCashflow with actual balances, prepays, defaults, and recoveries.
    """
    periods = len(scheduled_cf.period)
    gross_monthly = coupon / 12.0
    svc_monthly = servicing_fee / 12.0
    net_monthly = gross_monthly - svc_monthly

    # --- Allocate output arrays ---
    period = scheduled_cf.period.copy()
    perf_bal = np.zeros(periods)
    new_def = np.zeros(periods)
    fcl = np.zeros(periods)
    original_face = scheduled_cf.ending_balance[0] / scheduled_cf.pool_factor[0] if scheduled_cf.pool_factor[0] > 0 else 1.0
    sch_am = scheduled_cf.amortized_balance_fraction * original_face
    exp_am = np.zeros(periods)
    act_am = np.zeros(periods)
    am_def = np.zeros(periods)
    vol_prepay = np.zeros(periods)
    exp_int = np.zeros(periods)
    lost_int = np.zeros(periods)
    act_int = np.zeros(periods)
    svc_fee_arr = np.zeros(periods)
    adb = np.zeros(periods)
    prin_recov = np.zeros(periods)
    prin_loss = np.zeros(periods)
    smm = np.zeros(periods)
    mdr = np.zeros(periods)
    gross_rate = np.full(periods, gross_monthly)
    gross_rate[0] = 0.0
    net_rate = np.full(periods, net_monthly)
    net_rate[0] = 0.0
    age = scheduled_cf.age.copy() if len(scheduled_cf.age) == periods else np.zeros(periods)

    # Extend curves if shorter than periods (pad with last value)
    smm_curve = np.pad(smm_curve, (0, max(0, periods - len(smm_curve))), mode='edge')[:periods]
    mdr_curve = np.pad(mdr_curve, (0, max(0, periods - len(mdr_curve))), mode='edge')[:periods]
    severity_curve = np.pad(severity_curve, (0, max(0, periods - len(severity_curve))), mode='edge')[:periods]
    smm[:] = smm_curve
    mdr[:] = mdr_curve

    # --- Period 0: initial state ---
    perf_bal[0] = scheduled_cf.ending_balance[0]

    # --- Periods 1..N: apply prepays and defaults per BMA Section C.3 ---
    for i in range(1, periods):
        # Scheduled survival factor = sch_am[i] / sch_am[i-1] (fraction of balance surviving scheduled amort)
        if sch_am[i - 1] > 0:
            sched_surv_factor = sch_am[i] / sch_am[i - 1]
        else:
            sched_surv_factor = 0.0
        one_minus_af = 1.0 - sched_surv_factor  # Scheduled principal paydown rate

        if months_to_liquidation > 0 and i >= max(0, periods - months_to_liquidation):
            mdr[i] = 0.0  # No new defaults near maturity

        new_def[i] = perf_bal[i - 1] * mdr[i]
        vol_prepay[i] = perf_bal[i - 1] * sched_surv_factor * smm[i]
        act_am[i] = (perf_bal[i - 1] - new_def[i]) * one_minus_af

        total_unsched = new_def[i] + vol_prepay[i] + act_am[i]
        # Cap: total principal outflows cannot exceed performing balance
        if total_unsched > perf_bal[i - 1] and perf_bal[i - 1] > 0:
            excess = total_unsched - perf_bal[i - 1]
            vol_reduction = min(vol_prepay[i], excess)
            vol_prepay[i] -= vol_reduction
            excess -= vol_reduction
            if excess > 0:
                act_am[i] = max(act_am[i] - excess, 0.0)

        perf_bal[i] = perf_bal[i - 1] - new_def[i] - vol_prepay[i] - act_am[i]
        perf_bal[i] = max(perf_bal[i], 0.0)

        # Amortized Default Balance (ADB): defaults age through foreclosure; recovery after severity_lag months
        if i >= severity_lag:
            def_month = i - severity_lag
            if pi_advanced:
                if def_month > 0 and sch_am[def_month - 1] > 0:
                    adb[i] = new_def[def_month] * (sch_am[i - 1] / sch_am[def_month - 1])
                elif def_month == 0:
                    adb[i] = new_def[def_month] * (sch_am[i - 1] / sch_am[0]) if sch_am[0] > 0 else new_def[def_month]
                else:
                    adb[i] = new_def[def_month]
            else:
                adb[i] = new_def[def_month]

        if pi_advanced:
            am_def[i] = (new_def[i] + fcl[i - 1] - adb[i]) * one_minus_af
        else:
            am_def[i] = 0.0

        fcl[i] = (new_def[i] + fcl[i - 1] - adb[i]) - am_def[i]
        fcl[i] = max(fcl[i], 0.0)
        exp_am[i] = (perf_bal[i - 1] + fcl[i - 1] - adb[i]) * one_minus_af

        # Principal loss = severity * defaulted amount; recovery = remainder
        if i >= severity_lag:
            def_month = i - severity_lag
            prin_loss[i] = min(new_def[def_month] * severity_curve[def_month], adb[i])
            prin_recov[i] = max(adb[i] - prin_loss[i], 0.0)

        exp_int[i] = (perf_bal[i - 1] + fcl[i - 1]) * gross_monthly
        lost_int[i] = (new_def[i] + fcl[i - 1]) * gross_monthly
        act_int[i] = exp_int[i] - lost_int[i]
        svc_fee_arr[i] = (perf_bal[i - 1] + fcl[i - 1]) * svc_monthly

    return BMAActualCashflow(
        period=period,
        perf_bal=perf_bal,
        new_def=new_def,
        fcl=fcl,
        sch_am=sch_am,
        exp_am=exp_am,
        vol_prepay=vol_prepay,
        am_def=am_def,
        act_am=act_am,
        exp_int=exp_int,
        lost_int=lost_int,
        act_int=act_int,
        svc_fee=svc_fee_arr,
        prin_recov=prin_recov,
        prin_loss=prin_loss,
        adb=adb,
        mdr=mdr,
        smm=smm,
        gross_rate=gross_rate,
        net_rate=net_rate,
        age=age,
    )


# =============================================================================
# Loan Object
# =============================================================================
#
# The Loan dataclass holds loan-level inputs for cashflow generation. It stores
# rates as percentage (e.g. 8.0 for 8%) and provides conversion methods for the
# runners, which expect decimal (e.g. 0.08).
# =============================================================================

@dataclass(slots=True)
class Loan:
    """
    Loan-level data for BMA cashflow and pricing functions.

    Represents a single mortgage loan: balances, terms, interest rate (fixed or
    floating), and servicing. Use scheduled_cashflow_from_loan() or
    actual_cashflow_from_loan() to generate cashflows.

    Key fields:
        original_balance: Face value at origination (dollars).
        current_balance: Outstanding balance as of asof_date.
        rate_margin: Coupon rate in percent (e.g. 8.0 for 8%). For fixed-rate,
          this is the full coupon; for floating, it's the spread over the index.
        rate_index: For floating-rate, array of index rates per period (%). None for fixed.
        original_term: Loan term in months (e.g. 360 for 30-year).
        remaining_term: Months left to maturity.

    Computed properties:
        age: Months since origination (original_term - remaining_term).
        coupon_percent: Current coupon rate in percent (e.g. 8.0).

    Rate convention: All rates and servicing_fee are stored as percentage. The
    cashflow functions expect decimal; use coupon_decimal_for_cashflow() and
    servicing_fee_decimal() when calling them.
    """
    # Required
    origination_date: np.datetime64 | object  # date-like
    asof_date: np.datetime64 | object
    original_balance: float  # $ (original face)
    current_balance: float   # $ at asof
    rate_margin: float      # annual % (e.g. 8.0 for 8%); for fixed this is the full coupon
    rate_index: np.ndarray | None = None  # floating: per-period index %; fixed: None
    servicing_fee: float = 0.0  # annual % (e.g. 0.25 for 25 bp)
    original_term: int = 0   # months (M₀)
    remaining_term: int = 0   # months at asof (Mₙ)

    # Optional (BMA-relevant only: Section F settlement, Section C.3 actual CF)
    accrued_interest: float = 0.0  # Section F: settlement cost = principal + accrued
    maturity_date: np.datetime64 | object | None = None
    first_payment_date: np.datetime64 | object | None = None
    pi_advanced: bool = True  # Section C.3 actual cashflow
    index_type: str | None = None
    rate_cap: float | None = None
    rate_floor: float | None = None

    def __post_init__(self) -> None:
        """Validate loan data per BMA requirements."""
        if self.original_term <= 0:
            raise ValueError(f"original_term must be positive, got {self.original_term}")
        if self.remaining_term < 0:
            raise ValueError(f"remaining_term must be non-negative, got {self.remaining_term}")
        if self.original_balance < 0:
            raise ValueError(f"original_balance must be non-negative, got {self.original_balance}")
        if self.remaining_term > self.original_term:
            raise ValueError(
                f"remaining_term ({self.remaining_term}) cannot exceed "
                f"original_term ({self.original_term})"
            )
        if self.current_balance > self.original_balance:
            raise ValueError(
                f"current_balance ({self.current_balance}) cannot exceed "
                f"original_balance ({self.original_balance})"
            )
        if self.rate_index is not None:
            try:
                arr = np.asarray(self.rate_index, dtype=float)
                if not np.isfinite(arr).all():
                    raise ValueError("rate_index contains non-finite values")
            except (TypeError, ValueError) as e:
                raise ValueError(f"rate_index must be numeric array: {e}")
        try:
            orig = np.datetime64(self.origination_date)
            asof = np.datetime64(self.asof_date)
            if asof < orig:
                raise ValueError(
                    f"asof_date ({self.asof_date}) cannot be before "
                    f"origination_date ({self.origination_date})"
                )
        except (TypeError, ValueError):
            pass  # Skip if dates not convertible
        if self.rate_cap is not None and self.rate_floor is not None:
            if self.rate_cap < self.rate_floor:
                raise ValueError(
                    f"rate_cap ({self.rate_cap}) cannot be less than "
                    f"rate_floor ({self.rate_floor})"
                )

    @property
    def age(self) -> int:
        """Months since origination (original_term - remaining_term)."""
        return self.original_term - self.remaining_term

    @property
    def coupon_percent(self) -> float:
        """
        Current coupon rate in percent (e.g. 8.0 for 8%).

        Fixed-rate: returns rate_margin. Floating-rate: returns rate_margin plus
        the index rate for the current age (index extended backward if needed per BMA).
        """
        if self.is_fixed_rate():
            return self.rate_margin
        full_idx = self._get_extended_index()
        return float(self.rate_margin + full_idx[self.age])

    def is_fixed_rate(self) -> bool:
        """True if the loan has a fixed coupon (no floating index)."""
        return self.rate_index is None or (
            hasattr(self.rate_index, "__len__") and
            (len(self.rate_index) == 0 or np.all(np.asarray(self.rate_index) == 0))
        )

    def _get_extended_index(self) -> np.ndarray:
        """
        Extend rate_index backward if shorter than original_term (BMA convention).

        If the index has fewer entries than the loan term, prepend the first
        (oldest) rate to fill missing historical periods.
        """
        if self.is_fixed_rate():
            return np.zeros(self.original_term, dtype=float)
        idx = np.asarray(self.rate_index, dtype=float)
        if len(idx) >= self.original_term:
            return idx[:self.original_term]
        shortfall = self.original_term - len(idx)
        return np.concatenate([np.full(shortfall, idx[0]), idx])

    def get_coupon_vector(self, num_periods: int | None = None) -> np.ndarray:
        """
        Coupon rates in percent for the next num_periods months.

        Fixed-rate: all elements equal to rate_margin. Floating-rate: rate_margin
        plus index rate for each month (index extended backward if needed).
        """
        n = num_periods if num_periods is not None else self.remaining_term
        if n <= 0:
            return np.array([], dtype=float)
        if self.is_fixed_rate():
            return np.full(n, self.rate_margin, dtype=float)
        full_idx = self._get_extended_index()
        start = self.age
        end = self.age + n
        return full_idx[start:end] + self.rate_margin

    def coupon_decimal_for_cashflow(self) -> np.ndarray:
        """
        Coupon as decimal (e.g. 0.08 for 8%) for the cashflow runners.

        The cashflow functions expect decimal; Loan stores percent. This method
        does the conversion. Returns one value per remaining month.
        """
        c = self.get_coupon_vector(self.remaining_term)
        return c / 100.0

    def servicing_fee_decimal(self) -> float:
        """Servicing fee as decimal (e.g. 0.0025 for 25 bps) for cashflow functions."""
        return self.servicing_fee / 100.0


# =============================================================================
# Loan Wrapper Functions
# =============================================================================
#
# Convenience functions that take a Loan and call the cashflow runners with
# the correct parameter unpacking and percentage-to-decimal conversion.
# =============================================================================

def scheduled_cashflow_from_loan(loan: Loan) -> BMAScheduledCashflow:
    """
    Generate scheduled cashflows for a Loan (no prepays, no defaults).

    Extracts loan fields and converts rates from percent to decimal, then calls
    run_bma_scheduled_cashflow. Use this when you have a Loan object instead of
    individual parameters.
    """
    rate_margin = loan.rate_margin / 100.0
    if loan.is_fixed_rate():
        index = 0.0
    else:
        full_idx = loan._get_extended_index()
        start = loan.age
        end = loan.age + loan.remaining_term
        index = full_idx[start:end] / 100.0

    return run_bma_scheduled_cashflow(
        original_balance=loan.original_balance,
        current_balance=loan.current_balance,
        rate_margin=rate_margin,
        original_term=loan.original_term,
        remaining_term=loan.remaining_term,
        index=index,
        accrued_interest=loan.accrued_interest,
        servicing_fee=loan.servicing_fee_decimal(),
    )


def actual_cashflow_from_loan(
    loan: Loan,
    scheduled_cf: BMAScheduledCashflow,
    smm_curve: np.ndarray,
    mdr_curve: np.ndarray,
    severity_curve: np.ndarray,
    severity_lag: int = 12,
    months_to_liquidation: int = 12,
) -> BMAActualCashflow:
    """
    Generate actual cashflows for a Loan (with prepays and defaults).

    Takes a Loan and a scheduled cashflow, applies SMM/MDR/severity curves, and
    returns actual cashflows. Extracts coupon and pi_advanced from the loan;
    converts rates from percent to decimal.
    """
    coupon_vec = loan.coupon_decimal_for_cashflow()
    coupon = float(coupon_vec[0]) if len(coupon_vec) > 0 else 0.0

    return run_bma_actual_cashflow(
        scheduled_cf=scheduled_cf,
        smm_curve=smm_curve,
        mdr_curve=mdr_curve,
        severity_curve=severity_curve,
        severity_lag=severity_lag,
        coupon=coupon,
        servicing_fee=loan.servicing_fee_decimal(),
        pi_advanced=loan.pi_advanced,
        months_to_liquidation=months_to_liquidation,
    )
