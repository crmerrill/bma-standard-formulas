from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Callable

import pytest

from bma_standard_formulas.deals.schemas.common import RuleType
from bma_standard_formulas.deals.schemas.ir import BondDef, DealDefinition, RuleNode

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "emit_canonical_fixtures.py"


def _load_module() -> ModuleType:
    assert SCRIPT_PATH.exists(), f"Missing emitter script: {SCRIPT_PATH}"
    return importlib.import_module("scripts.emit_canonical_fixtures")


def _require_callable(module: ModuleType, name: str) -> Callable:
    candidate = getattr(module, name, None)
    assert callable(candidate), (
        "scripts.emit_canonical_fixtures.py must expose "
        f"`{name}(fixtures_root: Path, check: bool = False)`"
    )
    return candidate


def _minimal_deal(name: str) -> DealDefinition:
    return DealDefinition(
        deal_name=name,
        bonds=[BondDef(name="A")],
        waterfall_rules=[
            RuleNode(
                rule_id="r0",
                rule_type=RuleType.PAY_PRINCIPAL,
                order=0,
                from_sources=["ACT_PRIN"],
                to_targets=["A"],
            )
        ],
    )


def _write_builder_fixture(fixtures_root: Path, fixture_name: str) -> Path:
    fixture_dir = fixtures_root / fixture_name
    fixture_dir.mkdir(parents=True, exist_ok=True)
    (fixture_dir / "deal_definition.py").write_text(
        """
from bma_standard_formulas.deals.schemas.common import RuleType
from bma_standard_formulas.deals.schemas.ir import BondDef, DealDefinition, RuleNode

deal_definition = DealDefinition(
    deal_name="Builder fixture",
    bonds=[BondDef(name="A")],
    waterfall_rules=[
        RuleNode(
            rule_id="r0",
            rule_type=RuleType.PAY_PRINCIPAL,
            order=0,
            from_sources=["ACT_PRIN"],
            to_targets=["A"],
        )
    ],
)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return fixture_dir


def _write_deal_json_fixture(fixtures_root: Path, fixture_name: str, *, pretty: bool = True) -> Path:
    fixture_dir = fixtures_root / fixture_name
    fixture_dir.mkdir(parents=True, exist_ok=True)
    payload = _minimal_deal(fixture_name)
    if pretty:
        deal_json = payload.model_dump_json(indent=2)
    else:
        deal_json = json.dumps(payload.model_dump(mode="json"))
    (fixture_dir / "deal.json").write_text(deal_json + "\n", encoding="utf-8")
    return fixture_dir


def test_emitter_produces_byte_stable_canonical_artifacts_across_runs(tmp_path: Path):
    module = _load_module()
    emit_canonical_fixtures = _require_callable(module, "emit_canonical_fixtures")

    fixtures_root = tmp_path / "fixtures"
    _write_builder_fixture(fixtures_root, "builder_only")
    _write_deal_json_fixture(fixtures_root, "json_only")

    emit_canonical_fixtures(fixtures_root=fixtures_root, check=False)
    first_pass = {
        path.relative_to(fixtures_root).as_posix(): path.read_bytes()
        for path in sorted(fixtures_root.glob("**/deal*.json"))
    }
    assert first_pass, "Emitter did not materialize any deal artifacts."

    emit_canonical_fixtures(fixtures_root=fixtures_root, check=False)
    second_pass = {
        path.relative_to(fixtures_root).as_posix(): path.read_bytes()
        for path in sorted(fixtures_root.glob("**/deal*.json"))
    }
    assert second_pass, "Second emitter pass produced no deal artifacts."
    assert second_pass == first_pass, "Canonical emitter must be byte-stable across reruns."


def test_emitter_materializes_deal_json_from_builder_when_only_deal_definition_py_present(
    tmp_path: Path,
):
    module = _load_module()
    emit_canonical_fixtures = _require_callable(module, "emit_canonical_fixtures")

    fixtures_root = tmp_path / "fixtures"
    builder_dir = _write_builder_fixture(fixtures_root, "builder_only")
    assert not (builder_dir / "deal.json").exists()
    assert not (builder_dir / "deal.canonical.json").exists()

    emit_canonical_fixtures(fixtures_root=fixtures_root, check=False)

    deal_json_path = builder_dir / "deal.json"
    canonical_path = builder_dir / "deal.canonical.json"
    assert deal_json_path.exists(), "Builder fixture did not materialize deal.json."
    assert canonical_path.exists(), "Builder fixture did not materialize deal.canonical.json."

    materialized = json.loads(deal_json_path.read_text(encoding="utf-8"))
    assert materialized["deal_name"] == "Builder fixture"
    assert "waterfall_rules" in materialized


def test_emitter_passthrough_when_deal_json_already_present(tmp_path: Path):
    module = _load_module()
    emit_canonical_fixtures = _require_callable(module, "emit_canonical_fixtures")

    fixtures_root = tmp_path / "fixtures"
    fixture_dir = _write_deal_json_fixture(fixtures_root, "passthrough_fixture")
    deal_json_path = fixture_dir / "deal.json"
    original_bytes = deal_json_path.read_bytes()

    emit_canonical_fixtures(fixtures_root=fixtures_root, check=False)

    assert deal_json_path.read_bytes() == original_bytes, (
        "Emitter must passthrough existing deal.json bytes unchanged."
    )
    assert (fixture_dir / "deal.canonical.json").exists(), (
        "Emitter must also materialize deal.canonical.json for passthrough fixtures."
    )


def test_fixture_count_parity_guard_fails_when_deal_json_added_without_canonical(tmp_path: Path):
    module = _load_module()
    assert_fixture_count_parity = _require_callable(module, "assert_fixture_count_parity")

    fixtures_root = tmp_path / "fixtures"
    _write_deal_json_fixture(fixtures_root, "missing_canonical")

    with pytest.raises((AssertionError, RuntimeError, ValueError)):
        assert_fixture_count_parity(fixtures_root=fixtures_root)


def test_fixture_count_parity_guard_fails_when_canonical_exists_without_deal_json(tmp_path: Path):
    module = _load_module()
    assert_fixture_count_parity = _require_callable(module, "assert_fixture_count_parity")

    fixtures_root = tmp_path / "fixtures"
    orphan_dir = fixtures_root / "orphan_fixture"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / "deal.canonical.json").write_text("{}", encoding="utf-8")

    with pytest.raises((AssertionError, RuntimeError, ValueError)):
        assert_fixture_count_parity(fixtures_root=fixtures_root)
