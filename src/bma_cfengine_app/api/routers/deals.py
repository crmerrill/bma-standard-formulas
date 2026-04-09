"""HTTP API for Structuring Studio deal snapshots (Blockly IR JSON)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...orchestrator.deals.deal_store import (
    list_studio_deals,
    load_studio_snapshot,
    save_studio_ir,
)

router = APIRouter(tags=["deals"])


class StudioDealSaveBody(BaseModel):
    deal_id: str | None = None
    deal_name: str = Field(default="Deal", min_length=1, max_length=256)
    ir: dict[str, Any]


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
