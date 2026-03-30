# Requires Python 3.12+
# Uses native type hints: list[x], tuple[x], X | None (PEP 585, PEP 604)
from __future__ import annotations

"""
Loan data model and cashflow convenience wrappers.

The Loan dataclass holds loan-level inputs for BMA cashflow generation.  It
stores rates as PERCENTAGE (e.g. 8.0 for 8%) following market convention, and
provides conversion methods for the cashflow runners which expect DECIMAL
(e.g. 0.08).  This module is the impedance-mismatch boundary between how
humans think about rates and how the BMA formulas consume them.

Architecture layering:
    loan.py          → Loan data model, rate conversion, wrapper functions
      ↓ imports
    cashflows.py     → BMA C.3 leaf computation (scheduled + actual runners)
      ↓ imports
    portfolio.py     → Tier 2: aggregation, waterfall, cross-collat

Ref: BMA SF-4 (servicing), SF-18 (C.3 variables), SF-19 (formulas).
     FNMA F-1-20 (stop-advance), GNMA Ch. 14-15, 18.
"""

import warnings
from datetime import date
from typing import TYPE_CHECKING

import numpy as np
from dataclasses import dataclass

if TYPE_CHECKING:
    from .rate_index import RateIndex
    from .portfolio import PortfolioCashflow

from bma_standard_formulas.formulas.cashflows import (
    BMAScheduledCashflow,
    BMAActualCashflow,
    run_bma_scheduled_cashflow,
    run_bma_actual_cashflow,
)


# =============================================================================
# Loan Dataclass
# =============================================================================


