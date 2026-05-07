# Requires Python 3.12+
# Uses native type hints: list[x], tuple[x], X | None (PEP 585, PEP 604)
from __future__ import annotations

"""
Portfolio-level cashflow aggregation and trust waterfall (Tier 2).

PortfolioCashflow is a mutable container that holds leaf cashflows
(BMAScheduledCashflow, BMAActualCashflow, or CashFlowPair) and lazily
computes aggregate pool-level results plus trust waterfall outputs.

Operator semantics:
  cf + cf               -> new PortfolioCashflow  (two assets = portfolio)
  portfolio + cf        -> mutates portfolio IN PLACE, returns self  (see note)
  portfolio + portfolio -> new PortfolioCashflow  (merge without mutating either)
  portfolio += cf       -> mutates portfolio
  portfolio *= scalar   -> mutates portfolio

NOTE — intentional deviation from Python's usual `+` contract:
  ``portfolio + cf`` mutates ``self`` and returns ``self``, rather than returning
  a new object.  This is deliberate: building a portfolio loan-by-loan in a loop
  (the dominant use case) must not allocate a new object and copy _pending on
  every constituent.  The asymmetry with ``portfolio + portfolio`` (which does
  return a new object) is intentional — merging two complete portfolios is a
  rare operation where allocation is acceptable, while accumulation is hot-path.
  Callers who need non-mutating single-add semantics should use copy.copy() first.

Ref: BMA SF-4, SF-15, SF-17, SF-18, SF-19; FNMA F-1-20; GNMA Ch. 14-15; FHLMC AMP.
"""

import json
import logging
import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import warnings

