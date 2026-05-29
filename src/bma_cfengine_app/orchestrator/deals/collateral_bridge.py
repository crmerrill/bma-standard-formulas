"""Build DealRunInput payloads from either Run Setup refs or deal-native inputs.

RG2 (May 2026): the bridge prefers the true per-loan PAIRED artifact when
available — ``{prefix}_portfolio_paired`` — which serializes all per-loan
BMAActualCashflow constituents in long format. Loading this artifact gives
the deal runtime genuine per-loan visibility (``loans`` expression accessor,
``constituents_by_group``) instead of one synthetic aggregate constituent.
Falls back to the LDCMA-adapter path when the PAIRED artifact is absent
(backward compatibility with runs produced before this change).

Phase 1g (May 2026): the bridge now produces ``PairedCollateralInput``
payloads (BMA-native PortfolioCashflow) for both single-pool and grouped
runs. The legacy ``from_portfolio_cashflow`` / ``from_grouped_portfolio_cashflows``
LDCMA adapters are wrapped via ``ldcma_to_paired`` so the deal runtime
consumes the BMA-native PAIRED branch end-to-end. Bond outputs are
bit-identical to the pre-1g LDCMA path (Phase 1e parity tests).

Phase 0C (May 2026): the bridge reads per-group portfolio artifacts when
the source run was grouped, producing a multi-group payload that the
deal runtime routes via ``GROUP_<id>_*`` source tokens.

The bridge is tightly coupled to the orchestrator's artifact-naming
convention (see ``run_service._execute_single_scenario``):

    {prefix}_portfolio_paired                  - per-loan PAIRED (RG2, preferred)
    {prefix}_portfolio_actual                  - aggregate (fallback)
    {prefix}_group_{safe_group_id}_actual      - per group (grouped, fallback)

The PAIRED artifact is selected when present; aggregate fallback is used
with an explicit ``per_loan_visibility=false`` metadata note when absent.
"""
from __future__ import annotations

import logging
import re
import warnings
from typing import Any

_logger = logging.getLogger(__name__)

from bma_standard_formulas.deals.adapters import (
    from_grouped_portfolio_cashflows,
    from_portfolio_cashflow,
    ldcma_to_paired,
)
from bma_standard_formulas.deals.schemas.input import DealRunInput, PairedCollateralInput

