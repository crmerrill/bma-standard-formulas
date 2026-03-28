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

import uuid
import warnings
from enum import Enum, auto
from pathlib import Path

import numpy as np
import pandas as pd
from dataclasses import dataclass, field, fields

from .scheduled_payments import (
    sch_ending_balance_factor,
)

# ---------------------------------------------------------------------------
# Numba JIT compilation (optional performance accelerator)
# ---------------------------------------------------------------------------
#
# Numba is a just-in-time (JIT) compiler that translates Python functions into
# optimized machine code at runtime using LLVM.  It works best on functions that
# operate on numpy arrays and use only scalar math — no Python objects, no dicts,
# no string operations.  When applied via the @njit decorator, a function's first
# call triggers compilation (a one-time cost of ~0.1-1s), and all subsequent calls
# run at near-C speed (typically 10-50x faster than interpreted Python).
#
# We use numba on the two hot inner loops in this module:
#   _scheduled_cf_floating_loop  — floating-rate amortization (360 iterations/loan)
#   _actual_cf_loop              — actual cashflow with defaults/advances (~170 lines × 360)
#
# Numba requires: pip install numba (which also installs llvmlite).
# It is NOT a required dependency — if numba is not installed, the code below
# creates a no-op _njit decorator that simply returns the original function
# unmodified, so all loops run as plain Python.  The library is fully functional
# either way; numba just makes it ~10-30x faster for large portfolios.
#
# To install: pip install numba
# To verify:  python -c "from numba import njit; print('numba OK')"
# ---------------------------------------------------------------------------
try:
    from numba import njit as _njit
    _HAS_NUMBA = True
except ImportError:
    _HAS_NUMBA = False

    def _njit(fn=None, **kwargs):
        """Fallback no-op decorator used when numba is not installed.

        The @_njit decorator is used throughout this module on hot-loop functions.
        When numba IS installed, _njit is just numba.njit — it compiles the
        decorated function to machine code.

        When numba is NOT installed (this branch), we need a stand-in that
        accepts the same calling conventions as @njit but does nothing.
        numba.njit can be used two ways:

            @njit            — called without arguments (fn is the function)
            @njit(cache=True) — called WITH arguments (fn is None, returns a decorator)

        This fallback handles both:
            - If fn is not None: we were called as @_njit (no parens), so return fn as-is.
            - If fn is None: we were called as @_njit(cache=True), so return a
              decorator that accepts fn and returns it unchanged (lambda f: f).
        """
        return fn if fn is not None else lambda f: f



# =============================================================================
# FieldKind Registry
# =============================================================================
#
# THE PROBLEM THIS SOLVES:
#
# When you combine 10,000 individual loans into a single pool (a portfolio),
# you need to produce pool-level versions of every field: pool balance,
# pool interest, pool default rate, etc.  But different fields must be
# combined differently:
#
#   - "How much principal was paid across all loans this month?"
#     → Just add them up.  $50 from loan A + $70 from loan B = $120 total.
#     These are FLOW fields.
#
#   - "What is the pool's ending balance?"
#     → You CANNOT just add individual ending balances and get a correct pool
#     balance, because balances are running totals that depend on the entire
#     history of flows.  Instead, you sum the individual FLOWS (principal paid,
#     defaults, prepayments) and then re-derive the balance from those summed
#     flows using the same recurrence formula.  These are STOCK fields.
#
#   - "What is the pool's default rate (MDR)?"
#     → You CANNOT average the individual MDR values (that gives the wrong
#     answer because loans have different balances).  Instead, you take the
#     pool-level defaults (a summed FLOW) and divide by the pool-level balance
#     (a reconstructed STOCK) to get the pool MDR from first principles.
#     These are RATIO fields.
#
#   - "What is the pool's loan_id?"
#     → This question doesn't make sense for a pool.  Loan identity fields
#     are not aggregated at all.  These are META fields.
#
# HOW IT WORKS:
#
# Each field on the BMAScheduledCashflow and BMAActualCashflow dataclasses
# carries a FieldKind tag in its metadata:
#
#     principal_paid: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
#     ending_balance: np.ndarray = field(metadata={"kind": FieldKind.STOCK})
#     gross_rate:     np.ndarray = field(metadata={"kind": FieldKind.RATIO})
#     loan_id:        int        = field(metadata={"kind": FieldKind.META})
#
# The portfolio aggregation code (in portfolio.py) uses these tags to know
# which fields to sum, which to reconstruct, which to recompute, and which
# to skip.  The helper function fields_by_kind() queries these tags.
#
# Ref: docs/architecture/cashflow_aggregation_design.md
# =============================================================================


class FieldKind(Enum):
    """Semantic category of each cashflow field — determines how it is aggregated.

    FLOW:  Additive dollar amounts.  When pooling: sum across loans.
           Examples: principal_paid, interest_billed, new_def, vol_prepay.

    STOCK: Balance quantities derived from flows via recurrence (cumsum).
           When pooling: sum the underlying FLOWS, then reconstruct stocks
           from the summed flows.  NEVER sum stocks directly.
           Examples: ending_balance, perf_bal, adv_prin_outstanding.

    RATIO: Intensive quantities (rates, factors) that are recomputed from
           their defining formulas on the aggregate flows and stocks.
           NEVER accumulated, summed, or weighted-averaged.
           Examples: gross_rate = interest / balance, mdr = defaults / balance.

    META:  Loan identity and timing fields.  Not aggregated at all.
           Examples: loan_id, original_term, asof_date, period (index).
    """
    # auto() assigns each member a unique integer value automatically (1, 2, 3, 4).
    # The actual values don't matter — we only ever compare by name (FieldKind.FLOW, etc.).
    FLOW = auto()
    STOCK = auto()
    RATIO = auto()
    META = auto()


def fields_by_kind(cls: type, kind: FieldKind) -> list:
    """Return all dataclass fields on *cls* that have the given FieldKind tag.

    Each field's FieldKind is stored in its dataclass metadata dict under the
    key "kind".  This function filters to those matching the requested kind.

    Args:
        cls:   A dataclass type (e.g. BMAScheduledCashflow, BMAActualCashflow).
               Must be a class decorated with @dataclass whose fields use
               ``field(metadata={"kind": FieldKind.X})``.
        kind:  The FieldKind to filter by (FLOW, STOCK, RATIO, or META).

    Returns:
        list[dataclasses.Field]: The subset of dataclass fields whose metadata
        ``"kind"`` value matches *kind*.  Returns an empty list if no fields
        match.  The fields are returned in declaration order.

    Example:
        >>> flow_fields = fields_by_kind(BMAScheduledCashflow, FieldKind.FLOW)
        >>> [f.name for f in flow_fields]
        ['scheduled_payment', 'interest_billed', 'interest_paid', 'principal_paid']
    """
    return [f for f in fields(cls) if f.metadata.get("kind") == kind]


# =============================================================================
# Exceptions
# =============================================================================
#
# Custom exception classes for domain-specific error conditions.  Both inherit
# from ValueError so callers can catch them with a broad ``except ValueError``
# or a specific ``except PortfolioModeError`` depending on their needs.
# They are exported from __init__.py so users can import them directly:
#
#     from bma_standard_formulas import PortfolioModeError, CashFlowPairValidationError
# =============================================================================


class PortfolioModeError(ValueError):
    """Raised when a portfolio operation violates mode compatibility rules.

    A PortfolioCashflow operates in one of three modes: SCHEDULED_ONLY,
    ACTUAL_ONLY, or PAIRED.  This error is raised when you try to combine
    incompatible types — for example, adding a BMAActualCashflow to a
    SCHEDULED_ONLY portfolio, or merging ACTUAL_ONLY with SCHEDULED_ONLY
    (which has no valid Least Common Denominator coercion — see portfolio.py _LCD_TABLE).

    Example:
        >>> p = PortfolioCashflow([scheduled_cf], mode=PortfolioMode.SCHEDULED_ONLY)
        >>> p += actual_cf  # raises PortfolioModeError
    """


class CashFlowPairValidationError(ValueError):
    """Raised when a CashFlowPair fails loan-identity validation at construction.

    A CashFlowPair binds a scheduled and actual cashflow for the SAME loan.
    This error is raised if the two cashflows disagree on any identity field:
    loan_id, original_term, remaining_term, or (when both are provided)
    asof_date, first_payment_date, or maturity_date.

    Example:
        >>> CashFlowPair(scheduled=cf_loan_1, actual=cf_loan_2)
        CashFlowPairValidationError: loan_id mismatch: scheduled=1 vs actual=2
    """


# =============================================================================
# Cashflow GUID (cf_id) — unique identifier for each cashflow object
# =============================================================================
#
# Every BMAScheduledCashflow and BMAActualCashflow gets a globally unique cf_id
# at construction.  This is used by PortfolioCashflow's version history to track
# which specific cashflow objects were added/removed, without storing object refs
# (which would prevent garbage collection).
#
# The counter is process-global and auto-incrementing.  Not thread-safe — add a
# lock if multi-threaded construction is needed.
# =============================================================================

def _next_cf_id() -> str:
    """Generate a globally unique cashflow identifier (UUID4).

    Returns a standard 128-bit UUID as a string (e.g. "550e8400-e29b-41d4-a716-446655440000").
    Used by the cashflow runners to assign a unique cf_id at construction time.

    UUID4 is randomly generated, guaranteed unique across machines and processes
    (collision probability < 1 in 2^122).  Unlike an auto-incrementing counter,
    UUIDs remain unique even if multiple processes create cashflows concurrently
    or if the module is reloaded.

    Args:
        None.

    Returns:
        str: A new UUID4 string in standard hyphenated format.

    See Also:
        https://docs.python.org/3/library/uuid.html
    """
    return str(uuid.uuid4())


