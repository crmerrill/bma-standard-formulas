from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pathlib import Path

from ..storage.run_store import init_workspace, workspace_path
from .routers import uploads, mappings, runs, risk, curves, deals
from ..orchestrator.deals.deal_store import init_deals_workspace

log = logging.getLogger(__name__)

ws = init_workspace()
init_deals_workspace()

app = FastAPI(
    title="BMA Cashflow Engine",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(uploads.router, prefix="/api")
app.include_router(mappings.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(risk.router, prefix="/api")
app.include_router(curves.router, prefix="/api")
app.include_router(deals.router, prefix="/api")


@app.get("/api/health")
async def health():
    from bma_cfengine_app.api import models as api_models
    from bma_standard_formulas.deals.schemas.common import SCHEMA_VERSION

    return {
        "status": "ok",
        "workspace": str(workspace_path()),
        # Clients can use this to detect schema version mismatches before attempting runs.
        "deal_schema_version": SCHEMA_VERSION,
        # If false, the running process is not loading this repo's models (stale install / wrong PYTHONPATH).
        "group_id_in_allowlist": "group_id" in api_models.ALL_CANONICAL_FIELDS,
    }


@app.exception_handler(Exception)
async def api_unhandled_exception(request: Request, exc: Exception):
    """Return JSON error detail for /api (plain 500 responses hide the real error)."""
    if isinstance(exc, StarletteHTTPException):
        return await http_exception_handler(request, exc)
    if isinstance(exc, RequestValidationError):
        return await request_validation_exception_handler(request, exc)
    if not request.url.path.startswith("/api"):
        raise exc
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "type": type(exc).__name__,
        },
    )


UI_DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"
if UI_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(UI_DIST), html=True), name="ui")
