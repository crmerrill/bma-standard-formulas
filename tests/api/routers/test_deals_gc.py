from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from bma_cfengine_app.api.main import app
from bma_cfengine_app.api.routers import deals as deals_router
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
def client(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)
    deal_store.init_deals_workspace()
    return TestClient(app)


@pytest.fixture
def deal_id(client: TestClient) -> str:
    deal_identifier = "deal_gc_api"
    deal_store.save_deal(
        deal_identifier,
        _build_minimal_deal_definition(deal_name="gc-api-initial", coupon=5.0),
    )
    deal_store.save_deal(
        deal_identifier,
        _build_minimal_deal_definition(deal_name="gc-api-updated", coupon=5.5),
    )
    return deal_identifier


def _build_minimal_deal_definition(*, deal_name: str, coupon: float) -> DealDefinition:
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


def _service_for(deal_identifier: str) -> GitService:
    return GitService(repo_path=deal_store.deal_dir(deal_identifier))


def _run_git(args: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout.strip()


def _main_head_sha(deal_identifier: str) -> str:
    service = _service_for(deal_identifier)
    commits = service.log(branch="main", limit=1)
    assert commits, "Expected at least one commit on main"
    return commits[0].sha


def _branch_names(deal_identifier: str) -> set[str]:
    return {entry.name for entry in _service_for(deal_identifier).branch_list()}


def _commit_branch_edit(
    repo_path: Path,
    *,
    branch_name: str,
    updated_deal_name: str,
    message: str,
) -> None:
    _run_git(["checkout", branch_name], cwd=repo_path)
    try:
        deal_json_path = repo_path / "deal.json"
        payload = json.loads(deal_json_path.read_text(encoding="utf-8"))
        payload["deal_name"] = updated_deal_name
        deal_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        commit_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Tester",
            "GIT_AUTHOR_EMAIL": "tester@example.com",
            "GIT_COMMITTER_NAME": "Tester",
            "GIT_COMMITTER_EMAIL": "tester@example.com",
        }
        _run_git(["add", "deal.json"], cwd=repo_path, env=commit_env)
        _run_git(["commit", "-m", message], cwd=repo_path, env=commit_env)
    finally:
        _run_git(["checkout", "main"], cwd=repo_path)


def test_apply_endpoint_triggers_gc_branch_after_apply(
    client: TestClient,
    deal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC1 contract: merge success must invoke GC hook and remove ephemeral branch."""
    branch_name = "ai/turn-foo"
    service = _service_for(deal_id)
    head_sha = _main_head_sha(deal_id)
    service.branch_create(branch_name, from_sha=head_sha)
    _commit_branch_edit(
        deal_store.deal_dir(deal_id),
        branch_name=branch_name,
        updated_deal_name="gc-api-branch-edit",
        message="ephemeral branch edit before apply",
    )

    original_gc = deals_router.gc_branch_after_apply
    gc_spy = MagicMock(wraps=original_gc)
    monkeypatch.setattr(deals_router, "gc_branch_after_apply", gc_spy)

    response = client.post(
        f"/api/deals/{deal_id}/merge",
        json={"branch": branch_name, "into": "main"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body.get("sha")

    assert gc_spy.called, "merge endpoint should invoke gc_branch_after_apply(...)"
    assert branch_name not in _branch_names(deal_id)


def test_discard_endpoint_triggers_gc_branch_after_discard(
    client: TestClient,
    deal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC1 contract: discard endpoint delegates deletion through gc_branch_after_discard."""
    branch_name = "ai/turn-bar"
    service = _service_for(deal_id)
    service.branch_create(branch_name, from_sha=_main_head_sha(deal_id))

    original_gc = deals_router.gc_branch_after_discard
    gc_spy = MagicMock(wraps=original_gc)
    monkeypatch.setattr(deals_router, "gc_branch_after_discard", gc_spy)

    response = client.delete(f"/api/deals/{deal_id}/branches/{branch_name}")
    assert response.status_code == 204

    assert gc_spy.called, "delete endpoint should invoke gc_branch_after_discard(...)"
    assert branch_name not in _branch_names(deal_id)
