"""Engine-truth carry tie-out: YTM, duration, residual back-solve.

After a deal scenario runs, this module computes the realized
yield-to-maturity (CBE convention) and modified duration for each
tranche under par pricing, the pool's realized YTM and duration, and
back-solves the implied residual yield from the duration-weighted carry
equation:

    Σ(notional_i × ytm_i × dur_i) + resid_balance × resid_ytm × resid_dur
        = pool_balance × pool_ytm × pool_duration

The result is a `CarryTieoutSummary` artifact that gates structuring
status (OK / WARN / BLOCK based on the implied residual yield band) and
surfaces in the Studio post-run banner.

Status thresholds (locked tight per `engine_completeness_and_carry_tieout`
plan):

  - **OK**    : implied residual yield in [5%, 35%]
  - **WARN**  : in [0%, 5%) or (35%, 50%]
  - **BLOCK** : < 0% (residual paying out more than pool covers) or > 50%
                (residual unrealistically large -- bonds under-couponed)

Thresholds are user-overridable per deal via
``deal_knobs["tieout_thresholds"]`` in the IR.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .risk import (
    bond_ytm_cbe,
    io_cashflows_from_underlying_balance,
    monthly_to_cbe,
    solve_monthly_irr,
)
from .schemas.input import DealRunInput
from .schemas.ir import BondDef, DealDefinition
from .schemas.output_bond import (
    BondCashflowRow,
    CarryTieoutSummary,
    CarryTieoutTrancheRow,
)
from .schemas.output_bundle import ScenarioOutputBundle


# Default status thresholds (percent yield, CBE convention).
DEFAULT_THRESHOLDS = {
    "warn_low_pct": 5.0,
    "warn_high_pct": 35.0,
    "block_low_pct": 0.0,
    "block_high_pct": 50.0,
}


# ---------------------------------------------------------------------------
# Cashflow extraction helpers
# ---------------------------------------------------------------------------


def _rows_for_tranche(
    bond_cashflows: list[BondCashflowRow], tranche_id: str
) -> list[BondCashflowRow]:
    return sorted(
        (r for r in bond_cashflows if r.tranche_id == tranche_id),
        key=lambda r: r.period,
    )


def _bond_total_cashflows(rows: list[BondCashflowRow]) -> np.ndarray:
    """Build a period-indexed total-cashflow array from a tranche's rows.

    `cashflow[i]` = principal[i] + interest_paid[i]. Period 0 is zero
    (settlement). Returns an array of length ``max_period + 1``.
    """
    if not rows:
        return np.zeros(0)
    n = rows[-1].period + 1
    out = np.zeros(n)
    for r in rows:
        if r.period == 0:
            continue
        out[r.period] = float(r.total_principal) + float(r.interest_paid)
    return out


def _io_total_cashflows(
    bond_cashflows: list[BondCashflowRow], underlying_id: str, coupon_pct: float
) -> np.ndarray:
    """Build the cashflow stream for a notional IO whose balance tracks an
    underlying bond.
    """
    underlying_rows = _rows_for_tranche(bond_cashflows, underlying_id)
    return io_cashflows_from_underlying_balance(underlying_rows, coupon_pct)


def _pool_total_cashflows(run_input: DealRunInput) -> np.ndarray:
    """Net pool principal + interest cashflow, period-indexed.

    Handles all four ``CollateralInput`` variants:

      - ``PooledCollateralInput`` / ``StripCollateralInput``: read
        ``cf.principal`` + ``cf.interest`` from the inner LDCMA payload.
      - ``GroupedCollateralInput``: aggregate by summing each group's
        principal + interest streams.
      - ``PairedCollateralInput`` (Phase 1f): read directly from the
        BMA-native PortfolioCashflow's pool — ``portfolio.pool.act_prin``
        for principal and ``portfolio.pool.act_int`` for interest.
        ``act_int`` is whatever the deal runtime sees (already netted
        for FNR-style MBS-layer wedge handling done at fixture build
        time via ``dataclasses.replace``).
    """
    coll = run_input.collateral

    # PAIRED: BMA-native cashflow. Read from portfolio.pool directly.
    portfolio = getattr(coll, "portfolio", None)
    if portfolio is not None:
        try:
            pool = portfolio.pool
        except (ValueError, AttributeError, TypeError):
            return np.zeros(0)
        principal = np.asarray(pool.act_prin, dtype=float)
        interest = np.asarray(pool.act_int, dtype=float)
        n = max(len(principal), len(interest))
        pool_cf = np.zeros(n)
        if len(principal) > 0:
            pool_cf[: len(principal)] += principal
        if len(interest) > 0:
            pool_cf[: len(interest)] += interest
        return pool_cf

    # LDCMA paths: PooledCollateralInput and StripCollateralInput expose
    # the inner LDCMA payload as ``coll.collateral``; GroupedCollateralInput
    # exposes per-group payloads as ``coll.groups``.
    cf = getattr(coll, "collateral", None)
    if cf is None:
        groups = getattr(coll, "groups", None)
        if groups:
            # Aggregate across groups so single-group access does the
            # same thing as multi-group access (sum of principal +
            # interest streams). Pre-Phase-1f the loop just took the
            # first group, which dropped the rest of the cashflow.
            principal_total: np.ndarray | None = None
            interest_total: np.ndarray | None = None
            for g_cf in groups.values():
                p = np.asarray(g_cf.principal, dtype=float)
                i = np.asarray(g_cf.interest, dtype=float)
                principal_total = p if principal_total is None else principal_total + p
                interest_total = i if interest_total is None else interest_total + i
            if principal_total is None or interest_total is None:
                return np.zeros(0)
            n = max(len(principal_total), len(interest_total))
            pool_cf = np.zeros(n)
            pool_cf[: len(principal_total)] += principal_total
            pool_cf[: len(interest_total)] += interest_total
            return pool_cf
    if cf is None:
        return np.zeros(0)
    principal = np.asarray(cf.principal, dtype=float)
    interest = np.asarray(cf.interest, dtype=float)
    n = max(len(principal), len(interest))
    pool_cf = np.zeros(n)
    if len(principal) > 0:
        pool_cf[: len(principal)] += principal
    if len(interest) > 0:
        pool_cf[: len(interest)] += interest
    return pool_cf


# ---------------------------------------------------------------------------
# Modified duration under a solved YTM
# ---------------------------------------------------------------------------


def _modified_duration(cashflows: np.ndarray, monthly_rate: float) -> float:
    """Modified duration in years given a monthly rate.

    ``D_mod = (Σ t * cf_t * (1+r)^-t) / (Σ cf_t * (1+r)^-t) / (1 + r)``,
    where t runs over period indices and r is the monthly rate; result is
    converted to years by dividing by 12.
    """
    if monthly_rate <= -1.0 + 1e-9 or len(cashflows) == 0:
        return 0.0
    periods = np.arange(len(cashflows), dtype=float)
    df = (1.0 + monthly_rate) ** -periods
    pv = float((cashflows * df).sum())
    if pv <= 0.0:
        return 0.0
    weighted = float((periods * cashflows * df).sum())
    macaulay_periods = weighted / pv
    macaulay_years = macaulay_periods / 12.0
    return macaulay_years / (1.0 + monthly_rate)


def _wal_years(rows: list[BondCashflowRow]) -> float:
    pairs = [(r.period, r.total_principal) for r in rows if r.period > 0]
    total = sum(p for _, p in pairs)
    if total <= 0.0:
        return 0.0
    return float(sum(t * p for t, p in pairs)) / total / 12.0


# ---------------------------------------------------------------------------
# Per-tranche YTM at par
# ---------------------------------------------------------------------------


def _is_io_bond(bond_def: BondDef) -> bool:
    """Notional IO classes track another bond's balance."""
    if not bond_def.tracks_bonds:
        return False
    if not isinstance(bond_def.tracks_bonds, dict):
        return False
    return "balance" in bond_def.tracks_bonds


