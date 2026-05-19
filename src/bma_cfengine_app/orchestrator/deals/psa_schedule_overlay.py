"""Build PAC/TAC schedule_contract overlays from PSA collateral projections (Phase 1i).

Used by the structuring UI to replace Blockly placeholder schedules with
industry-standard lower-envelope PAC / target-PSA TAC contracts. Returns a
per-bond patch dict; callers merge into generated IR without mutating Blockly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bma_standard_formulas.deals.schemas.common import PrepayModelType, TrancheBehavior
from bma_standard_formulas.deals.schemas.ir import BondDef, DealDefinition

from .schedule_derivation import build_schedule_provenance, derive_pac_schedule, derive_tac_schedule


@dataclass(frozen=True)
class PoolDerivationInputs:
    balance: float
    wac_pct: float
    term_months: int
    horizon_months: int


def _original_face_usd(bond: BondDef, pool_balance: float) -> float:
    if bond.notional is not None and float(bond.notional) > 0:
        return float(bond.notional)
    if (
        bond.notional_pct_of_collateral is not None
        and float(bond.notional_pct_of_collateral) > 0
        and pool_balance > 0
    ):
        return float(bond.notional_pct_of_collateral) / 100.0 * pool_balance
    return 0.0


def build_psa_schedule_overlay(
    deal: DealDefinition,
    pool: PoolDerivationInputs,
) -> dict[str, dict[str, Any]]:
    """Return ``bond_name -> {schedule_contract, schedule_derivation}`` for PSA-mode PAC/TAC.

    Bonds using ``PrepayModelType.CPR``, ``ABS``, or ``CUSTOM_VECTOR`` are
    skipped (structuring continues to rely on authored vectors or future CPR
    projection support).
    """
    overlay: dict[str, dict[str, Any]] = {}
    if pool.balance <= 0 or pool.wac_pct <= 0 or pool.term_months <= 0 or pool.horizon_months <= 0:
        return overlay

    bal = float(pool.balance)
    wac = float(pool.wac_pct)
    term = int(pool.term_months)
    horizon = int(pool.horizon_months)

    for bond in deal.bonds:
        if bond.schedule_model_type != PrepayModelType.PSA:
            continue
        face = _original_face_usd(bond, bal)
        if face <= 0:
            continue

        if bond.tranche_behavior == TrancheBehavior.PAC:
            lo = (
                bond.schedule_speed_low
                if bond.schedule_speed_low is not None
                else bond.pac_lower_psa
            )
            hi = (
                bond.schedule_speed_high
                if bond.schedule_speed_high is not None
                else bond.pac_upper_psa
            )
            if lo is None or hi is None:
                continue
            psa_lo = float(min(lo, hi))
            psa_hi = float(max(lo, hi))
            sched = derive_pac_schedule(bal, wac, term, psa_lo, psa_hi, face, horizon)
            inputs: dict[str, Any] = {
                "bond": bond.name,
                "pool_balance": bal,
                "pool_wac_pct": wac,
                "pool_term_months": term,
                "horizon_months": horizon,
                "psa_low": psa_lo,
                "psa_high": psa_hi,
                "tranche_face": face,
            }
            prov = build_schedule_provenance(
                method="PSA_RANGE",
                inputs=inputs,
                schedule_length=len(sched),
            )
            overlay[bond.name] = {
                "schedule_contract": sched,
                "schedule_derivation": prov,
            }

        elif bond.tranche_behavior == TrancheBehavior.TAC:
            tgt = (
                bond.schedule_speed_target
                if bond.schedule_speed_target is not None
                else bond.tac_pricing_psa
            )
            if tgt is None:
                continue
            sched = derive_tac_schedule(bal, wac, term, float(tgt), face, horizon)
            inputs = {
                "bond": bond.name,
                "pool_balance": bal,
                "pool_wac_pct": wac,
                "pool_term_months": term,
                "horizon_months": horizon,
                "psa_target": float(tgt),
                "tranche_face": face,
            }
            prov = build_schedule_provenance(
                method="PSA_TARGET",
                inputs=inputs,
                schedule_length=len(sched),
            )
            overlay[bond.name] = {
                "schedule_contract": sched,
                "schedule_derivation": prov,
            }

    return overlay
