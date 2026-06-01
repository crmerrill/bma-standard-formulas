"""HTTP API for Structuring Studio + structured deal run/solve workflows."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from bma_standard_formulas.deals.schemas.input import DealRunInput
from bma_standard_formulas.deals.schemas.ir import DealDefinition
from bma_standard_formulas.deals.schemas.migrations import (
    migrate_deal_payload,
    LEGACY_RULE_TYPE_MAP,
    LEGACY_TRANCHE_KIND_MAP as _MIGRATIONS_TRANCHE_KIND_MAP,
)
from bma_standard_formulas.deals.schemas.solver import (
    ConstraintComparison,
    ObjectiveType,
    SolverSpec,
    WaterfallTargetPrimitive,
)

from ...orchestrator.deals.collateral_bridge import (
    build_from_deal_native,
    build_from_runsetup_ref,
)
from ...orchestrator.deals.deal_run_service import execute_deal_run
from ...orchestrator.deals.deal_solver_service import execute_deal_solve
from ...orchestrator.deals.deal_solver_service import (
    get_solver_progress,
    request_solver_cancel,
)
from ...orchestrator.deals.deal_store import (
    deal_dir,
    list_pool_snapshots,
    list_studio_deals,
    load_deal,
    load_pool_snapshot,
    list_solver_presets,
    load_studio_snapshot,
    save_pool_snapshot,
    save_deal as save_canonical_deal,
    save_solver_preset,
    save_studio_ir,
)
from ...orchestrator.deals.git_service import GitService, GitServiceError, InvalidBranchNameError
from ...orchestrator.deals.operational import export_deal
from ...orchestrator.deals.solver_catalog import build_solver_catalog
from ...orchestrator.deals.solver_templates import (
    all_templates,
    get_template,
    instantiate_template,
    list_templates_for_deal,
    template_view_for_deal,
)
from ...orchestrator.deals.psa_schedule_overlay import PoolDerivationInputs, build_psa_schedule_overlay
from ...orchestrator.deals.structuring_verification import verify_structure
from bma_standard_formulas.deals.schemas.solver_template import (
    TemplateInstantiationRequest,
    TemplateInstantiationResponse,
)
from ...orchestrator.run_service import get_cashflow_preview, list_all_runs
from ...storage import run_store

router = APIRouter(tags=["deals"])

_LEGACY_FEE_BASIS_MAP = {
    "PCT_POOL": "COLLATERAL_BALANCE",
}

_LEGACY_TRIGGER_METRIC_MAP = {
    "CUM_LOSS": "CUMULATIVE_LOSS",
    "CUM_DEFAULT": "CUMULATIVE_DEFAULT",
    "DELINQUENCY": "DELINQUENCY_RATE",
    "OC_RATIO": "OC_TEST",
    "IC_RATIO": "IC_TEST",
}

_LEGACY_RULE_SOURCE_MAP = {
    "COLLECTION": "CASH",
    # Preserve split-stream semantics: INT_COLLECTION carries interest-only
    # cash and must map to ACT_INT, not collapse to the combined CASH stream.
    # Similarly PRIN_COLLECTION → ACT_PRIN. Collapsing to CASH loses the
    # intent of rules that were authored against the split streams.
    "PRIN_COLLECTION": "ACT_PRIN",
    "INT_COLLECTION": "ACT_INT",
    "DISTRIBUTION": "CASH",
    "RESERVE": "CASH",
    "PREFUNDING": "CASH",
    "CAP_INTEREST": "CASH",
    "EXPENSE": "CASH",
    "REINVESTMENT": "CASH",
    "SWAP_HEDGE": "CASH",
    "ESCROW": "CASH",
    "YIELD_SUPPLEMENT": "CASH",
}

# Re-use the canonical map from the migration module so there is a single
# source of truth.  The local alias keeps call-sites in this file unchanged.
_LEGACY_TRANCHE_KIND_MAP = _MIGRATIONS_TRANCHE_KIND_MAP


class StudioDealSaveBody(BaseModel):
    deal_id: str | None = None
    deal_name: str = Field(default="Deal", min_length=1, max_length=256)
    ir: dict[str, Any]


class RunSetupRefSource(BaseModel):
    source_mode: Literal["runsetup_ref"] = "runsetup_ref"
    run_id: str
    scenario_names: list[str] | None = None


class DealNativeSource(BaseModel):
    source_mode: Literal["deal_native"] = "deal_native"
    run_input: dict[str, Any] | None = None
    scenario_name: str = "Base Case"
    scenario_inputs: dict[str, dict[str, Any]] | None = None


DealRunSource = Annotated[
    RunSetupRefSource | DealNativeSource,
    Field(discriminator="source_mode"),
]


class DealRunRequest(BaseModel):
    deal_version: int | None = None
    source: DealRunSource
    scenario_names: list[str] | None = None

    @model_validator(mode="after")
    def _validate_source(self) -> "DealRunRequest":
        if (
            isinstance(self.source, DealNativeSource)
            and not self.source.run_input
            and not self.source.scenario_inputs
        ):
            raise ValueError("deal_native source requires run_input or scenario_inputs")
        return self


class DealSolveRequest(BaseModel):
    deal_version: int | None = None
    source: DealRunSource
    solver_spec: SolverSpec
    scenario_name: str = "Base Case"


class SolverPresetUpsertBody(BaseModel):
    preset_name: str = Field(min_length=1, max_length=128)
    solver_spec: dict[str, Any]
    notes: str | None = None


class PoolSnapshotSaveBody(BaseModel):
    pool_id: str | None = None
    pool_name: str = Field(min_length=1, max_length=256)
    payload: dict[str, Any] = Field(default_factory=dict)


class SolverTypedEnumsResponse(BaseModel):
    objective_types: list[ObjectiveType]
    constraint_comparisons: list[ConstraintComparison]
    waterfall_target_primitives: list[WaterfallTargetPrimitive]


class SolverTemplateFamilyResponse(BaseModel):
    family: Literal["PRIME_JUMBO", "NON_QM_QRM", "AGENCY"]
    targets: list[WaterfallTargetPrimitive]


class SolverCatalogResponse(BaseModel):
    deal_id: str
    metric_paths: list[str]
    knobs: list[dict[str, Any]]
    typed_enums: SolverTypedEnumsResponse
    template_families: list[SolverTemplateFamilyResponse]
    suggested_defaults: dict[str, Any]
    source_run_id: str | None = None


class StructuringVerificationResponse(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]
    suggestions: list[str]


class PoolDerivationRequestBody(BaseModel):
    balance: float = Field(gt=0)
    wac_pct: float = Field(gt=0)
    term_months: int = Field(gt=0)
    horizon_months: int = Field(gt=0, le=720)


class DerivePsaSchedulesRequest(BaseModel):
    ir: dict[str, Any]
    pool: PoolDerivationRequestBody


class ScheduleOverlayEntryResponse(BaseModel):
    schedule_contract: list[dict[str, Any]]
    schedule_derivation: dict[str, Any]


class DerivePsaSchedulesResponse(BaseModel):
    overlay: dict[str, ScheduleOverlayEntryResponse]
    derived_bond_names: list[str]


@router.post("/deals/derive-psa-schedules", response_model=DerivePsaSchedulesResponse)
async def derive_psa_schedules(body: DerivePsaSchedulesRequest):
    """Structuring-time PAC/TAC PSA schedule_contract overlay (Phase 1i).

    Validates studio IR, projects collateral principal at PSA speeds, and
    returns a per-bond patch for ``schedule_contract`` +
    ``schedule_derivation``. The UI merges this into Blockly-generated IR
    without rewriting blocks.
    """
    normalized_ir = _normalize_legacy_studio_ir(body.ir)
    try:
        canonical = DealDefinition.model_validate(migrate_deal_payload(normalized_ir))
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid deal IR: {exc}",
        ) from exc

    pool = PoolDerivationInputs(
        balance=float(body.pool.balance),
        wac_pct=float(body.pool.wac_pct),
        term_months=int(body.pool.term_months),
        horizon_months=int(body.pool.horizon_months),
    )
    raw_overlay = build_psa_schedule_overlay(canonical, pool)
    overlay: dict[str, ScheduleOverlayEntryResponse] = {}
    for name, payload in raw_overlay.items():
        overlay[name] = ScheduleOverlayEntryResponse(
            schedule_contract=list(payload["schedule_contract"]),
            schedule_derivation=dict(payload["schedule_derivation"]),
        )
    return DerivePsaSchedulesResponse(
        overlay=overlay,
        derived_bond_names=sorted(overlay.keys()),
    )


@router.get("/deals/pools")
async def list_pools(search: str | None = Query(None)):
    return {"items": list_pool_snapshots(search=search)}


@router.get("/deals/pools/{pool_id}")
async def get_pool(pool_id: str, version: int | None = Query(None)):
    try:
        return load_pool_snapshot(pool_id, version=version)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/deals/pools")
async def save_pool(body: PoolSnapshotSaveBody):
    try:
        _, meta = save_pool_snapshot(
            pool_id=body.pool_id,
            pool_name=body.pool_name.strip() or "Pool",
            payload=body.payload,
        )
        return meta
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/deals")
async def list_deals():
    return list_studio_deals()


@router.get("/deals/{deal_id}")
async def get_deal(deal_id: str, version: int | None = Query(None)):
    """Return a studio snapshot with legacy IR fields normalized to 2.0 form.

    The raw snapshot file is NOT modified. Normalization is applied in memory
    on each GET so the UI always receives 2.0-canonical `kind`, `account_category`,
    `notional`, `relations`, etc., regardless of when the deal was saved.

    Response shape:
      - `ir`: the normalized IR (always present)
      - `ir_display_normalized`: true when normalization was applied
      - `ir_original_schema_version`: the schema_version field as persisted on disk
      - `normalization_error`: present when normalization encountered an error;
        in that case `ir` contains the best-effort partial normalization and
        the error detail explains what manual fix is needed.
    """
    try:
        snapshot = load_studio_snapshot(deal_id, version=version)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    if not isinstance(snapshot, dict):
        return snapshot

    raw_ir = snapshot.get("ir")
    if not isinstance(raw_ir, dict):
        return snapshot

    original_schema_version = raw_ir.get("schema_version")
    normalization_error: str | None = None
    migrated_ir: dict = raw_ir

    schema_validation_error: str | None = None
    try:
        normalized_ir = _normalize_legacy_studio_ir(raw_ir)
        migrated_ir = migrate_deal_payload(normalized_ir)
        # Attempt schema validation so the UI can surface structural errors early.
        # Failures here do NOT block the GET — we return the normalized IR plus
        # a `schema_validation_error` field so callers can decide whether to show
        # a warning or require fixes before allowing a run.
        try:
            DealDefinition.model_validate(migrated_ir)
        except Exception as ve:
            import pydantic
            if isinstance(ve, pydantic.ValidationError):
                # Omit input data from error messages to keep responses compact.
                schema_validation_error = "; ".join(
                    e.get("msg", str(e))
                    for e in ve.errors(include_input=False)
                )
            else:
                schema_validation_error = str(ve)
    except ValueError as exc:
        # ValueError from migrate_deal_payload means an ambiguous field that
        # requires manual intervention (e.g. PAY_FROM_RESERVE).  Return the
        # best-effort normalized form (pre-migration) plus an actionable error.
        normalization_error = str(exc)
        try:
            migrated_ir = _normalize_legacy_studio_ir(raw_ir)
        except Exception:
            migrated_ir = raw_ir
    except Exception as exc:
        normalization_error = f"Unexpected normalization error: {exc}"
        migrated_ir = raw_ir

    response = {
        **snapshot,
        "ir": migrated_ir,
        "ir_display_normalized": migrated_ir is not raw_ir,
        "ir_original_schema_version": original_schema_version,
    }
    if normalization_error:
        response["normalization_error"] = normalization_error
    if schema_validation_error:
        response["schema_validation_error"] = schema_validation_error
    return response


@router.post("/deals")
async def save_deal(body: StudioDealSaveBody):
    try:
        deal_id, meta = save_studio_ir(
            body.deal_id,
            body.deal_name.strip() or "Deal",
            body.ir,
        )
        # Keep canonical deal snapshots synchronized with studio saves so subsequent
        # runs/solves always pick up latest sizing/coupon edits.
        try:
            normalized_ir = _normalize_legacy_studio_ir(body.ir)
            canonical = DealDefinition.model_validate(migrate_deal_payload(normalized_ir))
            save_canonical_deal(deal_id, canonical, version=int(meta.get("version", 0) or 0))
        except Exception:
            # Studio saves remain source-of-truth even if canonical conversion fails.
            pass
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return meta


@router.get("/deals/{deal_id}/export")
def export_endpoint(deal_id: str, sha: str = Query(...)) -> Response:
    """Export the canonical deal.json at a specific commit SHA."""
    try:
        payload = export_deal(deal_id, sha)
    except GitServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=payload, media_type="application/json")


def _ensure_canonical_deal(deal_id: str, version: int | None = None):
    try:
        return load_deal(deal_id, version=version)
    except FileNotFoundError:
        snapshot = load_studio_snapshot(deal_id, version=version)
        raw_ir = snapshot.get("ir", {})
        normalized_ir = _normalize_legacy_studio_ir(raw_ir)
        try:
            # Always validate the normalized view so legacy snapshots are transparently upgraded.
            canonical = DealDefinition.model_validate(migrate_deal_payload(normalized_ir))
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot convert studio snapshot to canonical DealDefinition: {exc}",
            ) from exc
        save_canonical_deal(deal_id, canonical, version=version)
        return canonical


def _normalize_legacy_studio_ir(raw_ir: Any) -> dict[str, Any]:
    if not isinstance(raw_ir, dict):
        return {}

    # Only normalize known IR sections. Opaque metadata fields like
    # `studio_workspace_state`, `solver_presets`, `run_history`, etc. must
    # not be walked — their internal structure is uncontrolled and any key
    # that happens to match a legacy field name (e.g. `kind`, `rule_type`,
    # `from_sources`) would be silently rewritten.
    _NORMALIZABLE_IR_KEYS = frozenset({
        "bonds", "accounts", "fees", "triggers", "waterfall_rules",
        "calculations", "collateral_groups", "source_formulas",
    })

    def normalize_node(node: Any) -> Any:
        if isinstance(node, list):
            return [normalize_node(item) for item in node]
        if not isinstance(node, dict):
            return node

        next_node: dict[str, Any] = {k: v for k, v in node.items()}
        for key in list(next_node.keys()):
            if isinstance(next_node[key], (dict, list)):
                next_node[key] = normalize_node(next_node[key])

        basis = next_node.get("basis_type")
        if isinstance(basis, str) and basis in _LEGACY_FEE_BASIS_MAP:
            legacy_basis = basis
            next_node["basis_type"] = _LEGACY_FEE_BASIS_MAP[legacy_basis]
            if legacy_basis == "PCT_POOL":
                # Legacy snapshots may store bps either in `bps` or `amount`.
                bps = next_node.get("bps")
                if isinstance(bps, (int, float)):
                    next_node.setdefault("rate", float(bps) / 100.0)
                elif (
                    "rate" not in next_node
                    and isinstance(next_node.get("amount"), (int, float))
                    and float(next_node.get("amount") or 0.0) > 0.0
                ):
                    next_node["rate"] = float(next_node["amount"]) / 100.0
                next_node.setdefault("amount", 0.0)
            next_node.setdefault("frequency", "MONTHLY")
        elif isinstance(next_node.get("basis"), str) and next_node.get("basis_type") is None:
            legacy_basis = str(next_node["basis"])
            if legacy_basis in _LEGACY_FEE_BASIS_MAP:
                next_node["basis_type"] = _LEGACY_FEE_BASIS_MAP[legacy_basis]

        metric = next_node.get("metric_type")
        if isinstance(metric, str) and metric in _LEGACY_TRIGGER_METRIC_MAP:
            next_node["metric_type"] = _LEGACY_TRIGGER_METRIC_MAP[metric]
        elif isinstance(next_node.get("metric"), str) and next_node.get("metric_type") is None:
            legacy_metric = str(next_node["metric"])
            if legacy_metric in _LEGACY_TRIGGER_METRIC_MAP:
                next_node["metric_type"] = _LEGACY_TRIGGER_METRIC_MAP[legacy_metric]

        if isinstance(next_node.get("from_sources"), list):
            normalized_sources: list[Any] = []
            for source in next_node["from_sources"]:
                if isinstance(source, str) and source in _LEGACY_RULE_SOURCE_MAP:
                    normalized_sources.append(_LEGACY_RULE_SOURCE_MAP[source])
                else:
                    normalized_sources.append(source)
            next_node["from_sources"] = normalized_sources

        # Hard-cut TrancheKind migration: normalize legacy kind/type/behavior
        # payloads before schema validation.
        kind_value = next_node.get("kind")
        if isinstance(kind_value, str) and kind_value in _LEGACY_TRANCHE_KIND_MAP:
            next_node["kind"] = _LEGACY_TRANCHE_KIND_MAP[kind_value]
        elif isinstance(next_node.get("tranche_behavior"), str):
            legacy = str(next_node["tranche_behavior"])
            mapped = _LEGACY_TRANCHE_KIND_MAP.get(legacy)
            if mapped:
                next_node["kind"] = mapped
        elif isinstance(next_node.get("tranche_type"), str):
            legacy = str(next_node["tranche_type"])
            mapped = _LEGACY_TRANCHE_KIND_MAP.get(legacy)
            if mapped:
                next_node["kind"] = mapped
        if "tranche_type" in next_node:
            next_node.pop("tranche_type", None)
        if "tranche_behavior" in next_node:
            next_node.pop("tranche_behavior", None)

        # Normalize removed rule types so that legacy studio snapshots survive
        # migration even when loaded through the API normalizer path.
        rule_type = next_node.get("rule_type")
        if isinstance(rule_type, str) and rule_type in LEGACY_RULE_TYPE_MAP:
            new_rule_type, default_mode = LEGACY_RULE_TYPE_MAP[rule_type]
            next_node["rule_type"] = new_rule_type
            next_node.setdefault("coverage_mode", default_mode)

        return next_node

    # Build the result: only recurse into known IR sections; copy all other
    # top-level keys (workspace state, solver presets, metadata) unchanged.
    result: dict[str, Any] = {}
    for key, value in raw_ir.items():
        if key in _NORMALIZABLE_IR_KEYS:
            result[key] = normalize_node(value)
        else:
            result[key] = value
    return result


def _build_inputs(
    source: DealRunSource,
    scenario_names: list[str] | None,
) -> dict[str, DealRunInput]:
    if isinstance(source, RunSetupRefSource):
        return build_from_runsetup_ref(
            source.run_id,
            scenario_names=scenario_names or source.scenario_names,
        )
    return build_from_deal_native(source.model_dump())


def _verify_or_raise(deal: DealDefinition, *, mode: str) -> dict[str, Any]:
    verification = verify_structure(deal, scenario_context={"mode": mode})
    if verification.get("valid"):
        return verification
    raise HTTPException(
        status_code=422,
        detail={
            "message": "Structuring verification failed. Resolve blocking compatibility errors.",
            "verification": verification,
        },
    )


def _extract_collateral_risk_settings(deal_id: str, version: int | None) -> dict[str, Any]:
    try:
        snapshot = load_studio_snapshot(deal_id, version=version)
    except FileNotFoundError:
        return {}
    ir = snapshot.get("ir", {}) if isinstance(snapshot, dict) else {}
    if not isinstance(ir, dict):
        return {}
    presets = ir.get("solver_presets", {})
    if not isinstance(presets, dict):
        return {}
    payload = presets.get("collateral_risk_settings", {})
    return payload if isinstance(payload, dict) else {}


@router.post("/deals/{deal_id}/runs")
async def run_deal_endpoint(deal_id: str, body: DealRunRequest):
    canonical = _ensure_canonical_deal(deal_id, version=body.deal_version)
    _verify_or_raise(canonical, mode="run")
    try:
        scenario_inputs = _build_inputs(body.source, body.scenario_names)
        collateral_risk_settings = _extract_collateral_risk_settings(deal_id, body.deal_version)
        first = next(iter(scenario_inputs.values()))
        run_id = run_store.new_run_id()
        return execute_deal_run(
            run_id=run_id,
            deal_id=deal_id,
            deal_version=body.deal_version,
            run_input=first,
            run_inputs_by_scenario=scenario_inputs,
            source_mode=body.source.source_mode,
            run_kind="deal_run",
            collateral_risk_settings=collateral_risk_settings,
        ) | {"run_id": run_id}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/deals/{deal_id}/solve")
async def solve_deal_endpoint(deal_id: str, body: DealSolveRequest):
    canonical = _ensure_canonical_deal(deal_id, version=body.deal_version)
    _verify_or_raise(canonical, mode="solve")
    try:
        scenario_inputs = _build_inputs(body.source, [body.scenario_name])
        collateral_risk_settings = _extract_collateral_risk_settings(deal_id, body.deal_version)
        run_input = scenario_inputs.get(body.scenario_name) or next(iter(scenario_inputs.values()))
        run_id = run_store.new_run_id()
        thread = threading.Thread(
            target=execute_deal_solve,
            kwargs={
                "run_id": run_id,
                "deal_id": deal_id,
                "deal_version": body.deal_version,
                "run_input": run_input,
                "solver_spec": body.solver_spec,
                "scenario_name": body.scenario_name,
                "source_mode": body.source.source_mode,
                "collateral_risk_settings": collateral_risk_settings,
            },
            daemon=True,
        )
        thread.start()
        return {
            "status": "running",
            "run_type": "structured_deal",
            "run_kind": "solver",
            "deal_id": deal_id,
            "scenario_names": [body.scenario_name],
            "run_id": run_id,
            "progress_handle": {"run_id": run_id},
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/deals/{deal_id}/runs/{run_id}/progress")
async def get_deal_solver_progress(deal_id: str, run_id: str):
    try:
        progress = get_solver_progress(run_id)
    except FileNotFoundError:
        try:
            manifest = run_store.load_manifest(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if manifest.get("deal_id") != deal_id:
            raise HTTPException(
                status_code=404,
                detail=f"Run {run_id} not found for deal {deal_id}",
            )
        return {
            "run_id": run_id,
            "deal_id": deal_id,
            "status": manifest.get("status", "unknown"),
            "stage": "completed",
            "iteration": manifest.get("solver_summary", {}).get("total_iterations", 0),
            "cancel_requested": False,
            "diagnostic_artifacts": (
                (manifest.get("solver_diagnostics", {}) or {}).get("diagnostic_artifacts", [])
            ),
        }
    if progress.get("deal_id") != deal_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found for deal {deal_id}")
    return progress


@router.post("/deals/{deal_id}/runs/{run_id}/cancel")
async def cancel_deal_solver_run(deal_id: str, run_id: str):
    try:
        state = request_solver_cancel(run_id)
    except FileNotFoundError as exc:
        manifest = run_store.load_manifest(run_id)
        if manifest.get("deal_id") != deal_id:
            raise HTTPException(
                status_code=404,
                detail=f"Run {run_id} not found for deal {deal_id}",
            ) from exc
        return {
            "run_id": run_id,
            "deal_id": deal_id,
            "status": manifest.get("status"),
            "cancel_requested": False,
            "detail": "Run already completed or not cancellable.",
        }
    if state.get("deal_id") != deal_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found for deal {deal_id}")
    return {
        "run_id": run_id,
        "deal_id": deal_id,
        "status": state.get("status", "running"),
        "cancel_requested": True,
    }


@router.get("/deals/{deal_id}/runs")
async def list_deal_runs(deal_id: str, run_kind: str | None = Query(None)):
    all_runs = list_all_runs()
    runs = [r for r in all_runs if r.get("deal_id") == deal_id and r.get("run_type") == "structured_deal"]
    if run_kind:
        runs = [r for r in runs if r.get("run_kind") == run_kind]
    return runs


@router.get("/deals/{deal_id}/solver-runs")
async def list_solver_runs(deal_id: str):
    return await list_deal_runs(deal_id, run_kind="solver")


@router.get("/deals/{deal_id}/solver-catalog", response_model=SolverCatalogResponse)
async def get_solver_catalog(deal_id: str):
    """Legacy raw-knob solver catalog. New code should use the
    outcome-led template endpoints below (``solver-templates``) -- the
    catalog is preserved as a level-3 advanced fallback per the solver
    UX design doc.
    """
    canonical = _ensure_canonical_deal(deal_id, version=None)
    return build_solver_catalog(deal_id, canonical)


# ---------------------------------------------------------------------------
# Outcome-led solver templates (the new "Solve for X" cards).
#
# See ``docs/architecture/solver_ux_design.md`` for the design contract.
# These endpoints are the bridge between the Python template registry
# and the Structuring Studio level-1 cards. Every endpoint goes through
# ``_ensure_canonical_deal`` so the deal IR is migrated/normalized
# before any template logic resolves knobs against it.
# ---------------------------------------------------------------------------


@router.get("/deals/{deal_id}/solver-templates")
async def list_solver_templates(deal_id: str, version: int | None = Query(None)):
    """Return all registered solver templates with deal-aware defaults baked in.

    Drives the level-1 "Solve for..." cards on the DealEditor. Each
    entry includes the template metadata (title, summary, tooltips,
    primary input, locked aspects) plus ``resolved_knobs`` and
    ``resolved_constraints`` materialized against this specific deal's
    current bond coupons / sizes / fees. The UI renders one card per
    entry without needing to know the IR structure.
    """
    canonical = _ensure_canonical_deal(deal_id, version=version)
    views = list_templates_for_deal(canonical)
    return {
        "deal_id": deal_id,
        "templates": [view.model_dump() for view in views],
    }


@router.get("/deals/{deal_id}/solver-templates/{template_id}")
async def get_solver_template(
    deal_id: str,
    template_id: str,
    version: int | None = Query(None),
):
    """Return a single template view (template + deal-aware defaults).

    Used when the user opens the customize panel and the UI needs to
    display the resolved knob list and constraint defaults for one
    specific template.
    """
    try:
        template = get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    canonical = _ensure_canonical_deal(deal_id, version=version)
    view = template_view_for_deal(canonical, template)
    return view.model_dump()


@router.post(
    "/deals/{deal_id}/solver-templates/{template_id}/instantiate",
    response_model=TemplateInstantiationResponse,
)
async def instantiate_solver_template(
    deal_id: str,
    template_id: str,
    request: TemplateInstantiationRequest,
    version: int | None = Query(None),
):
    """Apply the user's level-1 + level-2 edits to produce a runnable SolverSpec.

    The user has picked a target value (level-1) and optionally edited
    knob bounds, locked specific knobs, or overridden constraints
    (level-2). This endpoint returns the resolved ``SolverSpec`` ready
    to POST to ``/deals/{id}/solve`` -- the Studio can pass the spec
    straight through to the existing solver service unchanged.
    """
    try:
        template = get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    canonical = _ensure_canonical_deal(deal_id, version=version)
    try:
        return instantiate_template(canonical, template, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/deals/{deal_id}/verify-structure", response_model=StructuringVerificationResponse)
async def verify_deal_structure(deal_id: str, version: int | None = Query(None)):
    canonical = _ensure_canonical_deal(deal_id, version=version)
    return verify_structure(canonical, scenario_context={"mode": "verify"})


@router.get("/deals/{deal_id}/solver-presets")
async def get_solver_presets(deal_id: str):
    try:
        return {"deal_id": deal_id, "presets": list_solver_presets(deal_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/deals/{deal_id}/solver-presets")
async def upsert_solver_preset(deal_id: str, body: SolverPresetUpsertBody):
    try:
        saved = save_solver_preset(
            deal_id=deal_id,
            preset_name=body.preset_name.strip(),
            solver_spec=body.solver_spec,
            notes=body.notes,
        )
        return {"deal_id": deal_id, "preset": saved}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/deals/{deal_id}/run-sources")
async def list_deal_run_sources(
    deal_id: str,
    status: str | None = Query(None),
    run_type: str | None = Query(None),
    run_kind: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(25, ge=1, le=200),
    cursor: int = Query(0, ge=0),
):
    rows = [r for r in list_all_runs() if r.get("deal_id") == deal_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if run_type:
        rows = [r for r in rows if (r.get("run_type") or "") == run_type]
    if run_kind:
        rows = [r for r in rows if (r.get("run_kind") or "") == run_kind]
    if search:
        needle = search.lower().strip()
        rows = [
            r
            for r in rows
            if needle
            in " ".join(
                [
                    str(r.get("deal_name") or ""),
                    str(r.get("run_id") or ""),
                    " ".join(r.get("scenario_names") or []),
                ]
            ).lower()
        ]
    total = len(rows)
    page = rows[cursor : cursor + limit]
    next_cursor = cursor + limit if cursor + limit < total else None
    return {
        "deal_id": deal_id,
        "total": total,
        "limit": limit,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "items": page,
    }


@router.get("/deals/{deal_id}/runs/{run_id}")
async def get_deal_run(deal_id: str, run_id: str):
    manifest = run_store.load_manifest(run_id)
    if manifest.get("deal_id") != deal_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found for deal {deal_id}")
    return manifest


@router.get("/deals/{deal_id}/runs/{run_id}/artifacts")
async def list_deal_run_artifacts(deal_id: str, run_id: str):
    manifest = run_store.load_manifest(run_id)
    if manifest.get("deal_id") != deal_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found for deal {deal_id}")
    return {"run_id": run_id, "artifacts": run_store.list_artifacts(run_id)}


@router.get("/deals/{deal_id}/runs/{run_id}/artifacts/{artifact}")
async def preview_deal_run_artifact(
    deal_id: str,
    run_id: str,
    artifact: str,
    max_rows: int = 500,
):
    manifest = run_store.load_manifest(run_id)
    if manifest.get("deal_id") != deal_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found for deal {deal_id}")
    return get_cashflow_preview(run_id, artifact, max_rows=max_rows)


# ---------------------------------------------------------------------------
# Git version-control HTTP API (irvc-4-http-api)
# ---------------------------------------------------------------------------


class CommitRequest(BaseModel):
    author: str
    message: str
    parent_sha: str | None = None
    force: bool = False


class CommitResponse(BaseModel):
    sha: str


class GitBranchInfo(BaseModel):
    name: str
    tip_sha: str
    created_at: datetime


class GitBranchListResponse(BaseModel):
    branches: list[GitBranchInfo]


class BranchCreateRequest(BaseModel):
    name: str
    from_sha: str


class GitCommitMeta(BaseModel):
    sha: str
    author: str
    message: str
    committed_at: datetime
    parent_sha: str | None


class GitLogResponse(BaseModel):
    commits: list[GitCommitMeta]


class StructuralDiffEntry(BaseModel):
    path: str
    change: Literal["added", "removed", "modified"]
    a_value: Any | None = None
    b_value: Any | None = None


class GitDiffResponse(BaseModel):
    structural_diff: list[StructuralDiffEntry]


class GitMergeRequest(BaseModel):
    branch: str
    into: str = "main"


class MergeConflictPayload(BaseModel):
    code: str
    severity: str
    path: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)


class GitMergeResult(BaseModel):
    status: Literal["success", "conflict"]
    sha: str | None = None
    diagnostic: MergeConflictPayload | None = None


class MergeProgressEvent(BaseModel):
    event_type: Literal["merge_started", "entity_merged", "merge_complete", "merge_failed"]
    progress: float
    current_entity: str | None = None
    total_entities: int = 0
    sha: str | None = None
    diagnostic: dict[str, Any] | None = None


def _flatten_diff(
    a: Any,
    b: Any,
    prefix: str = "",
) -> list[dict[str, Any]]:
    """Recursively compute a flat list of diff entries between two values."""
    if a == b:
        return []
    if isinstance(a, dict) and isinstance(b, dict):
        entries: list[dict[str, Any]] = []
        for key in sorted(set(a) | set(b)):
            child = f"{prefix}.{key}" if prefix else key
            if key not in a:
                entries.append({"path": child, "change": "added", "a_value": None, "b_value": b[key]})
            elif key not in b:
                entries.append({"path": child, "change": "removed", "a_value": a[key], "b_value": None})
            else:
                entries.extend(_flatten_diff(a[key], b[key], prefix=child))
        return entries
    if isinstance(a, list) and isinstance(b, list):
        entries = []
        for i in range(max(len(a), len(b))):
            child = f"{prefix}[{i}]"
            a_item = a[i] if i < len(a) else None
            b_item = b[i] if i < len(b) else None
            entries.extend(_flatten_diff(a_item, b_item, prefix=child))
        return entries
    if a is None:
        return [{"path": prefix, "change": "added", "a_value": None, "b_value": b}]
    if b is None:
        return [{"path": prefix, "change": "removed", "a_value": a, "b_value": None}]
    return [{"path": prefix, "change": "modified", "a_value": a, "b_value": b}]


@router.post("/deals/{deal_id}/commit", response_model=CommitResponse)
def commit_deal_endpoint(deal_id: str, body: CommitRequest) -> CommitResponse:
    service = GitService(repo_path=deal_dir(deal_id))
    head_commits = service.log(branch="main", limit=1)
    head_sha = head_commits[0].sha if head_commits else None

    if not body.force and head_sha != body.parent_sha:
        # FUTURE: collaboration — replace last-writer-wins with merge UI
        raise HTTPException(
            status_code=409,
            detail={"code": "STALE_PARENT_SHA", "head_sha": head_sha},
        )

    current_payload = service.show(head_sha, "deal.json") if head_sha else b"{}"
    try:
        sha = service.commit_deal(
            current_payload,
            author=body.author,
            message=body.message,
            parent_sha=head_sha,
        )
    except GitServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return CommitResponse(sha=sha)


@router.get("/deals/{deal_id}/branches", response_model=GitBranchListResponse)
def list_branches(deal_id: str) -> GitBranchListResponse:
    service = GitService(repo_path=deal_dir(deal_id))
    try:
        raw_branches = service.branch_list()
    except GitServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    api_branches: list[GitBranchInfo] = []
    for b in raw_branches:
        commits = service.log(branch=b.name, limit=1)
        api_branches.append(GitBranchInfo(
            name=b.name,
            tip_sha=b.tip_sha,
            created_at=commits[0].committed_at if commits else datetime.now(timezone.utc),
        ))
    return GitBranchListResponse(branches=api_branches)


@router.post("/deals/{deal_id}/branches", response_model=GitBranchInfo, status_code=201)
def create_branch(deal_id: str, body: BranchCreateRequest) -> GitBranchInfo:
    service = GitService(repo_path=deal_dir(deal_id))
    try:
        service.branch_create(body.name, from_sha=body.from_sha)
    except InvalidBranchNameError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GitServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    commits = service.log(branch=body.name, limit=1)
    return GitBranchInfo(
        name=body.name,
        tip_sha=body.from_sha,
        created_at=commits[0].committed_at if commits else datetime.now(timezone.utc),
    )


@router.delete("/deals/{deal_id}/branches/{name:path}", status_code=204)
def delete_branch(deal_id: str, name: str) -> Response:
    service = GitService(repo_path=deal_dir(deal_id))
    try:
        service.branch_delete(name)
    except InvalidBranchNameError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GitServiceError as exc:
        if "PROTECTED_BRANCH" in str(exc):
            raise HTTPException(
                status_code=409,
                detail={"code": "PROTECTED_BRANCH", "message": str(exc)},
            ) from exc
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post("/deals/{deal_id}/merge", response_model=GitMergeResult)
def merge_endpoint(deal_id: str, body: GitMergeRequest) -> GitMergeResult:
    service = GitService(repo_path=deal_dir(deal_id))
    try:
        result = service.merge(body.branch, into=body.into)
    except InvalidBranchNameError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GitServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if isinstance(result, str):
        return GitMergeResult(status="success", sha=result)
    return GitMergeResult(
        status="conflict",
        diagnostic=MergeConflictPayload(
            code=result.code,
            severity=str(result.severity),
            path=result.path,
            message=result.message,
            payload=result.payload,
        ),
    )


@router.get("/deals/{deal_id}/diff", response_model=GitDiffResponse)
def diff_endpoint(deal_id: str, a: str, b: str) -> GitDiffResponse:
    service = GitService(repo_path=deal_dir(deal_id))
    try:
        a_bytes = service.show(a, "deal.json")
        b_bytes = service.show(b, "deal.json")
    except GitServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    a_payload = json.loads(a_bytes)
    b_payload = json.loads(b_bytes)
    raw_entries = _flatten_diff(a_payload, b_payload)
    entries = [StructuralDiffEntry(**e) for e in raw_entries]
    return GitDiffResponse(structural_diff=entries)


@router.get("/deals/{deal_id}/log", response_model=GitLogResponse)
def log_endpoint(
    deal_id: str,
    branch: str = "main",
    limit: int = 50,
) -> GitLogResponse:
    service = GitService(repo_path=deal_dir(deal_id))
    try:
        git_commits = service.log(branch=branch, limit=limit)
    except GitServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    api_commits = [
        GitCommitMeta(
            sha=c.sha,
            author=c.author,
            message=c.message,
            committed_at=c.committed_at,
            parent_sha=c.parent_sha,
        )
        for c in git_commits
    ]
    return GitLogResponse(commits=api_commits)


@router.get("/deals/{deal_id}/show")
def show_endpoint(deal_id: str, sha: str, path: str) -> Response:
    service = GitService(repo_path=deal_dir(deal_id))
    try:
        content = service.show(sha, path)
    except GitServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=content, media_type="application/octet-stream")


@router.get("/deals/{deal_id}/merge/stream")
def merge_stream_endpoint(deal_id: str, branch: str) -> StreamingResponse:
    """SSE endpoint streaming merge progress events terminating in merge_complete or merge_failed."""
    service = GitService(repo_path=deal_dir(deal_id))

    def event_stream():  # type: ignore[return]
        start_event = MergeProgressEvent(
            event_type="merge_started",
            progress=0.0,
            total_entities=1,
        )
        yield f"data: {start_event.model_dump_json()}\n\n"
        try:
            result = service.merge(branch, into="main")
            if isinstance(result, str):
                terminal = MergeProgressEvent(
                    event_type="merge_complete",
                    progress=1.0,
                    total_entities=1,
                    sha=result,
                )
            else:
                terminal = MergeProgressEvent(
                    event_type="merge_failed",
                    progress=1.0,
                    total_entities=1,
                    diagnostic={
                        "code": result.code,
                        "severity": str(result.severity),
                        "path": result.path,
                        "message": result.message,
                        "payload": result.payload,
                    },
                )
        except Exception as exc:
            terminal = MergeProgressEvent(
                event_type="merge_failed",
                progress=1.0,
                total_entities=1,
                diagnostic={"code": "MERGE_INTERNAL_ERROR", "message": str(exc)},
            )
        yield f"data: {terminal.model_dump_json()}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