def _is_residual_bond(bond_def: BondDef) -> bool:
    return (
        bond_def.tranche_type is not None
        and bond_def.tranche_type.value == "RESIDUAL"
    )


def _tranche_face(bond_def: BondDef, rows: list[BondCashflowRow]) -> float:
    """Face for the YTM solve. For most bonds = size at issuance; for
    residual = end-of-deal cumulative cashflow (residual has no face).
    """
    if bond_def.notional and bond_def.notional > 0:
        return float(bond_def.notional)
    # Fallback: first non-zero begin_balance.
    for r in rows:
        if r.begin_balance > 0:
            return float(r.begin_balance)
    return 0.0


def _solve_tranche_ytm(
    bond_def: BondDef,
    rows: list[BondCashflowRow],
    bond_cashflows: list[BondCashflowRow],
) -> tuple[float, float]:
    """Return ``(ytm_cbe_pct, modified_duration_years)`` for a single tranche
    under par pricing.

    For notional IO classes, cashflows are reconstructed from the
    underlying balance trajectory (not the IO's own bond rows, which
    typically carry only interest_paid populated by the runtime tracker).
    """
    face = _tranche_face(bond_def, rows)
    if face <= 0.0:
        return 0.0, 0.0
    if _is_io_bond(bond_def):
        underlying_names = bond_def.tracks_bonds["balance"]
        # IO cashflows = sum of underlyings (typically one).
        cf = np.zeros(0)
        coupon_pct = float(bond_def.coupon or 0.0)
        for u_name in underlying_names:
            uflow = _io_total_cashflows(bond_cashflows, u_name, coupon_pct)
            if len(uflow) > len(cf):
                grown = np.zeros(len(uflow))
                grown[: len(cf)] = cf
                cf = grown
            cf[: len(uflow)] += uflow
    else:
        cf = _bond_total_cashflows(rows)
    if cf.sum() <= 0.0:
        return 0.0, 0.0
    try:
        r_m = solve_monthly_irr(cf, face)
    except ValueError:
        return 0.0, 0.0
    return monthly_to_cbe(r_m), _modified_duration(cf, r_m)