# =============================================================================
# Dataclass Immutability Helper
# =============================================================================
#
# WHY IMMUTABILITY MATTERS:
# Leaf cashflows (BMAScheduledCashflow, BMAActualCashflow) are treated as
# "facts" — once computed, they should never change.  Multiple portfolios
# may hold references to the same cashflow object, and the version history
# / rewind system assumes constituents are stable.  If someone accidentally
# mutates cf.ending_balance[5] = 0, every portfolio sharing that object
# would silently see corrupted data with no way to trace the change.
#
# Python's @dataclass(frozen=True) prevents REASSIGNMENT of fields:
#     cf.ending_balance = new_array   → FrozenInstanceError ✓
#
# But it does NOT prevent MUTATION of array elements:
#     cf.ending_balance[5] = 0.0      → silently succeeds ✗
#
# _freeze_arrays closes this loophole by flipping numpy's writeable flag on
# every array field, so element mutation also raises an error.
# Zero memory overhead (no copies made — just a flag flip on each buffer).
# =============================================================================


def _freeze_arrays(obj) -> None:
    """Set all ndarray fields on a dataclass instance to read-only.

    Called from __post_init__ on both BMAScheduledCashflow and BMAActualCashflow
    to enforce immutability.  After this call, any attempt to mutate an array
    element (e.g. ``cf.ending_balance[5] = 0``) raises ValueError.

    This does NOT copy the arrays — it flips the numpy writeable flag on the
    existing buffer, so there is zero memory overhead.

    Args:
        obj:  A dataclass instance (e.g. a BMAScheduledCashflow or
              BMAActualCashflow).  Must already be constructed — this is
              intended to be called from __post_init__.

    Returns:
        None.  Modifies the array flags in-place (no new objects created).
    """
    for f in fields(obj):
        val = getattr(obj, f.name)
        if isinstance(val, np.ndarray):
            val.flags.writeable = False




# =============================================================================
# Array Comparison Utility
# =============================================================================
#
# Used primarily in tests to verify that our cashflow outputs match the BMA
# reference fixtures (Cash Flow A, Cash Flow B, etc.).  Provides more detail
# than a bare np.allclose — reports which period has the worst mismatch and
# by how much, which is essential for debugging tolerance failures.
# =============================================================================


