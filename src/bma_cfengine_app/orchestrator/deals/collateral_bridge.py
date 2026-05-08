"""Build DealRunInput payloads from either Run Setup refs or deal-native inputs.

Phase 1g (May 2026): the bridge now produces ``PairedCollateralInput``
payloads (BMA-native PortfolioCashflow) for both single-pool and grouped
runs. The legacy ``from_portfolio_cashflow`` / ``from_grouped_portfolio_cashflows``
LDCMA adapters are wrapped via ``ldcma_to_paired`` so the deal runtime
consumes the BMA-native PAIRED branch end-to-end. Bond outputs are
bit-identical to the pre-1g LDCMA path (Phase 1e parity tests).

Phase 0C (May 2026): the bridge reads per-group portfolio artifacts when
the source run was grouped, producing a multi-group payload that the
deal runtime routes via ``GROUP_<id>_*`` source tokens.  Pre-Phase-0C the
bridge always read only the aggregate artifact, which meant multi-group
deals could not be wired to a Run-Setup-driven portfolio run from the UI.

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
import warnings
from typing import Any

from bma_standard_formulas.deals.adapters import (
    from_grouped_portfolio_cashflows,
    from_portfolio_cashflow,
    ldcma_to_paired,
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
    name.  The collateral payload is always a ``PairedCollateralInput``
    (Phase 1g, May 2026) wrapping a BMA-native ``PortfolioCashflow``:

      - Single-pool runs (manifest ``group_names`` empty) yield a
        portfolio with one ACTUAL_ONLY constituent, synthesized from
        the aggregate portfolio artifact.
      - Grouped runs yield a portfolio with one ACTUAL_ONLY constituent
        per group, each tagged with its original ``group_id`` from the
        manifest.  The runtime's ``aggregate_actual_by_group()``
        partitions the constituents back into per-group aggregates so
        ``GROUP_<id>_*`` source-token routing works.

    Both paths reuse the engine output directly — there is no engine
    re-invocation here.  The legacy LDCMA-format adapters
    (``from_portfolio_cashflow`` / ``from_grouped_portfolio_cashflows``)
    are wrapped via ``ldcma_to_paired`` so the runtime consumes the
    BMA-native PAIRED branch end-to-end.

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

        # The bridge bridges DataFrame artifacts to the BMA-native PAIRED
        # input via the LDCMA-format adapters as a transitional step.
        # The adapters emit DeprecationWarning (Phase 1h) but the bridge
        # IS the migration machinery here, so suppress at the call site —
        # we're not a caller that should be alerted to migrate.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)

            if group_names:
                # Grouped run: prefer per-group artifacts.  If they're all
                # missing for this scenario, fall through to the aggregate
                # artifact so a partially-built run remains usable.
                group_dfs = _load_group_dataframes(run_id, prefix, group_names)
                if group_dfs:
                    ldcma_input = from_grouped_portfolio_cashflows(
                        group_dfs,
                        loan_count=loan_count,
                        market_date=market_date,
                    )
                    deal_inputs[scenario_name] = ldcma_to_paired(ldcma_input)
                    continue

            # Single-pool path (or grouped run with missing per-group artifacts):
            # use the aggregate artifact.
            agg_section = f"{prefix}_portfolio_actual"
            df = run_store.load_artifact(run_id, agg_section)
            ldcma_input = from_portfolio_cashflow(
                df,
                loan_count=loan_count,
                market_date=market_date,
            )
            deal_inputs[scenario_name] = ldcma_to_paired(ldcma_input)

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
