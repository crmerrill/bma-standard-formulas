from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bma_cfengine_app.api.main import app
from bma_cfengine_app.api.routers.deals import CommitRequest
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

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@pytest.fixture
def client(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)
    deal_store.init_deals_workspace()
    return TestClient(app)


@pytest.fixture
def deal_id(client: TestClient) -> str:
    deal_identifier = "deal_commit_extension_api"
    deal_store.save_deal(
        deal_identifier,
        _build_minimal_deal_definition(deal_name="commit-extension-initial", coupon=5.0),
    )
    deal_store.save_deal(
        deal_identifier,
        _build_minimal_deal_definition(deal_name="commit-extension-updated", coupon=5.5),
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


def _main_head_sha(deal_identifier: str) -> str:
    commits = _service_for(deal_identifier).log(branch="main", limit=1)
    assert commits, "Expected at least one commit on main"
    return commits[0].sha


def _branch_tip_sha(deal_identifier: str, branch: str) -> str:
    tips = {entry.name: entry.tip_sha for entry in _service_for(deal_identifier).branch_list()}
    assert branch in tips, f"Expected branch {branch!r} to exist"
    return tips[branch]


def _canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    validated = DealDefinition.model_validate(payload)
    return validated.model_dump_json(indent=2).encode("utf-8")


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


def _commit_branch_edit(
    repo_path: Path,
    *,
    branch_name: str,
    updated_deal_name: str,
    message: str,
) -> str:
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
        return _run_git(["rev-parse", "HEAD"], cwd=repo_path)
    finally:
        _run_git(["checkout", "main"], cwd=repo_path)


def test_commit_with_payload_writes_supplied_bytes_to_main(
    client: TestClient,
    deal_id: str,
) -> None:
    """AC 1, 2: payload bytes are validated and committed exactly."""
    main_tip = _main_head_sha(deal_id)
    payload = _build_minimal_deal_definition(
        deal_name="commit-extension-payload-main",
        coupon=6.25,
    ).model_dump(mode="json")

    response = client.post(
        f"/api/deals/{deal_id}/commit",
        json={
            "author": "user:test",
            "message": "test",
            "parent_sha": main_tip,
            "payload": payload,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert _SHA_RE.fullmatch(body["sha"])

    service = _service_for(deal_id)
    assert service.show(body["sha"], "deal.json") == _canonical_payload_bytes(payload)


def test_commit_with_branch_routes_to_ephemeral_branch_tip(
    client: TestClient,
    deal_id: str,
) -> None:
    """AC 1, 3, 4: branch field routes commit onto supplied ephemeral branch."""
    main_tip = _main_head_sha(deal_id)
    branch = "ai/turn-route-test"
    create_response = client.post(
        f"/api/deals/{deal_id}/branches",
        json={"name": branch, "from_sha": main_tip},
    )
    assert create_response.status_code == 201
    ephemeral_tip_before = _branch_tip_sha(deal_id, branch)

    payload = _build_minimal_deal_definition(
        deal_name="commit-extension-ephemeral",
        coupon=6.75,
    ).model_dump(mode="json")
    response = client.post(
        f"/api/deals/{deal_id}/commit",
        json={
            "author": "user:test",
            "message": "branch commit",
            "parent_sha": ephemeral_tip_before,
            "branch": branch,
            "payload": payload,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert _SHA_RE.fullmatch(body["sha"])
    assert _branch_tip_sha(deal_id, branch) == body["sha"]
    assert _main_head_sha(deal_id) == main_tip


def test_commit_with_stale_parent_sha_on_ephemeral_branch_returns_409_with_detail_head_sha(
    client: TestClient,
    deal_id: str,
) -> None:
    """AC 3: stale parent checks and reports the supplied branch's tip SHA."""
    main_tip = _main_head_sha(deal_id)
    branch = "ai/turn-stale-check"
    create_response = client.post(
        f"/api/deals/{deal_id}/branches",
        json={"name": branch, "from_sha": main_tip},
    )
    assert create_response.status_code == 201

    repo_path = deal_store.deal_dir(deal_id)
    ephemeral_tip = _commit_branch_edit(
        repo_path,
        branch_name=branch,
        updated_deal_name="ephemeral-tip-e1",
        message="ephemeral branch commit",
    )
    assert _branch_tip_sha(deal_id, branch) == ephemeral_tip
    assert _main_head_sha(deal_id) == main_tip

    payload = _build_minimal_deal_definition(
        deal_name="stale-commit-attempt",
        coupon=7.0,
    ).model_dump(mode="json")
    response = client.post(
        f"/api/deals/{deal_id}/commit",
        json={
            "author": "user:test",
            "message": "should conflict",
            "branch": branch,
            "parent_sha": main_tip,  # stale for ephemeral branch (expects ephemeral_tip)
            "payload": payload,
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "STALE_PARENT_SHA", "head_sha": ephemeral_tip}
    }


def test_commit_with_invalid_payload_returns_422_with_pydantic_error(
    client: TestClient,
    deal_id: str,
) -> None:
    """AC 2: payload must validate as DealDefinition."""
    response = client.post(
        f"/api/deals/{deal_id}/commit",
        json={
            "author": "user:test",
            "message": "invalid payload",
            "parent_sha": _main_head_sha(deal_id),
            "payload": {"this": "is_not_a_valid_DealDefinition"},
        },
    )

    assert response.status_code == 422
    detail = response.json().get("detail")
    assert isinstance(detail, list) and detail
    first = detail[0]
    assert {"loc", "msg", "type"}.issubset(first)


@pytest.mark.parametrize("branch", ["../escape", "UPPERCASE"])
def test_commit_with_invalid_branch_name_returns_400(
    client: TestClient,
    deal_id: str,
    branch: str,
) -> None:
    """AC 4: invalid branch names should map to 400 at HTTP layer."""
    payload = _build_minimal_deal_definition(
        deal_name="invalid-branch-name",
        coupon=6.0,
    ).model_dump(mode="json")
    response = client.post(
        f"/api/deals/{deal_id}/commit",
        json={
            "author": "user:test",
            "message": "invalid branch",
            "parent_sha": _main_head_sha(deal_id),
            "branch": branch,
            "payload": payload,
        },
    )

    # Ticket AC 4 requires 400 here; 422 indicates a contract deviation.
    assert response.status_code == 400


def test_commit_with_null_parent_sha_permits_unborn_branch_initial_commit(
    client: TestClient,
) -> None:
    """AC 1: parent_sha remains nullable for unborn-branch initial commits."""
    deal_identifier = "deal_commit_extension_unborn"
    repo_path = deal_store.deal_dir(deal_identifier)
    subprocess.run(["git", "init", str(repo_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True,
        capture_output=True,
    )

    payload = _build_minimal_deal_definition(
        deal_name="unborn-initial-payload",
        coupon=4.75,
    ).model_dump(mode="json")
    response = client.post(
        f"/api/deals/{deal_identifier}/commit",
        json={
            "author": "user:test",
            "message": "initial unborn commit",
            "parent_sha": None,
            "branch": "main",
            "payload": payload,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert _SHA_RE.fullmatch(body["sha"])
    service = _service_for(deal_identifier)
    assert service.show(body["sha"], "deal.json") == _canonical_payload_bytes(payload)


def test_legacy_call_without_payload_and_branch_matches_irvc4_behavior(
    client: TestClient,
    deal_id: str,
) -> None:
    """AC 5: legacy body preserves irvc-4 behavior after extension fields are added."""
    assert "payload" in CommitRequest.model_fields
    assert "branch" in CommitRequest.model_fields
    assert CommitRequest.model_fields["payload"].default is None
    assert CommitRequest.model_fields["branch"].default == "main"

    service = _service_for(deal_id)
    head_before = _main_head_sha(deal_id)
    bytes_before = service.show(head_before, "deal.json")

    response = client.post(
        f"/api/deals/{deal_id}/commit",
        json={
            "author": "Tester <tester@example.com>",
            "message": "legacy request body",
            "parent_sha": head_before,
            "force": False,
        },
    )
    assert response.status_code == 200
    new_sha = response.json()["sha"]
    assert _SHA_RE.fullmatch(new_sha)
    assert service.show(new_sha, "deal.json") == bytes_before
    assert _main_head_sha(deal_id) == new_sha