@dataclass(slots=True)
class Loan:
    """Loan-level data for BMA cashflow and pricing functions.

    Represents a single mortgage loan: balances, terms, interest rate (fixed or
    floating), and servicing.  Use scheduled_cashflow_from_loan() or
    actual_cashflow_from_loan() to generate cashflows.

    Key fields:
        original_balance: Face value at origination (dollars).
        current_balance:  Outstanding balance as of asof_date (dollars).
        rate_margin:      Coupon rate in PERCENT (e.g. 8.0 for 8%).
                          For fixed-rate this is the full coupon;
                          for floating it's the spread over the index.
        original_term:    Loan term in months (e.g. 360 for 30-year).
        remaining_term:   Months left to maturity.
        reset_frequency:  Months between rate resets (0 = fixed, 12 = annual ARM).

    Computed properties:
        age:              Months since origination (original_term - remaining_term).

    Rate convention:
        All rates and servicing_fee are stored as PERCENTAGE (market convention).
        The cashflow runners expect DECIMAL.  Use coupon_decimal_for_cashflow()
        and servicing_fee_decimal() to convert.
    """
    # ── Required fields (Part A: loan identity + economics) ─────────────
    loan_id: int                              # uniquely identifies the loan
    origination_date: np.datetime64 | date     # date-like
    asof_date: np.datetime64 | date           # valuation / reporting date
    original_balance: float                   # $ at origination (face value)
    current_balance: float                    # $ outstanding at asof_date
    rate_margin: float                        # annual % (e.g. 8.0 for 8%)

    # ── Optional rate / grouping fields ─────────────────────────────────
    group_id: int | str | None = None         # supports numeric or text pool/group IDs
    servicing_fee: float = 0.0                # annual % (e.g. 0.25 for 25 bp)
    original_term: int = 0                    # months (M₀)
    remaining_term: int = 0                   # months at asof (Mₙ)

    # ── BMA-relevant optional fields ────────────────────────────────────
    # Section F: settlement cost = principal + accrued
    accrued_interest: float = 0.0

    maturity_date: np.datetime64 | date | None = None
    first_payment_date: np.datetime64 | date | None = None  # first payment date from origination
    next_payment_date: np.datetime64 | date | None = None   # next payment due after asof_date
    last_payment_date: np.datetime64 | date | None = None   # most recent payment before asof_date

    # Section C.3 actual cashflow: servicer advance behavior
    pi_advanced: bool = True   # whether servicer advances P&I to investors
    advance_months: int = -1   # per-vintage advance window:
                               #   -1 = until liquidation (BMA default per SF-15)
                               #    0 = no advancing
                               #    4 = FNMA/GNMA agency convention
                               # Ref: FNMA F-1-20 "Stop Delinquency Advance";
                               #      GNMA MBS Guide Ch. 18 (buyout at 4 months).

    # 3-tier servicing rates (annual %, same convention as servicing_fee).
    # Standard mortgage: all three equal.  Other asset classes may differ.
    # None = inherit from servicing_fee (performing rate).
    svc_rate_default: float | None = None      # fee on newly defaulted balance
    svc_rate_foreclosure: float | None = None  # fee on foreclosure pipeline

    index_type: str | None = None        # e.g. "SOFR", "LIBOR", "T-Bill"
    reset_frequency: int = 0             # months between resets (0 = fixed, 12 = annual ARM)
    next_reset_date: np.datetime64 | date | None = None  # date of next rate reset
    periodic_cap: float | None = None    # max rate increase per reset (%)
    periodic_floor: float | None = None  # max rate decrease per reset (%)
    rate_cap: float | None = None        # life cap: absolute max coupon (%)
    rate_floor: float | None = None      # life floor: absolute min coupon (%)

    # ── Delinquency / performance status ──────────────────────────────────
    # Optional with safe defaults — existing callers are not affected.
    # Populated by the DQ normalizer during tape ingest; used by the strat
    # engine for DQ distribution and by assumption resolvers for DQ-conditional
    # curves (future).
    days_past_due: int = 0              # 0, 30, 60, 90, 120, 150, 180+
    loan_status: str = "current"        # "current", "30_dpd", "60_dpd", ..., "fc", "reo"

    def __post_init__(self) -> None:
        """Validate loan data per BMA requirements.

        Validation philosophy for this educational library:
        - Dates: strict parseability checks at construction time.
        - Economics/terms: domain checks (balances, terms, cap/floor ordering).
        """
        if self.original_term <= 0:
            raise ValueError(f"original_term must be positive, got {self.original_term}")
        if self.remaining_term < 0:
            raise ValueError(f"remaining_term must be non-negative, got {self.remaining_term}")
        if self.original_balance <= 0:
            raise ValueError(f"original_balance must be positive, got {self.original_balance}")
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

        def _parse_date_or_raise(field: str, value: np.datetime64 | date | None, required: bool) -> np.datetime64 | None:
            if value is None:
                if required:
                    raise ValueError(f"{field} is required and cannot be None")
                return None
            try:
                return np.datetime64(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field} must be a valid date-like value, got {value!r}") from exc

        # Required dates must always parse.
        orig = _parse_date_or_raise("origination_date", self.origination_date, required=True)
        asof = _parse_date_or_raise("asof_date", self.asof_date, required=True)

        # Optional dates must parse when provided.
        _parse_date_or_raise("maturity_date", self.maturity_date, required=False)
        _parse_date_or_raise("first_payment_date", self.first_payment_date, required=False)
        _parse_date_or_raise("next_payment_date", self.next_payment_date, required=False)
        _parse_date_or_raise("last_payment_date", self.last_payment_date, required=False)
        _parse_date_or_raise("next_reset_date", self.next_reset_date, required=False)

        if asof < orig:
            raise ValueError(
                f"asof_date ({self.asof_date}) cannot be before "
                f"origination_date ({self.origination_date})"
            )
        if self.rate_cap is not None and self.rate_floor is not None:
            if self.rate_cap < self.rate_floor:
                raise ValueError(
                    f"rate_cap ({self.rate_cap}) cannot be less than "
                    f"rate_floor ({self.rate_floor})"
                )

    # ── Computed properties ─────────────────────────────────────────────

    @property
    def age(self) -> int:
        """Months since origination (original_term - remaining_term)."""
        return self.original_term - self.remaining_term

    def is_fixed_rate(self) -> bool:
        """True if the loan has a fixed coupon (no floating index)."""
        return self.reset_frequency == 0

    @property
    def is_delinquent(self) -> bool:
        """True if the loan has any days past due."""
        return self.days_past_due > 0

    @property
    def is_fc(self) -> bool:
        """True if the loan is in foreclosure."""
        return self.loan_status == "fc"

    @property
    def is_reo(self) -> bool:
        """True if the loan is REO (real-estate owned / liquidated)."""
        return self.loan_status == "reo"

    # ── Coupon vector construction ─────────────────────────────────────

    def build_coupon_vector(self, rate_index: RateIndex | None = None) -> np.ndarray:
        """Build an age-indexed coupon vector for sch_payment_factor_vector.

        Fixed-rate (reset_frequency == 0 or rate_index is None):
            Returns [0.0, margin, margin, ..., margin] of length original_term + 1.

        Floating-rate (rate_index provided and reset_frequency > 0):
            1. Retrieves per-period index rates from the RateIndex using the
               loan's first_payment_date, next_reset_date, and reset_frequency.
            2. Adds rate_margin to produce gross coupon per period.
            3. Applies periodic caps/floors (clamp change vs prior period).
            4. Applies life cap/floor (clamp absolute level).
            5. Prepends 0.0 at index 0 (origination).

        Args:
            rate_index: A RateIndex object providing dated index rates.
                Required for floating-rate loans (reset_frequency > 0).
                Ignored for fixed-rate loans.

        Returns:
            Age-indexed np.ndarray of length original_term + 1.
            result[0] = 0.0, result[n] = annual coupon rate (%) for period n.

        Raises:
            ValueError: If floating-rate but rate_index is None, or if
                first_payment_date is missing for a floating-rate loan.
        """
        n = self.original_term

        if self.is_fixed_rate() or rate_index is None:
            if not self.is_fixed_rate() and rate_index is None:
                raise ValueError(
                    "rate_index is required for floating-rate loans "
                    f"(reset_frequency={self.reset_frequency})"
                )
            return np.concatenate([[0.0], np.full(n, self.rate_margin)])

        if self.first_payment_date is None:
            raise ValueError("first_payment_date required for floating-rate loans")

        fpd = self.first_payment_date
        if not isinstance(fpd, date):
            fpd = np.datetime64(fpd, 'D').astype('datetime64[D]').item()

        nrd = self.next_reset_date
        if nrd is None:
            nrd = fpd
        elif not isinstance(nrd, date):
            nrd = np.datetime64(nrd, 'D').astype('datetime64[D]').item()

        from .rate_index import RateIndex as _RI
        index_rates = _RI.get_rate_vector(
            rate_index,
            next_payment_date=fpd,
            next_reset_date=nrd,
            reset_frequency=self.reset_frequency,
            remaining_term=n,
        )

        gross = index_rates + self.rate_margin

        if self.periodic_cap is not None or self.periodic_floor is not None:
            for i in range(1, len(gross)):
                change = gross[i] - gross[i - 1]
                if self.periodic_cap is not None:
                    change = min(change, self.periodic_cap)
                if self.periodic_floor is not None:
                    change = max(change, -self.periodic_floor)
                gross[i] = gross[i - 1] + change

        if self.rate_cap is not None:
            gross = np.minimum(gross, self.rate_cap)
        if self.rate_floor is not None:
            gross = np.maximum(gross, self.rate_floor)

        return np.concatenate([[0.0], gross])

    # ── Convenience accessors ─────────────────────────────────────────

    def get_coupon_vector(self, rate_index: RateIndex | None = None) -> np.ndarray:
        """Age-indexed coupon rates in PERCENT, ready for sch_payment_factor_vector.

        Delegates to build_coupon_vector(rate_index).  Returned vector has
        length original_term + 1 with [0] = 0.0 (origination).
        """
        return self.build_coupon_vector(rate_index)

    def coupon_decimal_for_cashflow(self, rate_index: RateIndex | None = None) -> np.ndarray:
        """Age-indexed coupon as DECIMAL (e.g. 0.08 for 8%).

        Same as get_coupon_vector() / 100.  Returned vector has
        length original_term + 1 with [0] = 0.0 (origination).
        """
        return self.build_coupon_vector(rate_index) / 100.0

    def servicing_fee_decimal(self) -> float:
        """Servicing fee as DECIMAL (e.g. 0.0025 for 25 bps) for cashflow runners."""
        return self.servicing_fee / 100.0