from bma_standard_formulas.formulas.cashflows import (
    BMAActualCashflow,
    BMAScheduledCashflow,
    CashFlowPair,
    FieldKind,
    PortfolioModeError,
    fields_by_kind,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Part G: Mode Locking and LCD Coercion
# ---------------------------------------------------------------------------


class PortfolioMode(Enum):
    """Portfolio aggregation mode, locked at first constituent addition.

    SCHEDULED_ONLY: Only BMAScheduledCashflow constituents accepted.
    ACTUAL_ONLY:    Only BMAActualCashflow constituents accepted.
    PAIRED:         Only CashFlowPair constituents accepted (both views available).

    When combining portfolios of different modes, the Least Common Denominator
    (LCD) rule applies: PAIRED + ACTUAL -> ACTUAL_ONLY (extracts .actual from
    pairs), PAIRED + SCHEDULED -> SCHEDULED_ONLY (extracts .scheduled).
    Mixing ACTUAL_ONLY with SCHEDULED_ONLY is always an error.
    """
    SCHEDULED_ONLY = auto()
    ACTUAL_ONLY = auto()
    PAIRED = auto()


# Exhaustive LCD lookup table.  Every (A, B) pair is mapped explicitly so that
# adding a new enum member forces a KeyError rather than silently falling through.
_LCD_TABLE: dict[tuple[PortfolioMode, PortfolioMode], PortfolioMode | None] = {
    (PortfolioMode.SCHEDULED_ONLY, PortfolioMode.SCHEDULED_ONLY): PortfolioMode.SCHEDULED_ONLY,
    (PortfolioMode.ACTUAL_ONLY,    PortfolioMode.ACTUAL_ONLY):    PortfolioMode.ACTUAL_ONLY,
    (PortfolioMode.PAIRED,         PortfolioMode.PAIRED):         PortfolioMode.PAIRED,
    (PortfolioMode.PAIRED,         PortfolioMode.ACTUAL_ONLY):    PortfolioMode.ACTUAL_ONLY,
    (PortfolioMode.PAIRED,         PortfolioMode.SCHEDULED_ONLY): PortfolioMode.SCHEDULED_ONLY,
    (PortfolioMode.ACTUAL_ONLY,    PortfolioMode.PAIRED):         PortfolioMode.ACTUAL_ONLY,
    (PortfolioMode.SCHEDULED_ONLY, PortfolioMode.PAIRED):         PortfolioMode.SCHEDULED_ONLY,
    # Incompatible combinations -> None means raise
    (PortfolioMode.ACTUAL_ONLY,    PortfolioMode.SCHEDULED_ONLY): None,
    (PortfolioMode.SCHEDULED_ONLY, PortfolioMode.ACTUAL_ONLY):    None,
}

_TYPE_TO_MODE: dict[type, PortfolioMode] = {
    BMAScheduledCashflow: PortfolioMode.SCHEDULED_ONLY,
    BMAActualCashflow:    PortfolioMode.ACTUAL_ONLY,
    CashFlowPair:         PortfolioMode.PAIRED,
}


def _lcd_mode(a: PortfolioMode, b: PortfolioMode | type) -> PortfolioMode:
    """Least Common Denominator mode when combining mode *a* with *b*.

    *b* may be a PortfolioMode or a constituent type (BMAScheduledCashflow, etc.).
    Raises PortfolioModeError for incompatible combinations (ACTUAL + SCHEDULED).
    """
    b_mode = b if isinstance(b, PortfolioMode) else _TYPE_TO_MODE.get(b)
    if b_mode is None:
        raise TypeError(f"Cannot determine mode for {b!r}")
    result = _LCD_TABLE.get((a, b_mode))
    if result is None:
        raise PortfolioModeError(
            f"Cannot combine {a.name} with {b_mode.name}"
        )
    return result


# ---------------------------------------------------------------------------
# Part H: Cross-Collateralization
# ---------------------------------------------------------------------------


class CrossCollateralMode(Enum):
    """Cross-collateralization mode at trust / portfolio level.

    NONE:  No cross-collat — each loan's recovery covers only its own advances.
           Standard for agency RMBS (FNMA, GNMA, FHLMC).
    FULL:  Pool-level excess recovery offsets pool-level advance shortfalls,
           up to cross_collateral_cap.  Used in non-agency (private-label) RMBS.
    GROUP: Within-group reallocation only (partitioned by loan group_id).
           Used for multi-group/multi-collateral deals.
           NOTE: NOT YET IMPLEMENTED — raises NotImplementedError.
           Design intent: run an independent FULL waterfall within each group_id
           partition, so excess recovery from one group cannot benefit another.
           Requires per-loan group_id to be set on all constituents.

    Ref: BMA SF-17 severity / advance recovery; PSA waterfall conventions.
    """
    NONE = auto()
    FULL = auto()
    GROUP = auto()


# ---------------------------------------------------------------------------
# Part J: Version History
# ---------------------------------------------------------------------------


class PortfolioOp(Enum):
    """Operation type for portfolio event log (Part J)."""
    ADD = auto()
    SUBTRACT = auto()
    SCALE = auto()


@dataclass(frozen=True)
class PortfolioEvent:
    """Immutable record of a single portfolio mutation.

    Stored in the append-only _history list.  Each event stores lightweight
    identifiers (cf_id, loan_id) and scalar metadata — NOT object references.
    This allows constituent cashflow objects to be garbage-collected after
    flush, while the history remains complete for audit and rewind.

    To reconstruct the portfolio at a prior version via rewind(), the caller
    must provide an external store mapping cf_id -> cashflow object.

    Attributes:
        version:         Monotonically increasing version counter.
        timestamp:       time.perf_counter() at event creation (monotonic, not wall-clock).
        op:              What happened: ADD, SUBTRACT, or SCALE.
        cf_id:           Globally unique cashflow ID (for ADD/SUBTRACT ops).
        loan_id:         Loan identifier (for audit trail).
        scalar:          Scaling factor (only for SCALE ops).
        n_constituents:  Total constituent count after this event.
        meta:            Scalar metadata dict for audit (e.g. original_balance, original_term).
                         No arrays or object refs — just scalars for reconstruction context.
    """
    version: int
    timestamp: float
    op: PortfolioOp
    cf_id: str | None = None
    loan_id: int | None = None
    scalar: float | None = None
    n_constituents: int | None = None
    meta: dict | None = None


# ---------------------------------------------------------------------------
# Aggregation helpers (standalone module-level functions — Part K Numba-ready)
# ---------------------------------------------------------------------------


def _pad_sum_field(cfs: list, attr: str, n: int) -> np.ndarray:
    """Sum a named field across cashflows, zero-padding shorter ones to length *n*.

    Each constituent's *attr* array is padded on the right with zeros to length
    *n* (the longest constituent), then all are stacked and summed.  This is the
    fundamental aggregation primitive for FLOW fields.
    """
    return np.sum(
        np.stack([
            np.pad(getattr(cf, attr), (0, n - len(cf.period)), constant_values=0)
            for cf in cfs
        ], axis=1),
        axis=1,
    )


def _pad_sum_product(cfs: list, attr_a: str, attr_b: str, n: int) -> np.ndarray:
    """Sum the element-wise product of two fields across cashflows (for weighted averages).

    Used for balance-weighted age: sum(age_i * balance_i) across constituents.
    """
    return np.sum(
        np.stack([
            np.pad(
                getattr(cf, attr_a) * getattr(cf, attr_b),
                (0, n - len(cf.period)),
                constant_values=0,
            )
            for cf in cfs
        ], axis=1),
        axis=1,
    )


def _aggregate_scheduled(cfs: list[BMAScheduledCashflow]) -> BMAScheduledCashflow:
    """Combine multiple scheduled cashflows into one pooled BMAScheduledCashflow.

    All FLOW fields are summed across constituents.  STOCK fields (balances,
    factors) and RATIO fields (gross_rate, payment_factor) are recomputed from
    the aggregated flows using their defining formulas — never weighted-averaged.

    For scheduled cashflows (no prepays, no defaults):
      pool_factor = amortized_balance_fraction  (F == BAL)
      survival_factor = 1.0  (no attrition)

    Raises ValueError if the combined cashflow fails the balance identity
    (ending = beginning - principal) or if combined original face is non-positive.
    """
    if len(cfs) == 0:
        raise ValueError("Cannot aggregate empty scheduled cashflow list")
    if len(cfs) == 1:
        return cfs[0]
    n = max(len(cf.period) for cf in cfs)

    # --- Sum FLOW fields across constituents (metadata-driven) ---
    # fields_by_kind queries the FieldKind.FLOW tag on each dataclass field,
    # so adding a new FLOW field to BMAScheduledCashflow automatically includes
    # it in aggregation without changing this function. Derived FLOW fields
    # (those tagged with metadata "derived": True, e.g. sched_cash) are
    # skipped here — they are recomputed by the new aggregate's __post_init__
    # from the summed primitives, so summing them across constituents would
    # be redundant work and add no information.
    flow_sums: dict[str, np.ndarray] = {
        f.name: _pad_sum_field(cfs, f.name, n)
        for f in fields_by_kind(BMAScheduledCashflow, FieldKind.FLOW)
        if not f.metadata.get("derived")
    }

    # STOCK fields (beginning_balance, ending_balance) are also directly summable
    # for scheduled CFs because the balance recurrence is linear (no prepay/default).
    # For actual CFs this would be wrong — stocks must be reconstructed from flows.
    beginning_balance = _pad_sum_field(cfs, "beginning_balance", n)
    ending_balance = _pad_sum_field(cfs, "ending_balance", n)
    scheduled_payment = flow_sums["scheduled_payment"]
    interest_billed = flow_sums["interest_billed"]
    interest_paid = flow_sums["interest_paid"]
    principal_paid = flow_sums["principal_paid"]

    # Sanity check: ending_balance = beginning_balance - principal_paid must hold
    # on the aggregate (linear identity preserved under summation).
    if not np.allclose(
        beginning_balance[1:] - principal_paid[1:],
        ending_balance[1:],
        rtol=0, atol=1e-5,
    ):
        raise ValueError("Combined cashflow fails balance check: ending != beginning - principal")

    # Recover original face for each constituent from its period-0 pool factor:
    #   pool_factor[0] = ending_balance[0] / original_face
    #   => original_face = ending_balance[0] / pool_factor[0]
    combined_original_face = sum(
        cf.ending_balance[0] / cf.pool_factor[0]
        for cf in cfs
        if len(cf.period) > 0 and cf.pool_factor[0] > 0
    )
    if combined_original_face <= 0:
        raise ValueError("Combined original face is non-positive")

    # --- Recompute STOCK and RATIO fields from aggregated flows ---
    period = np.arange(n)

    # pool_factor (F): aggregate ending balance as fraction of combined original face.
    pool_factor = ending_balance / combined_original_face

    # For scheduled cashflows there are no prepays or defaults, so the
    # amortized balance fraction (BAL) equals pool_factor (F == BAL).
    amortized_balance_fraction = pool_factor.copy()

    # survival_factor = F / BAL.  Since F == BAL for scheduled, this is 1.0
    # everywhere (or 0 where the pool has fully amortized).
    with np.errstate(divide="ignore", invalid="ignore"):
        survival_factor = np.where(
            amortized_balance_fraction > 0,
            pool_factor / amortized_balance_fraction,
            0.0,
        )

    # payment_factor: period-over-period balance decline rate.
    #   payment_factor[i] = 1 - ending_balance[i] / ending_balance[i-1]
    # Recomputed from aggregate stocks, not averaged across constituents.
    payment_factor = np.zeros(n)
    with np.errstate(divide="ignore", invalid="ignore"):
        payment_factor[1:] = 1.0 - np.where(
            pool_factor[:-1] > 0, pool_factor[1:] / pool_factor[:-1], 0.0
        )

    # gross_rate: recomputed as interest_billed / beginning_balance * 12 (annualized).
    # This is the pool WAC derived from first principles, not a weighted average.
    with np.errstate(divide="ignore", invalid="ignore"):
        gross_rate = np.where(
            beginning_balance > 0, interest_billed / beginning_balance * 12, 0.0
        )

    # age: balance-weighted average across constituents (standard BMA WAM convention).
    age_weighted = _pad_sum_product(cfs, "age", "ending_balance", n)
    with np.errstate(divide="ignore", invalid="ignore"):
        age = np.where(ending_balance > 0, age_weighted / ending_balance, 0.0)

    return BMAScheduledCashflow(
        period=period,
        beginning_balance=beginning_balance,
        scheduled_payment=scheduled_payment,
        payment_factor=payment_factor,
        gross_rate=gross_rate,
        accrued_interest=sum(cf.accrued_interest for cf in cfs),
        interest_billed=interest_billed,
        interest_paid=interest_paid,
        principal_paid=principal_paid,
        ending_balance=ending_balance,
        age=age,
        pool_factor=pool_factor,
        amortized_balance_fraction=amortized_balance_fraction,
        survival_factor=survival_factor,
        bal_path_is_estimated=any(cf.bal_path_is_estimated for cf in cfs),
        bal_path_note="; ".join(cf.bal_path_note for cf in cfs if cf.bal_path_note),
        loan_id=0,
        group_id=None,
        original_balance=combined_original_face,
        original_term=0,
        remaining_term=n,
        asof_date=None,
        first_payment_date=None,
        maturity_date=None,
    )


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
    svc_billed: np.ndarray,
    prin_recov: np.ndarray,
    prin_loss: np.ndarray,
    sch_am: np.ndarray,
    adb: np.ndarray,
    adv_prin: np.ndarray,
    adv_int: np.ndarray,
    adv_reimbursed_prin: np.ndarray,
    adv_reimbursed_int: np.ndarray,
    adv_unrecoverable: np.ndarray,
    age_weighted: np.ndarray,
    # Pool-level META fields (optional — defaults to zeros/None for pool-level CFs)
    original_balance: float = 0.0,
    current_balance: float = 0.0,
    original_term: int = 0,
    remaining_term: int = 0,
    accrued_interest: float = 0.0,
) -> BMAActualCashflow:
    """Vectorized stock rollforward and ratio derivation for portfolio aggregation.

    Takes FLOW arrays that have already been summed across multiple loans
    (by _aggregate_actual), plus initial stock values, and reconstructs all
    STOCK and RATIO fields without any Python loops.

    This function is ONLY needed when combining different loans — NOT for
    uniform constant scaling (where stocks scale linearly and ratios cancel).
    See BMAActualCashflow.scale_by for the simpler constant-scaling case.

    The three field categories and how they are handled:
      FLOW:  Passed in as inputs (already summed by the caller).
      STOCK: Reconstructed here via np.cumsum from the summed flow arrays.
      RATIO: Recomputed here from defining formulas on the reconstructed stocks.
             NEVER weighted-averaged — always first-principles on the aggregate.

    Args:
        n:             Number of periods (length of all arrays).
        perf_bal_0:    Initial performing balance (period 0, summed across loans).
        fcl_0:         Initial foreclosure pipeline (period 0, summed across loans).
        new_def..adv_unrecoverable: Summed FLOW arrays from all constituent loans.
        age_weighted:  Pre-computed sum of (age_i * perf_bal_i) across loans,
                       used to derive balance-weighted average age.

    Returns:
        A new BMAActualCashflow with all STOCK and RATIO fields reconstructed
        from the summed flows.
    """
    period = np.arange(n)

    # ── STOCK reconstruction via vectorized cumsum ──────────────────────
    #
    # PERF BAL (performing balance): starts at perf_bal_0, decreases each
    # period by the three types of balance reduction: defaults, prepays,
    # and scheduled amortization.
    #   perf_bal[i] = perf_bal[0] - Σ(new_def + vol_prepay + act_am) for 1..i
    perf_bal = np.empty(n)
    perf_bal[0] = perf_bal_0
    if n > 1:
        perf_bal[1:] = perf_bal_0 - np.cumsum(new_def[1:] + vol_prepay[1:] + act_am[1:])
    np.maximum(perf_bal, 0.0, out=perf_bal)  # floor at zero (rounding protection)

    # FCL (foreclosure pipeline): grows with new defaults, shrinks as loans
    # are liquidated (adb) or amortized while in foreclosure (am_def).
    #   fcl[i] = fcl[0] + Σ(new_def - adb - am_def) for 1..i
    fcl = np.empty(n)
    fcl[0] = fcl_0
    if n > 1:
        fcl[1:] = fcl_0 + np.cumsum(new_def[1:] - adb[1:] - am_def[1:])
    np.maximum(fcl, 0.0, out=fcl)

    # Advance outstanding: cumulative advances minus cumulative reimbursements.
    adv_prin_outstanding = np.cumsum(adv_prin - adv_reimbursed_prin)
    np.maximum(adv_prin_outstanding, 0.0, out=adv_prin_outstanding)
    adv_int_outstanding = np.cumsum(adv_int - adv_reimbursed_int)
    np.maximum(adv_int_outstanding, 0.0, out=adv_int_outstanding)
    adv_outstanding = adv_prin_outstanding + adv_int_outstanding

    # ── RATIO derivation from defining formulas ─────────────────────────
    #
    # Each ratio is computed from its BMA definition applied to the
    # aggregate stocks and flows — never weighted-averaged.
    with np.errstate(divide="ignore", invalid="ignore"):
        # MDR = new defaults / prior performing balance (BMA SF-18, inverted)
        mdr = np.zeros(n)
        if n > 1:
            mdr[1:] = np.where(perf_bal[:-1] > 1e-12, new_def[1:] / perf_bal[:-1], 0.0)

        # SMM = VOL PREPAY / (PERF BAL * scheduled_survival_factor)
        smm = np.zeros(n)
        if n > 1:
            sched_surv = np.where(sch_am[:-1] > 1e-12, sch_am[1:] / sch_am[:-1], 0.0)
            denom = perf_bal[:-1] * sched_surv
            smm[1:] = np.where(denom > 1e-12, vol_prepay[1:] / denom, 0.0)

        # Gross and net coupon rates (monthly, as decimal)
        gross_rate = np.zeros(n)
        net_rate = np.zeros(n)
        if n > 1:
            bal_prev = perf_bal[:-1] + fcl[:-1]
            # Annualize: monthly rate * 12 gives annual rate as decimal
            gross_rate[1:] = np.where(bal_prev > 1e-12, exp_int[1:] / bal_prev * 12, 0.0)
            net_rate[1:] = np.where(bal_prev > 1e-12, (exp_int[1:] - svc_billed[1:]) / bal_prev * 12, 0.0)

        # Age: balance-weighted average (standard BMA WAM convention)
        age = np.where(perf_bal > 1e-12, age_weighted / perf_bal, 0.0)

    # Sanity check: ACT INT = EXP INT - LOST INT (SF-18 identity)
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
        # Pool-level META: meaningful for downstream analysis (e.g. WAC, WAM).
        # loan_id=0 and group_id=None signal "aggregate, not a single loan".
        loan_id=0,
        original_balance=original_balance,
        current_balance=current_balance,
        original_term=original_term,
        remaining_term=remaining_term,
        accrued_interest=accrued_interest,
    )


