# Requires Python 3.12+
# Uses native type hints: list[x], tuple[x, y], X | None (PEP 585, PEP 604)
from __future__ import annotations

import numpy as np
from dataclasses import dataclass

__version__ = "0.3.1"


# =============================================================================
# BMA Section C.3: Standard Formulas for Mortgage Cash Flows with Defaults
# Reference: SF-18 to SF-19 (BMA_FORMULAS.md)
# =============================================================================

@dataclass
class BMAScheduledCashflow:
    """
    Container for BMA scheduled cashflow outputs.

    Field names match BMA terminology:
    - pool_factor (F): principal remaining / original face (scheduled, no prepays)
    - amortized_balance_fraction (BAL): amortized loan balance as fraction of par
    - survival_factor: F / BAL (fraction of original $1 loans surviving)

    payment_factor is a helper (not a BMA term): scheduled factor drop = 1 - pool_factor[i]/pool_factor[i-1]
    """
    period: np.ndarray
    beginning_balance: np.ndarray
    scheduled_payment: np.ndarray
    payment_factor: np.ndarray  # helper, not a BMA-defined variable
    interest_billed: np.ndarray
    interest_paid: np.ndarray
    principal_paid: np.ndarray
    ending_balance: np.ndarray
    pool_factor: np.ndarray
    amortized_balance_fraction: np.ndarray
    survival_factor: np.ndarray


@dataclass
class BMAActualCashflow:
    """
    Container for BMA actual cashflow outputs.

    BMA Reference: Section C.3, SF-18 to SF-19

    Variables correspond to BMA formula names:
    - PERF BAL: Performing Balance
    - NEW DEF: New Defaults
    - FCL: Foreclosure (loans in foreclosure pipeline)
    - SCH AM: Scheduled Amortization (assuming no prepayments/defaults)
    - EXP AM: Expected Amortization (adjusted for defaults and foreclosures)
    - AM DEF: Amortization from Defaults (if P&I advanced)
    - VOL PREPAY: Voluntary Prepayments
    - ACT AM: Actual Amortization
    - EXP INT: Expected Interest
    - LOST INT: Interest lost due to defaults and foreclosures
    - ACT INT: Actual Interest received
    - PRIN RECOV: Principal Recovery
    - PRIN LOSS: Principal Loss
    - ADB: Amortized Default Balance in recovery (amount in recovery process after default)
    - MDR: Monthly Default Rate (default rate applied to performing balance)
    - SMM: Single Monthly Mortality (prepayment rate)
    """
    period: np.ndarray
    perf_bal: np.ndarray
    new_def: np.ndarray
    fcl: np.ndarray
    sch_am: np.ndarray
    exp_am: np.ndarray
    am_def: np.ndarray
    act_am: np.ndarray
    vol_prepay: np.ndarray
    exp_int: np.ndarray
    lost_int: np.ndarray
    act_int: np.ndarray
    adb: np.ndarray
    prin_recov: np.ndarray
    prin_loss: np.ndarray
    smm: np.ndarray
    mdr: np.ndarray


