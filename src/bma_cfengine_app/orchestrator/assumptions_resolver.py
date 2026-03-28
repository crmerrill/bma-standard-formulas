from __future__ import annotations

from typing import Any

import numpy as np

from bma_standard_formulas.engine.loan import Loan

from ..api.models import AssumptionSet, AssumptionsPayload, ConstantCurve
from .curve_builder import build_curve


def resolve_assumptions_for_loan(
    loan: Loan,
    payload: AssumptionsPayload,
    horizon: int,
    group_id: str | None = None,
) -> dict[str, Any]:
    """Resolve the effective assumption set for a single loan.

    Applies portfolio_defaults -> group_overrides -> loan_overrides in order.
    Returns a dict with keys: smm, mdr, severity (np.ndarray each),
    severity_lag, months_to_liquidation, provenance.
    """
    effective = _assumption_set_to_dict(payload.portfolio_defaults, horizon)
    provenance: dict[str, str] = {k: "portfolio" for k in effective if k not in ("severity_lag", "months_to_liquidation")}

    if group_id and group_id in payload.group_overrides:
        group_set = payload.group_overrides[group_id]
        _overlay(effective, group_set, horizon)
        for k in ("smm", "mdr", "severity"):
            if getattr(group_set, k) is not None:
                provenance[k] = f"group:{group_id}"

    loan_key = str(loan.loan_id)
    if loan_key in payload.loan_overrides:
        loan_set = payload.loan_overrides[loan_key]
        _overlay(effective, loan_set, horizon)
        for k in ("smm", "mdr", "severity"):
            if getattr(loan_set, k) is not None:
                provenance[k] = f"loan:{loan_key}"

    effective["provenance"] = provenance
    return effective


def resolve_portfolio_curves(
    loans: list[Loan],
    payload: AssumptionsPayload,
    group_ids: dict[int, str] | None = None,
) -> tuple[Any, Any, Any, int, int]:
    """Resolve assumption curves for the full portfolio.

    If all loans share the same effective curves, returns single arrays.
    Otherwise returns per-loan dicts keyed by loan_id.

    Returns: (smm, mdr, severity, severity_lag, months_to_liquidation)
    """
    if not loans:
        raise ValueError("No loans to resolve assumptions for")

    max_term = max(l.original_term for l in loans)
    horizon = max_term + 1

    has_overrides = bool(payload.group_overrides or payload.loan_overrides)

    if not has_overrides:
        base = _assumption_set_to_dict(payload.portfolio_defaults, horizon)
        return (
            base["smm"],
            base["mdr"],
            base["severity"],
            base["severity_lag"],
            base["months_to_liquidation"],
        )

    smm_dict: dict[int, np.ndarray] = {}
    mdr_dict: dict[int, np.ndarray] = {}
    sev_dict: dict[int, np.ndarray] = {}
    severity_lag = payload.portfolio_defaults.severity_lag_months
    months_to_liq = payload.portfolio_defaults.months_to_liquidation

    for loan in loans:
        gid = group_ids.get(loan.loan_id) if group_ids else None
        resolved = resolve_assumptions_for_loan(loan, payload, horizon, gid)
        smm_dict[loan.loan_id] = resolved["smm"]
        mdr_dict[loan.loan_id] = resolved["mdr"]
        sev_dict[loan.loan_id] = resolved["severity"]

    return smm_dict, mdr_dict, sev_dict, severity_lag, months_to_liq


def _assumption_set_to_dict(aset: AssumptionSet, horizon: int) -> dict[str, Any]:
    default_zero = ConstantCurve(value=0.0)
    default_sev = ConstantCurve(value=0.0)
    return {
        "smm": build_curve(aset.smm or default_zero, horizon),
        "mdr": build_curve(aset.mdr or default_zero, horizon),
        "severity": build_curve(aset.severity or default_sev, horizon),
        "severity_lag": aset.severity_lag_months,
        "months_to_liquidation": aset.months_to_liquidation,
    }


def _overlay(base: dict[str, Any], overlay_set: AssumptionSet, horizon: int) -> None:
    if overlay_set.smm is not None:
        base["smm"] = build_curve(overlay_set.smm, horizon)
    if overlay_set.mdr is not None:
        base["mdr"] = build_curve(overlay_set.mdr, horizon)
    if overlay_set.severity is not None:
        base["severity"] = build_curve(overlay_set.severity, horizon)
    if overlay_set.severity_lag_months != 12:
        base["severity_lag"] = overlay_set.severity_lag_months
    if overlay_set.months_to_liquidation != 12:
        base["months_to_liquidation"] = overlay_set.months_to_liquidation
