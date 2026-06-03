"""Tests that manifest.json strictly excludes transitional studio fields (sdpm-5 AC 1).

AC 1: The manifest.json writer logic emits exactly:
    {deal_id, deal_name, asset_class, schema_version_pin, created_at, updated_at}
The fields studio_current_version, studio_versions, and solver_presets_library
must be absent after any write path (migration or canonical save).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bma_cfengine_app.orchestrator.deals import deal_store
from bma_standard_formulas.deals.schemas.common import RuleType
from bma_standard_formulas.deals.schemas.ir import (
    AccountDef,
    BondDef,
    DealDefinition,
    FeeDef,
    RuleNode,
)

_CANONICAL_MANIFEST_KEYS = frozenset(
    {"deal_id", "deal_name", "asset_class", "schema_version_pin", "created_at", "updated_at"}
)
_TRANSITIONAL_KEYS = frozenset(
    {"studio_current_version", "studio_versions", "solver_presets_library"}
)


def _build_deal_payload(*, deal_name: str, coupon: float) -> dict[str, Any]:
    deal = DealDefinition(
        deal_name=deal_name,
        bonds=[BondDef(name="A1", coupon=coupon, notional=1_000_000.0)],
        accounts=[AccountDef(name="Reserve", starting_amount=100.0)],
        fees=[FeeDef(name="Servicing", amount=10.0)],
        waterfall_rules=[
            RuleNode(
                rule_id="pay-principal-a1",
                rule_type=RuleType.PAY_PRINCIPAL,
                order=0,
                from_sources=["CASH"],
                to_targets=["A1"],
            )
        ],
    )
    return deal.model_dump(mode="json")


def _write_legacy_fixture(*, root: Path, deal_id: str, payload: dict[str, Any]) -> None:
    """Write a legacy deal directory with v1.json + studio_v1.json + manifest."""
    deal_path = root / deal_id
    deal_path.mkdir(parents=True, exist_ok=True)
    created_at = "2026-01-01T00:00:00+00:00"

    (deal_path / "v1.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    studio_v1 = {
        "deal_id": deal_id,
        "deal_name": payload["deal_name"],
        "schema_version": "studio",
        "saved_at": created_at,
        "ir": {"schema_version": "studio", "nodes": []},
    }
    (deal_path / "studio_v1.json").write_text(json.dumps(studio_v1, indent=2), encoding="utf-8")
    manifest = {
        "deal_id": deal_id,
        "deal_name": payload["deal_name"],
        "created_at": created_at,
        "current_version": 1,
        "versions": [{"version": 1, "created_at": created_at}],
        "studio_current_version": 1,
        "studio_versions": [{"version": 1, "created_at": created_at}],
        "updated_at": created_at,
    }
    (deal_path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


@pytest.fixture
def redirected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)
    deal_store.init_deals_workspace()
    return tmp_path


def test_manifest_strictly_excludes_transitional_studio_keys(
    redirected: Path,
) -> None:
    """AC 1: manifest.json must contain exactly the 6 canonical keys;
    transitional studio fields must not appear regardless of write path.
    """
    # --- Path A: legacy migration (irvc-3 path triggers _collapse_manifest_post_migration) ---
    deal_id_a = "deal_manifest_migrated"
    payload_a = _build_deal_payload(deal_name="migrated-deal", coupon=4.5)
    _write_legacy_fixture(root=redirected, deal_id=deal_id_a, payload=payload_a)

    deal_store.load_deal(deal_id_a)  # triggers _migrate_legacy_to_git + _collapse_manifest_post_migration

    manifest_a = json.loads(
        (redirected / deal_id_a / "manifest.json").read_text(encoding="utf-8")
    )
    actual_keys_a = set(manifest_a.keys())

    assert actual_keys_a == _CANONICAL_MANIFEST_KEYS, (
        f"After migration, manifest has unexpected keys. "
        f"Extra: {actual_keys_a - _CANONICAL_MANIFEST_KEYS}; "
        f"Missing: {_CANONICAL_MANIFEST_KEYS - actual_keys_a}"
    )
    for bad_key in _TRANSITIONAL_KEYS:
        assert bad_key not in manifest_a, (
            f"Transitional key '{bad_key}' must be absent from manifest.json after migration"
        )

    # --- Path B: fresh save_deal (_update_manifest_on_save) ---
    deal_id_b = "deal_manifest_fresh"
    deal_store.save_deal(
        deal_id_b,
        DealDefinition.model_validate(_build_deal_payload(deal_name="fresh-deal", coupon=5.0)),
    )

    manifest_b = json.loads(
        (redirected / deal_id_b / "manifest.json").read_text(encoding="utf-8")
    )
    actual_keys_b = set(manifest_b.keys())

    assert actual_keys_b == _CANONICAL_MANIFEST_KEYS, (
        f"After save_deal, manifest has unexpected keys. "
        f"Extra: {actual_keys_b - _CANONICAL_MANIFEST_KEYS}; "
        f"Missing: {_CANONICAL_MANIFEST_KEYS - actual_keys_b}"
    )
    for bad_key in _TRANSITIONAL_KEYS:
        assert bad_key not in manifest_b, (
            f"Transitional key '{bad_key}' must be absent from manifest.json after save_deal"
        )
