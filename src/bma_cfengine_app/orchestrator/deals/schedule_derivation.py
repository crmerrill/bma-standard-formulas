"""Structuring-time PAC/TAC schedule derivation helpers.

Industry-standard PAC mechanic: the schedule is the **lower envelope** of pool
principal across a published PSA range. Once derived, the schedule is the
contract — runtime never re-derives it. TAC is the same idea with a single
target PSA.

This module provides:
  - `project_pool_principal(...)` : light pool projection at a single PSA,
    returning principal cashflow per period (act_am + vol_prepay).
  - `derive_pac_schedule(...)` : builds `schedule_contract` as the lower
    envelope of two pool projections (lower vs upper PSA bound). Handles the
    case where the PAC bond receives only what it can absorb up to its current
    balance.
  - `derive_tac_schedule(...)` : single-PSA projection capped at the bond's
    balance.
  - `build_schedule_provenance(...)` : metadata block recording how the
    schedule was generated (method, inputs, timestamp) so audits and replays
    can reproduce the contract.

All output schedules are returned as `list[dict]` with keys `period` and
`target_principal`, matching the IR `BondDef.schedule_contract` field.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np

from bma_standard_formulas.formulas import (
    generate_smm_curve_from_psa,
    run_bma_actual_cashflow,
    run_bma_scheduled_cashflow,
)


def project_pool_principal(
    initial_balance: float,
    wac_pct: float,
    term_months: int,
    psa_speed: float,
    n_periods: int,
) -> np.ndarray:
    """Project per-period principal cash for a pool at a single PSA speed.

    Returns an array of length `n_periods + 1` where index 0 is the as-of
    snapshot (zero principal cash) and indices 1..n carry monthly principal
    (scheduled amortization plus voluntary prepayment, no defaults).

    Parameters
    ----------
    initial_balance:
        Pool starting balance in dollars.
    wac_pct:
        Weighted-average coupon as an annual percent (e.g. 6.0 for 6%).
    term_months:
        Pool original term in months (e.g. 360 for 30y).
    psa_speed:
        PSA speed in percent (e.g. 100 for 100% PSA, 250 for 250% PSA).
    n_periods:
        Number of periods to return (must be <= term_months).
    """
    if initial_balance <= 0.0 or wac_pct <= 0.0 or term_months <= 0 or n_periods <= 0:
        return np.zeros(n_periods + 1)

    sched = run_bma_scheduled_cashflow(
        original_balance=initial_balance,
        current_balance=initial_balance,
        coupon_vector=wac_pct,
        original_term=term_months,
        remaining_term=term_months,
    )
    smm = generate_smm_curve_from_psa(psa_speed, term_months)
    mdr = np.zeros(term_months + 1)
    sev = np.zeros(term_months + 1)
    actual = run_bma_actual_cashflow(
        scheduled_cf=sched,
        smm_curve=smm,
        mdr_curve=mdr,
        severity_curve=sev,
        coupon_vector=wac_pct,
    )
    # Total principal cash per period = scheduled amort + voluntary prepayment.
    principal = actual.act_am + actual.vol_prepay
    if len(principal) >= n_periods + 1:
        return np.asarray(principal[: n_periods + 1], dtype=float)
    out = np.zeros(n_periods + 1)
    out[: len(principal)] = principal
    return out


def _track_pac_principal(pool_principal: np.ndarray, pac_size: float) -> np.ndarray:
    """For a single scenario, compute principal that the PAC absorbs each period.

    Assumes the PAC sits at the top of the principal waterfall (i.e. it
    absorbs up to its remaining balance from pool principal each period before
    any support tranche). This is the conservative interpretation used to
    derive the schedule contract.
    """
    n = len(pool_principal)
    pac_principal = np.zeros(n)
    remaining = float(pac_size)
    for t in range(1, n):
        if remaining <= 0.0:
            break
        take = min(float(pool_principal[t]), remaining)
        pac_principal[t] = take
        remaining -= take
    return pac_principal


def derive_pac_schedule(
    pool_balance: float,
    pool_wac_pct: float,
    pool_term_months: int,
    psa_low: float,
    psa_high: float,
    pac_size: float,
    n_periods: int,
    min_target_dollars: float = 1.0,
) -> list[dict[str, float | int]]:
    """Derive PAC schedule_contract as the lower envelope of two PSA projections.

    For each period the published target equals the minimum principal the PAC
    receives across both speeds, so the bond is guaranteed at least that
    principal at any speed within the range.

    Parameters
    ----------
    pool_balance, pool_wac_pct, pool_term_months:
        Pool inputs for projection.
    psa_low, psa_high:
        Lower and upper PSA bounds defining the protected range. Order does
        not matter; the function takes min/max internally.
    pac_size:
        Original PAC face. Used to cap principal absorption when the PAC
        balance is below pool principal in a given period.
    n_periods:
        Modeled horizon (typically the deal CF length).
    min_target_dollars:
        Schedule entries with `target_principal` below this threshold are
        suppressed (output remains compact).

    Returns
    -------
    A `list[dict]` shaped `[{"period": int, "target_principal": float}, ...]`
    sorted by period, suitable for direct assignment to
    `BondDef.schedule_contract`.
    """
    psa_lo = float(min(psa_low, psa_high))
    psa_hi = float(max(psa_low, psa_high))
    if pac_size <= 0.0 or n_periods <= 0:
        return []

    proj_lo = project_pool_principal(pool_balance, pool_wac_pct, pool_term_months, psa_lo, n_periods)
    proj_hi = project_pool_principal(pool_balance, pool_wac_pct, pool_term_months, psa_hi, n_periods)
    pac_lo = _track_pac_principal(proj_lo, pac_size)
    pac_hi = _track_pac_principal(proj_hi, pac_size)

    schedule: list[dict[str, float | int]] = []
    horizon = min(len(pac_lo), len(pac_hi), n_periods + 1)
    for t in range(1, horizon):
        target = float(min(pac_lo[t], pac_hi[t]))
        if target < min_target_dollars:
            continue
        schedule.append({"period": t, "target_principal": round(target, 2)})
    return schedule


def derive_tac_schedule(
    pool_balance: float,
    pool_wac_pct: float,
    pool_term_months: int,
    psa_target: float,
    tac_size: float,
    n_periods: int,
    min_target_dollars: float = 1.0,
) -> list[dict[str, float | int]]:
    """Derive TAC schedule_contract from a single target PSA projection.

    Produces a schedule where the TAC absorbs principal up to its remaining
    balance at the target PSA. Provides one-sided (contraction) protection
    only — extension risk is exposed.
    """
    if tac_size <= 0.0 or n_periods <= 0:
        return []
    proj = project_pool_principal(pool_balance, pool_wac_pct, pool_term_months, float(psa_target), n_periods)
    tac_principal = _track_pac_principal(proj, tac_size)

    schedule: list[dict[str, float | int]] = []
    horizon = min(len(tac_principal), n_periods + 1)
    for t in range(1, horizon):
        target = float(tac_principal[t])
        if target < min_target_dollars:
            continue
        schedule.append({"period": t, "target_principal": round(target, 2)})
    return schedule


def build_schedule_provenance(
    *,
    method: str,
    inputs: dict[str, Any],
    schedule_length: int,
) -> dict[str, Any]:
    """Build a provenance metadata block that documents how a schedule was derived.

    Stored alongside `schedule_contract` so an audit/replay can reconstruct the
    schedule exactly from the captured inputs without depending on app state.

    Parameters
    ----------
    method:
        One of `"PSA_RANGE"` or `"PSA_TARGET"` (PAC vs TAC derivation).
    inputs:
        Raw inputs that drove the derivation (pool balance, WAC, term, PSA
        bounds, bond size). Kept verbatim for round-trip determinism.
    schedule_length:
        Number of entries in the produced schedule.
    """
    return {
        "method": method,
        "inputs": dict(inputs),
        "schedule_length": int(schedule_length),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
