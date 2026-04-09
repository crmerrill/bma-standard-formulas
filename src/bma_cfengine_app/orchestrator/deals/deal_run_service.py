"""Deal run orchestration — compose collateral + waterfall execution + persistence."""
import time
import traceback
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.ir import DealDefinition
from bma_standard_formulas.deals.schemas.input import DealRunInput
from bma_standard_formulas.deals.schemas.output_bundle import DealRunOutput, ScenarioOutputBundle

from ...storage import run_store
from .deal_store import load_deal, save_deal


def execute_deal_run(
    run_id: str,
    deal_id: str,
    deal_version: int | None,
    run_input: DealRunInput,
    scenario_names: list[str] | None = None,
) -> dict[str, Any]:
    """Execute a deal waterfall and persist all outputs.

    Returns a manifest dict with status, artifacts, and timing.
    """
    t_start = time.perf_counter()
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        deal = load_deal(deal_id, version=deal_version)

        if not scenario_names:
            scenario_names = ["Base Case"]

        all_scenarios: list[ScenarioOutputBundle] = []
        for scenario_name in scenario_names:
            result = run_deal(deal, run_input, scenario_name=scenario_name)
            all_scenarios.append(result)

            _persist_scenario_artifacts(run_id, scenario_name, result)

        elapsed = round(time.perf_counter() - t_start, 3)

        manifest = {
            "status": "completed",
            "deal_id": deal_id,
            "deal_version": deal_version,
            "scenario_names": scenario_names,
            "elapsed_seconds": elapsed,
            "created_at": created_at,
            "bond_count": len(deal.bonds),
            "rule_count": len(deal.waterfall_rules),
        }
        run_store.save_manifest(run_id, manifest)
        return manifest

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        manifest = {
            "status": "failed",
            "deal_id": deal_id,
            "error": error_msg,
            "traceback": traceback.format_exc(),
            "created_at": created_at,
        }
        run_store.save_manifest(run_id, manifest)
        return manifest


def _persist_scenario_artifacts(
    run_id: str,
    scenario_name: str,
    result: ScenarioOutputBundle,
) -> None:
    """Persist bond cashflows and waterfall trace as parquet + CSV artifacts."""
    prefix = scenario_name.replace(" ", "_")

    if result.bond_cashflows:
        rows = [row.model_dump() for row in result.bond_cashflows]
        df = pd.DataFrame(rows)
        run_store.save_artifact(run_id, f"{prefix}_bond_cashflows", df)
        run_store.save_artifact_csv(run_id, f"{prefix}_bond_cashflows", df)

    if result.waterfall_trace:
        rows = [row.model_dump() for row in result.waterfall_trace]
        df = pd.DataFrame(rows)
        run_store.save_artifact(run_id, f"{prefix}_waterfall_trace", df)
        run_store.save_artifact_csv(run_id, f"{prefix}_waterfall_trace", df)


def replay_deal_with_new_collateral(
    run_id: str,
    deal_id: str,
    deal_version: int | None,
    new_run_input: DealRunInput,
    scenario_names: list[str] | None = None,
) -> dict[str, Any]:
    """Re-run an existing deal definition with different collateral inputs."""
    return execute_deal_run(
        run_id=run_id,
        deal_id=deal_id,
        deal_version=deal_version,
        run_input=new_run_input,
        scenario_names=scenario_names,
    )
