"""Helpers to derive solver catalog options from canonical deal + recent artifacts."""
from __future__ import annotations

from typing import Any

from bma_standard_formulas.deals.schemas.solver import (
    ConstraintComparison,
    ObjectiveType,
    WaterfallTargetPrimitive,
)

from ...storage import run_store
from ..run_service import list_all_runs


def _default_knobs() -> list[dict[str, Any]]:
    return [
        {
            "knob_path": "deal_knobs.class_a_coupon",
            "label": "Class A coupon",
            "lower": 2.0,
            "upper": 12.0,
            "initial": 6.0,
            "step_hint": 0.25,
        },
        {
            "knob_path": "deal_knobs.class_b_coupon",
            "label": "Class B coupon",
            "lower": 2.0,
            "upper": 15.0,
            "initial": 8.0,
            "step_hint": 0.25,
        },
    ]


def _default_metrics() -> list[str]:
    return [
        "tranche_risk_summary[A].yield_pct",
        "tranche_risk_summary[A].wal_years",
        "credit_enhancement[A].total_ce_pct",
        "pac_tac_diagnostics[A].schedule_variance",
        "structure_composition[A].principal_conservation_error",
    ]


def _latest_structured_deal_run(deal_id: str) -> dict[str, Any] | None:
    for run in list_all_runs():
        if run.get("deal_id") != deal_id:
            continue
        if run.get("run_type") != "structured_deal":
            continue
        if run.get("status") != "completed":
            continue
        return run
    return None


def _derive_metric_paths_from_run(run_id: str) -> list[str]:
    metric_paths: set[str] = set()
    try:
        artifacts = run_store.list_artifacts(run_id)
    except FileNotFoundError:
        return []

    for artifact in artifacts:
        if not (
            artifact.endswith("_tranche_risk_summary")
            or artifact.endswith("_credit_enhancement")
            or artifact.endswith("_pac_tac_diagnostics")
            or artifact.endswith("_structure_composition")
            or artifact.endswith("_solver_selected_solution")
        ):
            continue
        try:
            df = run_store.load_artifact(run_id, artifact)
        except Exception:
            continue
        if df.empty:
            continue
        tranche_id = None
        if "tranche_id" in df.columns and len(df["tranche_id"]):
            tranche_id = str(df["tranche_id"].iloc[0])
        if "tranche_risk_summary" in artifact:
            root = "tranche_risk_summary"
        elif "credit_enhancement" in artifact:
            root = "credit_enhancement"
        elif "pac_tac_diagnostics" in artifact:
            root = "pac_tac_diagnostics"
        elif "structure_composition" in artifact:
            root = "structure_composition"
        else:
            root = "artifact"
        for col in df.columns:
            if col in {"scenario_name", "tranche_id"}:
                continue
            if tranche_id:
                metric_paths.add(f"{root}[{tranche_id}].{col}")
            else:
                metric_paths.add(f"{root}.{col}")
    return sorted(metric_paths)


def build_solver_catalog(deal_id: str, canonical_deal: Any) -> dict[str, Any]:
    latest_run = _latest_structured_deal_run(deal_id)
    metric_paths = _default_metrics()
    if latest_run:
        derived = _derive_metric_paths_from_run(latest_run["run_id"])
        if derived:
            metric_paths = derived

    knobs = _default_knobs()
    deal_knobs = getattr(canonical_deal, "deal_knobs", None)
    if isinstance(deal_knobs, dict):
        knobs = []
        for key, value in deal_knobs.items():
            numeric = isinstance(value, (int, float))
            lower = float(value) * 0.5 if numeric else 0.0
            upper = float(value) * 1.5 if numeric else 1.0
            initial = float(value) if numeric else 0.0
            knobs.append(
                {
                    "knob_path": f"deal_knobs.{key}",
                    "label": key,
                    "lower": lower,
                    "upper": upper,
                    "initial": initial,
                    "step_hint": max((upper - lower) / 20.0, 0.01),
                }
            )
        if not knobs:
            knobs = _default_knobs()

    return {
        "deal_id": deal_id,
        "metric_paths": metric_paths,
        "knobs": knobs,
        "typed_enums": {
            "objective_types": [item.value for item in ObjectiveType],
            "constraint_comparisons": [item.value for item in ConstraintComparison],
            "waterfall_target_primitives": [item.value for item in WaterfallTargetPrimitive],
        },
        "template_families": [
            {
                "family": "PRIME_JUMBO",
                "targets": [
                    "CUM_LOSS_MULTIPLE_GAP",
                    "NO_SHORTFALL_INTEREST",
                    "NO_SHORTFALL_PRINCIPAL",
                    "OC_IC_TRIGGER_RESILIENCE",
                    "CE_TARGET_DELTA",
                ],
            },
            {
                "family": "NON_QM_QRM",
                "targets": [
                    "CUM_LOSS_MULTIPLE_GAP",
                    "NO_SHORTFALL_INTEREST",
                    "NO_SHORTFALL_PRINCIPAL",
                    "STEPDOWN_ELIGIBILITY_SAFETY",
                    "SUBORDINATION_FLOOR_GAP",
                    "RESERVE_SUFFICIENCY_GAP",
                    "CE_TARGET_DELTA",
                ],
            },
            {
                "family": "AGENCY",
                "targets": [
                    "PAC_SCHEDULE_MISS",
                    "TAC_SCHEDULE_MISS",
                    "Z_ACCRUAL_RELEASE_GAP",
                    "SUPPORT_BURNDOWN_GAP",
                ],
            },
        ],
        "suggested_defaults": {
            "solver_name": "studio_solver",
            "layer_name": "base",
            "max_iterations": 24,
            "global_max_iterations": 120,
            "checkpoint_every_n": 5,
        },
        "source_run_id": latest_run.get("run_id") if latest_run else None,
    }
