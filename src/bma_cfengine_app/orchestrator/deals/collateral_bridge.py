"""Build DealRunInput payloads from either Run Setup refs or deal-native inputs."""
from __future__ import annotations

import re
from typing import Any

from bma_standard_formulas.deals.adapters import from_portfolio_cashflow
from bma_standard_formulas.deals.schemas.input import DealRunInput

from ...storage import run_store


def _safe_artifact_name(name: str) -> str:
    safe = re.sub(r"[^\w\-.]", "_", name)
    return safe[:80]


def build_from_runsetup_ref(
    run_id: str,
    scenario_names: list[str] | None = None,
) -> dict[str, DealRunInput]:
    """Reuse mapped tape + assumptions output from a completed portfolio run."""
    manifest = run_store.load_manifest(run_id)
    if manifest.get("status") != "completed":
        raise ValueError(f"Run {run_id} is not completed")

    available = manifest.get("scenario_names") or ["Base Case"]
    selected = scenario_names or list(available)
    unknown = [name for name in selected if name not in available]
    if unknown:
        raise ValueError(
            f"Scenario(s) not found in run {run_id}: {', '.join(unknown)}"
        )

    deal_inputs: dict[str, DealRunInput] = {}
    for scenario_name in selected:
        prefix = _safe_artifact_name(scenario_name)
        section = f"{prefix}_portfolio_actual"
        df = run_store.load_artifact(run_id, section)
        deal_inputs[scenario_name] = from_portfolio_cashflow(
            df,
            loan_count=manifest.get("loan_count"),
            market_date=manifest.get("created_at"),
        )
    return deal_inputs


def build_from_deal_native(source_payload: dict[str, Any]) -> dict[str, DealRunInput]:
    """Build run input(s) from explicit deal-local collateral payloads."""
    if "scenario_inputs" in source_payload:
        scenario_inputs = source_payload["scenario_inputs"] or {}
        out: dict[str, DealRunInput] = {}
        for scenario_name, payload in scenario_inputs.items():
            out[scenario_name] = DealRunInput.model_validate(payload)
        if out:
            return out

    run_input = source_payload.get("run_input")
    if run_input is None:
        raise ValueError("deal_native source requires run_input or scenario_inputs")
    scenario_name = source_payload.get("scenario_name", "Base Case")
    return {scenario_name: DealRunInput.model_validate(run_input)}