# =============================================================================
# Rate Vector Construction
# =============================================================================
#
# THE PROBLEM:
# Both the amortization loop (future payments) and sch_balance_factors
# (historical BAL path) need interest rates — potentially for every month
# from origination through maturity.  For a 30-year loan that's up to 360
# values.  But in practice, users rarely have the full history:
#
#   IDEAL:   A rate for every month from origination through maturity.
#            For a seasoned 360-month loan at age 60, that's 60 historical
#            rates (to reconstruct the BAL path the loan *should* have
#            followed) plus 300 future rates (for the amortization loop).
#
#   REALITY: We often get partial data:
#     - Fixed-rate loan: a single coupon rate (applies to every period).
#     - Floating-rate, new loan: an index forecast for the next N months,
#       but N might be less than the remaining term (rates run out before
#       maturity).
#     - Floating-rate, seasoned loan: we have recent index rates but are
#       missing the historical rates from before we started tracking.
#       Without those historical rates, sch_balance_factors can't compute
#       the exact BAL path — it has to approximate.
#
# THE SOLUTION:
# build_rate_vector() takes whatever index data the user provides and
# extends it to cover the full remaining term:
#   - Too short on the FUTURE side → pad forward with the most recent rate
#     (assumes current rate persists — standard projection convention).
#   - Too short on the HISTORICAL side → pad backward with the oldest known
#     rate (approximation — we emit a warning since we're guessing).
#   - Single value or scalar → treat as fixed rate (same value every period).
#
# Note: sch_balance_factors (called separately in the runner) does its own
# rate extension for the historical BAL path via sch_payment_factor_vector.
# build_rate_vector() handles rates for the amortization loop specifically.
# Both follow the same rate-extension convention.
# =============================================================================