def _aggregate_actual(cfs: list[BMAActualCashflow]) -> BMAActualCashflow:
    """Combine multiple actual cashflows into one pooled BMAActualCashflow.

    All FLOW fields are summed.  STOCK fields (perf_bal, fcl, advance outstanding)
    are reconstructed from aggregated flows via cumsum.  RATIO fields (mdr, smm,
    gross_rate, net_rate) are recomputed from their defining formulas applied to
    aggregated flows and stocks — never weighted-averaged.

    Ref: BMA SF-18 variable definitions; SF-19 formula constraints.

    Raises ValueError if the cashflow list is empty.
    """
    if len(cfs) == 0:
        raise ValueError("Cannot aggregate empty actual cashflow list")
    if len(cfs) == 1:
        return cfs[0]
    n = max(len(cf.period) for cf in cfs)

    # --- Single-pass accumulator over constituents (accum_A pattern) ---
    # One Python loop over all constituents; inner loop over field names does
    # in-place slice-add into a pre-allocated (n_cols, n) accumulator.
    # The accumulator (~0.05 MB) stays in CPU cache for the full run, giving
    # ~13x speedup vs per-field _pad_sum_field loops that each allocate a
    # 28.9 MB intermediate stack (10k × 361 × 8B) and blow the cache.
    #
    # Columns: all FLOW fields first (auto-discovered via FieldKind metadata),
    # then sch_am and adb (STOCK but directly additive at pool level).
    # Derived FLOW fields (metadata "derived": True, e.g. act_prin / act_cash)
    # are skipped — they're recomputed on the new aggregate's __post_init__
    # from the summed primitives, so summing them here would be redundant.
    flow_field_names = [
        f.name for f in fields_by_kind(BMAActualCashflow, FieldKind.FLOW)
        if not f.metadata.get("derived")
    ]
    all_names = flow_field_names + ["sch_am", "adb"]
    acc = np.zeros((len(all_names), n), dtype=np.float64)
    age_weighted = np.zeros(n, dtype=np.float64)

    for cf in cfs:
        m = len(cf.period)
        for j, name in enumerate(all_names):
            acc[j, :m] += getattr(cf, name)
        age_weighted[:m] += cf.age * cf.perf_bal

    n_flow = len(flow_field_names)
    flow_sums: dict[str, np.ndarray] = {flow_field_names[j]: acc[j] for j in range(n_flow)}
    sch_am = acc[n_flow]
    adb    = acc[n_flow + 1]

    return _reconstruct_stocks_and_ratios(
        n,
        sum(cf.perf_bal[0] for cf in cfs),
        sum(cf.fcl[0] for cf in cfs),
        flow_sums["new_def"],
        flow_sums["vol_prepay"],
        flow_sums["act_am"],
        flow_sums["am_def"],
        flow_sums["exp_am"],
        flow_sums["exp_int"],
        flow_sums["lost_int"],
        flow_sums["act_int"],
        flow_sums["svc_billed"],
        flow_sums["prin_recov"],
        flow_sums["prin_loss"],
        sch_am,
        adb,
        flow_sums["adv_prin"],
        flow_sums["adv_int"],
        flow_sums["adv_reimbursed_prin"],
        flow_sums["adv_reimbursed_int"],
        flow_sums["adv_unrecoverable"],
        age_weighted,
        # Pool-level META: sum dollar amounts; longest term gives the WAM proxy.
        original_balance=sum(cf.original_balance for cf in cfs),
        current_balance=sum(cf.current_balance for cf in cfs),
        original_term=max((cf.original_term for cf in cfs), default=0),
        remaining_term=n - 1,
        accrued_interest=sum(cf.accrued_interest for cf in cfs),
    )


# ---------------------------------------------------------------------------
# Group-aware aggregation
# ---------------------------------------------------------------------------
#
# Per-loan cashflows carry a `group_id` META field (propagated from Loan.group_id
# during cashflow construction).  These helpers partition a list of constituents
# by `group_id` and run the existing whole-portfolio aggregator against each
# partition, producing one aggregate per group in a SINGLE pass.
#
# This is the engine-layer primitive that replaces the wasteful "run engine N+1
# times for grouped portfolios" pattern at the orchestrator level.  Because
# the engine already supports per-loan assumption curves
# (smm_curves: dict[loan_id, np.ndarray]), one engine invocation against all
# loans is sufficient — per-group results then come from filter+aggregate of
# the resulting constituents.
#
# Bucket semantics:
#   - Constituents with `group_id != None` are partitioned by str(group_id).
#   - Constituents with `group_id == None` go into the special bucket "_ungrouped"
#     so callers can detect missing tags (a single mixed result with both
#     "_ungrouped" and explicit group keys is a signal that the upstream
#     loan tape is partially tagged).
#   - The output is `dict[str, BMAActualCashflow]` (or `BMAScheduledCashflow`)
#     keyed by stringified group_id.
#
# Ref: BMA SF-17 partitioned advance recovery; CrossCollateralMode.GROUP
# (per-group reallocation; not yet implemented at the trust waterfall layer
# but the per-group aggregation primitive is independent of it).


def _partition_by_group_id(
    cfs: list,
) -> dict[str, list]:
    """Partition a list of cashflow constituents by their `group_id` field.

    Constituents with `group_id == None` go into the bucket ``"_ungrouped"``.
    Constituents with non-None `group_id` go into the bucket ``str(group_id)``,
    so numeric and string group identifiers coexist (e.g., ``Loan.group_id=1``
    and ``Loan.group_id="GROUP_1"`` would be different buckets — callers should
    use one convention consistently across a tape).

    Returns:
        dict[str, list]: Bucket key -> list of constituents in that bucket.
        Empty dict if *cfs* is empty.
    """
    buckets: dict[str, list] = {}
    for cf in cfs:
        gid = getattr(cf, "group_id", None)
        key = "_ungrouped" if gid is None else str(gid)
        buckets.setdefault(key, []).append(cf)
    return buckets


def _aggregate_actual_by_group(
    cfs: list[BMAActualCashflow],
) -> dict[str, BMAActualCashflow]:
    """Aggregate actual cashflows per group_id, returning one aggregate per partition.

    Walks the constituents once to bucket by ``group_id`` (using
    :func:`_partition_by_group_id`), then calls :func:`_aggregate_actual` on
    each non-empty bucket.  The mathematical identity

        _aggregate_actual(cfs) == _sum_aggregates(_aggregate_actual_by_group(cfs).values())

    holds for FLOW fields (perf_bal, act_int, act_am, etc.) by linearity of
    summation; STOCK and RATIO fields are reconstructed per-group from the
    summed flows of that group, so they reflect the group-local pool.

    Returns:
        dict[str, BMAActualCashflow]: One aggregated cashflow per group,
        keyed by stringified group_id.  Returns ``{}`` when *cfs* is empty.

    Ref: BMA SF-18, SF-19 (C.3 variables / formulas applied per group).
    """
    if not cfs:
        return {}
    buckets = _partition_by_group_id(cfs)
    return {gid: _aggregate_actual(group_cfs) for gid, group_cfs in buckets.items()}


def _aggregate_scheduled_by_group(
    cfs: list[BMAScheduledCashflow],
) -> dict[str, BMAScheduledCashflow]:
    """Aggregate scheduled cashflows per group_id, returning one aggregate per partition.

    Same partitioning logic as :func:`_aggregate_actual_by_group`, applied to
    scheduled cashflows.  Used in PAIRED mode to expose per-group scheduled
    streams alongside per-group actual streams (e.g., for scheduled-vs-actual
    decomposition reporting per group, or for PAC/TAC schedule derivation
    that needs the scheduled stream of a specific collateral group).

    Returns:
        dict[str, BMAScheduledCashflow]: One aggregated cashflow per group,
        keyed by stringified group_id.  Returns ``{}`` when *cfs* is empty.
    """
    if not cfs:
        return {}
    buckets = _partition_by_group_id(cfs)
    return {gid: _aggregate_scheduled(group_cfs) for gid, group_cfs in buckets.items()}


