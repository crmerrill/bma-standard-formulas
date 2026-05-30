"""Module-level registry for diagnostic descriptors — lookup, iteration, and error types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from .payload import Owner, Severity


class DiagnosticNotRegisteredError(Exception):
    """Raised when a requested diagnostic code has no registered descriptor."""


class DuplicateDiagnosticError(Exception):
    """Raised when a diagnostic code is registered more than once."""


@dataclass(frozen=True)
class DiagnosticDescriptor:
    code: str
    severity: Severity
    path_schema: str
    owner: Owner
    validator_qualname: str
    validator_file_line: tuple[str, int]


_REGISTRY: dict[str, DiagnosticDescriptor] = {}


def register_diagnostic(descriptor: DiagnosticDescriptor) -> None:
    if descriptor.code in _REGISTRY:
        raise DuplicateDiagnosticError(
            f"Diagnostic code {descriptor.code!r} already registered"
        )
    _REGISTRY[descriptor.code] = descriptor


def get_diagnostic(code: str) -> DiagnosticDescriptor:
    try:
        return _REGISTRY[code]
    except KeyError:
        raise DiagnosticNotRegisteredError(
            f"No diagnostic registered for code {code!r}"
        )


def iter_diagnostics() -> Iterator[DiagnosticDescriptor]:
    return iter(_REGISTRY.values())