def build_rate_vector(
    index: float | np.ndarray,
    rate_margin: float,
    original_term: int,
    remaining_term: int,
) -> tuple[np.ndarray, bool]:
    """Build a monthly interest rate vector for the floating-rate amortization loop.

    Mortgage loans have two rate conventions:
      - Fixed rate: the coupon is constant for the life of the loan.
        index is 0 (or a single value), and the rate every period is
        (index + rate_margin) / 12.
      - Floating rate: the coupon changes each period based on a market index
        (e.g. SOFR, LIBOR).  index is an array of historical + projected
        index values (oldest first), and the rate each period is
        (index[i] + rate_margin) / 12.

    The returned vector has length (remaining_term + 1) with [0] = 0.0
    (period 0 is the as-of snapshot, no payment), and [1..remaining_term]
    holding the monthly decimal rate for each payment period.

    When the index array is shorter than needed, we extend it:
      - BACKWARD (for historical periods we don't have): pad with the oldest
        known rate.  This is an approximation — we emit a warning.
      - FORWARD (for future periods beyond the index): pad with the newest
        known rate (assumes the current rate persists).

    This follows the same BMA rate-extension convention used by
    sch_payment_factor_vector and sch_balance_factors in scheduled_payments.py.

    Args:
        index:          Market index rates as decimal (e.g. 0.05 for 5%).
                        Scalar for fixed-rate, 1-D array for floating.
        rate_margin:    Annual spread over the index as decimal (e.g. 0.02 for 2%).
                        The full coupon each period is (index + rate_margin).
        original_term:  Loan term at origination in months (e.g. 360).
        remaining_term: Months left to maturity.

    Returns:
        monthly_rate:  np.ndarray of length (remaining_term + 1).
                       monthly_rate[0] = 0.0 (no rate at period 0).
                       monthly_rate[i] = (index + rate_margin) / 12 for period i.
        is_fixed:      True if the rate is constant across all periods
                       (scalar index, or single-element array).

    Raises:
        ValueError: If index or rate_margin is negative, or index is an empty array.
    """
    index_arr = np.asarray(index, dtype=float)

    # --- Case 1: Scalar index → fixed rate ---
    # A single number means every period has the same coupon.
    if index_arr.ndim == 0:
        rate_scalar = float(index_arr)
        if rate_scalar < 0 or rate_margin < 0:
            raise ValueError("index and rate_margin must be >= 0")
        full_rate = rate_scalar + rate_margin
        # [0.0, rate/12, rate/12, ...] — period 0 has no rate
        return np.concatenate([[0.0], np.full(remaining_term, full_rate / 12.0)]), True

    # --- Validation for array index ---
    if len(index_arr) == 0:
        raise ValueError("index cannot be empty when array-like")
    if np.any(index_arr < 0) or rate_margin < 0:
        raise ValueError("all index values and rate_margin must be >= 0")

    # Combine index + margin into the full annual coupon for each provided period
    coupon_vec = index_arr + rate_margin
    coupons_given = len(coupon_vec)

    # --- Case 2: Single-element array → treat as fixed rate ---
    if coupons_given == 1:
        return np.concatenate([[0.0], np.full(remaining_term, float(coupon_vec[0]) / 12.0)]), True

    # --- Case 3: Enough rates provided (no extension needed) ---
    if coupons_given >= remaining_term:
        # Take the first remaining_term values, convert annual → monthly
        rates = np.concatenate([[0.0], np.asarray(coupon_vec[:remaining_term], dtype=float) / 12.0])
        return rates, False

    # --- Case 4: Fewer rates than needed → extend backward and/or forward ---
    oldest = float(coupon_vec[0])   # earliest known rate (used for backward fill)
    newest = float(coupon_vec[-1])  # most recent known rate (used for forward fill)
    loan_age = original_term - remaining_term  # how many periods have already elapsed

    # Backward fill: if we have fewer rates than the loan's age, we're missing
    # historical index values.  Pad with the oldest known rate (approximation).
    backward_fill = max(0, loan_age - coupons_given)
    if backward_fill > 0:
        warnings.warn(
            f"index has {coupons_given} rates but {loan_age} historical periods needed. "
            f"Extending oldest rate backwards for {backward_fill} period(s).",
            UserWarning,
        )

    # Forward fill: for future periods beyond the provided index, assume the
    # most recent rate persists (standard floating-rate projection convention).
    forward_fill = max(0, remaining_term - coupons_given - backward_fill)

    # Assemble: [backward_fill × oldest] + [actual index rates] + [forward_fill × newest]
    # Then slice to exactly remaining_term periods.
    full_annual = np.concatenate([
        np.full(backward_fill, oldest),
        np.asarray(coupon_vec, dtype=float),
        np.full(forward_fill, newest),
    ])[:remaining_term]

    # Convert annual decimal → monthly decimal, prepend 0.0 for period 0
    monthly = np.concatenate([[0.0], full_annual / 12.0])
    return monthly, False


