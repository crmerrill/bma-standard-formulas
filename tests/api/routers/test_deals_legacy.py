"""Tests that legacy studio endpoints return 404 after sdpm-5 retirement (AC 2, 3).

After deletion of the five legacy studio routes, each must return 404. The
irvc-4 commit endpoint and irvc-5a export endpoint must continue to work.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bma_cfengine_app.api.main import app
from bma_cfengine_app.orchestrator.deals import deal_store
from bma_cfengine_app.orchestrator.deals.git_service import GitService
from bma_standard_formulas.deals.schemas.common import RuleType
from bma_standard_formulas.deals.schemas.ir import (
    AccountDef,
    BondDef,
    DealDefinition,
    FeeDef,
    RuleNode,
)


def _build_minimal_deal(*, deal_name: str) -> DealDefinition:
    return DealDefinition(
        deal_name=deal_name,
        bonds=[BondDef(name="A1", coupon=5.0, notional=1_000_000.0)],
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
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)
    deal_store.init_deals_workspace()
    return TestClient(app)


def test_legacy_studio_endpoints_return_404(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """AC 2, 3: the 5 legacy studio routes must return 404 after retirement.

    Table-driven over the 5 deleted routes. Also verifies that
    POST /deals/{deal_id}/commit (irvc-4) and
    GET /deals/{deal_id}/export?sha=... (irvc-5a) still return 200.
    """
    deal_id = "deal_legacy_sdpm5"

    # Seed a full legacy fixture (v1.json + studio_v1.json + manifest with studio fields)
    # so that before deletion, GET /deals/{deal_id} returns 200 (studio snapshot present).
    deal = _build_minimal_deal(deal_name="legacy-studio")
    payload = deal.model_dump(mode="json")
    _write_legacy_fixture(root=tmp_path, deal_id=deal_id, payload=payload)

    # Trigger migration so the deal becomes git-backed (needed for commit/export tests).
    deal_store.load_deal(deal_id)

    repo_path = deal_store.deal_dir(deal_id)
    service = GitService(repo_path=repo_path)
    head = service.log(branch="main", limit=1)
    assert head, "Migration must produce at least one commit"
    head_sha = head[0].sha

    # ── Table-driven: all 5 legacy routes must return 404 ──────────────────
    legacy_routes: list[tuple[str, str, Any]] = [
        ("GET", "/api/deals", None),
        ("GET", f"/api/deals/{deal_id}", None),
        ("POST", "/api/deals", {"deal_id": None, "deal_name": "Test", "ir": {}}),
        ("GET", f"/api/deals/{deal_id}/solver-presets", None),
        ("POST", f"/api/deals/{deal_id}/solver-presets", {"preset_name": "p", "solver_spec": {}}),
    ]

    for method, path, body in legacy_routes:
        if method == "GET":
            resp = client.get(path)
        else:
            resp = client.post(path, json=body)
        assert resp.status_code == 404, (
            f"{method} {path} should return 404 (legacy route retired) "
            f"but got {resp.status_code}: {resp.text[:200]}"
        )

    # ── POST /deals/{deal_id}/commit (irvc-4) must still work ──────────────
    commit_resp = client.post(
        f"/api/deals/{deal_id}/commit",
        json={
            "author": "test <test@bma>",
            "message": "sdpm-5 regression commit",
            "parent_sha": head_sha,
            "payload": payload,
            "force": False,
        },
    )
    assert commit_resp.status_code == 200, (
        f"POST /deals/{{deal_id}}/commit (irvc-4) must still work: {commit_resp.text[:200]}"
    )

    # ── GET /deals/{deal_id}/export?sha=... (irvc-5a) must still work ──────
    export_resp = client.get(f"/api/deals/{deal_id}/export", params={"sha": head_sha})
    assert export_resp.status_code == 200, (
        f"GET /deals/{{deal_id}}/export (irvc-5a) must still work: {export_resp.text[:200]}"
    )
