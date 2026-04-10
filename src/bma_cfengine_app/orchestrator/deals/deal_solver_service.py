"""Deal solver orchestration and persistence."""
from __future__ import annotations

import re
import traceback
from datetime import datetime, timezone
from threading import Lock
from typing import Any

import pandas as pd

from bma_standard_formulas.deals.risk import compute_credit_enhancement, compute_tranche_risk
from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.solver import SolverCancelledError, solve_deal
from bma_standard_formulas.deals.schemas.input import DealRunInput
from bma_standard_formulas.deals.schemas.solver import SolverSpec

from ...storage import run_store
from .deal_run_service import _persist_scenario_artifacts
from .deal_store import load_deal, save_deal


def _safe_artifact_name(name: str) -> str:
    return re.sub(r"[^\w\-.]", "_", name)[:80]

_SOLVER_PROGRESS: dict[str, dict[str, Any]] = {}
_SOLVER_CANCEL_FLAGS: dict[str, bool] = {}
_REGISTRY_LOCK = Lock()


def init_solver_progress(run_id: str, *, deal_id: str, scenario_name: str) -> None:
    with _REGISTRY_LOCK:
        _SOLVER_PROGRESS[run_id] = {
            "run_id": run_id,
            "deal_id": deal_id,
            "scenario_name": scenario_name,
            "status": "running",
            "stage": "initializing",
            "iteration": 0,
            "objective_value": None,
            "constraint_violation_norm": None,
            "feasible": None,
            "elapsed_seconds": 0.0,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "cancel_requested": False,
        }
        _SOLVER_CANCEL_FLAGS[run_id] = False


def update_solver_progress(run_id: str, patch: dict[str, Any]) -> None:
    with _REGISTRY_LOCK:
        current = _SOLVER_PROGRESS.get(run_id)
        if not current:
            return
        current.update(patch)
        current["updated_at"] = datetime.now(timezone.utc).isoformat()


def get_solver_progress(run_id: str) -> dict[str, Any]:
    with _REGISTRY_LOCK:
        state = _SOLVER_PROGRESS.get(run_id)
        if not state:
            raise FileNotFoundError(f"No progress state for run {run_id}")
        return dict(state)


