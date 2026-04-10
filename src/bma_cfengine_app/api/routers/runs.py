from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import FileResponse

from ...orchestrator.run_service import (
    execute_run,
    get_cashflow_preview,
    get_run_config,
    get_run_input_assumptions,
    get_run_input_mappings,
    get_run_input_tape_preview,
    get_run_groups,
    get_run_scenarios,
    list_all_runs,
)
from ...storage import run_store
from ..models import (
    CashflowPreview,
    RunRequest,
    RunResponse,
    RunStatus,
    RunSummary,
)

router = APIRouter(tags=["runs"])


def _run_in_background(
    run_id: str,
    req: RunRequest,
    mappings_data: dict,
    mapping_id: str | None = None,
) -> None:
    from ..models import FieldMapping

    mappings = [FieldMapping(**m) for m in mappings_data["mappings"]]
    asof_date = mappings_data.get("asof_date")

    scenario_dicts = None
    if req.scenarios:
        scenario_dicts = [
            {"name": s.name, "assumptions": s.assumptions.model_dump(), "run_mode": s.run_mode}
            for s in req.scenarios
        ]

    execute_run(
        run_id=run_id,
        upload_id=req.upload_id,
        mappings=mappings,
        asof_date=asof_date,
        grouping=req.grouping,
        assumptions=req.assumptions,
        run_mode=req.run_mode,
        include_period_zero=req.include_period_zero,
        scenarios=scenario_dicts,
        mapping_id=mapping_id,
    )


@router.post("/runs", response_model=RunResponse)
async def create_run(req: RunRequest, background_tasks: BackgroundTasks):
    import logging
    logging.warning(f"CREATE RUN: grouping={req.grouping}, scenarios={len(req.scenarios) if req.scenarios else 0}")

    run_id = run_store.new_run_id()
    mappings_data = run_store.load_mapping(req.upload_id, req.mapping_id)

    from datetime import datetime, timezone
    created_at = datetime.now(timezone.utc).isoformat()

    run_store.save_manifest(run_id, {
        "status": "queued",
        "run_type": "portfolio",
        "upload_id": req.upload_id,
        "run_mode": req.run_mode,
    })

    background_tasks.add_task(_run_in_background, run_id, req, mappings_data, req.mapping_id)

    return RunResponse(
        run_id=run_id,
        status=RunStatus.queued,
        created_at=created_at,
    )


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: str):
    manifest = run_store.load_manifest(run_id)
    summary = None
    if "summary" in manifest:
        summary = RunSummary(**manifest["summary"])

    return RunResponse(
        run_id=run_id,
        status=RunStatus(manifest.get("status", "queued")),
        created_at=manifest.get("created_at", ""),
        summary=summary,
        sections=manifest.get("sections", []),
        error=manifest.get("error"),
    )


@router.get("/runs/{run_id}/preview/{section}", response_model=CashflowPreview)
async def preview(run_id: str, section: str, max_rows: int = 500):
    return get_cashflow_preview(run_id, section, max_rows)


@router.get("/runs/{run_id}/artifacts")
async def list_artifacts(run_id: str):
    artifacts = run_store.list_artifacts(run_id)
    return {"run_id": run_id, "artifacts": artifacts}


@router.get("/runs/{run_id}/download/{artifact}")
async def download_artifact(run_id: str, artifact: str, format: str = "csv"):
    d = run_store.run_dir(run_id) / "artifacts"
    if format == "csv":
        path = d / f"{artifact}.csv"
    else:
        path = d / f"{artifact}.parquet"
    if not path.exists():
        from fastapi import HTTPException
        raise HTTPException(404, f"Artifact '{artifact}' not found")
    return FileResponse(
        path,
        media_type="text/csv" if format == "csv" else "application/octet-stream",
        filename=f"{artifact}.{format}",
    )


@router.get("/runs/{run_id}/groups")
async def list_groups(run_id: str):
    groups, artifact_map = get_run_groups(run_id)
    return {"run_id": run_id, "groups": groups, "group_artifacts": artifact_map}


@router.get("/runs/{run_id}/scenarios")
async def list_scenarios(run_id: str):
    scenarios = get_run_scenarios(run_id)
    return {"run_id": run_id, "scenarios": scenarios}


@router.get("/runs-list")
async def list_runs():
    return list_all_runs()


@router.get("/runs/{run_id}/config")
async def run_config(run_id: str):
    return get_run_config(run_id)


@router.get("/runs/{run_id}/inputs/tape", response_model=CashflowPreview)
async def run_input_tape(run_id: str, max_rows: int = 500):
    return get_run_input_tape_preview(run_id, max_rows)


@router.get("/runs/{run_id}/inputs/assumptions")
async def run_input_assumptions(run_id: str):
    return get_run_input_assumptions(run_id)


@router.get("/runs/{run_id}/inputs/mappings")
async def run_input_mappings(run_id: str):
    return get_run_input_mappings(run_id)
