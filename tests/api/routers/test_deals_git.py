from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

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

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class CommitResponse(BaseModel):
    sha: str


class BranchInfo(BaseModel):
    name: str
    tip_sha: str
    created_at: datetime


class BranchListResponse(BaseModel):
    branches: list[BranchInfo]


class CommitMeta(BaseModel):
    sha: str
    author: str
    message: str
    committed_at: datetime
    parent_sha: str | None


class LogResponse(BaseModel):
    commits: list[CommitMeta]


class StructuralDiffEntry(BaseModel):
    model_config = ConfigDict(extra="allow")


class DiffResponse(BaseModel):
    structural_diff: list[StructuralDiffEntry]


class MergeProgressEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_type: Literal["merge_started", "entity_merged", "merge_complete", "merge_failed"]
    progress: float = Field(ge=0.0, le=1.0)
    current_entity: str | None = None
    total_entities: int = Field(ge=0)
    sha: str | None = None
    diagnostic: dict[str, Any] | None = None


@pytest.fixture
def client(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)
    deal_store.init_deals_workspace()
    return TestClient(app)


@pytest.fixture
def deal_id(client: TestClient) -> str:
    deal_identifier = "deal_git_api"
    deal_store.save_deal(
        deal_identifier,
        _build_minimal_deal_definition(deal_name="git-api-initial", coupon=5.0),
    )
    deal_store.save_deal(
        deal_identifier,
        _build_minimal_deal_definition(deal_name="git-api-updated", coupon=5.5),
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


def _main_history(deal_identifier: str, *, limit: int = 10) -> list[str]:
    commits = _service_for(deal_identifier).log(branch="main", limit=limit)
    return [commit.sha for commit in commits]


def _main_head_sha(deal_identifier: str) -> str:
    history = _main_history(deal_identifier, limit=1)
    assert history, "Expected at least one commit on main"
    return history[0]


def _extract_sse_data(line: str | bytes) -> dict[str, Any] | None:
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    if not line.startswith("data:"):
        return None
    payload = line[len("data:") :].strip()
    if not payload:
        return None
    return json.loads(payload)


def test_commit_endpoint_returns_409_on_stale_sha(client: TestClient, deal_id: str) -> None:
    stale = client.post(
        f"/api/deals/{deal_id}/commit",
        json={
            "author": "Tester <tester@example.com>",
            "message": "stale write",
            "parent_sha": "0" * 40,
            "force": False,
        },
    )
    assert stale.status_code == 409

    head_sha = _main_head_sha(deal_id)
    fresh = client.post(
        f"/api/deals/{deal_id}/commit",
        json={
            "author": "Tester <tester@example.com>",
            "message": "fresh write",
            "parent_sha": head_sha,
            "force": False,
        },
    )
    assert fresh.status_code in {200, 201}
    body = CommitResponse.model_validate(fresh.json())
    assert _SHA_RE.fullmatch(body.sha), f"Invalid commit SHA in response: {body.sha!r}"


def test_commit_endpoint_force_true_overwrites(client: TestClient, deal_id: str) -> None:
    response = client.post(
        f"/api/deals/{deal_id}/commit",
        json={
            "author": "Tester <tester@example.com>",
            "message": "force write",
            "parent_sha": "0" * 40,
            "force": True,
        },
    )
    assert response.status_code in {200, 201}
    body = CommitResponse.model_validate(response.json())
    assert _SHA_RE.fullmatch(body.sha), f"Invalid commit SHA in response: {body.sha!r}"


def test_git_read_endpoints_conform_to_schema(client: TestClient, deal_id: str) -> None:
    history = _main_history(deal_id, limit=10)
    assert len(history) >= 2, "Seed data must create at least two commits"
    head_sha = history[0]
    base_sha = history[1]

    branches_res = client.get(f"/api/deals/{deal_id}/branches")
    assert branches_res.status_code == 200
    branches = BranchListResponse.model_validate(branches_res.json())
    assert any(branch.name == "main" for branch in branches.branches)
    assert all(_SHA_RE.fullmatch(branch.tip_sha) for branch in branches.branches)

    create_branch_res = client.post(
        f"/api/deals/{deal_id}/branches",
        json={"name": "what-if/foo", "from_sha": head_sha},
    )
    assert create_branch_res.status_code == 201
    created_branch = BranchInfo.model_validate(create_branch_res.json())
    assert created_branch.name == "what-if/foo"
    assert _SHA_RE.fullmatch(created_branch.tip_sha)

    log_res = client.get(f"/api/deals/{deal_id}/log", params={"branch": "main", "limit": 10})
    assert log_res.status_code == 200
    log_body = LogResponse.model_validate(log_res.json())
    assert len(log_body.commits) >= 2
    assert all(_SHA_RE.fullmatch(entry.sha) for entry in log_body.commits)

    show_res = client.get(
        f"/api/deals/{deal_id}/show",
        params={"sha": head_sha, "path": "deal.json"},
    )
    assert show_res.status_code == 200
    deal_payload = json.loads(show_res.content.decode("utf-8"))
    assert deal_payload["deal_name"] == "git-api-updated"

    diff_res = client.get(
        f"/api/deals/{deal_id}/diff",
        params={"a": base_sha, "b": head_sha},
    )
    assert diff_res.status_code == 200
    diff_body = DiffResponse.model_validate(diff_res.json())
    assert isinstance(diff_body.structural_diff, list)


def test_branch_delete_namespace_ai_turn(client: TestClient, deal_id: str) -> None:
    branch_name = "ai/turn-myslug"
    service = _service_for(deal_id)
    service.branch_create(branch_name, from_sha=_main_head_sha(deal_id))

    delete_res = client.delete(f"/api/deals/{deal_id}/branches/{branch_name}")
    assert delete_res.status_code == 204

    list_res = client.get(f"/api/deals/{deal_id}/branches")
    assert list_res.status_code == 200
    branches = BranchListResponse.model_validate(list_res.json())
    assert branch_name not in {branch.name for branch in branches.branches}


def test_branch_delete_namespace_solver_run(client: TestClient, deal_id: str) -> None:
    branch_name = "solver/run-test1"
    service = _service_for(deal_id)
    service.branch_create(branch_name, from_sha=_main_head_sha(deal_id))

    delete_res = client.delete(f"/api/deals/{deal_id}/branches/{branch_name}")
    assert delete_res.status_code == 204

    list_res = client.get(f"/api/deals/{deal_id}/branches")
    assert list_res.status_code == 200
    branches = BranchListResponse.model_validate(list_res.json())
    assert branch_name not in {branch.name for branch in branches.branches}


def test_branch_delete_namespace_what_if(client: TestClient, deal_id: str) -> None:
    branch_name = "what-if/scenario-a"
    service = _service_for(deal_id)
    service.branch_create(branch_name, from_sha=_main_head_sha(deal_id))

    delete_res = client.delete(f"/api/deals/{deal_id}/branches/{branch_name}")
    assert delete_res.status_code == 204

    list_res = client.get(f"/api/deals/{deal_id}/branches")
    assert list_res.status_code == 200
    branches = BranchListResponse.model_validate(list_res.json())
    assert branch_name not in {branch.name for branch in branches.branches}


def test_merge_sse_telemetry_yields_progress_events_with_terminal_close(
    client: TestClient,
    deal_id: str,
) -> None:
    service = _service_for(deal_id)
    history = _main_history(deal_id, limit=2)
    assert len(history) >= 2, "Seed data must create at least two commits"
    service.branch_create("what-if/foo", from_sha=history[-1])

    events: list[MergeProgressEvent] = []
    post_terminal_events: list[MergeProgressEvent] = []
    terminal_types = {"merge_complete", "merge_failed"}
    terminal_seen = False

    with client.stream(
        "GET",
        f"/api/deals/{deal_id}/merge/stream",
        params={"branch": "what-if/foo"},
        timeout=10.0,
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            payload = _extract_sse_data(line)
            if payload is None:
                continue
            event = MergeProgressEvent.model_validate(payload)
            if terminal_seen:
                post_terminal_events.append(event)
                continue
            events.append(event)
            if event.event_type in terminal_types:
                terminal_seen = True

    assert events, "Expected at least one SSE merge event"
    assert events[0].event_type == "merge_started"

    event_types = [event.event_type for event in events]
    assert all(event_type == "entity_merged" for event_type in event_types[1:-1])
    assert event_types[-1] in terminal_types
    assert len([event for event in events if event.event_type in terminal_types]) == 1
    assert post_terminal_events == []

    terminal_event = events[-1]
    if terminal_event.event_type == "merge_complete":
        assert terminal_event.sha is not None
        assert _SHA_RE.fullmatch(terminal_event.sha)


# ---------------------------------------------------------------------------
# R1 regression tests (irvc-4-fix-pass)
# ---------------------------------------------------------------------------


def test_branch_delete_main_is_rejected_with_409(
    client: TestClient, deal_id: str
) -> None:
    """C1: DELETE /branches/main returns 409 with PROTECTED_BRANCH code."""
    response = client.delete(f"/api/deals/{deal_id}/branches/main")
    assert response.status_code == 409
    body = response.json()
    assert body.get("detail", {}).get("code") == "PROTECTED_BRANCH"


def test_commit_endpoint_accepts_null_parent_sha_on_brand_new_deal(
    client: TestClient,
) -> None:
    """M1: null parent_sha is accepted when the deal repo has no commits yet."""
    import subprocess

    deal_identifier = "deal_brand_new"
    repo_path = deal_store.deal_dir(deal_identifier)
    subprocess.run(["git", "init", str(repo_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True,
        capture_output=True,
    )

    response = client.post(
        f"/api/deals/{deal_identifier}/commit",
        json={
            "author": "Tester <tester@example.com>",
            "message": "initial commit on brand-new deal",
            "parent_sha": None,
            "force": False,
        },
    )
    assert response.status_code in {200, 201}
    body = response.json()
    assert _SHA_RE.fullmatch(body["sha"]), f"Invalid commit SHA: {body['sha']!r}"


def test_commit_endpoint_returns_409_on_null_parent_sha_when_head_exists(
    client: TestClient, deal_id: str
) -> None:
    """M1: null parent_sha conflicts with an existing HEAD commit, returning 409."""
    response = client.post(
        f"/api/deals/{deal_id}/commit",
        json={
            "author": "Tester <tester@example.com>",
            "message": "should be rejected",
            "parent_sha": None,
            "force": False,
        },
    )
    assert response.status_code == 409
    body = response.json()
    assert body.get("detail", {}).get("code") == "STALE_PARENT_SHA"


def test_merge_stream_emits_diagnostic_on_typed_conflict(
    client: TestClient, deal_id: str
) -> None:
    """M2: SSE merge_failed event carries full DiagnosticPayload shape on typed conflict."""
    import subprocess
    from typing import Any

    service = _service_for(deal_id)
    repo_path = deal_store.deal_dir(deal_id)
    author = "Tester <tester@example.com>"

    history = _main_history(deal_id, limit=10)
    assert len(history) >= 2, "Seed data must create at least two commits"
    # history is newest-first; oldest commit is the ancestor
    base_sha = history[-1]
    our_sha = history[0]

    # Create branch from ancestor (ours = main at our_sha, ancestor = base_sha)
    service.branch_create("what-if/sse-conflict", from_sha=base_sha)

    # Theirs: coupon=99.0 from the same ancestor; since main != base_sha,
    # commit_deal goes to detached HEAD, leaving main at our_sha.
    their_payload = _build_minimal_deal_definition(deal_name="git-api-initial", coupon=99.0)
    their_sha = service.commit_deal(
        their_payload.model_dump(mode="json"),
        author=author,
        message="theirs: coupon=99.0 (conflict branch)",
        parent_sha=base_sha,
    )
    subprocess.run(
        ["git", "branch", "-f", "what-if/sse-conflict", their_sha],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    # Restore main (commit_deal may have moved HEAD via set_head)
    subprocess.run(
        ["git", "checkout", "main"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    # Sanity: ensure main is still at our_sha
    subprocess.run(
        ["git", "reset", "--hard", our_sha],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    raw_events: list[dict[str, Any]] = []
    with client.stream(
        "GET",
        f"/api/deals/{deal_id}/merge/stream",
        params={"branch": "what-if/sse-conflict"},
        timeout=10.0,
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            payload = _extract_sse_data(line)
            if payload is None:
                continue
            raw_events.append(payload)

    assert raw_events, "Expected at least one SSE event"
    terminal = raw_events[-1]
    assert terminal["event_type"] == "merge_failed", (
        f"Expected merge_failed terminal event, got {terminal['event_type']!r}"
    )
    diag = terminal.get("diagnostic")
    assert diag is not None, "merge_failed event must carry a 'diagnostic' key"
    assert diag.get("code") == "MERGE_CONFLICT", f"Expected MERGE_CONFLICT, got {diag.get('code')!r}"
    assert "severity" in diag, "diagnostic must include 'severity'"
    assert "path" in diag, "diagnostic must include 'path'"
    assert "message" in diag, "diagnostic must include 'message'"


def test_lww_future_collaboration_marker_present_in_router() -> None:
    """m2/AC 4: The verbatim Python FUTURE marker must exist in the router.

    The TypeScript marker is deferred until the frontend conflict UI ticket opens.
    """
    from pathlib import Path

    router_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "bma_cfengine_app"
        / "api"
        / "routers"
        / "deals.py"
    )
    content = router_path.read_text(encoding="utf-8")
    assert "# FUTURE: collaboration — replace last-writer-wins with merge UI" in content, (
        "Python FUTURE marker missing from router; "
        "add: # FUTURE: collaboration — replace last-writer-wins with merge UI"
    )
