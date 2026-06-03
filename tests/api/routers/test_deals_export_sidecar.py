"""API regression: GET /deals/{id}/export returns only deal.json (sdpm-6 AC 2).

Pins the API-layer export isolation: the export endpoint must return exactly
the git-backed deal.json bytes and must never include sidecar.json or
sidecar.broken.json content in the response body.
"""
from __future__ import annotations

import json
from pathlib import Path

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


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)
    deal_store.init_deals_workspace()
    return TestClient(app)


def _build_minimal_deal(*, deal_name: str) -> DealDefinition:
    return DealDefinition(
        deal_name=deal_name,
        bonds=[BondDef(name="A1", coupon=5.0, notional=1_000_000.0)],
        accounts=[AccountDef(name="Reserve", starting_amount=100.0)],
        fees=[FeeDef(name="Servicing", amount=10.0)],
        waterfall_rules=[
            RuleNode(
                rule_id="pay-principal",
                rule_type=RuleType.PAY_PRINCIPAL,
                order=0,
                from_sources=["CASH"],
                to_targets=["A1"],
            )
        ],
    )


def test_export_endpoint_returns_only_deal_json_and_never_sidecar(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """AC 2: GET /deals/{id}/export?sha={sha} returns canonical deal.json bytes;
    sidecar.json and sidecar.broken.json content must not appear in the response.
    """
    deal_id = "deal_api_export_sidecar"
    deal_store.save_deal(deal_id, _build_minimal_deal(deal_name="api-sidecar-regression"))

    repo = deal_store.deal_dir(deal_id)
    service = GitService(repo_path=repo)
    head = service.log(branch="main", limit=1)
    assert head, "save_deal must create at least one commit"
    sha = head[0].sha

    # Plant sidecar.json and sidecar.broken.json in the working tree.
    sidecar_content = {"layout_overrides": {"node_api_test": {"x": 50, "y": 100}}}
    broken_content = {"__sidecar_broken__": True, "raw": "api sidecar broken"}
    (repo / "sidecar.json").write_text(json.dumps(sidecar_content), encoding="utf-8")
    (repo / "sidecar.broken.json").write_text(json.dumps(broken_content), encoding="utf-8")

    response = client.get(f"/api/deals/{deal_id}/export", params={"sha": sha})
    assert response.status_code == 200, (
        f"Export endpoint must return 200, got {response.status_code}: {response.text[:200]}"
    )

    # Response must equal the canonical deal.json exactly.
    expected = json.loads(service.show(sha, "deal.json").decode("utf-8"))
    actual = response.json()
    assert actual == expected, (
        "Export response payload must equal canonical deal.json; got unexpected content"
    )

    # Response body must not contain sidecar or sidecar.broken content.
    response_text = response.text
    assert "layout_overrides" not in response_text, (
        "sidecar.json key 'layout_overrides' must not appear in export response"
    )
    assert "node_api_test" not in response_text, (
        "sidecar.json node key must not appear in export response"
    )
    assert "__sidecar_broken__" not in response_text, (
        "sidecar.broken.json sentinel key must not appear in export response"
    )

    # The deal_name in the response must be the canonical deal, not any sidecar derivative.
    assert actual.get("deal_name") == "api-sidecar-regression", (
        "Exported deal_name must match the canonical deal"
    )