# ---------------------------------------------------------------------------
# Pool YTM
# ---------------------------------------------------------------------------


def _pool_principal_array(run_input: DealRunInput) -> np.ndarray:
    """Pool principal cashflow stream, period-indexed.

    Mirrors ``_pool_total_cashflows`` for the principal-only stream. Used
    by the WAL calculation. Handles all four CollateralInput variants.
    """
    coll = run_input.collateral
    portfolio = getattr(coll, "portfolio", None)
    if portfolio is not None:
        try:
            return np.asarray(portfolio.pool.act_prin, dtype=float)
        except (ValueError, AttributeError, TypeError):
            return np.zeros(0)
    cf = getattr(coll, "collateral", None)
    if cf is not None:
        return np.asarray(cf.principal, dtype=float)
    groups = getattr(coll, "groups", None)
    if groups:
        total: np.ndarray | None = None
        for g_cf in groups.values():
            arr = np.asarray(g_cf.principal, dtype=float)
            total = arr if total is None else total + arr
        return total if total is not None else np.zeros(0)
    return np.zeros(0)


def _pool_initial_balance(run_input: DealRunInput) -> float:
    """Pool starting balance for the YTM solve.

    Prefers ``run_input.original_collateral_balance``; falls back to the
    period-0 balance of the collateral payload (across all four variants).
    """
    declared = float(run_input.original_collateral_balance or 0.0)
    if declared > 0.0:
        return declared
    coll = run_input.collateral
    portfolio = getattr(coll, "portfolio", None)
    if portfolio is not None:
        try:
            pool = portfolio.pool
        except (ValueError, AttributeError, TypeError):
            return 0.0
        return float(pool.perf_bal[0]) if len(pool.perf_bal) > 0 else 0.0
    cf = getattr(coll, "collateral", None)
    if cf is not None and cf.balance:
        return float(cf.balance[0])
    groups = getattr(coll, "groups", None)
    if groups:
        return float(sum(
            (g_cf.balance[0] for g_cf in groups.values() if g_cf.balance), 0.0,
        ))
    return 0.0


def _solve_pool_ytm(run_input: DealRunInput) -> tuple[float, float, float, float]:
    """Return ``(pool_balance, ytm_cbe_pct, modified_duration_years, wal_years)``."""
    pool_cf = _pool_total_cashflows(run_input)
    if pool_cf.sum() <= 0.0:
        return 0.0, 0.0, 0.0, 0.0
    pool_balance = _pool_initial_balance(run_input)
    try:
        r_m = solve_monthly_irr(pool_cf, pool_balance)
    except ValueError:
        return pool_balance, 0.0, 0.0, 0.0
    ytm = monthly_to_cbe(r_m)
    dur = _modified_duration(pool_cf, r_m)
    principal = _pool_principal_array(run_input)
    if len(principal) > 0:
        periods = np.arange(len(principal), dtype=float)
        total = float(principal.sum())
        wal = float((periods * principal).sum() / total / 12.0) if total > 0 else 0.0
    else:
        wal = 0.0
    return pool_balance, ytm, dur, wal


# ---------------------------------------------------------------------------
# Residual yield back-solve and status
# ---------------------------------------------------------------------------


