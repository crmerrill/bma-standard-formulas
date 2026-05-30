"""Decorator for attaching a diagnostic code to a validator function and registering it."""

from __future__ import annotations

import inspect
from typing import Any, Callable

from .payload import Owner, Severity
from .registry import DiagnosticDescriptor, register_diagnostic


def diagnostic_code(
    code: str,
    *,
    severity: Severity,
    path_schema: str,
    owner: Owner,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if not isinstance(severity, Severity):
            raise TypeError(f"severity must be Severity, got {type(severity).__name__}")
        if not isinstance(owner, Owner):
            raise TypeError(f"owner must be Owner, got {type(owner).__name__}")

        try:
            file = inspect.getsourcefile(func) or "<unknown>"
            _, line = inspect.getsourcelines(func)
        except (OSError, TypeError):
            file, line = "<unknown>", 0

        descriptor = DiagnosticDescriptor(
            code=code,
            severity=severity,
            path_schema=path_schema,
            owner=owner,
            validator_qualname=f"{func.__module__}.{func.__qualname__}",
            validator_file_line=(file, line),
        )
        register_diagnostic(descriptor)
        func.__diagnostic_descriptor__ = descriptor  # type: ignore[attr-defined]
        return func

    return decorator