# =============================================================================
# Loan → Cashflow Wrapper Functions
# =============================================================================
#
# Convenience functions that take a Loan and call the cashflow runners with
# the correct parameter unpacking and percentage-to-decimal conversion.
# =============================================================================


def scheduled_cashflow_from_loan(
    loan: Loan,
    rate_index: RateIndex | None = None,
) -> BMAScheduledCashflow:
    """Generate scheduled cashflows for a Loan (no prepays, no defaults).

    Builds the coupon vector via loan.build_coupon_vector(rate_index), converts
    rates from percent to decimal, and calls run_bma_scheduled_cashflow.

    Args:
        loan: Loan object with all loan-level data.
        rate_index: RateIndex for floating-rate loans. Ignored for fixed-rate.
    """
    coupon_vec = loan.build_coupon_vector(rate_index)
    # Strip age-0 slot; pass remaining_term-length coupon vector in %
    cv_for_runner = coupon_vec[loan.age + 1:] if loan.age > 0 else coupon_vec[1:]

    return run_bma_scheduled_cashflow(
        original_balance=loan.original_balance,
        current_balance=loan.current_balance,
        coupon_vector=cv_for_runner,
        original_term=loan.original_term,
        remaining_term=loan.remaining_term,
        accrued_interest=loan.accrued_interest,
        servicing_fee=loan.servicing_fee,
        loan_id=loan.loan_id,
        group_id=loan.group_id,
        asof_date=np.datetime64(loan.asof_date) if loan.asof_date is not None else None,
        first_payment_date=np.datetime64(loan.first_payment_date) if loan.first_payment_date is not None else None,
        maturity_date=np.datetime64(loan.maturity_date) if loan.maturity_date is not None else None,
    )