def _back_solve_residual_yield(
    pool_balance: float,
    pool_ytm_pct: float,
    pool_dur: float,
    tranche_rows: list[CarryTieoutTrancheRow],
    io_tranche_ids: set[str],
    residual_balance: float,
    residual_dur: float,
) -> tuple[float, float]:
    """Back-solve residual YTM from the duration-weighted carry equation.

    Returns ``(implied_residual_ytm_pct, stack_weighted_ytm_pct)``.

    Notional IO classes are EXCLUDED from the carry equation: their
    cashflows are duplicative of the underlying bond's coupon (an IO/PO
    pair is just an exchangeable form of a single coupon-bearing bond),
    and "par pricing" for an IO produces a structurally negative YTM
    that pollutes the back-solve. The underlying bond carries the
    full 5.50% (or whatever) coupon duration weight.
    """
    contributing = [r for r in tranche_rows if r.tranche_id not in io_tranche_ids]
    pool_carry = pool_balance * pool_ytm_pct * pool_dur
    stack_carry = sum(
        r.notional * r.ytm_cbe_pct * r.modified_duration_years for r in contributing
    )
    stack_dur_weight = sum(
        r.notional * r.modified_duration_years for r in contributing
    )
    stack_weighted_ytm = (
        stack_carry / stack_dur_weight if stack_dur_weight > 0 else 0.0
    )
    if residual_balance <= 0.0 or residual_dur <= 0.0:
        return 0.0, stack_weighted_ytm
    implied_resid = (pool_carry - stack_carry) / (residual_balance * residual_dur)
    return implied_resid, stack_weighted_ytm


# A residual class with cumulative cashflows below this fraction of the
# pool balance is treated as a "pure pass-through" structure with no
# meaningful excess spread (e.g., FNR 2006-018 Group 2: pool 5.50% net,
# bonds 5.50%, residual collects only sub-basis-point rounding cash).
RESIDUAL_PASS_THROUGH_THRESHOLD = 0.001  # 0.1% of pool