def run_bma_scheduled_cashflow(
    original_balance: float,
    current_balance: float,
    coupon: float,
    original_term: int,
    remaining_term: int,
    accrued_interest: float = 0.0,
    servicing_fee: float = 0.0
) -> BMAScheduledCashflow:
    """
    Generate scheduled cashflows using exact BMA formulas.

    BMA Reference: Section B.1, SF-4

    This calculates the amortization schedule assuming no prepayments or defaults.

    Args:
        original_balance: Original loan balance
        current_balance: Current balance (for aged loans)
        coupon: Annual coupon rate as decimal (e.g., 0.08 for 8%)
        original_term: Original term in months
        remaining_term: Remaining term in months
        accrued_interest: Any accrued but unpaid interest
        servicing_fee: Annual servicing fee as decimal

    Returns:
        BMAScheduledCashflow with all scheduled cashflow arrays
    """
    loan_age = original_term - remaining_term

    # Allocate arrays (0-indexed, period 0 is initial state)
    periods = remaining_term + 1
    period = np.arange(periods)
    beginning_balance = np.zeros(periods)
    scheduled_payment = np.zeros(periods)
    interest_billed = np.zeros(periods)
    interest_paid = np.zeros(periods)
    principal_paid = np.zeros(periods)
    ending_balance = np.zeros(periods)
    pool_factor = np.zeros(periods)
    amortized_balance_fraction = np.zeros(periods)
    survival_factor = np.zeros(periods)
    payment_factor = np.zeros(periods)

    # Initialize period 0
    ending_balance[0] = current_balance
    pool_factor[0] = ending_balance[0] / original_balance if original_balance > 0 else 0.0
    amortized_balance_fraction[0] = pool_factor[0]  # with no prepays, BAL fraction matches F
    survival_factor[0] = 1.0  # scheduled case with no prepays/defaults

    monthly_rate = coupon / 12.0
    net_rate = (coupon - servicing_fee) / 12.0

    # Generate cashflows
    for i in range(1, periods):
        beginning_balance[i] = ending_balance[i - 1]
        remaining_periods = remaining_term - i + 1
        interest_billed[i] = beginning_balance[i] * monthly_rate

        if remaining_periods > 0 and monthly_rate > 0:
            r = monthly_rate
            M = remaining_periods
            if (1 + r) ** (-M) < 1.0:
                annuity_factor = r / (1 - (1 + r) ** (-M))
            else:
                annuity_factor = 1.0 / M if M > 0 else 1.0
            scheduled_payment[i] = beginning_balance[i] * annuity_factor
            scheduled_payment[i] = min(
                scheduled_payment[i],
                beginning_balance[i] + interest_billed[i]
            )
        else:
            scheduled_payment[i] = beginning_balance[i] + interest_billed[i]

        interest_paid[i] = min(interest_billed[i], scheduled_payment[i])
        principal_paid[i] = scheduled_payment[i] - interest_paid[i]
        ending_balance[i] = beginning_balance[i] - principal_paid[i]
        pool_factor[i] = ending_balance[i] / original_balance if original_balance > 0 else 0.0
        amortized_balance_fraction[i] = ending_balance[i] / original_balance if original_balance > 0 else 0.0
        survival_factor[i] = pool_factor[i] / amortized_balance_fraction[i] if amortized_balance_fraction[i] > 0 else 0.0
        if survival_factor[i - 1] > 0:
            payment_factor[i] = 1.0 - (survival_factor[i] / survival_factor[i - 1])
        else:
            payment_factor[i] = 0.0

    return BMAScheduledCashflow(
        period=period,
        beginning_balance=beginning_balance,
        scheduled_payment=scheduled_payment,
        interest_billed=interest_billed,
        interest_paid=interest_paid,
        principal_paid=principal_paid,
        ending_balance=ending_balance,
        pool_factor=pool_factor,
        amortized_balance_fraction=amortized_balance_fraction,
        survival_factor=survival_factor,
        payment_factor=payment_factor
    )


