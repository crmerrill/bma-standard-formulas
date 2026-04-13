"""HTTP API for Structuring Studio + structured deal run/solve workflows."""
from __future__ import annotations

import threading
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from bma_standard_formulas.deals.schemas.input import DealRunInput
from bma_standard_formulas.deals.schemas.ir import DealDefinition
from bma_standard_formulas.deals.schemas.migrations import migrate_deal_payload
from bma_standard_formulas.deals.schemas.solver import SolverSpec

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
from ...orchestrator.deals.solver_catalog import build_solver_catalog
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
    "PRIN_COLLECTION": "CASH",
    "INT_COLLECTION": "CASH",
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
    try:
        return load_studio_snapshot(deal_id, version=version)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/deals")
async def save_deal(body: StudioDealSaveBody):
    try:
        _, meta = save_studio_ir(
            body.deal_id,
            body.deal_name.strip() or "Deal",
            body.ir,
        )
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return meta


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

    def normalize_node(node: Any) -> Any:
        if isinstance(node, list):
            return [normalize_node(item) for item in node]
        if not isinstance(node, dict):
            return node

        next_node: dict[str, Any] = {
            key: normalize_node(value) for key, value in node.items()
        }

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

        return next_node

    return normalize_node(raw_ir)


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
    _ensure_canonical_deal(deal_id, version=body.deal_version)
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
    _ensure_canonical_deal(deal_id, version=body.deal_version)
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


@router.get("/deals/{deal_id}/solver-catalog")
async def get_solver_catalog(deal_id: str):
    canonical = _ensure_canonical_deal(deal_id, version=None)
    return build_solver_catalog(deal_id, canonical)


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
