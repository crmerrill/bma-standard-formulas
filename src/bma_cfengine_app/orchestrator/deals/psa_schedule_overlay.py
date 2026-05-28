"""Build PAC/TAC schedule_contract overlays from PSA collateral projections (Phase 1i).

Used by the structuring UI to replace Blockly placeholder schedules with
industry-standard lower-envelope PAC / target-PSA TAC contracts. Returns a
per-bond patch dict; callers merge into generated IR without mutating Blockly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bma_standard_formulas.deals.schemas.common import PrepayModelType, TrancheKind
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
        # Accept bonds where schedule_model_type is explicitly PSA, OR where it is
        # absent/None and PSA speed inputs are present. This matches the frontend
        # hasPsaStructuringBonds check which also accepts the null-model case when
        # speed values are set (irGenerator may omit schedule_model_type after round-trip).
        # Explicitly skip CPR, ABS, CUSTOM_VECTOR — those have their own derivation paths.
        if bond.schedule_model_type not in (PrepayModelType.PSA, None):
            continue
        if bond.schedule_model_type is None:
            # Only infer PSA eligibility when explicit speed inputs are present.
            has_pac_speeds = (
                bond.kind == TrancheKind.PAC
                and bond.schedule_speed_low is not None
                and bond.schedule_speed_high is not None
            )
            has_tac_speed = (
                bond.kind == TrancheKind.TAC
                and bond.schedule_speed_low is not None
            )
            if not (has_pac_speeds or has_tac_speed):
                continue
        face = _original_face_usd(bond, bal)
        if face <= 0:
            continue

        if bond.kind == TrancheKind.PAC:
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
            # Persist support tranche names so the frontend stale-detection
            # check can compare against the current SUPPORTED_BY relation set.
            support_names = ",".join(sorted(
                str(t) for rel in (bond.relations or [])
                if getattr(rel, "relation_type", None) is not None
                and rel.relation_type.value == "SUPPORTED_BY"
                for t in (getattr(rel, "targets", None) or [])
            ))
            inputs: dict[str, Any] = {
                "bond": bond.name,
                "pool_balance": bal,
                "pool_wac_pct": wac,
                "pool_term_months": term,
                "horizon_months": horizon,
                "psa_low": psa_lo,
                "psa_high": psa_hi,
                "tranche_face": face,
                "support_names": support_names,
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

        elif bond.kind == TrancheKind.TAC:
            lo = bond.schedule_speed_low
            hi = bond.schedule_speed_high
            if lo is not None and hi is not None:
                if abs(float(lo) - float(hi)) > 1e-9:
                    continue
                tgt = float(lo)
            else:
                tgt = bond.tac_pricing_psa
            if tgt is None:
                continue
            sched = derive_tac_schedule(bal, wac, term, float(tgt), face, horizon)
            tac_support_names = ",".join(sorted(
                str(t) for rel in (bond.relations or [])
                if getattr(rel, "relation_type", None) is not None
                and rel.relation_type.value == "SUPPORTED_BY"
                for t in (getattr(rel, "targets", None) or [])
            ))
            inputs = {
                "bond": bond.name,
                "pool_balance": bal,
                "pool_wac_pct": wac,
                "pool_term_months": term,
                "horizon_months": horizon,
                "psa_target": float(tgt),
                "tranche_face": face,
                "support_names": tac_support_names,
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
