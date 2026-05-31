"""Shared fixtures for orchestrator/deals tests."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _ensure_merge_diagnostic_registered() -> None:
    """Re-register MERGE_CONFLICT if the diagnostics registry was externally cleared.

    The diagnostics/test_registry.py suite clears _REGISTRY via autouse fixture.
    If those tests run before the merge diagnostic test, the import-time
    registration is lost. This fixture restores it from the cached descriptor.
    """
    from bma_standard_formulas.diagnostics.registry import _REGISTRY

    if "MERGE_CONFLICT" not in _REGISTRY:
        from bma_cfengine_app.orchestrator.deals.merge import _merge_conflict_validator

        descriptor = getattr(_merge_conflict_validator, "__diagnostic_descriptor__", None)
        if descriptor is not None:
            _REGISTRY[descriptor.code] = descriptor
