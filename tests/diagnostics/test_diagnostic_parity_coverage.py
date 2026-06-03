"""ve-2-worker-validator-coverage: Parametrised parity tests for the 6 new structural validators.

Each test loads one of the 6 new parity fixtures and asserts that the Python-side
validators produce the expected (code, path) tuples.  The companion Vitest suite
validates the TS side; cross-stack equality is guaranteed by both sides emitting
identical output for the same fixture input.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Validator module discovery — same pattern as test_diagnostic_parity.py
# ---------------------------------------------------------------------------

_VALIDATOR_MODULES: list[str] = [
    "bma_standard_formulas.diagnostics.structural_validators",
]

for _mod_name in _VALIDATOR_MODULES:
    importlib.import_module(_mod_name)

from bma_standard_formulas.diagnostics import Owner, iter_diagnostics  # noqa: E402
from bma_standard_formulas.diagnostics import registry as _diag_registry  # noqa: E402

_REGISTRY_SNAPSHOT: dict[str, Any] = dict(_diag_registry._REGISTRY)

# ---------------------------------------------------------------------------
# Fixture files — only the 6 new ve-2 fixtures
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "diagnostic_parity"

_VE2_FIXTURE_NAMES = [
    "bond_name_duplicate",
    "reference_broken",
    "multi_target_weight_sum_invalid",
    "kind_schedule_source_inconsistent",
    "nla_subordination_inconsistent",
    "multi_group_routing_invalid",
]

_FIXTURE_PATHS: list[Path] = [
    _FIXTURES_DIR / f"{name}.json" for name in _VE2_FIXTURE_NAMES
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_fn(qualname: str):  # type: ignore[return]
    module_name, func_name = qualname.rsplit(".", 1)
    mod = importlib.import_module(module_name)
    return getattr(mod, func_name)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _ensure_validators_registered() -> None:  # type: ignore[return]
    _diag_registry._REGISTRY.clear()
    _diag_registry._REGISTRY.update(_REGISTRY_SNAPSHOT)
    yield


# ---------------------------------------------------------------------------
# Parametrised parity test (AC 1, 4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_path",
    _FIXTURE_PATHS,
    ids=_VE2_FIXTURE_NAMES,
)
def test_new_worker_validators_maintain_parity(fixture_path: Path) -> None:
    """AC 1, 4: each ve-2 validator produces the expected (code, path) tuples."""
    data: dict[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))
    deal: dict[str, Any] = data["deal"]
    expected: set[tuple[str, str]] = {
        (d["code"], d["path"]) for d in data["expected_diagnostics"]
    }

    actual: set[tuple[str, str]] = set()
    for desc in iter_diagnostics():
        if desc.owner not in (Owner.worker, Owner.both):
            continue
        fn = _resolve_fn(desc.validator_qualname)
        for result in fn(deal):
            actual.add((result.code, result.path))

    assert actual == expected, (
        f"Parity mismatch for fixture '{fixture_path.stem}':\n"
        f"  expected: {sorted(expected)}\n"
        f"  actual:   {sorted(actual)}"
    )