def compare_arrays(
    bma_array: np.ndarray,
    test_array: np.ndarray,
    rtol: float = 1e-9,
    atol: float = 1e-10,
) -> tuple[bool, float, int]:
    """Compare two numeric arrays element-wise for near-equality.

    Goes beyond np.allclose by reporting the magnitude and location of the
    worst mismatch, making it easy to diagnose which period is failing and
    by how much.

    If the arrays have different lengths, a warning is raised and only the
    overlapping portion (shorter length) is compared.  Callers should treat
    a length mismatch as a bug: it usually means the cashflow engine returned
    a different number of periods than the reference fixture.

    Tolerance convention
    --------------------
    Two values ``a`` and ``b`` are considered equal when::

        |a - b| <= atol + rtol * |a|

    The defaults (``rtol=1e-9``, ``atol=1e-10``) are tight numerical-precision
    tolerances appropriate for comparing two implementations of the same formula
    (e.g. verifying the engine against the BMA reference examples).  They are
    NOT appropriate for comparing against externally rounded values such as
    tabulated dollar amounts rounded to cents — in that case, use a looser
    ``atol`` (e.g. ``atol=0.01`` for cent precision).

    Field-type guidance:
      - Balance / dollar flow fields: ``atol=0.01`` (cent), ``rtol=1e-6``
      - Rate / factor fields (SMM, CPR, pool factor): ``atol=1e-7``, ``rtol=1e-6``
      - BMA reference fixture comparisons: defaults (tight numerical precision)

    Args:
        bma_array:  The reference (expected) array — typically loaded from a
                    BMA fixture file or known-correct output.
        test_array: The computed array to validate against the reference.
        rtol:       Relative tolerance (default 1e-9).
        atol:       Absolute tolerance (default 1e-10).  Dominates when the
                    reference value is near zero.

    Returns:
        Tuple of (all_close, max_rel_diff, worst_period):
          all_close:     True if every element matches within tolerance.
          max_rel_diff:  The largest relative difference across all elements.
          worst_period:  The array index (period) where max_rel_diff occurs.
    """
    if len(bma_array) != len(test_array):
        warnings.warn(
            f"compare_arrays: length mismatch — bma_array has {len(bma_array)} elements "
            f"but test_array has {len(test_array)}. Only the first "
            f"{min(len(bma_array), len(test_array))} elements will be compared. "
            "This usually indicates a bug: the computed cashflow has a different "
            "number of periods than the reference fixture.",
            stacklevel=2,
        )
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
      - pool_factor (F): ACTUAL ending balance / original face.  Reflects whatever
        really happened to the balance, including any starting prepayment
        (current_balance < scheduled).  E.g. 0.95 means 95% of original face remains.
      - amortized_balance_fraction (BAL): SCHEDULED ending balance / original face.
        The no-prepay, no-default reference trajectory computed from sch_balance_factors.
        For scheduled cashflows, F == BAL (no prepays).  They diverge in actual cashflows
        where prepayments and defaults erode the balance faster than the scheduled path.
      - survival_factor: F / BAL.  Measures what fraction of the "expected" balance
        survived.  Equals 1.0 when current_balance == scheduled balance.  Less than 1.0
        if the loan started partially prepaid.  In actual cashflows, captures the
        combined attrition from both prepayments and defaults.
      - payment_factor: BMA C.3 amortization factor = 1 − BAL[i]/BAL[i−1].
        Used in ACT AM, EXP AM, AM DEF (SF-18).
      - gross_rate: Interest rate (interest_billed / beginning_balance), monthly decimal.
      - age: Loan age in months at each period. When combining cashflows, we use the
        ending_balance-weighted average age per period (standard BMA WAM convention).
      - bal_path_is_estimated: True if BAL path was estimated (e.g. floating rate with partial index).
      - bal_path_note: Optional note when bal_path_is_estimated (e.g. historical rates extended backward).

    Loan metadata (identity and timing):
      - loan_id: Integer uniquely identifying this loan.  Required for CashFlowPair
        validation (scheduled and actual must have the same loan_id) and for
        tracking which loans are in a portfolio.
      - group_id: Optional numeric or text identifier for GROUP cross-collateralization.
        Loans with the same group_id share recovery proceeds within the group.
        None = standalone.
      - original_balance, original_term, remaining_term: Loan economics at origination
        and as-of date.  Used by CashFlowPair to validate that scheduled and actual
        cashflows were generated from the same loan parameters.
      - asof_date, first_payment_date, maturity_date: Optional dates for CashFlowPair
        validation and audit trail.  None if not provided.

    Construction:
      - All array fields are required — no default factories.  A no-arg constructor
        is intentionally unsupported (it would create a fake zero-filled object that
        violates the "fully populated at construction" contract).
      - Normally created by run_bma_scheduled_cashflow(), not constructed directly.

    Operators:
      - cf1 + cf2 returns a new PortfolioCashflow (two assets = a portfolio).
      - cf * scalar returns a new BMAScheduledCashflow with dollar amounts scaled.
      - cf / scalar returns a new BMAScheduledCashflow (divides dollar amounts).
    """
    # --- FLOW fields (additive when pooling) ---
    scheduled_payment: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    interest_billed: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    interest_paid: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    principal_paid: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    # --- STOCK fields (derived from flows) ---
    period: np.ndarray = field(metadata={"kind": FieldKind.META})  # period index
    beginning_balance: np.ndarray = field(metadata={"kind": FieldKind.STOCK})
    ending_balance: np.ndarray = field(metadata={"kind": FieldKind.STOCK})
    # --- RATIO fields (recomputed from defining formulas on aggregate) ---
    pool_factor: np.ndarray = field(metadata={"kind": FieldKind.RATIO})  # ending_balance / original_balance
    amortized_balance_fraction: np.ndarray = field(metadata={"kind": FieldKind.RATIO})  # scheduled_balance / original_balance
    survival_factor: np.ndarray = field(metadata={"kind": FieldKind.RATIO})  # pool_factor / amortized_balance_fraction
    payment_factor: np.ndarray = field(metadata={"kind": FieldKind.RATIO})  # 1 - BAL[i]/BAL[i-1]
    gross_rate: np.ndarray = field(metadata={"kind": FieldKind.RATIO})  # annualized interest rate (interest_billed / beginning_balance * 12)
    age: np.ndarray = field(metadata={"kind": FieldKind.RATIO})  # loan age in months; when pooling, weighted by ending_balance
    # --- META fields (loan identity, timing, audit — not aggregated) ---
    cf_id: str = field(default="", metadata={"kind": FieldKind.META})  # globally unique UUID (auto-assigned by runner)
    loan_id: int = field(default=0, metadata={"kind": FieldKind.META})  # uniquely identifies the loan; 0 = unidentified
    group_id: int | str | None = field(default=None, metadata={"kind": FieldKind.META})  # for GROUP cross-collat; None = standalone
    asof_date: np.datetime64 | None = field(default=None, metadata={"kind": FieldKind.META})  # valuation / reporting date
    first_payment_date: np.datetime64 | None = field(default=None, metadata={"kind": FieldKind.META})  # first payment date from origination
    maturity_date: np.datetime64 | None = field(default=None, metadata={"kind": FieldKind.META})  # loan maturity date
    original_balance: float = field(default=0.0, metadata={"kind": FieldKind.META})  # face value at origination ($)
    current_balance: float = field(default=0.0, metadata={"kind": FieldKind.META})  # outstanding balance at asof ($)
    original_term: int = field(default=0, metadata={"kind": FieldKind.META})  # months at origination
    remaining_term: int = field(default=0, metadata={"kind": FieldKind.META})  # months left at asof
    accrued_interest: float = field(default=0.0, metadata={"kind": FieldKind.META})  # unpaid interest at asof ($)
    bal_path_is_estimated: bool = field(default=False, metadata={"kind": FieldKind.META})  # True if BAL path uses estimated historical rates
    bal_path_note: str = field(default="", metadata={"kind": FieldKind.META})  # explanation when bal_path_is_estimated

    def __post_init__(self) -> None:
        """Auto-assign cf_id if not provided, then lock all arrays to read-only.

        Two responsibilities:
          1. If cf_id is empty (default), generate a UUID4 automatically.
             Uses object.__setattr__ to bypass frozen=True (same mechanism
             Python's own __init__ uses on frozen dataclasses).
          2. Freeze all numpy array fields via _freeze_arrays() to prevent
             element-level mutation (e.g. cf.ending_balance[5] = 0).

        Args:
            None (called automatically by Python after __init__).

        Returns:
            None.
        """
        if not self.cf_id:
            object.__setattr__(self, "cf_id", _next_cf_id())
        _freeze_arrays(self)

    def __add__(self, other: BMAScheduledCashflow) -> "PortfolioCashflow":
        """Combine two scheduled cashflows into a new PortfolioCashflow.

        Two individual loan cashflows combined = a portfolio.  This is
        semantically mandated: if you hold two assets, you have a portfolio.
        The result is a new PortfolioCashflow in SCHEDULED_ONLY mode.

        Chaining works naturally: ``cf1 + cf2 + cf3`` first creates a portfolio
        from cf1+cf2, then the portfolio's __add__ mutates it to include cf3.

        Args:
            other:  Another BMAScheduledCashflow to combine with.

        Returns:
            PortfolioCashflow: A new portfolio containing both cashflows.

        Raises:
            None.
        """
        from bma_standard_formulas.engine.portfolio import PortfolioCashflow, PortfolioMode
        return PortfolioCashflow([self, other], mode=PortfolioMode.SCHEDULED_ONLY)

    def __sub__(self, other: BMAScheduledCashflow) -> "PortfolioCashflow":
        """Subtract one cashflow from another, returning a new PortfolioCashflow.

        Produces a portfolio where ``self`` is positive and ``other`` is negated
        (scaled by -1.0).  Useful for computing the difference between two
        loan scenarios (e.g. with vs without a rate change).

        Args:
            other:  The BMAScheduledCashflow to subtract.

        Returns:
            PortfolioCashflow: A new portfolio containing self + (-other).

        Raises:
            None.
        """
        from bma_standard_formulas.engine.portfolio import PortfolioCashflow, PortfolioMode
        return PortfolioCashflow([self, other.scale_by(-1.0)], mode=PortfolioMode.SCHEDULED_ONLY)

    def __mul__(self, scalar: float) -> BMAScheduledCashflow:
        """Scale all dollar amounts by a scalar, returning a new cashflow.

        ``cf * 2.0`` doubles every balance and payment.  Ratios (gross_rate,
        pool_factor, age) are unchanged because they are intensive quantities
        that don't scale with notional.

        Design choice: returns a new leaf CF (same type), NOT a PortfolioCashflow.
        Scaling a single loan gives you a scaled loan, not a one-element portfolio.

        Args:
            scalar:  The multiplier (e.g. 2.0 to double, 0.5 to halve).

        Returns:
            BMAScheduledCashflow: A new cashflow with dollar amounts scaled.

        Raises:
            None.
        """
        return self.scale_by(scalar)

    def __rmul__(self, scalar: float) -> BMAScheduledCashflow:
        """Support ``scalar * cf`` (commutative with __mul__).

        Args:
            scalar:  The multiplier.

        Returns:
            BMAScheduledCashflow: A new cashflow with dollar amounts scaled.

        Raises:
            None.
        """
        return self.scale_by(scalar)

    def __truediv__(self, scalar: float) -> BMAScheduledCashflow:
        """Divide all dollar amounts by a scalar, returning a new cashflow.

        ``cf / 2.0`` halves every balance and payment.  Equivalent to
        ``cf * (1.0 / scalar)``.

        Args:
            scalar:  The divisor.  Must be non-zero.

        Returns:
            BMAScheduledCashflow: A new cashflow with dollar amounts divided.

        Raises:
            ValueError: If scalar is zero.
        """
        if scalar == 0:
            raise ValueError("division by zero")
        return self.scale_by(1.0 / scalar)

    def scale_by(self, scalar: float) -> BMAScheduledCashflow:
        """Scale all dollar amounts (balances, payments) by a constant.

        Multiplies every FLOW and STOCK field by ``scalar``.  RATIO and META
        fields are copied unchanged (ratios are intensive — they don't scale
        with notional; meta is identity data).

        Example: ``cf.scale_by(2.0)`` doubles every balance and payment.
        Pool factor, gross rate, and age are unchanged.

        WHY explicit field-by-field (not FieldKind-driven):
            For scheduled CFs, stocks (balances) scale linearly because there
            are no nonlinear interactions (no prepay/default).  We can simply
            multiply dollar fields and copy ratio fields.  This is clearer for
            educational readers than a generic metadata-driven loop, and it
            makes explicit which fields are FLOW (scaled) vs RATIO/META
            (preserved).

            Compare with BMAActualCashflow.scale_by, which also scales directly
            (stocks are linear under uniform scaling — k cancels in all
            recurrences).  The reconstruction approach via
            _reconstruct_stocks_and_ratios is only needed when combining
            DIFFERENT loans (where the flow inputs come from different balance
            paths).

        Args:
            scalar:  The multiplier (e.g. 2.0 to double, -1.0 to negate).

        Returns:
            BMAScheduledCashflow: A new cashflow with dollar amounts scaled.
            The cf_id, loan_id, and all META fields are preserved from self.

        Raises:
            None.
        """
        return type(self)(
            # FLOW fields: scale by scalar
            scheduled_payment=self.scheduled_payment * scalar,
            interest_billed=self.interest_billed * scalar,
            interest_paid=self.interest_paid * scalar,
            principal_paid=self.principal_paid * scalar,
            # STOCK fields: scale by scalar (linear recurrence, k factors out)
            period=self.period.copy(),
            beginning_balance=self.beginning_balance * scalar,
            ending_balance=self.ending_balance * scalar,
            # RATIO fields: unchanged (k cancels in numerator/denominator)
            pool_factor=self.pool_factor.copy(),
            amortized_balance_fraction=self.amortized_balance_fraction.copy(),
            survival_factor=self.survival_factor.copy(),
            payment_factor=self.payment_factor.copy(),
            gross_rate=self.gross_rate.copy(),
            age=self.age.copy(),
            # META fields: identity preserved, dollar amounts scaled
            # cf_id omitted — __post_init__ auto-assigns a new UUID (scaled CF is a new object)
            loan_id=self.loan_id,
            group_id=self.group_id,
            original_balance=self.original_balance * scalar,
            current_balance=self.current_balance * scalar,
            original_term=self.original_term,
            remaining_term=self.remaining_term,
            accrued_interest=self.accrued_interest * scalar,
            bal_path_is_estimated=self.bal_path_is_estimated,
            bal_path_note=self.bal_path_note,
            asof_date=self.asof_date,
            first_payment_date=self.first_payment_date,
            maturity_date=self.maturity_date,
        )

    def to_dataframe(self) -> pd.DataFrame:
        """Convert the cashflow arrays to a pandas DataFrame for inspection.

        Only array-valued fields (FLOW, STOCK, RATIO) are included as columns.
        Scalar META fields (loan_id, cf_id, dates, etc.) are omitted to keep
        the DataFrame clean and avoid broadcasting scalars into full columns.

        Each row corresponds to one period (period 0 = as-of snapshot,
        periods 1..N = payment months).

        Args:
            None.

        Returns:
            pd.DataFrame: One column per array field, indexed by row number.
            Columns: period, beginning_balance, scheduled_payment, payment_factor,
            gross_rate, interest_billed, interest_paid, principal_paid,
            ending_balance, age, pool_factor, amortized_balance_fraction,
            survival_factor.

        Raises:
            None.
        """
        return pd.DataFrame({
            "period": self.period,
            "age": self.age,
            "beginning_balance": self.beginning_balance,
            "payment_factor": self.payment_factor,
            "scheduled_payment": self.scheduled_payment,
            "gross_rate": self.gross_rate,
            "interest_billed": self.interest_billed,
            "interest_paid": self.interest_paid,
            "principal_paid": self.principal_paid,
            "ending_balance": self.ending_balance,
            "pool_factor": self.pool_factor,
            "amortized_balance_fraction": self.amortized_balance_fraction,
            "survival_factor": self.survival_factor,
        })

    def __repr__(self) -> str:
        """Display the cashflow as a pandas DataFrame table.

        Called automatically when the object is printed or displayed in a REPL
        (e.g. typing ``cf`` in a Jupyter cell).  Shows all array fields in a
        tabular format with one row per period.

        Args:
            None.

        Returns:
            str: The string representation of the DataFrame.

        Raises:
            None.
        """
        return repr(self.to_dataframe())

    @classmethod
    def from_dataframe(
        cls,
        df: pd.DataFrame,
        cf_id: str | None = None,
        loan_id: int = 0,
        group_id: int | str | None = None,
        **meta_kwargs,
    ) -> BMAScheduledCashflow:
        """Reconstruct a scheduled cashflow from a pandas DataFrame.

        The DataFrame should have the same columns as ``to_dataframe()`` output
        (period, beginning_balance, scheduled_payment, etc.).  Scalar META fields
        are passed as keyword arguments.

        Args:
            df:           DataFrame with array field columns.
            cf_id:        UUID for the cashflow.  Auto-generated if None.
            loan_id:      Loan identifier (default 0).
            group_id:     Group identifier (default None).
            **meta_kwargs: Additional META fields (original_balance, original_term,
                          remaining_term, accrued_interest, bal_path_is_estimated,
                          bal_path_note, asof_date, first_payment_date, maturity_date).

        Returns:
            BMAScheduledCashflow: A new frozen cashflow.

        Raises:
            KeyError: If required columns are missing from the DataFrame.
        """
        kwargs: dict = {}
        # Array fields from DataFrame columns
        for col in df.columns:
            if col in ("cf_id",):
                continue
            kwargs[col] = df[col].values
        # META fields from explicit args + kwargs
        if cf_id is not None:
            kwargs["cf_id"] = cf_id
        kwargs["loan_id"] = loan_id
        kwargs["group_id"] = group_id
        kwargs.update(meta_kwargs)
        return cls(**kwargs)


# =============================================================================
# Scheduled Cashflow Runner (and njit-compiled helpers)
# =============================================================================


@_njit(cache=True)
def _annuity_payment(balance: float, monthly_rate: float, remaining_term: int) -> float:
    """Compute the level monthly payment for a fully amortizing loan.

    This is the standard annuity formula (BMA SF-4):

        payment = balance × r / [1 - (1 + r)^(-M)]

    where r is the monthly interest rate and M is the number of remaining
    monthly payments.  The payment is "level" — the same dollar amount each
    month — and covers both principal and interest.

    Special cases:
        - remaining_term <= 0:  No payments left → returns 0.0.
        - monthly_rate <= 0:    Zero-interest loan → returns balance / M
          (straight-line principal paydown, no interest component).

    Args:
        balance:        Current outstanding loan balance in dollars.
        monthly_rate:   Monthly interest rate as a decimal (e.g. 0.005 for 6%/12).
        remaining_term: Number of monthly payments remaining (M).

    Returns:
        The level monthly payment in dollars (principal + interest combined).

    See Also:
        sch_payment_factor in scheduled_payments.py for the full BMA derivation
        including the PVAF ratio insight and notation conventions.
    """
    if remaining_term <= 0:
        return 0.0
    if monthly_rate <= 0:
        return balance / remaining_term
    return balance * monthly_rate / (1 - (1 + monthly_rate) ** (-remaining_term))


def _normalize_coupon_vector(
    coupon_vector: float | np.ndarray,
    remaining_term: int,
    *,
    allow_period_indexed_with_snapshot: bool = False,
) -> tuple[np.ndarray, bool]:
    """Normalize coupon input to a remaining-term annual-rate vector in percent.

    Returns:
        (cv, is_fixed_like_input) where cv has length remaining_term and
        is_fixed_like_input reflects whether the original input was scalar or
        constant-valued.
    """
    cv = np.atleast_1d(np.asarray(coupon_vector, dtype=float))
    if not np.all(np.isfinite(cv)):
        raise ValueError("coupon_vector contains non-finite values (NaN or Inf)")

    if allow_period_indexed_with_snapshot and len(cv) == remaining_term + 1:
        cv = cv[1:]

    is_fixed_like_input = len(cv) == 1 or np.all(cv == cv[0])

    if len(cv) < remaining_term:
        if is_fixed_like_input:
            cv = np.full(remaining_term, cv[0])
        else:
            raise ValueError(
                f"coupon_vector has {len(cv)} rates but remaining_term is {remaining_term}. "
                "Provide a complete vector for floating-rate loans."
            )
    elif len(cv) > remaining_term:
        cv = cv[:remaining_term]

    return cv, is_fixed_like_input


@_njit(cache=True)
def _scheduled_cf_floating_loop(
    periods: int,
    remaining_term: int,
    current_balance: float,
    monthly_rate_vec: np.ndarray,
    beginning_balance: np.ndarray,
    scheduled_payment: np.ndarray,
    interest_billed: np.ndarray,
    interest_paid: np.ndarray,
    principal_paid: np.ndarray,
    ending_balance: np.ndarray,
    gross_rate: np.ndarray,
) -> None:
    """Floating-rate scheduled amortization loop (njit-compiled).

    For floating-rate loans, each period's payment depends on the prior period's
    balance (which depends on all prior payments), creating a sequential dependency
    that prevents numpy vectorization.  This loop computes the full amortization
    schedule period by period.

    When numba is installed, @_njit compiles this to machine code (~30x faster).
    When numba is not installed, it runs as plain Python (still correct, just slower).

    All arrays are pre-allocated by the caller and filled in-place by this function.

    Args:
        periods:           Total number of periods (remaining_term + 1).
        remaining_term:    Months remaining at start (used to compute M for each period).
        current_balance:   Starting balance (written to ending_balance[0]).
        monthly_rate_vec:  Monthly rate for each period (length = periods, [0] = 0.0).
        beginning_balance..gross_rate: Pre-allocated output arrays (length = periods),
                           filled in-place by this function.

    Returns:
        None.  All output arrays are modified in-place.
    """
    ending_balance[0] = current_balance
    for i in range(1, periods):
        beginning_balance[i] = ending_balance[i - 1]
        interest_billed[i] = beginning_balance[i] * monthly_rate_vec[i]
        scheduled_payment[i] = _annuity_payment(
            beginning_balance[i], monthly_rate_vec[i], remaining_term - i + 1
        )
        # Cap payment at balance + interest (prevents overpayment in final period)
        cap = beginning_balance[i] + interest_billed[i]
        if scheduled_payment[i] > cap:
            scheduled_payment[i] = cap
        interest_paid[i] = min(interest_billed[i], scheduled_payment[i])
        principal_paid[i] = scheduled_payment[i] - interest_paid[i]
        ending_balance[i] = beginning_balance[i] - principal_paid[i]
        # Annualize: monthly rate * 12
        gross_rate[i] = (
            interest_billed[i] / beginning_balance[i] * 12 if beginning_balance[i] > 0 else 0.0
        )


def run_bma_scheduled_cashflow(
    original_balance: float,
    current_balance: float,
    coupon_vector: float | np.ndarray,
    original_term: int,
    remaining_term: int,
    accrued_interest: float = 0.0,
    servicing_fee: float = 0.0,
    loan_id: int = 0,
    group_id: int | str | None = None,
    asof_date: np.datetime64 | None = None,
    first_payment_date: np.datetime64 | None = None,
    maturity_date: np.datetime64 | None = None,
) -> BMAScheduledCashflow:
    """
    Generate the scheduled amortization for a single loan (no prepays, no defaults).

    This is the "what if" scenario: what would the monthly payments and balances
    be if the borrower pays exactly on schedule until maturity? Used as the base
    for actual cashflows (which apply prepayment and default assumptions).

    Args:
        original_balance: Original loan amount (face value at origination), in dollars.
        current_balance: Current outstanding balance (for aged loans that have made payments).
        coupon_vector: Annual coupon rate in PERCENT (e.g. 8.0 for 8%).
            Scalar: fixed-rate, expanded to remaining_term.
            Array of length remaining_term: one coupon per period.
            Array shorter than remaining_term with all equal values: treated as fixed.
            Array shorter than remaining_term with varying values: rejected (ValueError).
        original_term: Original loan term in months (e.g. 360 for 30-year).
        remaining_term: Months left to maturity (e.g. 300 if 60 months have passed).
        accrued_interest: Accrued but unpaid interest (optional).
        servicing_fee: Annual servicing fee as PERCENT (e.g. 0.25 for 25 bps).

    Returns:
        BMAScheduledCashflow with arrays for each period (period 0 = initial, 1..N = payment months).

    Raises:
        ValueError: If any input fails validation.
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

    # ── Validate and normalize coupon_vector ──────────────────────────
    cv, is_fixed = _normalize_coupon_vector(
        coupon_vector=coupon_vector,
        remaining_term=remaining_term,
        allow_period_indexed_with_snapshot=False,
    )

    periods = remaining_term + 1
    loan_age = original_term - remaining_term

    period = np.arange(periods)
    age = loan_age + period

    # ── Monthly rate vector from coupon_vector ────────────────────────
    monthly_rate_vec = np.concatenate([[0.0], cv / 1200.0])

    # ── Amortize current_balance via the loop ─────────────────────────
    beginning_balance = np.zeros(periods)
    scheduled_payment = np.zeros(periods)
    gross_rate = np.zeros(periods)
    interest_billed = np.zeros(periods)
    interest_paid = np.zeros(periods)
    principal_paid = np.zeros(periods)
    ending_balance = np.zeros(periods)

    _scheduled_cf_floating_loop(
        periods, remaining_term, current_balance, monthly_rate_vec,
        beginning_balance, scheduled_payment, interest_billed,
        interest_paid, principal_paid, ending_balance, gross_rate,
    )

    # ── Scheduled BAL path (amortized_balance_fraction) ───────────────
    # BAL is the scheduled balance as a fraction of par (original face),
    # assuming zero prepayment and zero default.  It anchors at loan_age
    # and rolls forward for each period.
    #
    # amortized_balance_fraction[0] = BAL(loan_age): what fraction of par
    # should remain at this age under 0% CPR.
    # amortized_balance_fraction[i] = BAL(loan_age + i): the scheduled path
    # from here to maturity.
    #
    # survival_factor = pool_factor / amortized_balance_fraction: what
    # fraction of the scheduled balance is still performing.

    coupon_pct = float(cv[0])

    if is_fixed:
        # Vectorized BAL path: BMA B.1 SF-4 — BAL(Mₙ) = [1-(1+r)^-Mₙ] / [1-(1+r)^-M₀].
        # Denominator is a scalar; numerator is a vector over the projection horizon.
        # np.where handles periods after maturity (remaining <= 0 → BAL = 0).
        r = coupon_pct / 1200.0
        remaining_at_period = remaining_term - np.arange(periods)
        active = remaining_at_period > 0
        if r == 0.0:
            amortized_balance_fraction = np.where(
                active, remaining_at_period / original_term, 0.0
            ).astype(float)
        else:
            denom = 1.0 - (1.0 + r) ** (-original_term)
            numer = np.where(active, 1.0 - (1.0 + r) ** (-remaining_at_period.astype(float)), 0.0)
            amortized_balance_fraction = numer / denom
        bal_path_is_estimated = False
        bal_path_note = f"BAL path exact: fixed rate {coupon_pct:.4f}%"
    else:
        # Build age-indexed vector for historical BAL computation
        cv_age = np.concatenate([[0.0], cv])
        if len(cv_age) - 1 < original_term:
            oldest, newest = cv[0], cv[-1]
            back = max(0, loan_age - len(cv))
            fwd = max(0, original_term - len(cv) - back)
            cv_full = np.concatenate([
                [0.0], np.full(back, oldest), cv, np.full(fwd, newest),
            ])[:original_term + 1]
        else:
            cv_full = cv_age[:original_term + 1]

        bal_anchor = sch_ending_balance_factor(cv_full, original_term, age=loan_age)

        amortized_balance_fraction = np.empty(periods)
        amortized_balance_fraction[0] = bal_anchor
        for i in range(1, periods):
            r_i = monthly_rate_vec[i]
            M_i = remaining_term - i + 1
            if M_i <= 0:
                amortized_balance_fraction[i] = 0.0
            elif r_i <= 0:
                am = 1.0 / M_i
                amortized_balance_fraction[i] = amortized_balance_fraction[i - 1] * (1.0 - am)
            else:
                af = r_i / (1.0 - (1.0 + r_i) ** (-M_i))
                am = af - r_i
                amortized_balance_fraction[i] = amortized_balance_fraction[i - 1] * (1.0 - am)

        bal_path_is_estimated = max(0, loan_age - len(cv)) > 0
        if bal_path_is_estimated:
            bal_path_note = (
                f"BAL path estimated: floating rate with partial index "
                f"({len(cv)} rates, {max(0, loan_age - len(cv))} historical periods extended backward)"
            )
        else:
            bal_path_note = f"BAL path exact: floating rate with full index ({len(cv)} rates)"

    # ── BMA factor tracking (common to both branches) ──────────────────
    #
    # pool_factor (F): ending balance as fraction of original face.
    # This is the "actual" pool factor — for scheduled CFs it equals BAL
    # (since there are no prepays), but differs when current_balance < scheduled.
    pool_factor = ending_balance / original_balance

    # payment_factor: the BMA C.3 amortization factor per period.
    #   payment_factor[i] = principal_paid[i] / beginning_balance[i]
    # Equivalent to 1 - BAL[i]/BAL[i-1] for scheduled CFs.
    # Used in ACT AM, EXP AM, AM DEF (SF-18).
    payment_factor = np.zeros(periods)
    with np.errstate(divide="ignore", invalid="ignore"):
        payment_factor[1:] = np.where(
            beginning_balance[1:] > 0, principal_paid[1:] / beginning_balance[1:], 0.0,
        )

    # survival_factor = F / BAL = pool_factor / amortized_balance_fraction.
    #
    # Interpretation: what fraction of the "expected" (scheduled) balance is
    # still present?  For scheduled CFs, F == BAL so survival = 1.0.
    # If the loan started with current_balance < scheduled (partial prepay
    # before the as-of date), survival < 1 and stays constant.
    # For ACTUAL cashflows, survival captures both prepays and defaults
    # (the combined attrition from both sources).
    # At maturity, both F and BAL approach 0; we use 1.0 as the limit.
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(amortized_balance_fraction > 1e-12, pool_factor / amortized_balance_fraction, np.nan)
        survival_factor = np.where(np.isfinite(ratio), ratio, 1.0)

    # Construct immutable cashflow; __post_init__ auto-assigns cf_id and freezes arrays
    return BMAScheduledCashflow(
        # FLOW
        scheduled_payment=scheduled_payment,
        interest_billed=interest_billed,
        interest_paid=interest_paid,
        principal_paid=principal_paid,
        # STOCK
        period=period,
        beginning_balance=beginning_balance,
        ending_balance=ending_balance,
        # RATIO
        pool_factor=pool_factor,
        amortized_balance_fraction=amortized_balance_fraction,
        survival_factor=survival_factor,
        payment_factor=payment_factor,
        gross_rate=gross_rate,
        age=age,
        # META
        loan_id=loan_id,
        group_id=group_id,
        original_balance=original_balance,
        current_balance=current_balance,
        original_term=original_term,
        remaining_term=remaining_term,
        accrued_interest=accrued_interest,
        bal_path_is_estimated=bal_path_is_estimated,
        bal_path_note=bal_path_note,
        asof_date=asof_date,
        first_payment_date=first_payment_date,
        maturity_date=maturity_date,
    )


# =============================================================================
# Actual Cashflows: Prepayments and Defaults Applied
# =============================================================================


@dataclass(frozen=True, slots=True)
class BMAActualCashflow:
    """
    Monthly actual cashflow with prepayments and defaults applied (Tier 1).

    Implements BMA Section C.3 (SF-18, SF-19) loan-level cashflow projection with
    prepayments, defaults, foreclosure, and liquidation. Each field is a 1D array
    of length (periods + 1), indexed by period.

    This is the loan/projection level — no trust waterfall. For trust-level
    servicing collection, pass-through, and cross-collateralization, combine into
    a pool and wrap with PortfolioCashflow (see portfolio.py).

    Field groups:

    BMA C.3 Variables (SF-18 table order):
      Stocks (balances at a point in time):
        - perf_bal: PERF BAL — Performing Balance
        - fcl: FCL — Foreclosure pipeline
        - sch_am: SCH AM — Scheduled balance path (no prepay/default)
        - adb: ADB — Amortized Default Balance
      Flows (per-period amounts):
        - new_def: NEW DEF — New Defaults
        - exp_am: EXP AM — Expected Amortization
        - vol_prepay: VOL PREPAY — Voluntary Prepayments
        - am_def: AM DEF — Amortization from Defaults
        - act_am: ACT AM — Actual Amortization
        - exp_int: EXP INT — Expected Interest (gross)
        - lost_int: LOST INT — Interest lost to defaults
        - act_int: ACT INT — Actual Interest (gross)
        - prin_recov: PRIN RECOV — Principal Recovery
        - prin_loss: PRIN LOSS — Principal Loss

    Servicing (loan-level accrual):
      - svc_billed: Total servicing fee accrued on all outstanding balance.
        3-tier: performing * svc_rate_performing + new_def * svc_rate_default
        + fcl * svc_rate_foreclosure. Ref: BMA SF-4 "Servicing Fee = BAL1 * S/1200".

    Servicer Advance Tracking (BMA SF-15, SF-17):
      Flows:
        - adv_prin: Principal advanced this period = AM DEF from advancing vintages.
          Ref: SF-15 "amount of principal advanced = Amortization from Defaults".
        - adv_int: Interest advanced this period = LOST INT from advancing vintages.
          Ref: SF-15 "interest advanced exactly compensates for Lost Interest".
      Stocks:
        - adv_prin_outstanding: Cumulative unreimbursed principal advances.
        - adv_int_outstanding: Cumulative unreimbursed interest advances.
        - adv_outstanding: Total unreimbursed = adv_prin_outstanding + adv_int_outstanding.
      Note: at the loan level, advances accumulate but are NOT reimbursed.
      Reimbursement is a trust-level concept (PortfolioCashflow).

    Ratios (derived):
      - mdr: MDR — Monthly Default Rate = new_def / perf_bal_prev
      - smm: SMM — Monthly Prepayment Rate
      - gross_rate: Gross coupon rate (monthly)
      - net_rate: Net pass-through rate (monthly) = gross - servicing
      - age: Loan age in months

    Leaf-level advance reimbursement (Part C): When reimburse_advances=True in the
    runner, adv_reimbursed_prin/int are filled from this loan's prin_recov.
    adv_unrecoverable = advances this loan cannot cover on its own at liquidation.
    """
    # --- FLOW fields (BMA C.3 SF-18) ---
    new_def: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    exp_am: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    vol_prepay: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    am_def: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    act_am: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    exp_int: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    lost_int: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    act_int: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    prin_recov: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    prin_loss: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    svc_billed: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    adv_prin: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    adv_int: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    adv_reimbursed_prin: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    adv_reimbursed_int: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    adv_unrecoverable: np.ndarray = field(metadata={"kind": FieldKind.FLOW})
    # NOTE — two distinct "adv_unrecoverable" values exist in this codebase:
    #
    #   1. Loan-level (this field): advances this specific loan cannot cover from
    #      its own prin_recov at liquidation, assuming it stands alone.  Computed
    #      per-period in _actual_cf_loop.  When multiple loans are pooled via
    #      _aggregate_actual, this field is summed across constituents — giving the
    #      gross unrecoverables if every loan were treated independently (i.e. as if
    #      CrossCollateralMode.NONE were in effect, regardless of the actual mode).
    #
    #   2. Trust-level (PortfolioCashflow.adv_unrecoverable property): recomputed
    #      from scratch in _compute_waterfall as
    #        max(pool.adv_prin + pool.adv_int - adv_reimbursed_prin - adv_reimbursed_int, 0)
    #      after cross-collateralization has run.  Under CrossCollateralMode.FULL,
    #      excess recoveries from strong loans offset shortfalls of weak loans, so
    #      this trust-level value will be LOWER than the summed constituent value.
    #      Under CrossCollateralMode.NONE the two values are identical.
    #
    #   The pool-level FLOW field (pool.adv_unrecoverable) is the pre-cross-collat
    #   diagnostic.  PortfolioCashflow.adv_unrecoverable is the definitive trust
    #   loss figure.  Use the latter for any loss/severity analysis.
    # --- STOCK fields ---
    period: np.ndarray = field(metadata={"kind": FieldKind.META})  # period index, not derived from flows
    perf_bal: np.ndarray = field(metadata={"kind": FieldKind.STOCK})
    fcl: np.ndarray = field(metadata={"kind": FieldKind.STOCK})
    sch_am: np.ndarray = field(metadata={"kind": FieldKind.STOCK})
    adb: np.ndarray = field(metadata={"kind": FieldKind.STOCK})
    adv_prin_outstanding: np.ndarray = field(metadata={"kind": FieldKind.STOCK})
    adv_int_outstanding: np.ndarray = field(metadata={"kind": FieldKind.STOCK})
    adv_outstanding: np.ndarray = field(metadata={"kind": FieldKind.STOCK})
    # --- RATIO fields ---
    mdr: np.ndarray = field(metadata={"kind": FieldKind.RATIO})
    smm: np.ndarray = field(metadata={"kind": FieldKind.RATIO})
    gross_rate: np.ndarray = field(metadata={"kind": FieldKind.RATIO})
    net_rate: np.ndarray = field(metadata={"kind": FieldKind.RATIO})
    age: np.ndarray = field(metadata={"kind": FieldKind.RATIO})
    # --- META: loan identity (Part A) ---
    cf_id: str = field(default="", metadata={"kind": FieldKind.META})  # globally unique UUID
    loan_id: int = field(default=0, metadata={"kind": FieldKind.META})
    group_id: int | str | None = field(default=None, metadata={"kind": FieldKind.META})
    original_balance: float = field(default=0.0, metadata={"kind": FieldKind.META})
    current_balance: float = field(default=0.0, metadata={"kind": FieldKind.META})  # outstanding balance at asof ($)
    original_term: int = field(default=0, metadata={"kind": FieldKind.META})
    remaining_term: int = field(default=0, metadata={"kind": FieldKind.META})
    accrued_interest: float = field(default=0.0, metadata={"kind": FieldKind.META})  # unpaid interest at asof ($)
    asof_date: np.datetime64 | None = field(default=None, metadata={"kind": FieldKind.META})
    first_payment_date: np.datetime64 | None = field(default=None, metadata={"kind": FieldKind.META})
    maturity_date: np.datetime64 | None = field(default=None, metadata={"kind": FieldKind.META})
    scheduled_loan_id: int | None = field(default=None, metadata={"kind": FieldKind.META})

    def __post_init__(self) -> None:
        """Auto-assign cf_id if not provided, then lock all arrays to read-only.

        See BMAScheduledCashflow.__post_init__ for full explanation.

        Args:
            None (called automatically by Python after __init__).

        Returns:
            None.
        """
        if not self.cf_id:
            object.__setattr__(self, "cf_id", _next_cf_id())
        _freeze_arrays(self)

    def __add__(self, other: BMAActualCashflow) -> "PortfolioCashflow":
        """cf + cf returns new PortfolioCashflow (Part E)."""
        from bma_standard_formulas.engine.portfolio import PortfolioCashflow, PortfolioMode
        return PortfolioCashflow([self, other], mode=PortfolioMode.ACTUAL_ONLY)

    def __sub__(self, other: BMAActualCashflow) -> "PortfolioCashflow":
        """cf - cf returns new PortfolioCashflow (one positive, one negative) (Part E)."""
        from bma_standard_formulas.engine.portfolio import PortfolioCashflow, PortfolioMode
        return PortfolioCashflow([self, other.scale_by(-1.0)], mode=PortfolioMode.ACTUAL_ONLY)

    def __mul__(self, scalar: float) -> BMAActualCashflow:
        return self.scale_by(scalar)

    def __rmul__(self, scalar: float) -> BMAActualCashflow:
        return self.scale_by(scalar)

    def __truediv__(self, scalar: float) -> BMAActualCashflow:
        if scalar == 0:
            raise ValueError("division by zero")
        return self.scale_by(1.0 / scalar)

    def scale_by(self, scalar: float) -> BMAActualCashflow:
        """Scale all dollar amounts by a constant, preserving ratios and metadata.

        For uniform constant scaling, the balance recurrences are linear:
          perf_bal_scaled[i] = k * perf_bal[0] - Σ(k * flows) = k * perf_bal[i]
        and ratios are invariant (k cancels in numerator and denominator):
          mdr_scaled = (new_def * k) / (perf_bal * k) = mdr

        So we can simply multiply FLOW and STOCK fields by the scalar and
        copy RATIO and META fields unchanged — no reconstruction needed.
        This is much cheaper than _reconstruct_stocks_and_ratios (which IS
        needed when combining different loans, but not for uniform scaling).
        """
        return BMAActualCashflow(
            # FLOW fields: scale by scalar
            new_def=self.new_def * scalar,
            exp_am=self.exp_am * scalar,
            vol_prepay=self.vol_prepay * scalar,
            am_def=self.am_def * scalar,
            act_am=self.act_am * scalar,
            exp_int=self.exp_int * scalar,
            lost_int=self.lost_int * scalar,
            act_int=self.act_int * scalar,
            prin_recov=self.prin_recov * scalar,
            prin_loss=self.prin_loss * scalar,
            svc_billed=self.svc_billed * scalar,
            adv_prin=self.adv_prin * scalar,
            adv_int=self.adv_int * scalar,
            adv_reimbursed_prin=self.adv_reimbursed_prin * scalar,
            adv_reimbursed_int=self.adv_reimbursed_int * scalar,
            adv_unrecoverable=self.adv_unrecoverable * scalar,
            # STOCK fields: scale by scalar (linear recurrence, k factors out)
            period=self.period.copy(),
            perf_bal=self.perf_bal * scalar,
            fcl=self.fcl * scalar,
            sch_am=self.sch_am * scalar,
            adb=self.adb * scalar,
            adv_prin_outstanding=self.adv_prin_outstanding * scalar,
            adv_int_outstanding=self.adv_int_outstanding * scalar,
            adv_outstanding=self.adv_outstanding * scalar,
            # RATIO fields: unchanged (k cancels in numerator/denominator)
            mdr=self.mdr.copy(),
            smm=self.smm.copy(),
            gross_rate=self.gross_rate.copy(),
            net_rate=self.net_rate.copy(),
            age=self.age.copy(),
            # META fields: identity preserved, dollar amounts scaled
            # cf_id omitted — __post_init__ auto-assigns a new UUID
            loan_id=self.loan_id,
            group_id=self.group_id,
            original_balance=self.original_balance * scalar,
            current_balance=self.current_balance * scalar,
            original_term=self.original_term,
            remaining_term=self.remaining_term,
            accrued_interest=self.accrued_interest * scalar,
            asof_date=self.asof_date,
            first_payment_date=self.first_payment_date,
            maturity_date=self.maturity_date,
            scheduled_loan_id=self.scheduled_loan_id,
        )

    def to_dataframe(self):
        """Return a pandas DataFrame with key array fields as columns.

        Only array-valued fields are included — scalar META fields (loan_id,
        group_id, dates, etc.) are omitted to keep the DataFrame clean.
        This matches the convention on BMAScheduledCashflow.to_dataframe.
        """
        return pd.DataFrame({
            "period": self.period,
            "perf_bal": self.perf_bal,
            "new_def": self.new_def,
            "fcl": self.fcl,
            "sch_am": self.sch_am,
            "exp_am": self.exp_am,
            "vol_prepay": self.vol_prepay,
            "am_def": self.am_def,
            "act_am": self.act_am,
            "exp_int": self.exp_int,
            "lost_int": self.lost_int,
            "act_int": self.act_int,
            "prin_recov": self.prin_recov,
            "prin_loss": self.prin_loss,
            "adb": self.adb,
            "svc_billed": self.svc_billed,
            "adv_prin": self.adv_prin,
            "adv_int": self.adv_int,
            "adv_reimbursed_prin": self.adv_reimbursed_prin,
            "adv_reimbursed_int": self.adv_reimbursed_int,
            "adv_unrecoverable": self.adv_unrecoverable,
            "adv_prin_outstanding": self.adv_prin_outstanding,
            "adv_int_outstanding": self.adv_int_outstanding,
            "adv_outstanding": self.adv_outstanding,
            "mdr": self.mdr,
            "smm": self.smm,
            "gross_rate": self.gross_rate,
            "net_rate": self.net_rate,
            "age": self.age,
        })

    def __repr__(self) -> str:
        """Display as pandas DataFrame."""
        return repr(self.to_dataframe())

    @classmethod
    def from_dataframe(
        cls,
        df: pd.DataFrame,
        cf_id: str | None = None,
        loan_id: int = 0,
        group_id: int | str | None = None,
        **meta_kwargs,
    ) -> BMAActualCashflow:
        """Reconstruct an actual cashflow from a pandas DataFrame.

        The DataFrame should have the same columns as ``to_dataframe()`` output.

        Args:
            df:           DataFrame with array field columns.
            cf_id:        UUID for the cashflow.  Auto-generated if None.
            loan_id:      Loan identifier (default 0).
            group_id:     Group identifier (default None).
            **meta_kwargs: Additional META fields (original_balance, original_term,
                          remaining_term, asof_date, etc.).

        Returns:
            BMAActualCashflow: A new frozen cashflow.

        Raises:
            KeyError: If required columns are missing.
        """
        kwargs: dict = {}
        for col in df.columns:
            if col in ("cf_id",):
                continue
            kwargs[col] = df[col].values
        if cf_id is not None:
            kwargs["cf_id"] = cf_id
        kwargs["loan_id"] = loan_id
        kwargs["group_id"] = group_id
        kwargs.update(meta_kwargs)
        return cls(**kwargs)


# =============================================================================
# CashFlowPair (Part D)
# =============================================================================


@dataclass(frozen=True)
class CashFlowPair:
    """
    Validated wrapper holding scheduled and actual cashflows for the same loan.

    Used as the atomic unit when PortfolioCashflow operates in PAIRED mode.
    Validates at construction: loan_id, original_term, remaining_term must match;
    asof_date, first_payment_date, maturity_date must match if both provided.
    """

    scheduled: BMAScheduledCashflow
    actual: BMAActualCashflow

    def __post_init__(self) -> None:
        s, a = self.scheduled, self.actual
        if s.loan_id != a.loan_id:
            raise CashFlowPairValidationError(
                f"loan_id mismatch: scheduled={s.loan_id} vs actual={a.loan_id}"
            )
        if s.original_term != a.original_term:
            raise CashFlowPairValidationError(
                f"original_term mismatch on loan {s.loan_id}: {s.original_term} vs {a.original_term}"
            )
        if s.remaining_term != a.remaining_term:
            raise CashFlowPairValidationError(
                f"remaining_term mismatch on loan {s.loan_id}: {s.remaining_term} vs {a.remaining_term}"
            )
        for name in ("asof_date", "first_payment_date", "maturity_date"):
            sv = getattr(s, name, None)
            av = getattr(a, name, None)
            if sv is not None and av is not None and sv != av:
                raise CashFlowPairValidationError(
                    f"{name} mismatch on loan {s.loan_id}: {sv} vs {av}"
                )

    def scale_by(self, scalar: float) -> CashFlowPair:
        """Scale both scheduled and actual by scalar; returns new CashFlowPair."""
        return CashFlowPair(
            scheduled=self.scheduled.scale_by(scalar),
            actual=self.actual.scale_by(scalar),
        )


# =============================================================================
# Actual Cashflow Inner Loop (njit-compatible standalone function)
# =============================================================================


@_njit(cache=True)
def _actual_cf_loop(
    periods: int,
    perf_bal: np.ndarray,
    new_def: np.ndarray,
    fcl: np.ndarray,
    sch_am: np.ndarray,
    exp_am: np.ndarray,
    act_am: np.ndarray,
    am_def: np.ndarray,
    vol_prepay: np.ndarray,
    exp_int: np.ndarray,
    lost_int: np.ndarray,
    act_int: np.ndarray,
    prin_recov: np.ndarray,
    prin_loss: np.ndarray,
    adb: np.ndarray,
    svc_billed: np.ndarray,
    adv_prin: np.ndarray,
    adv_int: np.ndarray,
    adv_reimbursed_prin: np.ndarray,
    adv_reimbursed_int: np.ndarray,
    adv_unrecoverable: np.ndarray,
    adv_prin_outstanding: np.ndarray,
    adv_int_outstanding: np.ndarray,
    adv_outstanding: np.ndarray,
    smm_arr: np.ndarray,
    mdr_arr: np.ndarray,
    severity_curve: np.ndarray,
    gross_monthly_vec: np.ndarray,
    svc_monthly_perf: float,
    svc_monthly_def: float,
    svc_monthly_fcl: float,
    severity_lag: int,
    months_to_liquidation: int,
    effective_advancing: bool,
    advance_months: int,
    reimburse_advances: bool,
    reimburse_interest_first: bool,
) -> None:
    """BMA C.3 actual cashflow inner loop (SF-18, SF-19).

    Operates on pre-allocated arrays in-place.  All inputs are scalars or
    1-D float64 arrays — no Python objects — so this function is numba @njit
    compatible for ~10-50x speedup over the interpreted Python loop.
    """
    for i in range(1, periods):
        # Scheduled survival factor: SCH AM(i) / SCH AM(i-1)
        sched_surv_factor = sch_am[i] / sch_am[i - 1] if sch_am[i - 1] > 0 else 0.0
        one_minus_af = 1.0 - sched_surv_factor

        # Force MDR to 0 near maturity (SF-19j)
        if months_to_liquidation > 0 and i >= max(0, periods - months_to_liquidation):
            mdr_arr[i] = 0.0

        # NEW DEF, VOL PREPAY, ACT AM (SF-18)
        new_def[i] = perf_bal[i - 1] * mdr_arr[i]
        vol_prepay[i] = perf_bal[i - 1] * sched_surv_factor * smm_arr[i]
        act_am[i] = (perf_bal[i - 1] - new_def[i]) * one_minus_af

        # Outflow clamp (SF-19c)
        total_outflow = new_def[i] + vol_prepay[i] + act_am[i]
        if total_outflow > perf_bal[i - 1] and perf_bal[i - 1] > 0:
            excess = total_outflow - perf_bal[i - 1]
            vol_reduction = min(vol_prepay[i], excess)
            vol_prepay[i] -= vol_reduction
            excess -= vol_reduction
            if excess > 0:
                act_am[i] = max(act_am[i] - excess, 0.0)

        perf_bal[i] = max(perf_bal[i - 1] - new_def[i] - vol_prepay[i] - act_am[i], 0.0)

        # ADB at liquidation
        if i >= severity_lag:
            def_month = i - severity_lag
            if effective_advancing:
                if def_month > 0 and sch_am[def_month - 1] > 0:
                    adb[i] = new_def[def_month] * (sch_am[i - 1] / sch_am[def_month - 1])
                elif def_month == 0:
                    adb[i] = (
                        new_def[def_month] * (sch_am[i - 1] / sch_am[0])
                        if sch_am[0] > 0 else new_def[def_month]
                    )
                else:
                    adb[i] = new_def[def_month]
            else:
                adb[i] = new_def[def_month]

        # AM DEF (SF-15)
        if effective_advancing:
            am_def[i] = (new_def[i] + fcl[i - 1] - adb[i]) * one_minus_af
        else:
            am_def[i] = 0.0

        fcl[i] = max((new_def[i] + fcl[i - 1] - adb[i]) - am_def[i], 0.0)
        exp_am[i] = (perf_bal[i - 1] + fcl[i - 1] - adb[i]) * one_minus_af

        # Principal loss and recovery
        if i >= severity_lag:
            def_month = i - severity_lag
            prin_loss[i] = min(new_def[def_month] * severity_curve[def_month], adb[i])
            prin_recov[i] = max(adb[i] - prin_loss[i], 0.0)

        # Interest
        gross_monthly_i = gross_monthly_vec[i]
        exp_int[i] = (perf_bal[i - 1] + fcl[i - 1]) * gross_monthly_i
        lost_int[i] = (new_def[i] + fcl[i - 1]) * gross_monthly_i
        act_int[i] = exp_int[i] - lost_int[i]

        # 3-tier servicing
        svc_billed[i] = (
            (perf_bal[i - 1] - new_def[i]) * svc_monthly_perf
            + new_def[i] * svc_monthly_def
            + fcl[i - 1] * svc_monthly_fcl
        )

        # Advance tracking
        if effective_advancing:
            if advance_months < 0:
                adv_prin[i] = am_def[i]
                adv_int[i] = lost_int[i]
            else:
                adv_prin[i] = 0.0
                adv_int[i] = 0.0
                if advance_months >= 1:
                    adv_prin[i] += new_def[i] * one_minus_af
                    adv_int[i] += new_def[i] * gross_monthly_i
                advancing_fcl = 0.0
                for d in range(max(0, i - advance_months), i):
                    advancing_fcl += new_def[d]
                if fcl[i - 1] > 1e-12 and advancing_fcl > 0:
                    adv_fraction = min(advancing_fcl / (fcl[i - 1] + new_def[i]), 1.0)
                    adv_prin[i] = am_def[i] * adv_fraction
                    adv_int[i] = lost_int[i] * adv_fraction

        # Leaf-level advance reimbursement (Part C)
        if reimburse_advances and prin_recov[i] > 1e-12:
            prev_prin = adv_prin_outstanding[i - 1]
            prev_int = adv_int_outstanding[i - 1]
            if reimburse_interest_first:
                adv_reimbursed_int[i] = min(prin_recov[i], prev_int)
                excess_r = prin_recov[i] - adv_reimbursed_int[i]
                adv_reimbursed_prin[i] = min(excess_r, prev_prin)
            else:
                adv_reimbursed_prin[i] = min(prin_recov[i], prev_prin)
                excess_r = prin_recov[i] - adv_reimbursed_prin[i]
                adv_reimbursed_int[i] = min(excess_r, prev_int)
            adv_unrecoverable[i] = max(
                (prev_prin - adv_reimbursed_prin[i]) + (prev_int - adv_reimbursed_int[i]),
                0.0,
            )

        # Cumulative advance outstanding
        adv_prin_outstanding[i] = max(
            adv_prin_outstanding[i - 1] + adv_prin[i] - adv_reimbursed_prin[i], 0.0
        )
        adv_int_outstanding[i] = max(
            adv_int_outstanding[i - 1] + adv_int[i] - adv_reimbursed_int[i], 0.0
        )
        adv_outstanding[i] = adv_prin_outstanding[i] + adv_int_outstanding[i]


# =============================================================================
# Actual Cashflow Runner
# =============================================================================

def run_bma_actual_cashflow(
    scheduled_cf: BMAScheduledCashflow,
    smm_curve: np.ndarray,
    mdr_curve: np.ndarray,
    severity_curve: np.ndarray,
    severity_lag: int = 12,
    coupon_vector: float | np.ndarray = 8.0,
    pi_advanced: bool = True,
    advance_months: int = -1,
    svc_rate_performing: float = 0.0,
    svc_rate_default: float | None = None,
    svc_rate_foreclosure: float | None = None,
    months_to_liquidation: int = 12,
    reimburse_advances: bool = True,
    reimburse_interest_first: bool = True,
) -> BMAActualCashflow:
    """
    Apply prepayment and default assumptions to a scheduled cashflow.

    Implements BMA Section C.3 (SF-18, SF-19) with extensions for:
    - 3-tier servicing fees (performing / default / foreclosure rates)
    - Per-vintage servicer advance tracking with configurable advance window
    - Advance outstanding accumulation (reimbursement is trust-level; see portfolio.py)

    BMA References:
        SF-15: Servicer advance mechanics ("amount of principal advanced each month
               is equal to Amortization from Defaults")
        SF-17: Loss severity "should include all costs: foreclosure costs, servicer
               interest advances and principal advances"
        SF-18: C.3 variable definitions and formulas
        SF-19: Clarification notes (constraints, ordering)

    Servicing Guide References:
        FNMA Servicing Guide F-1-20: Stop Delinquency Advance at 4 months DQ
        GNMA MBS Guide Ch. 14, 15: Issuer advance obligation, full and timely payment
        FHLMC Seller/Servicer Guide Ch. 9203: Advance Management Program

    Args:
        scheduled_cf: Scheduled cashflow from run_bma_scheduled_cashflow.
        smm_curve: Monthly prepayment rate (decimal, 0-1), **period-indexed**.
            Index 0 is the as-of snapshot (unused by the loop); index t is the
            SMM applied at projection period t.  Length must be >= remaining_term + 1.
            When calling via the engine layer (actual_cashflow_from_loan), curves
            are age-indexed and sliced automatically.  Direct callers are
            responsible for passing the correct period-indexed slice.
        mdr_curve: Monthly default rate on performing balance (decimal, 0-1).
            Same period-indexed convention as smm_curve.
        severity_curve: Loss severity per dollar defaulted (decimal, 0-1).
            Same period-indexed convention as smm_curve.
        severity_lag: Months from default to liquidation (BMA default 12).
        coupon_vector: Annual gross coupon rate in PERCENT (e.g. 9.5 for 9.5%).
            Scalar: fixed-rate, expanded to remaining_term.
            Array of length remaining_term: one coupon per period.
            Array of length remaining_term + 1: period-indexed with slot 0
                as snapshot, which is dropped.
            Array shorter than remaining_term with all equal values: treated as fixed.
            Array shorter than remaining_term with varying values: rejected (ValueError).
        pi_advanced: Whether servicer advances P&I to investors on defaulted loans.
        advance_months: Per-vintage advance window. -1 = until liquidation (BMA default).
            0 = no advancing. 4 = FNMA/GNMA agency convention.
        svc_rate_performing: Annual servicing fee rate on performing balance as a
            decimal fraction (e.g. 0.0025 for 25 bps). Converted to a monthly rate
            internally via division by 12. Default 0.0 (no servicing fee).
        svc_rate_default: Annual rate on newly defaulted balance as a decimal fraction.
            None = inherit svc_rate_performing.
        svc_rate_foreclosure: Annual rate on foreclosure balance as a decimal fraction.
            None = inherit svc_rate_performing.
        months_to_liquidation: MDR forced to 0 in final N months (SF-19j).
        reimburse_advances: Apply loan-level reimbursement from prin_recov (Part C).
            If False, all reimbursement deferred to portfolio waterfall.
        reimburse_interest_first: Interest advances reimbursed before principal
            from liquidation proceeds (default True per BMA SF-17).

    Returns:
        BMAActualCashflow with BMA C.3 variables, servicing accrual, and advance tracking.
        Trust-level outputs (pass-through, advance recovery) require PortfolioCashflow.
    """
    # --- Parameter validation ---
    # Warn on contradictory pi_advanced / advance_months combinations.
    effective_advancing = pi_advanced and advance_months != 0
    if pi_advanced and advance_months == 0:
        warnings.warn(
            "pi_advanced=True but advance_months=0: no advances will be made. "
            "Set pi_advanced=False or advance_months > 0 (or -1 for until liquidation).",
            UserWarning,
        )
    if not pi_advanced and advance_months != 0:
        warnings.warn(
            f"pi_advanced=False but advance_months={advance_months}: "
            "advance_months is ignored when pi_advanced=False.",
            UserWarning,
        )

    # Resolve 3-tier servicing rates (None = inherit from performing).
    # Standard mortgage: all three are the same. Other asset classes may differ.
    svc_rate_def = svc_rate_default if svc_rate_default is not None else svc_rate_performing
    svc_rate_fcl = svc_rate_foreclosure if svc_rate_foreclosure is not None else svc_rate_performing
    svc_monthly_perf = svc_rate_performing / 12.0
    svc_monthly_def = svc_rate_def / 12.0
    svc_monthly_fcl = svc_rate_fcl / 12.0

    periods = len(scheduled_cf.period)
    remaining_term = periods - 1

    # Normalize coupon vector (shared contract with scheduled runner).
    cv, _ = _normalize_coupon_vector(
        coupon_vector=coupon_vector,
        remaining_term=remaining_term,
        allow_period_indexed_with_snapshot=True,
    )

    gross_monthly_vec = np.concatenate([[0.0], cv / 1200.0])
    net_monthly_vec = gross_monthly_vec - svc_rate_performing / 12.0

    # --- Allocate output arrays ---
    period = scheduled_cf.period.copy()
    perf_bal = np.zeros(periods)
    new_def = np.zeros(periods)
    fcl = np.zeros(periods)
    # BMA C.3: SCH AM = scheduled balance path in dollars.
    # Derived from amortized_balance_fraction (BAL as fraction of par) * original face.
    original_face = (scheduled_cf.ending_balance[0] / scheduled_cf.pool_factor[0]
                     if scheduled_cf.pool_factor[0] > 0 else 1.0)
    sch_am = scheduled_cf.amortized_balance_fraction * original_face
    exp_am = np.zeros(periods)
    act_am = np.zeros(periods)
    am_def = np.zeros(periods)
    vol_prepay = np.zeros(periods)
    exp_int = np.zeros(periods)
    lost_int = np.zeros(periods)
    act_int = np.zeros(periods)
    prin_recov = np.zeros(periods)
    prin_loss = np.zeros(periods)
    adb = np.zeros(periods)
    svc_billed = np.zeros(periods)
    adv_prin = np.zeros(periods)
    adv_int = np.zeros(periods)
    adv_reimbursed_prin = np.zeros(periods)
    adv_reimbursed_int = np.zeros(periods)
    adv_unrecoverable = np.zeros(periods)
    adv_prin_outstanding = np.zeros(periods)
    adv_int_outstanding = np.zeros(periods)
    adv_outstanding = np.zeros(periods)
    smm = np.zeros(periods)
    mdr = np.zeros(periods)
    # Store annualized rates (monthly * 12) for readability
    gross_rate = gross_monthly_vec * 12.0
    net_rate = net_monthly_vec * 12.0
    gross_rate[0] = 0.0
    net_rate[0] = 0.0
    age = scheduled_cf.age.copy() if len(scheduled_cf.age) == periods else np.zeros(periods)

    # Extend input curves if shorter than periods (pad with last value).
    smm_curve = np.pad(smm_curve, (0, max(0, periods - len(smm_curve))), mode='edge')[:periods]
    mdr_curve = np.pad(mdr_curve, (0, max(0, periods - len(mdr_curve))), mode='edge')[:periods]
    severity_curve = np.pad(severity_curve, (0, max(0, periods - len(severity_curve))), mode='edge')[:periods]
    smm[:] = smm_curve
    mdr[:] = mdr_curve

    # --- Period 0: initial state ---
    perf_bal[0] = scheduled_cf.ending_balance[0]

    # --- Periods 1..N: delegate to njit-compiled loop (or pure Python if no numba) ---
    _actual_cf_loop(
        periods, perf_bal, new_def, fcl, sch_am, exp_am, act_am, am_def,
        vol_prepay, exp_int, lost_int, act_int, prin_recov, prin_loss, adb,
        svc_billed, adv_prin, adv_int, adv_reimbursed_prin, adv_reimbursed_int,
        adv_unrecoverable, adv_prin_outstanding, adv_int_outstanding, adv_outstanding,
        smm, mdr, severity_curve, gross_monthly_vec,
        svc_monthly_perf, svc_monthly_def, svc_monthly_fcl,
        severity_lag, months_to_liquidation,
        effective_advancing, advance_months,
        reimburse_advances, reimburse_interest_first,
    )

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
        prin_recov=prin_recov,
        prin_loss=prin_loss,
        adb=adb,
        svc_billed=svc_billed,
        adv_prin=adv_prin,
        adv_int=adv_int,
        adv_reimbursed_prin=adv_reimbursed_prin,
        adv_reimbursed_int=adv_reimbursed_int,
        adv_unrecoverable=adv_unrecoverable,
        adv_prin_outstanding=adv_prin_outstanding,
        adv_int_outstanding=adv_int_outstanding,
        adv_outstanding=adv_outstanding,
        mdr=mdr,
        smm=smm,
        gross_rate=gross_rate,
        net_rate=net_rate,
        age=age,
        loan_id=scheduled_cf.loan_id,
        group_id=scheduled_cf.group_id,
        original_balance=scheduled_cf.original_balance or original_face,
        current_balance=scheduled_cf.current_balance,
        original_term=scheduled_cf.original_term,
        remaining_term=scheduled_cf.remaining_term,
        accrued_interest=scheduled_cf.accrued_interest,
        asof_date=scheduled_cf.asof_date,
        first_payment_date=scheduled_cf.first_payment_date,
        maturity_date=scheduled_cf.maturity_date,
        scheduled_loan_id=scheduled_cf.loan_id or None,
    )


