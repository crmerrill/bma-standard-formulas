"""Contract tests for the diagnostics registry APIs."""

from __future__ import annotations

import pytest

from bma_standard_formulas.diagnostics import (
    DiagnosticDescriptor,
    DiagnosticNotRegisteredError,
    DuplicateDiagnosticError,
    Owner,
    Severity,
    get_diagnostic,
    iter_diagnostics,
    register_diagnostic,
)


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """Reset diagnostics registry around each test via private test API."""
    from bma_standard_formulas.diagnostics import registry

    clear_registry = (
        getattr(registry, "clear_registry", None)
        or getattr(registry, "_clear_registry_for_tests", None)
    )
    if callable(clear_registry):
        clear_registry()
    elif hasattr(registry, "_REGISTRY"):
        registry._REGISTRY.clear()

    yield

    clear_registry = (
        getattr(registry, "clear_registry", None)
        or getattr(registry, "_clear_registry_for_tests", None)
    )
    if callable(clear_registry):
        clear_registry()
    elif hasattr(registry, "_REGISTRY"):
        registry._REGISTRY.clear()


def _descriptor(code: str, *, severity: Severity = Severity.error) -> DiagnosticDescriptor:
    return DiagnosticDescriptor(
        code=code,
        severity=severity,
        path_schema="deal.bonds[*].coupon",
        owner=Owner.both,
        validator_qualname="tests.diagnostics.stub.validator",
        validator_file_line=("tests/diagnostics/test_registry.py", 1),
    )


def test_registry_lifecycle_and_lookups() -> None:
    """AC 5: Registry supports registration, iteration, and missing lookups."""
    first = _descriptor("TEST_REGISTRY_ONE")
    register_diagnostic(first)
    assert get_diagnostic(first.code) == first

    second = _descriptor("TEST_REGISTRY_TWO", severity=Severity.warning)
    register_diagnostic(second)

    descriptors = list(iter_diagnostics())
    assert first in descriptors
    assert second in descriptors
    assert len(descriptors) == 2

    with pytest.raises(DiagnosticNotRegisteredError):
        get_diagnostic("NONEXISTENT_CODE")


def test_duplicate_registration_raises_error() -> None:
    """AC 5: Any duplicate code re-registration raises DuplicateDiagnosticError."""
    original = _descriptor("TEST_DUPLICATE", severity=Severity.error)
    register_diagnostic(original)

    conflicting = _descriptor("TEST_DUPLICATE", severity=Severity.warning)
    with pytest.raises(DuplicateDiagnosticError):
        register_diagnostic(conflicting)

    with pytest.raises(DuplicateDiagnosticError):
        register_diagnostic(original)