def _compute_waterfall(
    pool: BMAActualCashflow,
    cross_collateral_mode: CrossCollateralMode = CrossCollateralMode.NONE,
    cross_collateral_cap: float = 1.0,
) -> dict:
    """Compute trust waterfall outputs from a pooled BMAActualCashflow.

    The waterfall determines how cash from the pool is distributed between
    the servicer (servicing fees, advance recovery) and investors (pass-through
    principal + interest).

    Steps:
      1. Servicing fee collection (full in advancing periods, pro-rata otherwise).
      2. Trust advance rollforward and reimbursement from principal recoveries.
      3. Cross-collateralization (FULL mode only — excess recovery offsets shortfalls).
      4. Pass-through computation (investor principal + interest).

    Args:
        pool:                   Aggregated BMAActualCashflow (from _aggregate_actual).
        cross_collateral_mode:  NONE (agency), FULL (non-agency), or GROUP.
        cross_collateral_cap:   Maximum fraction of excess recovery available for
                                cross-collateral reimbursement (0.0 to 1.0).

    Returns:
        Dict with keys: svc_paid, svc_shortfall, adv_reimbursed_prin,
        adv_reimbursed_int, adv_unrecoverable, pt_principal, pt_interest,
        pt_cashflow, gross_cashflow, svc_cashflow.

    Raises:
        NotImplementedError: If cross_collateral_mode is GROUP (not yet implemented).

    Ref: BMA SF-17 (loss severity / advance recovery); SF-19h (pass-through).
         FNMA F-1-20 (stop-advance); GNMA Ch. 14-15 (full P&I guarantee).
    """
    if cross_collateral_mode == CrossCollateralMode.GROUP:
        raise NotImplementedError(
            "CrossCollateralMode.GROUP requires per-loan group_id partitioning "
            "and is not yet implemented.  Use NONE or FULL."
        )

    n = len(pool.period)

    # --- Step 1: Servicing fee collection ---
    # In advancing periods (where the servicer is making P&I advances to
    # investors), the servicer collects full servicing fees because they
    # have a contractual right to reimbursement from the trust.
    # In non-advancing periods, only the performing share of the pool
    # generates collectible servicing fees.
    advancing_periods = (pool.adv_prin + pool.adv_int) > 1e-12
    svc_paid = np.where(advancing_periods, pool.svc_billed, 0.0)
    if n > 1:
        # perf_share = performing balance / total pool balance (prior period).
        # Non-advancing periods: servicer collects only the performing share.
        with np.errstate(divide="ignore", invalid="ignore"):
            total_bal = np.zeros(n)
            total_bal[1:] = pool.perf_bal[:-1] + pool.fcl[:-1]
            perf_share = np.where(
                total_bal > 1e-12,
                np.concatenate([[0.0], pool.perf_bal[:-1]]) / np.maximum(total_bal, 1e-12),
                0.0,
            )
        svc_paid = np.where(
            advancing_periods, pool.svc_billed, pool.svc_billed * perf_share
        )
    svc_shortfall = pool.svc_billed - svc_paid

    # --- Step 2: Trust advance rollforward and reimbursement ---
    # The trust accumulates outstanding advances (principal + interest).
    # When a defaulted loan liquidates (prin_recov > 0), the recovery
    # reimburses outstanding advances: principal advances first, then
    # interest advances from any excess.
    adv_reimbursed_prin = np.zeros(n)
    adv_reimbursed_int = np.zeros(n)
    trust_adv_prin_out = np.zeros(n)
    trust_adv_int_out = np.zeros(n)

    for i in range(n):
        # Accumulate outstanding advances (cumulative, carried forward)
        trust_adv_prin_out[i] = (
            (trust_adv_prin_out[i - 1] if i > 0 else 0.0) + pool.adv_prin[i]
        )
        trust_adv_int_out[i] = (
            (trust_adv_int_out[i - 1] if i > 0 else 0.0) + pool.adv_int[i]
        )
        # Reimburse from liquidation proceeds: principal advances first
        if pool.prin_recov[i] > 1e-12:
            adv_reimbursed_prin[i] = min(pool.prin_recov[i], trust_adv_prin_out[i])
            trust_adv_prin_out[i] -= adv_reimbursed_prin[i]
            excess = pool.prin_recov[i] - adv_reimbursed_prin[i]
            adv_reimbursed_int[i] = min(excess, trust_adv_int_out[i])
            trust_adv_int_out[i] -= adv_reimbursed_int[i]

    # --- Step 3: Cross-collateralization (FULL mode) ---
    # In FULL mode, excess recovery from one loan (beyond its own advance
    # reimbursement) can offset unreimbursed advances from other loans.
    # The cap limits how much excess is available for cross-collat.
    #
    # The shortfall available for cross-collat at period i is:
    #   trust_adv_*_out[i] - total_xc_*_applied_so_far
    # where total_xc_*_applied_so_far is a running scalar accumulated over
    # all prior periods.  This avoids the O(n²) slice-subtract approach
    # (cumulative_shortfall[i:] -= xc) and reduces Step 3 to O(n).
    if cross_collateral_mode == CrossCollateralMode.FULL:
        excess_recovery = np.maximum(
            pool.prin_recov - adv_reimbursed_prin - adv_reimbursed_int, 0.0
        )
        cap = max(0.0, min(1.0, cross_collateral_cap))
        total_xc_prin = 0.0
        total_xc_int  = 0.0
        for i in range(n):
            if excess_recovery[i] > 1e-12:
                # Remaining shortfall = original outstanding minus all prior xc applied
                avail_prin = max(0.0, trust_adv_prin_out[i] - total_xc_prin) * cap
                xc_prin = min(excess_recovery[i], avail_prin)
                adv_reimbursed_prin[i] += xc_prin
                total_xc_prin += xc_prin
                remaining = excess_recovery[i] - xc_prin
                if remaining > 1e-12:
                    avail_int = max(0.0, trust_adv_int_out[i] - total_xc_int) * cap
                    xc_int = min(remaining, avail_int)
                    adv_reimbursed_int[i] += xc_int
                    total_xc_int += xc_int

    # Trust-level unrecoverable: advances that will never be reimbursed after
    # all reimbursement sources (including cross-collateralization) are exhausted.
    # This is recomputed from scratch here rather than summing the constituent
    # adv_unrecoverable FLOW fields, because cross-collateralization changes the
    # answer: under FULL mode, excess recovery from strong loans offsets the
    # shortfalls of weak loans, reducing the trust-level figure below the sum of
    # loan-level estimates.  pool.adv_unrecoverable (the summed FLOW field) is a
    # pre-cross-collat diagnostic; THIS value is the definitive trust loss.
    # Ref: BMA SF-17 — severity includes all servicer advance costs.
    adv_unrecoverable = np.maximum(
        pool.adv_prin + pool.adv_int - adv_reimbursed_prin - adv_reimbursed_int,
        0.0,
    )

    # --- Step 4: Pass-through computation ---
    # Investor principal recovery = liquidation proceeds minus advance reimbursement
    investor_prin_recov = np.maximum(
        pool.prin_recov - adv_reimbursed_prin - adv_reimbursed_int, 0.0
    )
    # Pass-through principal: amortization + voluntary prepay + advances + investor recovery
    pt_principal = pool.act_am + pool.vol_prepay + pool.adv_prin + investor_prin_recov
    # Pass-through interest: actual interest + interest advances - servicing
    pt_interest = pool.act_int + pool.adv_int - svc_paid
    pt_cashflow = pt_principal + pt_interest
    gross_cashflow = pt_cashflow + svc_paid
    # Servicer net cashflow: fees collected minus advances made plus reimbursements
    svc_cashflow = (
        svc_paid - pool.adv_prin - pool.adv_int
        + adv_reimbursed_prin + adv_reimbursed_int
    )

    return {
        "svc_paid": svc_paid,
        "svc_shortfall": svc_shortfall,
        "adv_reimbursed_prin": adv_reimbursed_prin,
        "adv_reimbursed_int": adv_reimbursed_int,
        "adv_unrecoverable": adv_unrecoverable,
        "pt_principal": pt_principal,
        "pt_interest": pt_interest,
        "pt_cashflow": pt_cashflow,
        "gross_cashflow": gross_cashflow,
        "svc_cashflow": svc_cashflow,
    }


# ---------------------------------------------------------------------------
# PortfolioCashflow (Parts F, G, H, I, J)
# ---------------------------------------------------------------------------


