from __future__ import annotations

from fastapi import APIRouter

from ...orchestrator.curve_builder import build_curve
from ..models import CurvePreviewRequest, CurvePreviewResponse

router = APIRouter(tags=["curves"])


@router.post("/curve-preview", response_model=CurvePreviewResponse)
async def preview_curve(req: CurvePreviewRequest):
    arr = build_curve(req.spec, req.horizon)
    return CurvePreviewResponse(values=arr.tolist(), length=len(arr))
