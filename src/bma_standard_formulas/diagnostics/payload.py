"""Diagnostic payload schema — enums and Pydantic model for validator diagnostics."""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, enum.Enum):
    error = "error"
    warning = "warning"
    info = "info"


class Owner(str, enum.Enum):
    worker = "worker"
    backend = "backend"
    both = "both"


class QuickFix(BaseModel):
    """Optional quick-fix payload attached to a diagnostic (ve-5).

    A QuickFix names a typed action (`action_id`) the UI can dispatch through
    the store on user click. `params` carries the typed payload for that
    action. Worker validators may emit a `manual_resolve_*` action_id when
    automatic resolution requires user judgment; the panel renders the hint
    and the user resolves manually.

    Both fields are required to make the contract explicit — a quick-fix
    without a clear action_id and params shape can't be dispatched anyway.
    """

    model_config = ConfigDict(extra="forbid")

    action_id: str
    params: dict[str, Any]


class DiagnosticPayload(BaseModel):
    code: str
    severity: Severity
    path: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    # ve-5: optional QuickFix; backward-compat — payloads without `fix` remain valid.
    fix: QuickFix | None = None