def _slice_curve(curve: np.ndarray, loan: "Loan", name: str) -> np.ndarray:
    """Slice an age-indexed assumption curve to the loan's projection window.

    Assumption curves (SMM, MDR, severity) are indexed by loan age — index 0
    corresponds to origination, index t to the loan at age t months.  For a
    seasoned loan at age A with remaining_term R, the projection uses indices
    A through A+R (inclusive), giving a period-indexed array of length R+1
    suitable for run_bma_actual_cashflow.

    Args:
        curve: Age-indexed array.  Must have length >= loan.age + loan.remaining_term + 1.
        loan:  Loan providing age and remaining_term for the slice bounds.
        name:  Parameter name for error messages (e.g. "smm_curve").

    Returns:
        np.ndarray of length loan.remaining_term + 1, period-indexed.

    Raises:
        ValueError: If the curve is too short to cover the loan's projection window.
    """
    required = loan.age + loan.remaining_term + 1
    if len(curve) < required:
        raise ValueError(
            f"{name} is too short for this loan: need length >= {required} "
            f"(loan.age={loan.age} + remaining_term={loan.remaining_term} + 1), "
            f"got {len(curve)}. Curves must be age-indexed from origination (index 0)."
        )
    return curve[loan.age : loan.age + loan.remaining_term + 1]


def actual_cashflow_from_loan(
    loan: Loan,
    scheduled_cf: BMAScheduledCashflow,
    smm_curve: np.ndarray,
    mdr_curve: np.ndarray,
    severity_curve: np.ndarray,
    severity_lag: int = 12,
    months_to_liquidation: int = 12,
    rate_index: RateIndex | None = None,
) -> BMAActualCashflow:
    """Generate actual cashflows for a Loan (with prepays and defaults).

    Assumption curves are **age-indexed**: index 0 corresponds to loan
    origination, index t to the loan at age t months.  For a pool of loans
    with varying seasoning, a single age-indexed curve (e.g. a full PSA SMM
    curve of length original_term + 1) can be passed for every loan; this
    function slices the correct window per loan automatically.

    The underlying runner (run_bma_actual_cashflow) is period-indexed — this
    wrapper handles the age-to-period translation.

    Args:
        loan: Loan object.
        scheduled_cf: Pre-computed scheduled cashflow from scheduled_cashflow_from_loan.
        smm_curve: Monthly prepayment rate (decimal, 0-1), age-indexed.
            Length must be >= loan.age + loan.remaining_term + 1.
        mdr_curve: Monthly default rate (decimal, 0-1), age-indexed.
            Same length requirement as smm_curve.
        severity_curve: Loss severity fraction (0-1), age-indexed.
            Same length requirement as smm_curve.
        severity_lag: Months from default to liquidation (default 12).
        months_to_liquidation: MDR forced to 0 in final N months (SF-19j).
        rate_index: RateIndex for floating-rate loans. Ignored for fixed-rate.

    Raises:
        ValueError: If any curve is too short to cover loan.age + loan.remaining_term + 1.
    """
    coupon_vec = loan.build_coupon_vector(rate_index)
    # Strip age-0 slot and align to this loan's remaining projection periods.
    cv_for_runner = coupon_vec[loan.age + 1:] if loan.age > 0 else coupon_vec[1:]

    # Slice age-indexed curves to the period-indexed window for this loan.
    smm_sliced = _slice_curve(smm_curve, loan, "smm_curve")
    mdr_sliced = _slice_curve(mdr_curve, loan, "mdr_curve")
    sev_sliced = _slice_curve(severity_curve, loan, "severity_curve")

    return run_bma_actual_cashflow(
        scheduled_cf=scheduled_cf,
        smm_curve=smm_sliced,
        mdr_curve=mdr_sliced,
        severity_curve=sev_sliced,
        severity_lag=severity_lag,
        coupon_vector=cv_for_runner,
        pi_advanced=loan.pi_advanced,
        advance_months=loan.advance_months,
        svc_rate_performing=loan.servicing_fee_decimal(),
        svc_rate_default=loan.svc_rate_default / 100.0 if loan.svc_rate_default is not None else None,
        svc_rate_foreclosure=loan.svc_rate_foreclosure / 100.0 if loan.svc_rate_foreclosure is not None else None,
        months_to_liquidation=months_to_liquidation,
    )


# =============================================================================
# Portfolio Runner Wrappers
# =============================================================================
#
# High-level entry points that accept a list[Loan] plus assumption curves and
# return an aggregated PortfolioCashflow.  These are the primary entry points
# for both notebook exploration and production pipeline use.
#
# Curve arguments follow a uniform convention:
#   - Single np.ndarray  → the same curve is applied to every loan.
#   - dict[loan_id, np.ndarray] → per-loan curves for heterogeneous portfolios.
#
# The returned PortfolioCashflow is in lazy (un-flushed) mode by default.
# Pass flush=True to release individual loan cashflow references after
# aggregation, which reduces memory for large portfolios.
# =============================================================================