def run_bma_actual_cashflow(
    scheduled_cf: BMAScheduledCashflow,
    smm_curve: np.ndarray,
    mdr_curve: np.ndarray,
    severity_curve: np.ndarray,
    severity_lag: int = 12,
    coupon: float = 0.08,
    pi_advanced: bool = True,
    months_to_liquidation: int = 12,
) -> BMAActualCashflow:
    """
    Generate actual cashflows with prepayments and defaults using exact BMA formulas.

    BMA Reference: Section C.3, SF-18 to SF-19
    """
    periods = len(scheduled_cf.period)
    monthly_rate = coupon / 12.0

    period = scheduled_cf.period.copy()
    perf_bal = np.zeros(periods)
    new_def = np.zeros(periods)
    fcl = np.zeros(periods)
    sch_am = scheduled_cf.ending_balance.copy()
    exp_am = np.zeros(periods)
    act_am = np.zeros(periods)
    am_def = np.zeros(periods)
    vol_prepay = np.zeros(periods)
    exp_int = np.zeros(periods)
    lost_int = np.zeros(periods)
    act_int = np.zeros(periods)
    adb = np.zeros(periods)
    prin_recov = np.zeros(periods)
    prin_loss = np.zeros(periods)
    smm = np.zeros(periods)
    mdr = np.zeros(periods)

    smm_curve = np.pad(smm_curve, (0, max(0, periods - len(smm_curve))), mode='edge')[:periods]
    mdr_curve = np.pad(mdr_curve, (0, max(0, periods - len(mdr_curve))), mode='edge')[:periods]
    severity_curve = np.pad(severity_curve, (0, max(0, periods - len(severity_curve))), mode='edge')[:periods]

    smm[:] = smm_curve
    mdr[:] = mdr_curve
    perf_bal[0] = scheduled_cf.ending_balance[0]

    for i in range(1, periods):
        if sch_am[i - 1] > 0:
            sched_surv_factor = sch_am[i] / sch_am[i - 1]
        else:
            sched_surv_factor = 0.0
        one_minus_af = 1.0 - sched_surv_factor

        if months_to_liquidation > 0 and i >= max(0, periods - months_to_liquidation):
            mdr[i] = 0.0

        new_def[i] = perf_bal[i - 1] * mdr[i]
        vol_prepay[i] = perf_bal[i - 1] * sched_surv_factor * smm[i]
        act_am[i] = (perf_bal[i - 1] - new_def[i]) * one_minus_af

        total_unsched = new_def[i] + vol_prepay[i] + act_am[i]
        if total_unsched > perf_bal[i - 1] and perf_bal[i - 1] > 0:
            excess = total_unsched - perf_bal[i - 1]
            vol_reduction = min(vol_prepay[i], excess)
            vol_prepay[i] -= vol_reduction
            excess -= vol_reduction
            if excess > 0:
                act_am[i] = max(act_am[i] - excess, 0.0)

        perf_bal[i] = perf_bal[i - 1] - new_def[i] - vol_prepay[i] - act_am[i]
        perf_bal[i] = max(perf_bal[i], 0.0)

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

        if i >= severity_lag:
            def_month = i - severity_lag
            prin_loss[i] = min(new_def[def_month] * severity_curve[def_month], adb[i])
            prin_recov[i] = max(adb[i] - prin_loss[i], 0.0)

        exp_int[i] = (perf_bal[i - 1] + fcl[i - 1]) * monthly_rate
        lost_int[i] = (new_def[i] + fcl[i - 1]) * monthly_rate
        act_int[i] = exp_int[i] - lost_int[i]

    return BMAActualCashflow(
        period=period,
        perf_bal=perf_bal,
        new_def=new_def,
        fcl=fcl,
        sch_am=sch_am,
        exp_am=exp_am,
        act_am=act_am,
        am_def=am_def,
        vol_prepay=vol_prepay,
        exp_int=exp_int,
        lost_int=lost_int,
        act_int=act_int,
        adb=adb,
        prin_recov=prin_recov,
        prin_loss=prin_loss,
        smm=smm,
        mdr=mdr
    )


def compare_arrays(bma_array: np.ndarray, test_array: np.ndarray,
                   rtol: float = 1e-9, atol: float = 1e-10) -> tuple[bool, float, int]:
    """Compare two arrays with BMA-specified tolerance."""
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
# Loan Object
# =============================================================================
#
# The Loan is the primary input to the cashflow runners. It stores rates and
# servicing fee as percentage (matching B.1 and Section F convention) and
# provides helper methods to convert to decimal for the runners above.
#
# See DESIGN_MODULES_AND_LOAN.md Section 2 for the full specification.
# =============================================================================