def _classify_status(
    implied_residual_ytm: float,
    residual_balance: float,
    pool_balance: float,
    thresholds: dict[str, float],
) -> tuple[str, str]:
    """Classify carry-tieout status from implied residual yield.

    Special case: when the residual cumulative cashflow is < 0.1% of
    pool balance, the structure is a pure pass-through (no excess
    spread) and the implied-residual back-solve is numerically ill-posed
    (division by ~0). We report status=OK with a "pass-through"
    explanation and ignore the implied-yield magnitude.
    """
    if (
        pool_balance > 0.0
        and residual_balance / pool_balance < RESIDUAL_PASS_THROUGH_THRESHOLD
    ):
        return (
            "OK",
            f"Pure pass-through structure: residual cumulative cashflow "
            f"${residual_balance:,.2f} is < 0.1% of pool balance "
            f"${pool_balance:,.2f}; no excess spread to back-solve.",
        )
    warn_lo = thresholds["warn_low_pct"]
    warn_hi = thresholds["warn_high_pct"]
    block_lo = thresholds["block_low_pct"]
    block_hi = thresholds["block_high_pct"]
    if implied_residual_ytm < block_lo or implied_residual_ytm > block_hi:
        side = "below" if implied_residual_ytm < block_lo else "above"
        return (
            "BLOCK",
            f"Implied residual yield {implied_residual_ytm:.2f}% {side} "
            f"the block band [{block_lo:.1f}%, {block_hi:.1f}%]; "
            f"structure may be over-couponed or under-collateralized.",
        )
    if implied_residual_ytm < warn_lo or implied_residual_ytm > warn_hi:
        side = "below" if implied_residual_ytm < warn_lo else "above"
        return (
            "WARN",
            f"Implied residual yield {implied_residual_ytm:.2f}% {side} "
            f"the OK band [{warn_lo:.1f}%, {warn_hi:.1f}%]; "
            f"review residual size or coupon structure.",
        )
    return (
        "OK",
        f"Implied residual yield {implied_residual_ytm:.2f}% within "
        f"OK band [{warn_lo:.1f}%, {warn_hi:.1f}%].",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_carry_tieout(
    deal: DealDefinition,
    run_input: DealRunInput,
    scenario: ScenarioOutputBundle,
    *,
    thresholds: dict[str, float] | None = None,
) -> CarryTieoutSummary:
    """Build a ``CarryTieoutSummary`` for one scenario's realized cashflows.

    Per-tranche YTM is solved at par pricing (the tranche's notional
    face = price × face). Pool YTM is solved against the deal's original
    collateral balance. Residual yield is back-solved so the
    duration-weighted carry equation balances. Status is derived from
    the implied residual yield against per-deal thresholds.
    """
    deal_thresholds = dict(DEFAULT_THRESHOLDS)
    knob_thresholds = (
        deal.deal_knobs.get("tieout_thresholds") if deal.deal_knobs else None
    )
    if isinstance(knob_thresholds, dict):
        deal_thresholds.update(
            {k: float(v) for k, v in knob_thresholds.items() if k in DEFAULT_THRESHOLDS}
        )
    if thresholds is not None:
        deal_thresholds.update(
            {k: float(v) for k, v in thresholds.items() if k in DEFAULT_THRESHOLDS}
        )

    pool_balance, pool_ytm, pool_dur, pool_wal = _solve_pool_ytm(run_input)

    tranche_rows: list[CarryTieoutTrancheRow] = []
    io_tranche_ids: set[str] = set()
    residual_balance = 0.0
    residual_dur = 0.0
    bond_defs_by_name = {b.name: b for b in deal.bonds}
    for bond_def in deal.bonds:
        rows = _rows_for_tranche(scenario.bond_cashflows, bond_def.name)
        if not rows:
            continue
        if _is_residual_bond(bond_def):
            # Residual size and duration computed from its realized cashflow
            # so the back-solve can use realistic numbers; balance is the
            # cumulative cash distributed (approximation -- residuals have
            # no face, so we treat their "size" as the total cash they
            # collected, which is what they deliver to investors).
            cf = _bond_total_cashflows(rows)
            residual_balance = float(cf.sum())
            if residual_balance > 0.0:
                try:
                    r_m = solve_monthly_irr(cf, residual_balance)
                    residual_dur = _modified_duration(cf, r_m)
                except ValueError:
                    residual_dur = 0.0
            continue
        ytm, dur = _solve_tranche_ytm(bond_def, rows, scenario.bond_cashflows)
        wal = _wal_years(rows)
        if _is_io_bond(bond_def):
            io_tranche_ids.add(bond_def.name)
            if wal == 0.0 and bond_def.tracks_bonds:
                # IOs have no principal cashflow; copy underlying WAL.
                for u_name in bond_def.tracks_bonds.get("balance", []):
                    under = _rows_for_tranche(scenario.bond_cashflows, u_name)
                    u_wal = _wal_years(under)
                    if u_wal > 0.0:
                        wal = u_wal
                        break
        tranche_rows.append(
            CarryTieoutTrancheRow(
                scenario_name=scenario.scenario_name,
                tranche_id=bond_def.name,
                notional=float(bond_def.notional or 0.0),
                coupon_pct=float(bond_def.coupon or 0.0),
                ytm_cbe_pct=ytm,
                modified_duration_years=dur,
                wal_years=wal,
            )
        )

    implied_resid, stack_ytm = _back_solve_residual_yield(
        pool_balance,
        pool_ytm,
        pool_dur,
        tranche_rows,
        io_tranche_ids,
        residual_balance,
        residual_dur,
    )
    # Pure pass-through guard: when residual cashflow is sub-basis-point of
    # pool, the back-solve is numerically ill-posed; clamp to a sentinel.
    if (
        pool_balance > 0.0
        and residual_balance / pool_balance < RESIDUAL_PASS_THROUGH_THRESHOLD
    ):
        implied_resid = 0.0
    status, reason = _classify_status(
        implied_resid, residual_balance, pool_balance, deal_thresholds
    )

    return CarryTieoutSummary(
        scenario_name=scenario.scenario_name,
        pool_balance=pool_balance,
        pool_ytm_cbe_pct=pool_ytm,
        pool_modified_duration_years=pool_dur,
        pool_wal_years=pool_wal,
        tranches=tranche_rows,
        residual_balance=residual_balance,
        residual_modified_duration_years=residual_dur,
        implied_residual_ytm_cbe_pct=implied_resid,
        stack_weighted_ytm_cbe_pct=stack_ytm,
        status=status,
        reason=reason,
        warn_low_pct=deal_thresholds["warn_low_pct"],
        warn_high_pct=deal_thresholds["warn_high_pct"],
        block_low_pct=deal_thresholds["block_low_pct"],
        block_high_pct=deal_thresholds["block_high_pct"],
    )
