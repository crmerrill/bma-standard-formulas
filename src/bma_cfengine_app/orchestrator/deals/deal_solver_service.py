"""Deal solver orchestration and persistence."""
from __future__ import annotations

import traceback
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from bma_standard_formulas.deals.risk import compute_credit_enhancement, compute_tranche_risk
from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.solver import solve_deal
from bma_standard_formulas.deals.schemas.input import DealRunInput
from bma_standard_formulas.deals.schemas.solver import SolverSpec

from ...storage import run_store
from .deal_run_service import _persist_scenario_artifacts
from .deal_store import load_deal, save_deal


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
    try:
        deal = load_deal(deal_id, version=deal_version)
        solved_deal, solver_summary = solve_deal(
            deal,
            run_input,
            solver_spec,
            scenario_name=scenario_name,
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

        iter_rows = []
        for idx in range(int(solver_summary.total_iterations)):
            iter_rows.append(
                {
                    "solver_job_id": solver_summary.solver_job_id,
                    "solver_layer": solver_summary.solver_layers_run[0] if solver_summary.solver_layers_run else "layer",
                    "iteration": idx,
                    "objective_value": solver_summary.final_objective_value,
                    "constraint_violation_norm": 0.0,
                    "feasible_flag": solver_summary.final_feasible,
                    "step_size": 0.0,
                    "convergence_metric": solver_summary.final_objective_value,
                    "status": str(solver_summary.final_status),
                    "mutated_knobs_json": solver_summary.solved_knobs,
                    "checkpoint_deal_version": saved_version,
                }
            )
        if iter_rows:
            iter_df = pd.DataFrame(iter_rows)
            run_store.save_artifact(run_id, f"{scenario_name}_solver_iterations", iter_df)
            run_store.save_artifact_csv(run_id, f"{scenario_name}_solver_iterations", iter_df)
            artifact_keys.append(f"{scenario_name}_solver_iterations")

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
        return manifest