class PortfolioCashflow:
    """Mutable portfolio of leaf cashflows with lazy aggregation and trust waterfall.

    PortfolioCashflow holds a list of leaf cashflows (_pending) and lazily
    computes aggregated pool-level results plus trust waterfall outputs when
    accessed via properties (.scheduled, .pool, .pt_principal, etc.).

    Key design features:
      - _pending:    List of leaf constituents (raw references, never copied).
      - _committed:  Dict caching computed results ('_scheduled', '_pool', '_waterfall').
                     Cleared by _invalidate() on any mutation.
      - _history:    Append-only list of PortfolioEvent for version tracking / rewind.
                     Retention is bounded by max_history_events (default 5,000).
                     Old events are dropped from the front when cap is exceeded.
      - Mode locking: PortfolioMode (SCHEDULED_ONLY, ACTUAL_ONLY, PAIRED) with
                      LCD coercion when combining different modes.
      - Cross-collat: CrossCollateralMode (NONE, FULL, GROUP) with configurable cap.

    Ref: BMA SF-17 (servicing / advance); SF-18, SF-19 (C.3 variables / formulas).
    """

    def __init__(
        self,
        constituents: list[BMAScheduledCashflow | BMAActualCashflow | CashFlowPair],
        mode: PortfolioMode | str = PortfolioMode.SCHEDULED_ONLY,
        cross_collateral_mode: CrossCollateralMode | None = None,
        cross_collateral_cap: float = 1.0,
        persistent_history: bool = False,
        history_path: str | Path | None = None,
        max_history_events: int | None = 5000,
    ):
        self._pending: list[BMAScheduledCashflow | BMAActualCashflow | CashFlowPair] = []

        # --- Resolve mode ---
        if isinstance(mode, PortfolioMode):
            self._mode = mode
        elif isinstance(mode, str):
            try:
                self._mode = PortfolioMode[mode.upper().replace(" ", "_")]
            except KeyError:
                raise ValueError(
                    f"Invalid mode string {mode!r}. "
                    f"Expected one of: {', '.join(m.name for m in PortfolioMode)}"
                )
        else:
            raise TypeError(f"mode must be PortfolioMode or str, got {type(mode)}")

        self._cross_collateral_mode = cross_collateral_mode or CrossCollateralMode.NONE
        self._cross_collateral_cap = max(0.0, min(1.0, cross_collateral_cap))
        self._persistent_history = persistent_history
        self._history_path = Path(history_path) if history_path else None
        if max_history_events is not None and (not isinstance(max_history_events, int) or max_history_events <= 0):
            raise ValueError("max_history_events must be a positive int or None")
        self._max_history_events = max_history_events
        self._committed: dict[str, object] = {}
        self._history: list[PortfolioEvent] = []
        self._history_dropped_events = 0
        self._version = 0
        self._n_constituents = 0
        self._flushed = False  # True after flush() has released _pending
        self._parquet_writer: Any = None   # pq.ParquetWriter, opened lazily on first flush
        self._cf_meta_store: dict[str, dict] = {}  # accumulated scalar META for footer
        self._persistent_writer_opened = False

        # Ingest initial constituents (with mode extraction and history logging)
        for c in constituents:
            extracted = self._extract_for_mode(c)
            self._pending.extend(extracted)
            self._n_constituents += len(extracted)
            for item in extracted:
                self._version += 1
                self._append_history_event(PortfolioEvent(
                    version=self._version,
                    timestamp=time.perf_counter(),
                    op=PortfolioOp.ADD,
                    cf_id=getattr(item, "cf_id", None),
                    loan_id=getattr(item, "loan_id", None),
                    n_constituents=self._n_constituents,
                    meta={"original_balance": getattr(item, "original_balance", 0.0),
                          "original_term": getattr(item, "original_term", 0)},
                ))

    def _invalidate(self) -> None:
        """Clear all cached aggregation results, forcing recomputation on next access."""
        self._committed.clear()

    def _append_history_event(self, evt: PortfolioEvent) -> None:
        """Append one event and enforce bounded history retention."""
        self._history.append(evt)
        if self._max_history_events is None:
            return
        excess = len(self._history) - self._max_history_events
        if excess > 0:
            del self._history[:excess]
            self._history_dropped_events += excess
            logger.info(
                "Portfolio history trimmed: dropped=%d total_dropped=%d retained=%d max_history_events=%d",
                excess,
                self._history_dropped_events,
                len(self._history),
                self._max_history_events,
            )

    def _unflushed_for_mutation(self) -> None:
        """If flushed, move the committed aggregate back to _pending as a super-constituent.

        Called before any mutation (add, subtract) when the portfolio has been
        flushed.  The committed aggregate is a valid cashflow that can be used
        as a single "super-constituent" in the next aggregation.
        """
        if self._flushed and self._committed:
            if "_pool" in self._committed:
                self._pending.append(self._committed["_pool"])
            elif "_scheduled" in self._committed:
                self._pending.append(self._committed["_scheduled"])
            self._committed.clear()
            self._flushed = False

    def flush(self) -> None:
        """Force aggregation, then release individual constituent refs.

        After flush:
          - _committed holds the aggregated result (small: ~87KB for 361 periods)
          - _pending is empty (individual cashflow objects can be GC'd)
          - _flushed is True

        Per-group aggregates are also computed at flush time when any constituent
        carries a non-None ``group_id``.  This is necessary because per-loan
        ``group_id`` metadata only exists on individual constituents, so once
        ``_pending`` is cleared the per-group decomposition cannot be reconstructed
        from the whole-portfolio aggregate alone.  Callers that consume per-group
        results post-flush (e.g. the orchestrator's grouped-portfolio artifact
        emission) can therefore call :meth:`aggregate_actual_by_group` and
        :meth:`aggregate_scheduled_by_group` after ``flush()`` returns without
        re-running the engine.

        If persistent_history=True, appends all constituents currently in _pending
        as a new Parquet row group (O(1) per flush — no re-reads of prior data).
        Only individual constituents are written — never the aggregate.

        When using persistent_history=True the portfolio MUST be used as a context
        manager (or close() called explicitly) to finalize the Parquet file footer
        with scalar metadata and safely close the writer.

        If the portfolio is mutated after flush (e.g. portfolio += new_cf),
        the committed aggregate is moved back to _pending as a single
        super-constituent before adding the new item.
        """
        # Trigger whole-portfolio aggregation
        if self._mode in (PortfolioMode.SCHEDULED_ONLY, PortfolioMode.PAIRED):
            _ = self.scheduled
        if self._mode in (PortfolioMode.ACTUAL_ONLY, PortfolioMode.PAIRED):
            _ = self.pool

        # Trigger per-group aggregation BEFORE clearing _pending.
        # We only pay the partition cost when at least one constituent carries
        # an explicit group_id — pure single-pool runs (every constituent's
        # group_id is None) skip per-group work entirely.
        if self._has_grouped_constituents():
            if self._mode in (PortfolioMode.SCHEDULED_ONLY, PortfolioMode.PAIRED):
                _ = self.aggregate_scheduled_by_group()
            if self._mode in (PortfolioMode.ACTUAL_ONLY, PortfolioMode.PAIRED):
                _ = self.aggregate_actual_by_group()

        # Persist constituents to Parquet before releasing refs
        if self._persistent_history and self._history_path and self._pending:
            self._write_constituents_to_parquet()

        self._pending.clear()
        self._flushed = True

    def _has_grouped_constituents(self) -> bool:
        """Return True if any pending constituent carries a non-None group_id.

        Used by :meth:`flush` to decide whether per-group aggregation is worth
        triggering.  Walks ``_pending`` and short-circuits on the first tagged
        constituent, so the cost is O(1) for ungrouped tapes and O(k) for
        grouped tapes (where k is the index of the first tagged constituent).

        For PAIRED-mode constituents the ``group_id`` is read off the
        underlying ``.actual`` (or ``.scheduled``) — every CashFlowPair carries
        the same ``group_id`` on both halves because both halves derive from
        the same source ``Loan``.
        """
        for c in self._pending:
            if isinstance(c, CashFlowPair):
                if c.actual.group_id is not None or c.scheduled.group_id is not None:
                    return True
            elif getattr(c, "group_id", None) is not None:
                return True
        return False

    def _write_constituents_to_parquet(self) -> None:
        """Append current _pending constituents as one row group to the Parquet file.

        Opens a pq.ParquetWriter on the first call (lazy init); subsequent flushes
        reuse the same writer.  Each flush writes exactly one row group — no re-reads
        of previously written data, so cost is O(batch_size) per flush.

        Scalar META fields (loan_id, original_balance, etc.) are accumulated in
        _cf_meta_store and written to the Parquet file footer by close().

        Note: each PortfolioCashflow instance creates a fresh output file.  If the
        path already exists from a prior run it will be overwritten on the first flush.
        To accumulate across sessions, use a unique path per run.
        """
        import pyarrow as pa
        import pyarrow.parquet as pq
        from bma_standard_formulas.engine.cashflow_persistence import (
            _cf_to_arrow_table,
            _encode_meta,
            ACTUAL_SCHEMA,
            SCHEDULED_SCHEMA,
        )

        tables = []
        for cf in self._pending:
            cf_id = getattr(cf, "cf_id", "")
            if not cf_id:
                # Skip aggregate super-constituents produced by _reconstruct_stocks_and_ratios
                continue
            if isinstance(cf, BMAActualCashflow):
                schema, cf_type = ACTUAL_SCHEMA, "actual"
            elif isinstance(cf, BMAScheduledCashflow):
                schema, cf_type = SCHEDULED_SCHEMA, "scheduled"
            else:
                continue
            tables.append(_cf_to_arrow_table(cf, schema, cf_type))
            self._cf_meta_store[cf_id] = _encode_meta(cf)

        if not tables:
            return

        batch = pa.concat_tables(tables)

        if self._parquet_writer is None:
            self._parquet_writer = pq.ParquetWriter(
                self._history_path,
                batch.schema,
                compression="snappy",
            )
            self._persistent_writer_opened = True

        self._parquet_writer.write_table(batch)

    # -------------------------------------------------------------------------
    # Context manager + explicit close (required for persistent_history=True)
    # -------------------------------------------------------------------------

    def __enter__(self) -> "PortfolioCashflow":
        """Enter the context manager, returning self.

        Example::

            with PortfolioCashflow(
                [], mode="actual_only",
                persistent_history=True, history_path="out.parquet",
            ) as portfolio:
                for cf in cashflows:
                    portfolio += cf
                    if len(portfolio._pending) >= 500:
                        portfolio.flush()
            # writer closed, file footer finalized — file is valid
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit the context manager, closing the writer regardless of exception."""
        self.close()

    def close(self) -> None:
        """Close the persistent-history ParquetWriter and finalize the Parquet file.

        Writes the accumulated CF scalar metadata (loan_id, original_balance, etc.)
        to the Parquet file footer, then closes the writer.  Safe to call multiple
        times — subsequent calls are no-ops.

        This method is called automatically by __exit__ when using the portfolio as
        a context manager.  If not using a context manager, it MUST be called
        explicitly when persistent_history=True to ensure the output file is valid.
        """
        if self._parquet_writer is None:
            return
        try:
            self._parquet_writer.close()
        finally:
            self._parquet_writer = None

        # One-time footer update: stamp the accumulated scalar META into the file.
        # This is the only full file read+rewrite in the lifecycle — each flush()
        # was a pure O(1) row-group append; only close() does I/O proportional to
        # total output size.
        if self._history_path and self._history_path.exists() and self._cf_meta_store:
            self._finalize_parquet_metadata()

    def __del__(self) -> None:
        """Best-effort safety net for unclosed persistent-history writers."""
        if not getattr(self, "_persistent_history", False):
            return
        if getattr(self, "_parquet_writer", None) is None:
            return
        if not getattr(self, "_persistent_writer_opened", False):
            return
        warnings.warn(
            "PortfolioCashflow with persistent_history=True was not closed; "
            "closing automatically in __del__. Use a context manager or call close().",
            ResourceWarning,
            stacklevel=2,
        )
        try:
            self.close()
        except Exception:
            # Never raise from __del__; best-effort cleanup only.
            pass

    def _finalize_parquet_metadata(self) -> None:
        """Rewrite the Parquet file footer with accumulated CF scalar metadata.

        Reads the full file once to attach the cf_meta JSON (scalar META fields
        for all persisted CFs) to the Parquet file-level metadata, then writes it
        back.  Called exactly once by close().
        """
        import pyarrow.parquet as pq

        table = pq.read_table(self._history_path)
        updated = table.replace_schema_metadata(
            {b"cf_meta": json.dumps(self._cf_meta_store).encode()}
        )
        pq.write_table(updated, self._history_path)

    @staticmethod
    def load_rewind_components(path: str | Path) -> dict[str, BMAActualCashflow | BMAScheduledCashflow]:
        """Load persisted cashflows for rewind, keyed by cf_id.

        Uses the schema-aware persistence reader to preserve scalar metadata
        (loan/date/term fields) and array data exactly.
        """
        from bma_standard_formulas.engine.cashflow_persistence import read_cashflows

        result: dict[str, BMAActualCashflow | BMAScheduledCashflow] = {}
        for cf in read_cashflows(path):
            cid = str(cf.cf_id)
            if cid in result:
                raise ValueError(f"Duplicate cf_id {cid!r} found in persisted history: {path}")
            result[cid] = cf
        return result

    @classmethod
    def empty(cls, mode: PortfolioMode = PortfolioMode.SCHEDULED_ONLY) -> "PortfolioCashflow":
        """Return an empty portfolio (additive identity for sum/reduce patterns).

        Usage: ``portfolio = sum(cashflows, start=PortfolioCashflow.empty())``

        Args:
            mode:  The portfolio mode (default SCHEDULED_ONLY).

        Returns:
            An empty PortfolioCashflow with zero constituents.
        """
        return cls([], mode=mode)

    # --- Read-only properties ---

    @property
    def n_constituents(self) -> int:
        """Number of leaf cashflows currently in the portfolio."""
        return self._n_constituents

    @property
    def mode(self) -> PortfolioMode:
        """Current portfolio mode (may have been coerced by LCD on combination)."""
        return self._mode

    @property
    def history_dropped_events(self) -> int:
        """Cumulative count of event-log entries dropped by bounded retention."""
        return self._history_dropped_events

    # --- Lazy aggregation ---

    @property
    def scheduled(self) -> BMAScheduledCashflow:
        """Aggregated scheduled cashflow (lazy — computed on first access, then cached).

        Available in SCHEDULED_ONLY and PAIRED modes.  In PAIRED mode, extracts
        the .scheduled component from each CashFlowPair constituent.
        """
        if "_scheduled" in self._committed:
            return self._committed["_scheduled"]
        cfs = self._extract_scheduled_constituents()
        if not cfs:
            raise ValueError("Portfolio has no scheduled cashflows to aggregate")
        result = _aggregate_scheduled(cfs)
        self._committed["_scheduled"] = result
        return result

    @property
    def pool(self) -> BMAActualCashflow:
        """Aggregated actual cashflow (lazy — computed on first access, then cached).

        Available in ACTUAL_ONLY and PAIRED modes.  In PAIRED mode, extracts
        the .actual component from each CashFlowPair constituent.
        """
        if "_pool" in self._committed:
            return self._committed["_pool"]
        cfs = self._extract_actual_constituents()
        if not cfs:
            raise ValueError("Portfolio has no actual cashflows to aggregate")
        result = _aggregate_actual(cfs)
        self._committed["_pool"] = result
        return result

    # --- Per-group lazy aggregation ---
    #
    # Per-loan cashflows carry `group_id` from their source Loan.  When the
    # caller wants per-group views (multi-group RMBS deals, segment-level
    # analytics), these methods partition the constituents by `group_id` and
    # run the existing whole-portfolio aggregator against each partition.
    #
    # IMPORTANT: per-group aggregation MUST run before flush() clears _pending,
    # because the partition step requires walking every constituent.  flush()
    # opportunistically populates the cache (see _trigger_group_aggregation_if_needed)
    # so callers can still get per-group results post-flush.

    def aggregate_actual_by_group(self) -> dict[str, BMAActualCashflow]:
        """Per-group aggregated actual cashflows (lazy — computed on first access, cached).

        Walks every constituent, partitions them by `group_id`, and runs the
        whole-portfolio actual aggregator (:func:`_aggregate_actual`) against
        each partition.  The result is the dollar-summable decomposition of
        the whole pool::

            sum(group_aggregate.flow_field
                for group_aggregate in aggregate_actual_by_group().values())
            == self.pool.flow_field   for any FLOW field

        Constituents with `group_id == None` go into the special bucket
        ``"_ungrouped"`` so callers can detect partially-tagged tapes (mixed
        explicit-group and ungrouped constituents).

        Available in ACTUAL_ONLY and PAIRED modes.  In PAIRED mode, the
        ``.actual`` component of each CashFlowPair is used (mirroring the
        ``pool`` property).

        Returns:
            dict[str, BMAActualCashflow]: One aggregate per group, keyed by
            stringified ``group_id``.  Returns ``{}`` if the portfolio has no
            actual constituents.

        Caching: result is stored in ``_committed["_pool_by_group"]`` and
        invalidated by any portfolio mutation (via :meth:`_invalidate`).

        Lifecycle: if called on a flushed portfolio that did NOT have
        per-group aggregation triggered before flush, this method falls back
        to the cached aggregate result if available — but with only a single
        ``"_ungrouped"`` bucket since per-loan group_id is no longer
        accessible.  To guarantee per-group results post-flush, callers
        should ensure :meth:`flush` runs after constituents with non-None
        group_ids are added (the flush implementation auto-triggers
        per-group aggregation in that case).
        """
        if "_pool_by_group" in self._committed:
            return self._committed["_pool_by_group"]
        cfs = self._extract_actual_constituents()
        if not cfs:
            return {}
        result = _aggregate_actual_by_group(cfs)
        self._committed["_pool_by_group"] = result
        return result

    def aggregate_scheduled_by_group(self) -> dict[str, BMAScheduledCashflow]:
        """Per-group aggregated scheduled cashflows (lazy — computed on first access, cached).

        Same partition-and-aggregate pattern as :meth:`aggregate_actual_by_group`,
        applied to scheduled cashflows.  Available in SCHEDULED_ONLY and PAIRED
        modes.  In PAIRED mode, the ``.scheduled`` component of each
        CashFlowPair is used.

        Returns:
            dict[str, BMAScheduledCashflow]: One aggregate per group, keyed by
            stringified ``group_id``.  Returns ``{}`` if the portfolio has no
            scheduled constituents.

        Caching: result is stored in ``_committed["_scheduled_by_group"]``.
        """
        if "_scheduled_by_group" in self._committed:
            return self._committed["_scheduled_by_group"]
        cfs = self._extract_scheduled_constituents()
        if not cfs:
            return {}
        result = _aggregate_scheduled_by_group(cfs)
        self._committed["_scheduled_by_group"] = result
        return result

    # --- Constituent extraction helpers ---
    #
    # Both .pool / .scheduled and .aggregate_*_by_group need to walk _pending
    # and unwrap CashFlowPair constituents into BMAActualCashflow /
    # BMAScheduledCashflow.  Centralized here so the unwrap logic stays in
    # one place.

    def _extract_actual_constituents(self) -> list[BMAActualCashflow]:
        """Walk _pending and return the BMAActualCashflow leaves.

        For PAIRED mode constituents (CashFlowPair) returns the ``.actual``
        component; for ACTUAL_ONLY constituents returns them directly.
        Raises ``TypeError`` for any other constituent type encountered.
        """
        out: list[BMAActualCashflow] = []
        for c in self._pending:
            if isinstance(c, CashFlowPair):
                out.append(c.actual)
            elif isinstance(c, BMAActualCashflow):
                out.append(c)
            else:
                raise TypeError(
                    f"Cannot extract actual cashflow from {type(c).__name__}"
                )
        return out

    def _extract_scheduled_constituents(self) -> list[BMAScheduledCashflow]:
        """Walk _pending and return the BMAScheduledCashflow leaves.

        For PAIRED mode constituents (CashFlowPair) returns the ``.scheduled``
        component; for SCHEDULED_ONLY constituents returns them directly.
        Raises ``TypeError`` for any other constituent type encountered.
        """
        out: list[BMAScheduledCashflow] = []
        for c in self._pending:
            if isinstance(c, CashFlowPair):
                out.append(c.scheduled)
            elif isinstance(c, BMAScheduledCashflow):
                out.append(c)
            else:
                raise TypeError(
                    f"Cannot extract scheduled cashflow from {type(c).__name__}"
                )
        return out

    # --- Public per-loan constituent accessors (Phase 1d.1) ---
    #
    # These expose per-loan cashflow leaves so downstream consumers (deal
    # runtime ExecutionContext, structuring tools, analytics) can reference
    # individual loan trajectories rather than only the aggregated pool.
    # They wrap the private _extract_*_constituents helpers and return new
    # lists so caller mutation cannot corrupt internal state.
    #
    # Lifecycle: these read from _pending and require constituents to be
    # present (i.e., the portfolio has not been flushed). After flush(),
    # _pending is cleared and these methods return [].

    def actual_constituents(self) -> list[BMAActualCashflow]:
        """Per-loan ``BMAActualCashflow`` leaves (PAIRED extracts .actual).

        Returns a new list, not a view; caller mutation does not affect
        internal state. Empty if the portfolio has been flushed or
        contains no actual cashflows.

        Available in ``ACTUAL_ONLY`` and ``PAIRED`` modes. Use
        ``actual_constituents_by_group`` for the partitioned view.
        """
        if not self._pending:
            return []
        return list(self._extract_actual_constituents())

    def scheduled_constituents(self) -> list[BMAScheduledCashflow]:
        """Per-loan ``BMAScheduledCashflow`` leaves (PAIRED extracts .scheduled).

        Returns a new list, not a view; caller mutation does not affect
        internal state. Empty if the portfolio has been flushed or
        contains no scheduled cashflows.

        Available in ``SCHEDULED_ONLY`` and ``PAIRED`` modes.
        """
        if not self._pending:
            return []
        return list(self._extract_scheduled_constituents())

    def actual_constituents_by_group(self) -> dict[str, list[BMAActualCashflow]]:
        """Per-loan actual cashflows partitioned by ``group_id``.

        Walks every constituent and groups by ``group_id`` *without*
        aggregating — each group's value is the list of original per-loan
        ``BMAActualCashflow`` objects, not a summed aggregate.

        Constituents with ``group_id == None`` go into the special bucket
        ``"_ungrouped"`` so callers can detect partially-tagged tapes
        (mirrors the convention used by ``aggregate_actual_by_group``).
        Numeric ``group_id`` values are stringified for stable dict keys
        (matches ``_partition_by_group_id`` semantics).

        Returns ``{}`` if the portfolio has been flushed or contains no
        actual cashflows. Result is computed fresh on each call (no
        caching) since the partition is cheap relative to aggregation.

        Use ``aggregate_actual_by_group`` when you want per-group
        aggregated cashflows; use this when you need the underlying
        per-loan trajectories per group.
        """
        return _partition_by_group_id(self.actual_constituents())

    def scheduled_constituents_by_group(self) -> dict[str, list[BMAScheduledCashflow]]:
        """Per-loan scheduled cashflows partitioned by ``group_id``.

        Mirror of ``actual_constituents_by_group`` for the scheduled
        cashflow stream. See that method's docstring for semantics.
        """
        return _partition_by_group_id(self.scheduled_constituents())

    # --- Mode extraction (Part G) ---

    def _extract_for_mode(
        self,
        other: BMAScheduledCashflow | BMAActualCashflow | CashFlowPair | PortfolioCashflow,
    ) -> list[BMAScheduledCashflow | BMAActualCashflow | CashFlowPair]:
        """Extract constituent(s) compatible with the current portfolio mode.

        If the portfolio is SCHEDULED_ONLY and the operand is a CashFlowPair,
        only the .scheduled component is extracted (LCD coercion).  Similarly,
        ACTUAL_ONLY extracts .actual from pairs.  PAIRED mode passes through.

        Raises PortfolioModeError if the operand is incompatible (e.g. adding
        a BMAActualCashflow to a SCHEDULED_ONLY portfolio).
        """
        items = other._pending if isinstance(other, PortfolioCashflow) else [other]
        result: list = []
        for c in items:
            if self._mode == PortfolioMode.SCHEDULED_ONLY:
                if isinstance(c, CashFlowPair):
                    result.append(c.scheduled)
                elif isinstance(c, BMAScheduledCashflow):
                    result.append(c)
                else:
                    raise PortfolioModeError(
                        f"Cannot add {type(c).__name__} to SCHEDULED_ONLY portfolio"
                    )
            elif self._mode == PortfolioMode.ACTUAL_ONLY:
                if isinstance(c, CashFlowPair):
                    result.append(c.actual)
                elif isinstance(c, BMAActualCashflow):
                    result.append(c)
                else:
                    raise PortfolioModeError(
                        f"Cannot add {type(c).__name__} to ACTUAL_ONLY portfolio"
                    )
            else:  # PAIRED
                result.append(c)
        return result

    # --- Operators (Part F) ---

    def __add__(self, other):
        """Add a constituent or merge another portfolio.

        ``portfolio + cf`` — intentional in-place mutation:
            Mutates self and returns self.  This deliberately deviates from
            Python's usual ``+`` contract to avoid O(n) allocation on every
            constituent addition in a build loop.  ``b = portfolio + cf`` sets
            ``b is portfolio`` — both names refer to the same (now-mutated) object.
            Use ``+=`` for clarity; the behavior is identical.

        ``portfolio + portfolio`` — returns a NEW PortfolioCashflow:
            Neither operand is mutated.  Used to combine two independently
            built portfolios (e.g. results from parallel workers).
        """
        if isinstance(other, PortfolioCashflow):
            # portfolio + portfolio: create a new portfolio without mutating either
            new_mode = _lcd_mode(self._mode, other._mode)
            # Build a temporary with the resolved mode to extract correctly
            new_portfolio = PortfolioCashflow(
                [],
                mode=new_mode,
                cross_collateral_mode=self._cross_collateral_mode,
                cross_collateral_cap=self._cross_collateral_cap,
                max_history_events=self._max_history_events,
            )
            # Transfer constituents from both sides (re-extract under new_mode)
            new_portfolio._pending = list(self._pending) + list(other._pending)
            new_portfolio._n_constituents = len(new_portfolio._pending)
            new_portfolio._version = self._version + other._version
            new_portfolio._history = list(self._history) + list(other._history)
            new_portfolio._history_dropped_events = (
                self._history_dropped_events + other._history_dropped_events
            )
            if new_portfolio._max_history_events is not None:
                excess = len(new_portfolio._history) - new_portfolio._max_history_events
                if excess > 0:
                    del new_portfolio._history[:excess]
                    new_portfolio._history_dropped_events += excess
            return new_portfolio

        # portfolio + cf: mutate self
        self._unflushed_for_mutation()
        new_mode = _lcd_mode(self._mode, type(other))
        if new_mode != self._mode:
            self._mode = new_mode
        extracted = self._extract_for_mode(other)
        self._pending.extend(extracted)
        self._n_constituents += len(extracted)
        self._invalidate()
        for item in extracted:
            self._version += 1
            self._append_history_event(PortfolioEvent(
                version=self._version,
                timestamp=time.perf_counter(),
                op=PortfolioOp.ADD,
                cf_id=getattr(item, "cf_id", None),
                loan_id=getattr(item, "loan_id", None),
                n_constituents=self._n_constituents,
                meta={"original_balance": getattr(item, "original_balance", 0.0),
                      "original_term": getattr(item, "original_term", 0)},
            ))
        return self

    def __iadd__(self, other):
        """In-place add: always mutates self."""
        return self.__add__(other)

    def __sub__(self, other):
        """Remove a constituent or subtract another portfolio's constituents.

        portfolio - cf        -> mutates self (removes by object identity)
        portfolio - portfolio -> returns NEW portfolio with non-shared constituents

        Raises ValueError if the constituent is not found in self._pending.
        """
        if isinstance(other, PortfolioCashflow):
            # portfolio - portfolio: return new (use object identity via id())
            other_ids = {id(c) for c in other._pending}
            remaining = [c for c in self._pending if id(c) not in other_ids]
            new_portfolio = PortfolioCashflow(
                [],
                mode=self._mode,
                cross_collateral_mode=self._cross_collateral_mode,
                cross_collateral_cap=self._cross_collateral_cap,
                max_history_events=self._max_history_events,
            )
            new_portfolio._pending = remaining
            new_portfolio._n_constituents = len(remaining)
            return new_portfolio

        # portfolio - cf: mutate self (remove by identity)
        self._unflushed_for_mutation()
        extracted = self._extract_for_mode(other)
        removed = []
        for x in extracted:
            for idx, pending_item in enumerate(self._pending):
                if pending_item is x:
                    self._pending.pop(idx)
                    removed.append(x)
                    break
            else:
                raise ValueError(
                    f"Constituent {type(x).__name__} (loan_id={getattr(x, 'loan_id', '?')}) "
                    f"not found in portfolio"
                )
        self._n_constituents -= len(removed)
        self._invalidate()
        for item in removed:
            self._version += 1
            self._append_history_event(PortfolioEvent(
                version=self._version,
                timestamp=time.perf_counter(),
                op=PortfolioOp.SUBTRACT,
                cf_id=getattr(item, "cf_id", None),
                loan_id=getattr(item, "loan_id", None),
                n_constituents=self._n_constituents,
            ))
        return self

    def __isub__(self, other):
        """In-place subtract: always mutates self."""
        return self.__sub__(other)

    def __mul__(self, scalar: float):
        """Scale all constituents by scalar, returning a NEW portfolio."""
        return PortfolioCashflow(
            [c.scale_by(scalar) for c in self._pending],
            mode=self._mode,
            cross_collateral_mode=self._cross_collateral_mode,
            cross_collateral_cap=self._cross_collateral_cap,
        )

    def __rmul__(self, scalar: float):
        """Support scalar * portfolio (commutative with __mul__)."""
        return self.__mul__(scalar)

    def __imul__(self, scalar: float):
        """Scale all constituents in-place, mutating self."""
        self._pending[:] = [c.scale_by(scalar) for c in self._pending]
        self._invalidate()
        self._version += 1
        self._append_history_event(PortfolioEvent(
            version=self._version,
            timestamp=time.perf_counter(),
            op=PortfolioOp.SCALE,
            scalar=scalar,
            n_constituents=self._n_constituents,
        ))
        return self

    def __truediv__(self, scalar: float):
        """Divide all constituents by scalar, returning a NEW portfolio."""
        if scalar == 0:
            raise ValueError("division by zero")
        return self * (1.0 / scalar)

    def __itruediv__(self, scalar: float):
        """Divide all constituents in-place."""
        if scalar == 0:
            raise ValueError("division by zero")
        return self.__imul__(1.0 / scalar)

    # --- Version history (Part J) ---

    def rewind(self, version: int, store: dict[str, object]) -> "PortfolioCashflow":
        """Reconstruct the portfolio at a prior version by replaying history.

        History events store cf_id identifiers (not object references).  The
        caller must provide an external store mapping cf_id -> cashflow object
        so that rewind can look up the actual data for each ADD event.

        Args:
            version:  Target version number (inclusive).  Events with version >
                      target are not replayed.
            store:    Dict mapping cf_id -> cashflow object.  Must contain all
                      cashflow objects referenced by ADD events up to the target
                      version.  Raises KeyError if a cf_id is missing.

        Returns:
            A new PortfolioCashflow representing the state at the target version.

        Raises:
            ValueError: If version predates retained history (bounded retention
                dropped older events).
        """
        current = PortfolioCashflow(
            [],
            mode=self._mode,
            cross_collateral_mode=self._cross_collateral_mode,
            cross_collateral_cap=self._cross_collateral_cap,
            max_history_events=self._max_history_events,
        )
        if self._history:
            earliest_version = self._history[0].version
            if version < earliest_version:
                raise ValueError(
                    f"Cannot rewind to version {version}: earliest retained history is version "
                    f"{earliest_version}. {self._history_dropped_events} event(s) were dropped "
                    "from the front of history."
                )
        for evt in self._history:
            if evt.version > version:
                break
            if evt.op == PortfolioOp.ADD and evt.cf_id is not None:
                cf = store[evt.cf_id]
                current._pending.append(cf)
                current._n_constituents += 1
                current._invalidate()
            elif evt.op == PortfolioOp.SUBTRACT and evt.cf_id is not None:
                cf = store[evt.cf_id]
                for idx, item in enumerate(current._pending):
                    if item is cf:
                        current._pending.pop(idx)
                        break
                current._n_constituents -= 1
                current._invalidate()
            elif evt.op == PortfolioOp.SCALE and evt.scalar is not None:
                current *= evt.scalar
        current._version = version
        current._history = [e for e in self._history if e.version <= version]
        return current

    # --- Waterfall outputs (cached, from .pool) ---

    def _get_waterfall(self) -> dict:
        """Compute and cache trust waterfall results from the aggregated pool."""
        if "_waterfall" in self._committed:
            return self._committed["_waterfall"]
        wf = _compute_waterfall(
            self.pool,
            cross_collateral_mode=self._cross_collateral_mode,
            cross_collateral_cap=self._cross_collateral_cap,
        )
        self._committed["_waterfall"] = wf
        return wf

    @property
    def _waterfall(self) -> dict:
        return self._get_waterfall()

    @property
    def svc_paid(self) -> np.ndarray:
        """Servicing fees actually collected by the servicer each period."""
        return self._waterfall["svc_paid"]

    @property
    def svc_shortfall(self) -> np.ndarray:
        """Servicing fees billed but not collected (svc_billed - svc_paid)."""
        return self._waterfall["svc_shortfall"]

    @property
    def adv_reimbursed_prin(self) -> np.ndarray:
        """Trust-level principal advances reimbursed from liquidation proceeds."""
        return self._waterfall["adv_reimbursed_prin"]

    @property
    def adv_reimbursed_int(self) -> np.ndarray:
        """Trust-level interest advances reimbursed from liquidation proceeds."""
        return self._waterfall["adv_reimbursed_int"]

    @property
    def adv_unrecoverable(self) -> np.ndarray:
        """Trust-level advances that will never be reimbursed (permanent trust loss).

        Recomputed in _compute_waterfall after all reimbursement sources —
        including cross-collateralization — are exhausted:
            max(adv_prin + adv_int - adv_reimbursed_prin - adv_reimbursed_int, 0)

        NOTE — this differs from ``portfolio.pool.adv_unrecoverable`` (the FLOW
        field summed from constituent loans), which represents the gross
        unrecoverables if each loan stood alone (pre-cross-collat).  Under
        CrossCollateralMode.FULL the two values diverge: excess recoveries from
        strong loans reduce the trust-level figure below the constituent sum.
        Use THIS property for loss/severity analysis; use ``pool.adv_unrecoverable``
        as a diagnostic for the pre-cross-collat exposure.
        """
        return self._waterfall["adv_unrecoverable"]

    @property
    def pt_principal(self) -> np.ndarray:
        """Pass-through principal to investors (amort + prepay + advances + recovery)."""
        return self._waterfall["pt_principal"]

    @property
    def pt_interest(self) -> np.ndarray:
        """Pass-through interest to investors (actual interest + advances - servicing)."""
        return self._waterfall["pt_interest"]

    @property
    def pt_cashflow(self) -> np.ndarray:
        """Total pass-through cashflow to investors (principal + interest)."""
        return self._waterfall["pt_cashflow"]

    @property
    def gross_cashflow(self) -> np.ndarray:
        """Gross pool cashflow before servicer/investor split."""
        return self._waterfall["gross_cashflow"]

    @property
    def svc_cashflow(self) -> np.ndarray:
        """Servicer net cashflow (fees collected - advances + reimbursements)."""
        return self._waterfall["svc_cashflow"]

    # --- Display ---

    def to_dataframe(self) -> pd.DataFrame:
        """Convert the aggregated cashflow(s) to a pandas DataFrame.

        The returned DataFrame depends on the portfolio mode:

        SCHEDULED_ONLY:
            One row per period from the aggregated scheduled cashflow
            (balance factors, payments, interest, principal).

        ACTUAL_ONLY:
            One row per period from the aggregated actual cashflow (pool
            variables: perf_bal, new_def, vol_prepay, etc.) joined with
            the trust waterfall outputs (pt_principal, pt_interest, etc.).

        PAIRED:
            Pool view joined with waterfall, same as ACTUAL_ONLY.  To get
            the scheduled view in PAIRED mode call portfolio.scheduled.to_dataframe()
            directly.

        Returns:
            pandas DataFrame indexed 0..remaining_term.

        Raises:
            ValueError: If the portfolio is empty (no constituents added yet).
        """
        if self._mode == PortfolioMode.SCHEDULED_ONLY:
            return self.scheduled.to_dataframe()
        # ACTUAL_ONLY or PAIRED: pool + waterfall side-by-side.
        pool_df = self.pool.to_dataframe()
        waterfall_df = pd.DataFrame(self._get_waterfall())
        return pd.concat([pool_df, waterfall_df], axis=1)

    def __repr__(self) -> str:
        if self._n_constituents == 0:
            return (
                f"PortfolioCashflow(mode={self._mode.name}, "
                f"0 constituents)"
            )
        try:
            return repr(self.to_dataframe())
        except Exception:
            return (
                f"PortfolioCashflow(mode={self._mode.name}, "
                f"{self._n_constituents} constituents)"
            )


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def apply_waterfall(
    pool: BMAActualCashflow,
    cross_collateralize: bool = False,
    cross_collateral_mode: CrossCollateralMode | None = None,
    cross_collateral_cap: float = 1.0,
) -> PortfolioCashflow:
    """Wrap a pooled BMAActualCashflow in a PortfolioCashflow with waterfall outputs.

    This is a convenience for applying the trust waterfall to an already-aggregated
    actual cashflow.  Pass cross_collateralize=True for full pool-level cross-collat,
    or provide a specific CrossCollateralMode.

    Ref: BMA SF-17, SF-19h; FNMA F-1-20; GNMA Ch. 14-15.
    """
    xc_mode = (
        CrossCollateralMode.FULL
        if cross_collateralize
        else (cross_collateral_mode or CrossCollateralMode.NONE)
    )
    return PortfolioCashflow(
        [pool],
        mode=PortfolioMode.ACTUAL_ONLY,
        cross_collateral_mode=xc_mode,
        cross_collateral_cap=cross_collateral_cap,
    )
