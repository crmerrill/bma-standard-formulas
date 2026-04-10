"""HTTP API for Structuring Studio + structured deal run/solve workflows."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from bma_standard_formulas.deals.schemas.input import DealRunInput
from bma_standard_formulas.deals.schemas.ir import DealDefinition
from bma_standard_formulas.deals.schemas.solver import SolverSpec

from ...orchestrator.deals.collateral_bridge import (
    build_from_deal_native,
    build_from_runsetup_ref,
)
from ...orchestrator.deals.deal_run_service import execute_deal_run
from ...orchestrator.deals.deal_solver_service import execute_deal_solve
from ...orchestrator.deals.deal_store import (
    list_studio_deals,
    load_deal,
    load_studio_snapshot,
    save_deal as save_canonical_deal,
    save_studio_ir,
)
from ...orchestrator.run_service import get_cashflow_preview, list_all_runs
from ...storage import run_store

router = APIRouter(tags=["deals"])


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
        try:
            canonical = DealDefinition.model_validate(snapshot.get("ir", {}))
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot convert studio snapshot to canonical DealDefinition: {exc}",
            ) from exc
        save_canonical_deal(deal_id, canonical, version=version)
        return canonical


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


@router.post("/deals/{deal_id}/runs")
async def run_deal_endpoint(deal_id: str, body: DealRunRequest):
    _ensure_canonical_deal(deal_id, version=body.deal_version)
    try:
        scenario_inputs = _build_inputs(body.source, body.scenario_names)
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
        run_input = scenario_inputs.get(body.scenario_name) or next(iter(scenario_inputs.values()))
        run_id = run_store.new_run_id()
        return execute_deal_solve(
            run_id=run_id,
            deal_id=deal_id,
            deal_version=body.deal_version,
            run_input=run_input,
            solver_spec=body.solver_spec,
            scenario_name=body.scenario_name,
            source_mode=body.source.source_mode,
        ) | {"run_id": run_id}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/deals/{deal_id}/runs")
async def list_deal_runs(deal_id: str):
    all_runs = list_all_runs()
    runs = [r for r in all_runs if r.get("deal_id") == deal_id and r.get("run_type") == "structured_deal"]
    return runs


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
