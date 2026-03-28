from __future__ import annotations

from fastapi import APIRouter

from ...orchestrator.run_service import execute_risk
from ..models import RiskRequest, RiskResponse

router = APIRouter(tags=["risk"])


@router.post("/runs/{run_id}/risk", response_model=RiskResponse)
async def compute_risk(run_id: str, req: RiskRequest):
    import logging
    logging.warning(f"RISK: input_kind={req.input_kind}, base_value={req.base_value}, column_inputs={req.column_inputs[:5]}...")
    return execute_risk(
        run_id=run_id,
        analytics=req.analytics,
        input_kind=req.input_kind,
        base_value=req.base_value,
        column_inputs=req.column_inputs,
    )