def _resolve_curve(
    curves: np.ndarray | dict[int, np.ndarray],
    loan_id: int,
) -> np.ndarray:
    """Return the assumption curve for a specific loan.

    Args:
        curves:  A single array (same curve for all loans) or a
                 dict[loan_id → array] for per-loan assumptions.
        loan_id: The loan identifier to look up.

    Returns:
        np.ndarray for this loan.

    Raises:
        KeyError: If curves is a dict and loan_id is not present.
    """
    if isinstance(curves, np.ndarray):
        return curves
    try:
        return curves[loan_id]
    except KeyError:
        raise KeyError(
            f"No curve found for loan_id={loan_id}. "
            "Provide either a single array (uniform assumption) or a "
            "dict[loan_id, np.ndarray] with an entry for every loan."
        )


def run_scheduled_portfolio(
    loans: list[Loan],
    rate_index: RateIndex | None = None,
    flush: bool = False,
) -> "PortfolioCashflow":
    """Run scheduled cashflows for every loan and return an aggregated portfolio.

    Calls scheduled_cashflow_from_loan() for each loan and accumulates the
    results in a PortfolioCashflow (SCHEDULED_ONLY mode).  No prepayment or
    default assumptions are applied — this is the pure contractual cash flow.

    Args:
        loans:      List of Loan objects (e.g. from read_loan_tape).
        rate_index: RateIndex for floating-rate loans.  Pass None for
                    fixed-rate-only portfolios (the default).
        flush:      If True, call portfolio.flush() after building.  Releases
                    individual loan cashflow references to save memory on large
                    portfolios.  Default False (references kept for inspection).

    Returns:
        PortfolioCashflow in SCHEDULED_ONLY mode, one constituent per loan.

    Raises:
        ValueError: If loans is empty.

    Example::

        from bma_standard_formulas.engine import read_loan_tape, run_scheduled_portfolio

        loans = read_loan_tape("tape.csv", asof_date="2024-01-01")
        portfolio = run_scheduled_portfolio(loans)
        df = portfolio.scheduled.to_dataframe()
    """
    if not loans:
        raise ValueError("loans list is empty")

    # Lazy import to avoid circular dependency: loan.py → portfolio.py → cashflows.py
    from .portfolio import PortfolioCashflow, PortfolioMode

    portfolio = PortfolioCashflow([], mode=PortfolioMode.SCHEDULED_ONLY)
    for loan in loans:
        portfolio += scheduled_cashflow_from_loan(loan, rate_index=rate_index)

    if flush:
        portfolio.flush()

    return portfolio


