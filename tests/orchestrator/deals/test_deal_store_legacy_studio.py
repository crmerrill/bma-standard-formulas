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


def _write_legacy_fixture_with_studio(
    *,
    root: Path,
    deal_id: str,
    payload: dict[str, Any],
) -> Path:
    deal_path = root / deal_id
    deal_path.mkdir(parents=True, exist_ok=True)
    created_at = "2026-01-01T00:00:00+00:00"

    (deal_path / "v1.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    studio_v1 = {
        "deal_id": deal_id,
        "deal_name": payload["deal_name"],
        "schema_version": "studio",
        "saved_at": created_at,
        "ir": {
            "schema_version": "studio",
            "nodes": [{"id": "node-1", "type": "BLOCK"}],
        },
    }
    (deal_path / "studio_v1.json").write_text(
        json.dumps(studio_v1, indent=2),
        encoding="utf-8",
    )

    manifest = {
        "deal_id": deal_id,
        "deal_name": payload["deal_name"],
        "created_at": created_at,
        "current_version": 1,
        "versions": [
            {
                "version": 1,
                "schema_version": payload["schema_version"],
                "checksum": "legacy-checksum-v1",
                "created_at": created_at,
            }
        ],
        "studio_current_version": 1,
        "studio_versions": [{"version": 1, "created_at": created_at}],
        "updated_at": created_at,
    }
    (deal_path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return deal_path


def _redirect_deal_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)


def test_studio_apis_preserved_during_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deal_id = "deal_studio_transition"
    payload = _build_deal_payload(deal_name="legacy-studio", coupon=5.0)
    deal_path = _write_legacy_fixture_with_studio(
        root=tmp_path,
        deal_id=deal_id,
        payload=payload,
    )
    _redirect_deal_dirs(monkeypatch, tmp_path)

    deal_store.load_deal(deal_id)
    assert (deal_path / ".git").exists()

    studio_ir = {
        "schema_version": "studio",
        "nodes": [{"id": "node-2", "type": "BLOCK"}],
        "edges": [],
    }
    saved_deal_id, saved_meta = deal_store.save_studio_ir(
        deal_id=deal_id,
        deal_name="legacy-studio",
        ir=studio_ir,
    )
    assert saved_deal_id == deal_id
    assert saved_meta["version"] == 2

    loaded_studio = deal_store.load_studio_snapshot(deal_id, version=saved_meta["version"])
    assert loaded_studio["ir"] == studio_ir

    listed_deals = deal_store.list_studio_deals()
    listed_row = next(row for row in listed_deals if row["deal_id"] == deal_id)
    assert listed_row["current_version"] == saved_meta["version"]

    saved_preset = deal_store.save_solver_preset(
        deal_id=deal_id,
        preset_name="legacy-preset",
        solver_spec={"iterations": 15},
        notes="migration compatibility",
    )
    assert saved_preset["preset_name"] == "legacy-preset"

    presets = deal_store.list_solver_presets(deal_id)
    assert any(preset["preset_name"] == "legacy-preset" for preset in presets)

    assert (deal_path / "studio_v1.json").exists()
    assert (deal_path / "studio_v2.json").exists()

    post_manifest = json.loads((deal_path / "manifest.json").read_text(encoding="utf-8"))
    assert post_manifest["studio_current_version"] == 2
    assert any(version["version"] == 2 for version in post_manifest["studio_versions"])