@dataclass
class Loan:
    """
    Loan for BMA scheduled/actual cashflows and pricing.

    Required fields:
        origination_date, asof_date, original_balance, current_balance,
        rate_margin, rate_index, servicing_fee, original_term, remaining_term.

    Computed properties:
        age: original_term - remaining_term (months since origination)
        coupon_percent: current coupon rate in percentage (at current age)

    Rate convention (matches bma_reference.py B.1 and Section F):
        - All rates and servicing_fee are stored as percentage (e.g. 8.0 for 8%, 0.25 for 25 bp).
        - Floating: rate_index is array of annual index rates %; coupon at period i = rate_index[i] + rate_margin.
        - Fixed: rate_index is None or zero-length; coupon = rate_margin for all periods.
        - BMA convention: If rate_index is shorter than original_term, extend BACKWARDS
          by prepending the oldest rate (first element) to fill missing historical periods.
        - run_bma_scheduled_cashflow / run_bma_actual_cashflow expect coupon as decimal;
          use coupon_decimal_for_cashflow() and servicing_fee_decimal().
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
        """Loan age in months (n = M₀ − Mₙ). Always computed from terms."""
        return self.original_term - self.remaining_term

    @property
    def coupon_percent(self) -> float:
        """Current coupon rate in percentage (e.g. 8.0 for 8%).

        For floating rate, returns rate_margin + rate_index[age] after extending
        the index backwards to full original_term (BMA convention). For fixed,
        returns rate_margin.
        """
        if self.is_fixed_rate():
            return self.rate_margin
        full_idx = self._get_extended_index()
        return float(self.rate_margin + full_idx[self.age])

    def is_fixed_rate(self) -> bool:
        """True if loan is fixed rate (no index or all-zero index)."""
        return self.rate_index is None or (
            hasattr(self.rate_index, "__len__") and
            (len(self.rate_index) == 0 or np.all(np.asarray(self.rate_index) == 0))
        )

    def _get_extended_index(self) -> np.ndarray:
        """
        Get rate_index extended backwards to full original_term length (BMA convention).

        Per BMA standard, if rate_index is shorter than original_term, prepend the
        oldest rate (first element) to fill missing historical periods.

        Returns:
            ndarray of length original_term with index rates (%)
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
        Annual coupon rates in percentage (%) for the next num_periods periods.

        For use with B.1 functions (sch_balance_factor_fixed_rate, sch_balance_factors,
        pool dicts). Fixed: constant rate_margin. Floating: rate_index[age : age+num_periods]
        + rate_margin.

        BMA convention: If rate_index is shorter than needed, extend BACKWARDS by
        prepending the oldest rate (first element) to fill missing historical periods.
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
        Coupon as decimal (e.g. 0.08 for 8%) for run_bma_scheduled_cashflow
        and run_bma_actual_cashflow.

        Those two functions are the only ones that take coupon as decimal;
        all other B.1 and Section F functions use percentage.

        Returns:
            ndarray of length remaining_term with coupon rates as decimals.
            For fixed-rate loans, all elements are equal (constant coupon).
        """
        c = self.get_coupon_vector(self.remaining_term)
        return c / 100.0

    def servicing_fee_decimal(self) -> float:
        """
        Servicing fee as decimal (e.g. 0.0025 for 25 bp) for cashflow functions.

        Returns:
            Servicing fee converted from percentage to decimal.
        """
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
    Generate scheduled cashflows from a Loan object.

    Unpacks the Loan fields and converts rates from percentage to decimal
    for run_bma_scheduled_cashflow.

    Args:
        loan: Loan object with rates in percentage convention.

    Returns:
        BMAScheduledCashflow with all scheduled cashflow arrays.
    """
    coupon_vec = loan.coupon_decimal_for_cashflow()
    # run_bma_scheduled_cashflow takes a single coupon (decimal);
    # for fixed-rate, all elements are equal so use the first
    coupon = float(coupon_vec[0]) if len(coupon_vec) > 0 else 0.0

    return run_bma_scheduled_cashflow(
        original_balance=loan.original_balance,
        current_balance=loan.current_balance,
        coupon=coupon,
        original_term=loan.original_term,
        remaining_term=loan.remaining_term,
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
    Generate actual cashflows from a Loan object.

    Unpacks the Loan fields and converts rates from percentage to decimal
    for run_bma_actual_cashflow.

    Args:
        loan: Loan object with rates in percentage convention.
        scheduled_cf: BMAScheduledCashflow from run_bma_scheduled_cashflow
            or scheduled_cashflow_from_loan.
        smm_curve: Monthly SMM values as decimals (0-1).
        mdr_curve: Monthly MDR values as decimals (0-1).
        severity_curve: Loss severity as decimals (0-1).
        severity_lag: Months from default to recovery (BMA default: 12).
        months_to_liquidation: Months before maturity where MDR is forced to zero.

    Returns:
        BMAActualCashflow with all actual cashflow arrays.
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
        pi_advanced=loan.pi_advanced,
        months_to_liquidation=months_to_liquidation,
    )