def run_actual_portfolio(
    loans: list[Loan],
    smm_curves: np.ndarray | dict[int, np.ndarray],
    mdr_curves: np.ndarray | dict[int, np.ndarray],
    severity_curves: np.ndarray | dict[int, np.ndarray],
    rate_index: RateIndex | None = None,
    severity_lag: int = 12,
    months_to_liquidation: int = 12,
    flush: bool = False,
) -> "PortfolioCashflow":
    """Run actual cashflows for every loan and return an aggregated portfolio.

    Runs scheduled_cashflow_from_loan() followed by actual_cashflow_from_loan()
    for each loan and accumulates the results in a PortfolioCashflow
    (ACTUAL_ONLY mode).  The scheduled cashflows are intermediate — only the
    actual cashflows are stored in the portfolio.  For access to both views,
    use run_paired_portfolio() instead.

    Args:
        loans:        List of Loan objects (e.g. from read_loan_tape).
        smm_curves:   Monthly prepayment rates as decimal (e.g. 0.005 = 0.5%).
                      Single array applied to all loans, or dict[loan_id → array]
                      for per-loan assumptions.
        mdr_curves:   Monthly default rates as decimal.  Same convention.
        severity_curves: Loss severity as a fraction (e.g. 0.35 = 35% loss on
                      defaulted balance at liquidation).  Same convention.
        rate_index:   RateIndex for floating-rate loans.  Pass None for
                      fixed-rate-only portfolios.
        severity_lag: Months between default and loss recognition.  Default 12.
                      Ref: BMA SF-17.
        months_to_liquidation: Months in the foreclosure pipeline before REO
                      proceeds are received.  Default 12.
        flush:        If True, flush the portfolio after building.

    Returns:
        PortfolioCashflow in ACTUAL_ONLY mode, one constituent per loan.

    Raises:
        ValueError: If loans is empty.
        KeyError:   If any loan_id is absent from a per-loan curve dict.

    Example::

        import numpy as np
        from bma_standard_formulas.engine import read_loan_tape, run_actual_portfolio
        from bma_standard_formulas.formulas import (
            generate_smm_curve_from_psa, generate_sda_curve, cdr_to_mdr_vector,
        )

        loans = read_loan_tape("tape.csv", asof_date="2024-01-01")
        smm = generate_smm_curve_from_psa(150, 360)   # 150% PSA
        mdr = cdr_to_mdr_vector(generate_sda_curve(100, 360))
        sev = np.full(361, 0.35)

        portfolio = run_actual_portfolio(loans, smm, mdr, sev)
        df = portfolio.pool.to_dataframe()
    """
    if not loans:
        raise ValueError("loans list is empty")

    from .portfolio import PortfolioCashflow, PortfolioMode

    portfolio = PortfolioCashflow([], mode=PortfolioMode.ACTUAL_ONLY)
    for loan in loans:
        sch = scheduled_cashflow_from_loan(loan, rate_index=rate_index)
        act = actual_cashflow_from_loan(
            loan=loan,
            scheduled_cf=sch,
            smm_curve=_resolve_curve(smm_curves, loan.loan_id),
            mdr_curve=_resolve_curve(mdr_curves, loan.loan_id),
            severity_curve=_resolve_curve(severity_curves, loan.loan_id),
            severity_lag=severity_lag,
            months_to_liquidation=months_to_liquidation,
            rate_index=rate_index,
        )
        portfolio += act

    if flush:
        portfolio.flush()

    return portfolio


def run_paired_portfolio(
    loans: list[Loan],
    smm_curves: np.ndarray | dict[int, np.ndarray],
    mdr_curves: np.ndarray | dict[int, np.ndarray],
    severity_curves: np.ndarray | dict[int, np.ndarray],
    rate_index: RateIndex | None = None,
    severity_lag: int = 12,
    months_to_liquidation: int = 12,
    flush: bool = False,
) -> "PortfolioCashflow":
    """Run paired (scheduled + actual) cashflows and return a PAIRED portfolio.

    Like run_actual_portfolio(), but retains both the scheduled and actual
    cashflow for each loan as a CashFlowPair.  The returned portfolio is in
    PAIRED mode, giving simultaneous access to portfolio.scheduled (contractual
    amortization) and portfolio.pool (with prepayments and defaults applied).

    PAIRED mode is useful for:
      - Comparing scheduled vs actual factor paths (excess prepayment).
      - Computing scheduled vs actual interest collection.
      - Detailed advance tracking relative to contractual obligations.

    Args:
        (same as run_actual_portfolio — see that docstring for full details)

    Returns:
        PortfolioCashflow in PAIRED mode, one CashFlowPair per loan.

    Raises:
        ValueError: If loans is empty.
        KeyError:   If any loan_id is absent from a per-loan curve dict.

    Example::

        portfolio = run_paired_portfolio(loans, smm, mdr, sev)
        sch_df  = portfolio.scheduled.to_dataframe()
        pool_df = portfolio.pool.to_dataframe()
    """
    if not loans:
        raise ValueError("loans list is empty")

    from .portfolio import PortfolioCashflow, PortfolioMode
    from bma_standard_formulas.formulas.cashflows import CashFlowPair

    portfolio = PortfolioCashflow([], mode=PortfolioMode.PAIRED)
    for loan in loans:
        sch = scheduled_cashflow_from_loan(loan, rate_index=rate_index)
        act = actual_cashflow_from_loan(
            loan=loan,
            scheduled_cf=sch,
            smm_curve=_resolve_curve(smm_curves, loan.loan_id),
            mdr_curve=_resolve_curve(mdr_curves, loan.loan_id),
            severity_curve=_resolve_curve(severity_curves, loan.loan_id),
            severity_lag=severity_lag,
            months_to_liquidation=months_to_liquidation,
            rate_index=rate_index,
        )
        portfolio += CashFlowPair(scheduled=sch, actual=act)

    if flush:
        portfolio.flush()

    return portfolio
