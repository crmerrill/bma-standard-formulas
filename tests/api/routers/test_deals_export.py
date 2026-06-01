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


def _build_minimal_deal(*, deal_name: str, coupon: float) -> DealDefinition:
    return DealDefinition(
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


def test_export_endpoint_returns_deal_json(client: TestClient) -> None:
    deal_id = "deal_api_export"
    deal_store.save_deal(
        deal_id,
        _build_minimal_deal(deal_name="api-export", coupon=5.0),
    )

    repo_path = deal_store.deal_dir(deal_id)
    service = GitService(repo_path=repo_path)
    head = service.log(branch="main", limit=1)
    assert head, "Expected seeded deal to create at least one commit"
    sha = head[0].sha

    response = client.get(f"/api/deals/{deal_id}/export", params={"sha": sha})
    assert response.status_code == 200
    assert "application/json" in response.headers.get("content-type", "").lower()

    response_payload = json.loads(response.content.decode("utf-8"))
    expected_payload = json.loads(service.show(sha, "deal.json").decode("utf-8"))
    assert response_payload == expected_payload


def test_router_endpoint_surfaces_repo_corrupt_through_gitservice(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1 regression: an HTTP endpoint that constructs GitService directly must
    surface REPO_CORRUPT via the app-level exception handler (503)."""
    from bma_cfengine_app.orchestrator.deals import operational

    deal_id = "deal_api_corrupt_branch"
    deal_store.save_deal(
        deal_id,
        _build_minimal_deal(deal_name="corrupt-branch", coupon=5.0),
    )

    repo_path = deal_store.deal_dir(deal_id)
    operational._FSCK_VERIFIED_REPOS.discard(str(repo_path.resolve()))

    objects_root = repo_path / ".git" / "objects"
    for prefix_dir in objects_root.iterdir():
        if not prefix_dir.is_dir() or len(prefix_dir.name) != 2:
            continue
        for object_file in prefix_dir.iterdir():
            if object_file.is_file():
                object_file.chmod(0o644)
                object_file.write_bytes(b"corrupt")
                break
        else:
            continue
        break

    response = client.get(f"/api/deals/{deal_id}/branches")
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "REPO_CORRUPT"
    assert "diagnostic" in body
