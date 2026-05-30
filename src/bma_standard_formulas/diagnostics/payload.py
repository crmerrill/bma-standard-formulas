"""Diagnostic payload schema — enums and Pydantic model for validator diagnostics."""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, enum.Enum):
    error = "error"
    warning = "warning"
    info = "info"


class Owner(str, enum.Enum):
    worker = "worker"
    backend = "backend"
    both = "both"


class DiagnosticPayload(BaseModel):
    code: str
    severity: Severity
    path: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
