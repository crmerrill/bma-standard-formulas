"""vpc-5-parity-fixture-set: Pytest parity runner for JSON diagnostic fixtures.

For each fixture in ``tests/fixtures/diagnostic_parity/*.json`` the runner:

  1. Loads the deal payload from ``fixture["deal"]``.
  2. Runs every registered validator whose ``owner`` is ``worker`` or ``both``
     against that deal.
  3. Asserts the resulting ``(code, path)`` tuples exactly match the fixture's
     ``expected_diagnostics`` list.

To add coverage for a new validator module, append its fully-qualified module
name to ``_VALIDATOR_MODULES``.  The module is imported at collection time so
its ``@diagnostic_code`` decorators register with the Python diagnostic registry
before any test executes.

AC 5 (owner=backend exclusion): validators with ``owner='backend'`` are
intentionally skipped — only ``worker`` and ``both`` codes are subject to
cross-stack parity checks.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Validator module discovery
# ---------------------------------------------------------------------------
# All modules listed here are imported at collection time so their
# @diagnostic_code decorators register with the Python diagnostic registry
# before any test executes.  Add new validator module names here as they are
# introduced.

_VALIDATOR_MODULES: list[str] = [
    "bma_standard_formulas.diagnostics.structural_validators",
]

for _mod_name in _VALIDATOR_MODULES:
    importlib.import_module(_mod_name)

# These imports must come AFTER the validator modules are loaded so that the
# registry is already populated when we snapshot it below.
from bma_standard_formulas.diagnostics import Owner, iter_diagnostics  # noqa: E402
from bma_standard_formulas.diagnostics import registry as _diag_registry  # noqa: E402

# ---------------------------------------------------------------------------
# Registry snapshot
# ---------------------------------------------------------------------------
# Captured once after all validator modules are imported.  Restored before
# each test to handle cases where other test modules in the same pytest
# session clear the registry (e.g. test_decorator.py's autouse
# _clean_registry fixture).

_REGISTRY_SNAPSHOT: dict[str, Any] = dict(_diag_registry._REGISTRY)

# ---------------------------------------------------------------------------
# Fixture files
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "diagnostic_parity"
_FIXTURE_PATHS: list[Path] = (
    sorted(_FIXTURES_DIR.glob("*.json")) if _FIXTURES_DIR.exists() else []
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_fn(qualname: str):  # type: ignore[return]
    """Return the callable identified by its fully-qualified module.attribute name.

    The ``validator_qualname`` stored in the registry descriptor has the form
    ``<module>.<funcname>``, e.g.
    ``bma_standard_formulas.diagnostics.structural_validators.validate_bond_name_empty``.
    Splitting on the last ``.`` yields the importable module path and the
    attribute name, which is sufficient for all module-level validator functions.
    """
    module_name, func_name = qualname.rsplit(".", 1)
    mod = importlib.import_module(module_name)
    return getattr(mod, func_name)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _ensure_validators_registered() -> None:  # type: ignore[return]
    """Restore the registry to the post-import snapshot before each test.

    Prevents cross-contamination when other test modules clear the registry
    as part of their teardown.
    """
    _diag_registry._REGISTRY.clear()
    _diag_registry._REGISTRY.update(_REGISTRY_SNAPSHOT)
    yield


# ---------------------------------------------------------------------------
# Parametrised parity test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_path",
    _FIXTURE_PATHS,
    ids=[p.stem for p in _FIXTURE_PATHS],
)
def test_parity_fixture(fixture_path: Path) -> None:
    """AC 2, 4, 5: run owner=worker/both validators and assert parity with expected output."""
    data: dict[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))
    deal: dict[str, Any] = data["deal"]
    expected: set[tuple[str, str]] = {
        (d["code"], d["path"]) for d in data["expected_diagnostics"]
    }

    actual: set[tuple[str, str]] = set()
    for desc in iter_diagnostics():
        if desc.owner not in (Owner.worker, Owner.both):
            continue  # AC 5: backend codes excluded from parity checks
        fn = _resolve_fn(desc.validator_qualname)
        for result in fn(deal):
            actual.add((result.code, result.path))

    assert actual == expected, (
        f"Parity mismatch for fixture '{fixture_path.stem}':\n"
        f"  expected: {sorted(expected)}\n"
        f"  actual:   {sorted(actual)}"
    )
