"""Build DealRunInput payloads from either Run Setup refs or deal-native inputs.

Phase 0C (May 2026): the bridge now reads per-group portfolio artifacts when
the source run was grouped, producing a ``GroupedCollateralInput`` that the
deal runtime routes via ``GROUP_<id>_*`` source tokens.  Pre-Phase-0C the
bridge always read only the aggregate artifact and produced
``PooledCollateralInput``, which meant multi-group deals could not be wired
to a Run-Setup-driven portfolio run from the UI — they had to use
``deal_native`` payloads with hand-built per-group dicts.

The bridge is tightly coupled to the orchestrator's artifact-naming
convention (see ``run_service._execute_single_scenario``):

    {prefix}_portfolio_actual                  - aggregate (always)
    {prefix}_group_{safe_group_id}_actual      - per group (grouped runs)

The grouped path is selected when the run manifest carries non-empty
``group_names``.  Single-pool runs continue to use the aggregate-only
path unchanged.
"""
from __future__ import annotations

import re
from typing import Any

from bma_standard_formulas.deals.adapters import (
    from_grouped_portfolio_cashflows,
    from_portfolio_cashflow,
)
from bma_standard_formulas.deals.schemas.input import DealRunInput

from ...storage import run_store


def _safe_artifact_name(name: str) -> str:
    safe = re.sub(r"[^\w\-.]", "_", name)
    return safe[:80]


def _load_group_dataframes(
    run_id: str,
    prefix: str,
    group_names: list[str],
) -> dict[str, Any]:
    """Load per-group portfolio artifacts emitted by the orchestrator.

    The orchestrator saves one DataFrame per group at the artifact key
    ``{prefix}_group_{safe(group_id)}_actual`` (see
    ``run_service._execute_single_scenario``).  This helper loads each
    DataFrame into a dict keyed by the un-mangled ``group_id`` so the
    downstream adapter can preserve the original group identifier in the
    GroupedCollateralInput dict.

    Args:
        run_id: Run identifier (used by run_store).
        prefix: Sanitized scenario prefix (e.g. ``"Base_Case"``).
        group_names: List of original group_ids from the run manifest.

    Returns:
        ``dict[group_id, pd.DataFrame]``.  Groups whose artifact failed to
        load are silently omitted (matching the orchestrator's per-group
        error tolerance), so a partial result is preferred over a hard
        failure when one of several groups is missing.
    """
    out: dict[str, Any] = {}
    for gid in group_names:
        gname = _safe_artifact_name(gid)
        artifact_key = f"{prefix}_group_{gname}_actual"
        try:
            out[str(gid)] = run_store.load_artifact(run_id, artifact_key)
        except Exception:
            continue
    return out


def build_from_runsetup_ref(
    run_id: str,
    scenario_names: list[str] | None = None,
) -> dict[str, DealRunInput]:
    """Build DealRunInput(s) from a completed portfolio run's stored artifacts.

    Returns one ``DealRunInput`` per requested scenario, keyed by scenario
    name.  The collateral payload is:

      - ``PooledCollateralInput`` when the source run was single-pool
        (manifest ``group_names`` is empty), built from the aggregate
        portfolio artifact.
      - ``GroupedCollateralInput`` when the source run was grouped, built
        from the per-group portfolio artifacts.  Each group's
        ``CollateralCashflows`` is keyed by the original ``group_id``
        from the manifest.

    Both paths reuse the engine output directly — there is no engine
    re-invocation here.

    Args:
        run_id: Identifier of a completed portfolio run.
        scenario_names: Subset of scenarios to bind, or None for all.

    Returns:
        ``dict[scenario_name, DealRunInput]`` with one entry per requested
        scenario.

    Raises:
        ValueError: If the source run is not completed, or any requested
            scenario is not present in the run.
    """
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

    group_names = manifest.get("group_names") or []
    loan_count = manifest.get("loan_count")
    market_date = manifest.get("created_at")

    deal_inputs: dict[str, DealRunInput] = {}
    for scenario_name in selected:
        prefix = _safe_artifact_name(scenario_name)

        if group_names:
            # Grouped run: prefer per-group artifacts.  If they're all
            # missing for this scenario, fall through to the aggregate
            # artifact so a partially-built run remains usable.
            group_dfs = _load_group_dataframes(run_id, prefix, group_names)
            if group_dfs:
                deal_inputs[scenario_name] = from_grouped_portfolio_cashflows(
                    group_dfs,
                    loan_count=loan_count,
                    market_date=market_date,
                )
                continue

        # Single-pool path (or grouped run with missing per-group artifacts):
        # use the aggregate artifact.
        agg_section = f"{prefix}_portfolio_actual"
        df = run_store.load_artifact(run_id, agg_section)
        deal_inputs[scenario_name] = from_portfolio_cashflow(
            df,
            loan_count=loan_count,
            market_date=market_date,
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
