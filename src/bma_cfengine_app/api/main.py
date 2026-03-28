from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from ..storage.run_store import init_workspace, workspace_path
from .routers import uploads, mappings, runs, risk, curves

ws = init_workspace()

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


@app.get("/api/health")
async def health():
    return {"status": "ok", "workspace": str(workspace_path())}


UI_DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"
if UI_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(UI_DIST), html=True), name="ui")
