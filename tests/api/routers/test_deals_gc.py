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


# ---------------------------------------------------------------------------
# R1 fix-pass regression tests (irvc-5c C1/C2/C3)
# ---------------------------------------------------------------------------


def test_apply_via_router_squashes_ephemeral_branch_history(
    client: TestClient,
    deal_id: str,
) -> None:
    """C1 (R1 fix): POST /deals/{id}/merge with branch=ai/turn-* squashes;
    git log --all on the deal repo does not contain the ephemeral commit
    messages after Apply + branch delete."""
    branch_name = "ai/turn-squash"
    service = _service_for(deal_id)
    head_sha = _main_head_sha(deal_id)
    service.branch_create(branch_name, from_sha=head_sha)

    repo_path = deal_store.deal_dir(deal_id)
    sensitive_msg = "User said: 'Add a 5% reserve for PRIVATE-DEAL-XYZ'"
    _commit_branch_edit(
        repo_path,
        branch_name=branch_name,
        updated_deal_name="squash-test-edit",
        message=sensitive_msg,
    )

    response = client.post(
        f"/api/deals/{deal_id}/merge",
        json={"branch": branch_name, "into": "main"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    merge_sha = body["sha"]

    # Verify single-parent (squash) commit
    parent_line = _run_git(["rev-list", "--parents", "-1", merge_sha], cwd=repo_path)
    parents = parent_line.strip().split()
    assert len(parents) == 2, f"Expected single parent (squash), got {len(parents) - 1}"

    # Branch should be GC'd by gc_branch_after_apply
    assert branch_name not in _branch_names(deal_id)

    # Sensitive message unreachable from any ref
    all_messages = _run_git(["log", "--all", "--format=%B"], cwd=repo_path)
    assert "PRIVATE-DEAL-XYZ" not in all_messages


def test_discard_ephemeral_branch_redacts_pii_and_archives(
    client: TestClient,
    deal_id: str,
) -> None:
    """C2+C3 (R1 fix): DELETE /branches/{name} for ephemeral branches redacts
    PII into discarded_branches archive and audits the event."""
    branch_name = "ai/turn-redact-discard"
    service = _service_for(deal_id)
    head_sha = _main_head_sha(deal_id)
    service.branch_create(branch_name, from_sha=head_sha)

    repo_path = deal_store.deal_dir(deal_id)
    sensitive_msg = (
        "User said: 'Please structure my deal ABC-SECRET-789'\n"
        "tool_call model=gpt-5 tool_name=update_waterfall "
        "args={\"user_prompt\": \"structure deal ABC-SECRET-789\", \"reserve_pct\": \"5%\"}"
    )
    _commit_branch_edit(
        repo_path,
        branch_name=branch_name,
        updated_deal_name="discard-redact-edit",
        message=sensitive_msg,
    )

    response = client.delete(f"/api/deals/{deal_id}/branches/{branch_name}")
    assert response.status_code == 204

    # (a) branch is gone
    assert branch_name not in _branch_names(deal_id)

    # (b) redacted archive exists
    safe_branch = branch_name.replace("/", "_")
    archive_path = repo_path / "discarded_branches" / safe_branch / "redacted_messages.txt"
    assert archive_path.exists(), "Expected redacted_messages.txt archive"

    # (c) verbatim PII NOT in archive
    archive_text = archive_path.read_text(encoding="utf-8")
    assert "ABC-SECRET-789" not in archive_text

    # (d) audit log records the event
    audit_path = repo_path / "audit.log"
    assert audit_path.exists()
    audit_lines = audit_path.read_text(encoding="utf-8").splitlines()
    discard_records = [
        json.loads(line) for line in audit_lines
        if "branch_discarded" in line
    ]
    assert any(r.get("branch") == branch_name for r in discard_records)


def test_merge_stream_squashes_ephemeral_branch_and_runs_gc(
    client: TestClient,
    deal_id: str,
) -> None:
    """R1 pass-2 follow-up to C1: GET /merge/stream with branch=ai/turn-* must
    apply the same squash-on-Apply + gc_branch_after_apply logic as the
    POST /merge endpoint. Otherwise the SSE route is a PII back-door."""
    branch_name = "ai/turn-stream-apply"
    service = _service_for(deal_id)
    head_sha = _main_head_sha(deal_id)
    service.branch_create(branch_name, from_sha=head_sha)

    repo_path = deal_store.deal_dir(deal_id)
    sensitive_msg = "User said: 'Stream-apply for PRIVATE-STREAMED-DEAL-555'"
    _commit_branch_edit(
        repo_path,
        branch_name=branch_name,
        updated_deal_name="stream-apply-edit",
        message=sensitive_msg,
    )

    with client.stream(
        "GET",
        f"/api/deals/{deal_id}/merge/stream",
        params={"branch": branch_name},
    ) as response:
        assert response.status_code == 200
        events = []
        for line in response.iter_lines():
            if not line:
                continue
            text = line if isinstance(line, str) else line.decode("utf-8")
            if text.startswith("data: "):
                events.append(json.loads(text[len("data: "):]))

    # Stream should terminate with merge_complete carrying a SHA
    assert events[-1]["event_type"] == "merge_complete"
    merge_sha = events[-1]["sha"]
    assert merge_sha is not None

    # Single-parent (squash) on the merge commit
    parent_line = _run_git(["rev-list", "--parents", "-1", merge_sha], cwd=repo_path)
    parents = parent_line.strip().split()
    assert len(parents) == 2, (
        f"Expected single-parent squash via SSE; got {len(parents) - 1} parents."
    )

    # GC ran: the ephemeral branch is gone
    assert branch_name not in _branch_names(deal_id)

    # PII unreachable from any ref
    all_messages = _run_git(["log", "--all", "--format=%B"], cwd=repo_path)
    assert "PRIVATE-STREAMED-DEAL-555" not in all_messages
