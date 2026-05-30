"""Diagnostics sub-package — enums, payload schema, decorator, and registry APIs."""

from __future__ import annotations

from .decorator import diagnostic_code
from .payload import DiagnosticPayload, Owner, Severity
from .registry import (
    DiagnosticDescriptor,
    DiagnosticNotRegisteredError,
    DuplicateDiagnosticError,
    get_diagnostic,
    iter_diagnostics,
    register_diagnostic,
)

__all__ = [
    "DiagnosticPayload",
    "Severity",
    "Owner",
    "DiagnosticDescriptor",
    "DiagnosticNotRegisteredError",
    "DuplicateDiagnosticError",
    "diagnostic_code",
    "register_diagnostic",
    "get_diagnostic",
    "iter_diagnostics",
]