def request_solver_cancel(run_id: str) -> dict[str, Any]:
    with _REGISTRY_LOCK:
        if run_id not in _SOLVER_CANCEL_FLAGS:
            raise FileNotFoundError(f"Run {run_id} is not currently cancellable")
        _SOLVER_CANCEL_FLAGS[run_id] = True
        if run_id in _SOLVER_PROGRESS:
            _SOLVER_PROGRESS[run_id]["cancel_requested"] = True
            _SOLVER_PROGRESS[run_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
            return dict(_SOLVER_PROGRESS[run_id])
        return {"run_id": run_id, "cancel_requested": True}


def _should_cancel(run_id: str) -> bool:
    with _REGISTRY_LOCK:
        return bool(_SOLVER_CANCEL_FLAGS.get(run_id, False))


def execute_deal_solve(
    run_id: str,
    deal_id: str,
    deal_version: int | None,
    run_input: DealRunInput,
    solver_spec: SolverSpec,
    *,
    scenario_name: str = "Base Case",
    source_mode: str = "deal_native",
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    init_solver_progress(run_id, deal_id=deal_id, scenario_name=scenario_name)
    run_store.save_manifest(
        run_id,
        {
            "status": "running",
            "run_type": "structured_deal",
            "run_kind": "solver",
            "deal_id": deal_id,
            "scenario_names": [scenario_name],
            "created_at": created_at,
        },
    )

    t_start = datetime.now(timezone.utc)
    try:
        def _progress_callback(payload: dict[str, Any]) -> None:
            elapsed = (datetime.now(timezone.utc) - t_start).total_seconds()
            update_solver_progress(
                run_id,
                {
                    "status": "running",
                    "stage": payload.get("stage", "optimizing"),
                    "layer": payload.get("layer"),
                    "iteration": int(payload.get("iteration", 0)),
                    "objective_value": payload.get("objective_value"),
                    "constraint_violation_norm": payload.get("constraint_violation_norm"),
                    "feasible": payload.get("feasible"),
                    "elapsed_seconds": round(float(elapsed), 3),
                },
            )

        deal = load_deal(deal_id, version=deal_version)
        solved_deal, solver_summary = solve_deal(
            deal,
            run_input,
            solver_spec,
            scenario_name=scenario_name,
            progress_callback=_progress_callback,
            should_cancel=lambda: _should_cancel(run_id),
        )
        saved_version = save_deal(deal_id, solved_deal).get("version")
        result = run_deal(solved_deal, run_input, scenario_name=scenario_name)
        if not result.tranche_risk_summary:
            result.tranche_risk_summary = compute_tranche_risk(result)
        if not result.credit_enhancement:
            result.credit_enhancement = compute_credit_enhancement(
                result,
                run_input.original_collateral_balance or 0.0,
            )
        artifact_keys = _persist_scenario_artifacts(run_id, scenario_name, result)

        scenario_prefix = _safe_artifact_name(scenario_name)
        if solver_summary.iteration_log:
            iter_df = pd.DataFrame([row.model_dump() for row in solver_summary.iteration_log])
            run_store.save_artifact(run_id, f"{scenario_prefix}_solver_iterations", iter_df)
            run_store.save_artifact_csv(run_id, f"{scenario_prefix}_solver_iterations", iter_df)
            artifact_keys.append(f"{scenario_prefix}_solver_iterations")
        selected_df = pd.DataFrame([solver_summary.selected_solution | {"solver_job_id": solver_summary.solver_job_id}])
        run_store.save_artifact(run_id, f"{scenario_prefix}_solver_selected_solution", selected_df)
        run_store.save_artifact_csv(run_id, f"{scenario_prefix}_solver_selected_solution", selected_df)
        artifact_keys.append(f"{scenario_prefix}_solver_selected_solution")

        run_store.save_run_input_json(
            run_id,
            "deal_solver_request",
            {
                "deal_id": deal_id,
                "deal_version": deal_version,
                "solver_spec": solver_spec.model_dump(),
                "source_mode": source_mode,
                "scenario_name": scenario_name,
            },
        )
        manifest = {
            "status": "completed",
            "run_type": "structured_deal",
            "run_kind": "solver",
            "deal_id": deal_id,
            "deal_name": solved_deal.deal_name,
            "deal_version": saved_version,
            "scenario_names": [scenario_name],
            "deal_context": {
                "deal_id": deal_id,
                "deal_name": solved_deal.deal_name,
                "scenario_set": [scenario_name],
                "source_mode": source_mode,
                "deal_version": saved_version,
            },
            "solver_summary": solver_summary.model_dump(),
            "artifact_keys": artifact_keys,
            "created_at": created_at,
            "summary": {
                "elapsed_seconds": solver_summary.elapsed_seconds,
                "deal_name": solved_deal.deal_name,
                "solver_iterations": solver_summary.total_iterations,
            },
        }
        run_store.save_manifest(run_id, manifest)
        update_solver_progress(
            run_id,
            {
                "status": "completed",
                "stage": "completed",
                "iteration": solver_summary.total_iterations,
                "objective_value": solver_summary.final_objective_value,
                "feasible": solver_summary.final_feasible,
                "elapsed_seconds": solver_summary.elapsed_seconds,
            },
        )
        return manifest
    except SolverCancelledError:
        manifest = {
            "status": "cancelled",
            "run_type": "structured_deal",
            "run_kind": "solver",
            "deal_id": deal_id,
            "created_at": created_at,
            "scenario_names": [scenario_name],
            "error": "Solver cancelled by user request",
        }
        run_store.save_manifest(run_id, manifest)
        update_solver_progress(
            run_id,
            {
                "status": "cancelled",
                "stage": "cancelled",
                "error": "Solver cancelled by user request",
            },
        )
        return manifest
    except Exception as exc:
        manifest = {
            "status": "failed",
            "run_type": "structured_deal",
            "run_kind": "solver",
            "deal_id": deal_id,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "created_at": created_at,
        }
        run_store.save_manifest(run_id, manifest)
        update_solver_progress(
            run_id,
            {
                "status": "failed",
                "stage": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        return manifest
