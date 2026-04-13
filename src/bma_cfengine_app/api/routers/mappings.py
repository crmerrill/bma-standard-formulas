from __future__ import annotations

from fastapi import APIRouter

from ...orchestrator.grouping import preview_groups
from ...orchestrator.mapping import apply_mapping, sanitize_field_mappings, validate_mapping
from ...storage import run_store
from ..models import (
    GroupingConfig,
    GroupPreview,
    MappingRequest,
    MappingValidation,
)

router = APIRouter(tags=["mappings"])


@router.post("/mappings/validate", response_model=MappingValidation)
async def validate(req: MappingRequest):
    df, _ = run_store.load_upload_df(req.upload_id)
    return validate_mapping(df, sanitize_field_mappings(req.mappings), req.asof_date)


@router.post("/mappings/save")
async def save_mapping(req: MappingRequest):
    mapping_id = run_store.new_mapping_id()
    clean = sanitize_field_mappings(req.mappings)
    run_store.save_mapping(
        req.upload_id,
        mapping_id,
        {
            "mappings": [m.model_dump() for m in clean],
            "asof_date": req.asof_date,
        },
    )
    return {"mapping_id": mapping_id, "upload_id": req.upload_id}


@router.post("/mappings/group-preview", response_model=list[GroupPreview])
async def group_preview(upload_id: str, grouping: GroupingConfig):
    df, _ = run_store.load_upload_df(upload_id)
    return preview_groups(df, grouping)


@router.get("/mappings/{upload_id}/{mapping_id}")
async def get_mapping(upload_id: str, mapping_id: str):
    return run_store.load_mapping(upload_id, mapping_id)
