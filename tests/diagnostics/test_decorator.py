"""Contract tests for the diagnostic code decorator."""

from __future__ import annotations

import pytest

from bma_standard_formulas.diagnostics import (
    DiagnosticDescriptor,
    Owner,
    Severity,
    diagnostic_code,
    get_diagnostic,
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


def test_decorator_records_descriptor_metadata_correctly() -> None:
    """AC 3, 4, 6: Decorator stores descriptor metadata and validates severity."""

    @diagnostic_code(
        "TEST_FOO_BAR",
        severity=Severity.error,
        path_schema="deal.bonds[*].coupon",
        owner=Owner.both,
    )
    def _validator_foo(value):
        return value

    assert callable(_validator_foo)
    assert _validator_foo(123) == 123

    descriptor = get_diagnostic("TEST_FOO_BAR")
    assert isinstance(descriptor, DiagnosticDescriptor)
    assert descriptor.code == "TEST_FOO_BAR"
    assert descriptor.severity is Severity.error
    assert descriptor.path_schema == "deal.bonds[*].coupon"
    assert descriptor.owner is Owner.both
    assert descriptor.validator_qualname == (
        _validator_foo.__module__ + "." + _validator_foo.__qualname__
    )

    file_path, line_number = descriptor.validator_file_line
    assert isinstance(file_path, str)
    assert file_path.endswith("test_decorator.py")
    assert isinstance(line_number, int)
    assert line_number >= 1

    path_schemas = (".coupon", "deal.bonds[*].coupon", "deal.bond_by_id[id_var].coupon")
    for index, path_schema in enumerate(path_schemas, start=1):
        code = f"TEST_PATH_PATTERN_{index}"

        @diagnostic_code(
            code,
            severity=Severity.warning,
            path_schema=path_schema,
            owner=Owner.worker,
        )
        def _validator_path(value):
            return value

        assert _validator_path("ok") == "ok"
        assert get_diagnostic(code).path_schema == path_schema

    with pytest.raises((TypeError, ValueError)):

        @diagnostic_code(
            "TEST_BAD_SEVERITY",
            severity="critical",  # type: ignore[arg-type]
            path_schema=".coupon",
            owner=Owner.backend,
        )
        def _validator_bad_severity(value):
            return value
