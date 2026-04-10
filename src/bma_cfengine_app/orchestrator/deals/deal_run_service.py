"""Deal run orchestration — compose collateral + waterfall execution + persistence."""
import time
import traceback
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.risk import (
    compute_credit_enhancement,
    compute_tranche_risk,
)
from bma_standard_formulas.deals.schemas.input import DealRunInput
from bma_standard_formulas.deals.schemas.output_bundle import ScenarioOutputBundle

from ...storage import run_store
from .deal_store import load_deal


def execute_deal_run(
    run_id: str,
    deal_id: str,
    deal_version: int | None,
    run_input: DealRunInput,
    scenario_names: list[str] | None = None,
    run_inputs_by_scenario: dict[str, DealRunInput] | None = None,
    source_mode: str = "deal_native",
    run_kind: str = "deal_run",
) -> dict[str, Any]:
    """Execute a deal waterfall and persist all outputs.

    Returns a manifest dict with status, artifacts, and timing.
    """
    t_start = time.perf_counter()
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        deal = load_deal(deal_id, version=deal_version)

        if run_inputs_by_scenario:
            scenario_names = list(run_inputs_by_scenario.keys())
        elif not scenario_names:
            scenario_names = ["Base Case"]

        all_scenarios: list[ScenarioOutputBundle] = []
        artifact_keys: list[str] = []
        for scenario_name in scenario_names:
            scenario_input = (
                run_inputs_by_scenario.get(scenario_name, run_input)
                if run_inputs_by_scenario
                else run_input
            )
            result = run_deal(deal, scenario_input, scenario_name=scenario_name)
            if not result.tranche_risk_summary:
                result.tranche_risk_summary = compute_tranche_risk(result)
            if not result.credit_enhancement:
                result.credit_enhancement = compute_credit_enhancement(
                    result,
                    scenario_input.original_collateral_balance or 0.0,
                )
            all_scenarios.append(result)
            artifact_keys.extend(_persist_scenario_artifacts(run_id, scenario_name, result))

        elapsed = round(time.perf_counter() - t_start, 3)

        deal_context = {
            "deal_id": deal_id,
            "deal_name": deal.deal_name,
            "scenario_set": scenario_names,
            "source_mode": source_mode,
            "deal_version": deal_version,
        }
        manifest = {
            "status": "completed",
            "run_type": "structured_deal",
            "run_kind": run_kind,
            "deal_id": deal_id,
            "deal_name": deal.deal_name,
            "deal_version": deal_version,
            "deal_context": deal_context,
            "scenario_names": scenario_names,
            "elapsed_seconds": elapsed,
            "created_at": created_at,
            "bond_count": len(deal.bonds),
            "rule_count": len(deal.waterfall_rules),
            "artifact_keys": artifact_keys,
            "summary": {
                "elapsed_seconds": elapsed,
                "bond_count": len(deal.bonds),
                "rule_count": len(deal.waterfall_rules),
                "deal_name": deal.deal_name,
            },
        }
        run_store.save_run_input_json(
            run_id,
            "deal_run_request",
            {
                "source_mode": source_mode,
                "scenario_names": scenario_names,
                "deal_id": deal_id,
                "deal_version": deal_version,
            },
        )
        run_store.save_manifest(run_id, manifest)
        return manifest

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        manifest = {
            "status": "failed",
            "run_type": "structured_deal",
            "run_kind": run_kind,
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
) -> list[str]:
    """Persist scenario artifacts as parquet + CSV and return artifact keys."""
    prefix = scenario_name.replace(" ", "_")
    artifact_keys: list[str] = []

    if result.bond_cashflows:
        rows = [row.model_dump() for row in result.bond_cashflows]
        df = pd.DataFrame(rows)
        run_store.save_artifact(run_id, f"{prefix}_bond_cashflows", df)
        run_store.save_artifact_csv(run_id, f"{prefix}_bond_cashflows", df)
        artifact_keys.append(f"{prefix}_bond_cashflows")
        decrement_df = _build_decrement_table(df, scenario_name)
        if not decrement_df.empty:
            run_store.save_artifact(run_id, f"{prefix}_decrement_table", decrement_df)
            run_store.save_artifact_csv(run_id, f"{prefix}_decrement_table", decrement_df)
            artifact_keys.append(f"{prefix}_decrement_table")

    if result.waterfall_trace:
        rows = [row.model_dump() for row in result.waterfall_trace]
        df = pd.DataFrame(rows)
        run_store.save_artifact(run_id, f"{prefix}_waterfall_trace", df)
        run_store.save_artifact_csv(run_id, f"{prefix}_waterfall_trace", df)
        artifact_keys.append(f"{prefix}_waterfall_trace")

    _persist_model_rows(run_id, f"{prefix}_trigger_state_history", result.trigger_state_history, artifact_keys)
    _persist_model_rows(run_id, f"{prefix}_tranche_risk_summary", result.tranche_risk_summary, artifact_keys)
    _persist_model_rows(run_id, f"{prefix}_credit_enhancement", result.credit_enhancement, artifact_keys)
    _persist_model_rows(run_id, f"{prefix}_pac_tac_diagnostics", result.pac_tac_diagnostics, artifact_keys)
    _persist_model_rows(run_id, f"{prefix}_structure_composition", result.structure_composition, artifact_keys)
    return artifact_keys


def _persist_model_rows(
    run_id: str,
    artifact_name: str,
    rows: list[Any],
    artifact_keys: list[str],
) -> None:
    if not rows:
        return
    df = pd.DataFrame([row.model_dump() for row in rows])
    run_store.save_artifact(run_id, artifact_name, df)
    run_store.save_artifact_csv(run_id, artifact_name, df)
    artifact_keys.append(artifact_name)


def _build_decrement_table(
    bond_cashflows_df: pd.DataFrame,
    scenario_name: str,
) -> pd.DataFrame:
    if bond_cashflows_df.empty:
        return pd.DataFrame()
    grouped = (
        bond_cashflows_df
        .groupby(["tranche_id", "period"], as_index=False)
        .agg(
            end_balance=("end_balance", "sum"),
            total_principal=("total_principal", "sum"),
        )
    )
    wal_rows: list[dict[str, Any]] = []
    for tranche_id, tdf in grouped.groupby("tranche_id"):
        principal_sum = float(tdf["total_principal"].sum())
        wal = 0.0
        if principal_sum > 0:
            wal = float((tdf["period"] * tdf["total_principal"]).sum() / principal_sum / 12.0)
        wal_rows.append(
            {
                "scenario_name": scenario_name,
                "tranche_id": tranche_id,
                "wal_years": wal,
            }
        )
    wal_df = pd.DataFrame(wal_rows)
    return grouped.merge(wal_df, on="tranche_id", how="left")


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