from ...orchestrator.run_service import _read_paired_artifact
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

        # ── Preferred path: per-loan PAIRED artifact (RG2 / OA-B2) ─────────
        # Primary: consult ArtifactRef catalog for the paired artifact.
        # Fallback: path-convention lookup (pre-OA-B2 runs without catalog).
        paired_artifact_name = f"{prefix}_portfolio_paired"
        plv_error: str | None = None

        # OA-B2: Read per_loan_visibility error from ArtifactRef catalog first,
        # then fall back to legacy per_loan_visibility manifest section.
        from ...orchestrator.artifact_catalog import artifact_ref_from_dict
        paired_ref_dict = run_store.get_artifact_ref(run_id, paired_artifact_name)
        paired_ref = artifact_ref_from_dict(paired_ref_dict) if paired_ref_dict else None
        # skip_paired: True when catalog says artifact is invalid (checksum mismatch /
        # file missing). We do NOT fall back to _read_paired_artifact in that case
        # because the catalog's integrity verdict is authoritative.
        skip_paired = False
        if paired_ref is not None:
            # Artifact exists in catalog — verify checksum if available.
            if paired_ref.checksum:
                try:
                    from ...storage.run_store import _artifact_path as _ap
                    _apath = _ap(run_id, paired_artifact_name)
                    from ...orchestrator.artifact_catalog import verify_checksum
                    if not verify_checksum(_apath, paired_ref.checksum):
                        # Emit both a structured log and a UserWarning so the
                        # mismatch is visible in both server logs and client-facing
                        # warning streams (e.g., test captures with catch_warnings).
                        _checksum_msg = (
                            f"Run {run_id!r} scenario {scenario_name!r}: "
                            f"paired artifact {paired_artifact_name!r} checksum mismatch "
                            f"— expected {paired_ref.checksum!r}, artifact may be corrupt. "
                            f"Falling back to aggregate path. [per_loan_visibility=false]"
                        )
                        _logger.warning(_checksum_msg)
                        warnings.warn(_checksum_msg, UserWarning, stacklevel=2)
                        paired_ref = None
                        skip_paired = True
                except FileNotFoundError:
                    paired_ref = None
                    skip_paired = True  # file missing per catalog; skip attempted read
        else:
            # Legacy run without ArtifactRef catalog — read error from old manifest key.
            plv_manifest = manifest.get("per_loan_visibility") or {}
            plv_for_scenario = plv_manifest.get(scenario_name, {})
            plv_error = plv_for_scenario.get("per_loan_visibility_error")

        constituents = [] if skip_paired else _read_paired_artifact(run_id, paired_artifact_name)
        if constituents:
            from bma_standard_formulas.engine import PortfolioCashflow
            from bma_standard_formulas.engine.portfolio import PortfolioMode
            portfolio = PortfolioCashflow(
                constituents=constituents,
                mode=PortfolioMode.ACTUAL_ONLY,
            )
            deal_inputs[scenario_name] = DealRunInput(
                collateral=PairedCollateralInput(portfolio=portfolio),
                original_collateral_balance=float(
                    manifest.get("original_collateral_balance") or 0.0
                ),
                loan_count=loan_count or len(constituents),
            )
            continue

        # ── Fallback path: LDCMA-format aggregate artifacts ──────────────────
        # Produces one synthetic constituent per group (or one for the whole
        # pool). Per-loan visibility is NOT available on this path. Emits a
        # warning so operators can identify runs that need to be regenerated.
        # OA-B2: Include ArtifactRef status in warning for actionable diagnostics.
        if paired_ref is not None and paired_ref.per_loan_visibility is False:
            plv_error = "ArtifactRef.per_loan_visibility=false (aggregate-only artifact)"
        plv_detail = f" Recorded error: {plv_error}" if plv_error else ""
        warnings.warn(
            f"Run {run_id!r} scenario {scenario_name!r}: per-loan PAIRED artifact "
            f"not found; falling back to aggregate-only LDCMA adapter. "
            f"Per-loan expression access (loans, loans_by_group) will be unavailable.{plv_detail} "
            f"Re-run the portfolio to regenerate. [per_loan_visibility=false]",
            UserWarning,
            stacklevel=2,
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)

            if group_names:
                group_dfs = _load_group_dataframes(run_id, prefix, group_names)
                if group_dfs:
                    ldcma_input = from_grouped_portfolio_cashflows(
                        group_dfs,
                        loan_count=loan_count,
                        market_date=market_date,
                    )
                    deal_inputs[scenario_name] = ldcma_to_paired(ldcma_input)
                    continue

            agg_section = f"{prefix}_portfolio_actual"
            df = run_store.load_artifact(run_id, agg_section)
            ldcma_input = from_portfolio_cashflow(
                df,
                loan_count=loan_count,
                market_date=market_date,
            )
            deal_inputs[scenario_name] = ldcma_to_paired(ldcma_input)

    return deal_inputs


def _reject_paired_in_json(payload: Any) -> None:
    """Raise ValueError if a raw JSON payload specifies PAIRED collateral mode.

    ``PortfolioCashflow`` is an in-process engine object and cannot be
    deserialized from JSON. Callers that need PAIRED input must supply a
    ``runsetup_ref`` source so the bridge reconstructs the portfolio from
    persisted per-loan artifacts, not from a raw JSON body.
    """
    if not isinstance(payload, dict):
        return
    coll = payload.get("collateral") or {}
    if isinstance(coll, dict) and coll.get("mode") == "PAIRED":
        raise ValueError(
            "collateral.mode='PAIRED' is not accepted via HTTP JSON. "
            "PortfolioCashflow cannot be serialized or deserialized from JSON. "
            "Use source_mode='runsetup_ref' to reference a server-side "
            "PortfolioCashflow artifact instead."
        )


def build_from_deal_native(source_payload: dict[str, Any]) -> dict[str, DealRunInput]:
    """Build run input(s) from explicit deal-local collateral payloads."""
    if "scenario_inputs" in source_payload:
        scenario_inputs = source_payload["scenario_inputs"] or {}
        out: dict[str, DealRunInput] = {}
        for scenario_name, payload in scenario_inputs.items():
            _reject_paired_in_json(payload)
            out[scenario_name] = DealRunInput.model_validate(payload)
        if out:
            return out

    run_input = source_payload.get("run_input")
    if run_input is None:
        raise ValueError("deal_native source requires run_input or scenario_inputs")
    _reject_paired_in_json(run_input)
    scenario_name = source_payload.get("scenario_name", "Base Case")
    return {scenario_name: DealRunInput.model_validate(run_input)}
