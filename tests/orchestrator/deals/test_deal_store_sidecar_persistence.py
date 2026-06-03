from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bma_cfengine_app.api.main import app
from bma_cfengine_app.api.routers.deals import CommitRequest
from bma_cfengine_app.orchestrator.deals import deal_store
from bma_cfengine_app.orchestrator.deals import git_service as git_service_module
from bma_cfengine_app.orchestrator.deals.git_service import GitService
from bma_standard_formulas.deals.schemas.common import RuleType
from bma_standard_formulas.deals.schemas.ir import (
    AccountDef,
    BondDef,
    DealDefinition,
    FeeDef,
    RuleNode,
)
from bma_standard_formulas.deals.schemas.studio_sidecar import StudioSidecar
from bma_standard_formulas.diagnostics import Severity

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SIDECAR_LOAD_FAILED_MESSAGE = (
    "Sidecar could not be loaded; falling back to defaults. No deal data was lost."
)


def _run_git(
    repo_path: Path,
    *args: str,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
        env=env,
        input=input_text,
    )
    return proc.stdout.strip()


def _init_empty_repo(repo_path: Path) -> None:
    repo_path.mkdir(parents=True, exist_ok=True)
    _run_git(repo_path, "init")
    _run_git(repo_path, "symbolic-ref", "HEAD", "refs/heads/main")


def _force_backend(use_cli: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    if not use_cli:
        return
    if shutil.which("git") is None:
        pytest.skip("git CLI not available on PATH")
    monkeypatch.setattr(git_service_module, "pygit2", None, raising=False)


def _build_minimal_deal_payload(*, deal_name: str, coupon: float) -> dict[str, Any]:
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


def _build_sidecar_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "layout_overrides": {
            "A1": {"x": 120.0, "y": 80.0, "collapsed": False},
            "Reserve": {"x": 15.5, "y": 210.0},
        },
        "ui_preferences": {"graph_zoom": 1.1, "left_panel_open": True},
    }


def _canonical_deal_bytes(payload: dict[str, Any]) -> bytes:
    return DealDefinition.model_validate(payload).model_dump_json(indent=2).encode("utf-8")


def _canonical_sidecar_bytes(payload: dict[str, Any]) -> bytes:
    return StudioSidecar.model_validate(payload).model_dump_json(indent=2).encode("utf-8")


def _head_sha(service: GitService) -> str:
    commits = service.log(branch="main", limit=1)
    assert commits, "Expected at least one commit on main"
    return commits[0].sha


def _unpack_sidecar_load_result(
    loaded: Any,
) -> tuple[DealDefinition, StudioSidecar, list[Any]]:
    if not isinstance(loaded, tuple):
        pytest.fail(
            "load_deal must return (DealDefinition, StudioSidecar, diagnostics)"
        )
    if len(loaded) < 2:
        pytest.fail("load_deal must return at least deal + sidecar")
    deal_obj = loaded[0]
    sidecar_obj = loaded[1]
    diagnostics_obj = loaded[2] if len(loaded) > 2 else []
    if diagnostics_obj is None:
        diagnostics: list[Any] = []
    elif isinstance(diagnostics_obj, list):
        diagnostics = diagnostics_obj
    elif isinstance(diagnostics_obj, tuple):
        diagnostics = list(diagnostics_obj)
    else:
        diagnostics = [diagnostics_obj]
    return deal_obj, sidecar_obj, diagnostics


def _seed_commit_with_deal_and_optional_sidecar(
    *,
    repo_path: Path,
    deal_payload: dict[str, Any],
    sidecar_bytes: bytes | None,
    message: str,
) -> str:
    _init_empty_repo(repo_path)
    (repo_path / "deal.json").write_bytes(_canonical_deal_bytes(deal_payload))
    add_paths = ["deal.json"]
    if sidecar_bytes is not None:
        (repo_path / "sidecar.json").write_bytes(sidecar_bytes)
        add_paths.append("sidecar.json")
    _run_git(repo_path, "add", *add_paths)
    commit_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Tester",
        "GIT_AUTHOR_EMAIL": "tester@example.com",
        "GIT_COMMITTER_NAME": "Tester",
        "GIT_COMMITTER_EMAIL": "tester@example.com",
    }
    _run_git(repo_path, "commit", "-m", message, env=commit_env)
    return _run_git(repo_path, "rev-parse", "HEAD")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)
    deal_store.init_deals_workspace()
    return TestClient(app)


@pytest.mark.parametrize("use_cli", [False, True], ids=["pygit2", "cli"])
def test_commit_deal_writes_deal_and_sidecar_atomically(
    tmp_path: Path,
    use_cli: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_backend(use_cli, monkeypatch)
    repo_path = tmp_path / "repo"
    _init_empty_repo(repo_path)
    service = GitService(repo_path=repo_path)

    deal_payload = _build_minimal_deal_payload(
        deal_name="sdpm2-atomic-sidecar",
        coupon=6.0,
    )
    sidecar_payload = _build_sidecar_payload()

    sha = service.commit_deal(
        deal_payload,
        author="Tester <tester@example.com>",
        message="commit deal and sidecar atomically",
        parent_sha=None,
        sidecar_payload=sidecar_payload,
    )

    assert _SHA_RE.fullmatch(sha)
    assert service.show(sha, "deal.json") == _canonical_deal_bytes(deal_payload)
    assert service.show(sha, "sidecar.json") == _canonical_sidecar_bytes(sidecar_payload)


@pytest.mark.parametrize("use_cli", [False, True], ids=["pygit2", "cli"])
def test_load_deal_reads_deal_and_sidecar(
    tmp_path: Path,
    use_cli: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_backend(use_cli, monkeypatch)
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)
    deal_store.init_deals_workspace()

    deal_id = "deal_sidecar_load_happy_path"
    repo_path = deal_store.deal_dir(deal_id)
    _init_empty_repo(repo_path)
    service = GitService(repo_path=repo_path)

    deal_payload = _build_minimal_deal_payload(
        deal_name="sdpm2-load-sidecar",
        coupon=6.1,
    )
    sidecar_payload = _build_sidecar_payload()
    service.commit_deal(
        deal_payload,
        author="Tester <tester@example.com>",
        message="seed deal with sidecar",
        parent_sha=None,
        sidecar_payload=sidecar_payload,
    )

    loaded = deal_store.load_deal(deal_id)
    loaded_deal, loaded_sidecar, _diagnostics = _unpack_sidecar_load_result(loaded)

    assert loaded_deal.model_dump(mode="json") == DealDefinition.model_validate(
        deal_payload
    ).model_dump(mode="json")
    assert loaded_sidecar == StudioSidecar.model_validate(sidecar_payload)


@pytest.mark.parametrize("use_cli", [False, True], ids=["pygit2", "cli"])
def test_corrupted_sidecar_triggers_rollback_archive_and_diagnostic(
    tmp_path: Path,
    use_cli: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_backend(use_cli, monkeypatch)
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)
    deal_store.init_deals_workspace()

    deal_id = "deal_sidecar_corrupted_load"
    repo_path = deal_store.deal_dir(deal_id)
    malformed_sidecar = b'{"schema_version":"1.0.0","layout_overrides":'
    expected_deal_payload = _build_minimal_deal_payload(
        deal_name="sdpm2-corrupted-sidecar",
        coupon=6.2,
    )
    _seed_commit_with_deal_and_optional_sidecar(
        repo_path=repo_path,
        deal_payload=expected_deal_payload,
        sidecar_bytes=malformed_sidecar,
        message="seed malformed sidecar",
    )
    service = GitService(repo_path=repo_path)
    head_sha = _head_sha(service)

    loaded = deal_store.load_deal(deal_id)
    loaded_deal, loaded_sidecar, diagnostics = _unpack_sidecar_load_result(loaded)

    assert loaded_deal.model_dump(mode="json") == DealDefinition.model_validate(
        expected_deal_payload
    ).model_dump(mode="json")

    broken_path = repo_path / "sidecar.broken.json"
    assert broken_path.exists()
    assert broken_path.read_bytes() == malformed_sidecar
    with pytest.raises(Exception):
        service.show(head_sha, "sidecar.broken.json")

    assert loaded_sidecar == StudioSidecar()

    failure_diagnostics = [
        diag for diag in diagnostics if getattr(diag, "code", None) == "SIDECAR_LOAD_FAILED"
    ]
    assert failure_diagnostics, "Expected SIDECAR_LOAD_FAILED diagnostic"
    diagnostic = failure_diagnostics[0]
    assert getattr(diagnostic, "severity", None) in (Severity.info, "info")
    assert getattr(diagnostic, "message", None) == _SIDECAR_LOAD_FAILED_MESSAGE


def test_commit_request_extension_accepts_sidecar_payload(client: TestClient) -> None:
    deal_id = "deal_http_sidecar_commit"
    initial = DealDefinition.model_validate(
        _build_minimal_deal_payload(deal_name="sdpm2-http-initial", coupon=5.0)
    )
    deal_store.save_deal(deal_id, initial)

    service = GitService(repo_path=deal_store.deal_dir(deal_id))
    parent_sha = _head_sha(service)
    next_payload = _build_minimal_deal_payload(deal_name="sdpm2-http-next", coupon=5.2)
    sidecar_payload = _build_sidecar_payload()

    response = client.post(
        f"/api/deals/{deal_id}/commit",
        json={
            "author": "Tester <tester@example.com>",
            "message": "http commit with sidecar",
            "parent_sha": parent_sha,
            "payload": next_payload,
            "sidecar_payload": sidecar_payload,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert _SHA_RE.fullmatch(body["sha"])
    assert service.show(body["sha"], "sidecar.json") == _canonical_sidecar_bytes(
        sidecar_payload
    )


def test_commit_request_omits_sidecar_payload_preserves_irvc4_behavior(
    client: TestClient,
) -> None:
    assert "sidecar_payload" in CommitRequest.model_fields
    assert CommitRequest.model_fields["sidecar_payload"].default is None

    deal_id = "deal_http_sidecar_legacy_compat"
    repo_path = deal_store.deal_dir(deal_id)
    expected_deal_payload = _build_minimal_deal_payload(
        deal_name="sdpm2-http-compat",
        coupon=5.1,
    )
    expected_sidecar_payload = _build_sidecar_payload()
    parent_sha = _seed_commit_with_deal_and_optional_sidecar(
        repo_path=repo_path,
        deal_payload=expected_deal_payload,
        sidecar_bytes=_canonical_sidecar_bytes(expected_sidecar_payload),
        message="seed deal + sidecar before legacy commit",
    )

    response = client.post(
        f"/api/deals/{deal_id}/commit",
        json={
            "author": "Tester <tester@example.com>",
            "message": "legacy commit body without sidecar payload",
            "parent_sha": parent_sha,
            "force": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert _SHA_RE.fullmatch(body["sha"])

    service = GitService(repo_path=repo_path)
    assert service.show(body["sha"], "deal.json") == service.show(parent_sha, "deal.json")
    assert service.show(body["sha"], "sidecar.json") == _canonical_sidecar_bytes(
        expected_sidecar_payload
    )


# ---------------------------------------------------------------------------
# Regression: M1 — successful save removes sidecar.broken.json from working tree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("use_cli", [False, True], ids=["pygit2", "cli"])
def test_successful_save_removes_broken_sidecar(
    tmp_path: Path,
    use_cli: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a corrupted-sidecar load creates sidecar.broken.json, a subsequent
    commit_deal with a valid sidecar_payload must remove sidecar.broken.json
    from the working tree. (R1 M1 regression)"""
    _force_backend(use_cli, monkeypatch)
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)
    deal_store.init_deals_workspace()

    deal_id = "deal_m1_broken_cleanup"
    repo_path = deal_store.deal_dir(deal_id)
    deal_payload = _build_minimal_deal_payload(deal_name="sdpm2-m1-cleanup", coupon=6.3)
    malformed_sidecar = b'{"schema_version":"1.0.0","layout_overrides":'
    parent_sha = _seed_commit_with_deal_and_optional_sidecar(
        repo_path=repo_path,
        deal_payload=deal_payload,
        sidecar_bytes=malformed_sidecar,
        message="seed malformed sidecar",
    )

    deal_store.load_deal(deal_id)
    broken_path = repo_path / "sidecar.broken.json"
    assert broken_path.exists(), "sidecar.broken.json should exist after loading corrupted sidecar"

    service = GitService(repo_path=repo_path)
    sidecar_payload = _build_sidecar_payload()
    service.commit_deal(
        deal_payload,
        author="Tester <tester@example.com>",
        message="repair: save valid sidecar",
        parent_sha=parent_sha,
        sidecar_payload=sidecar_payload,
    )

    assert not broken_path.exists(), (
        "sidecar.broken.json must be removed from the working tree after a "
        "successful commit_deal with a valid sidecar_payload"
    )


# ---------------------------------------------------------------------------
# Regression: M2 — staged sidecar.broken.json must not appear in commit tree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("use_cli", [False, True], ids=["pygit2", "cli"])
def test_staged_broken_sidecar_excluded_from_commit(
    tmp_path: Path,
    use_cli: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even if sidecar.broken.json was already staged (e.g. by manual git add),
    the resulting commit_deal tree must NOT contain it. (R1 M2 regression)"""
    _force_backend(use_cli, monkeypatch)

    repo_path = tmp_path / "repo"
    _init_empty_repo(repo_path)

    broken_content = b'{"schema_version":"1.0.0","broken":true}'
    (repo_path / "sidecar.broken.json").write_bytes(broken_content)
    _run_git(repo_path, "add", "sidecar.broken.json")

    service = GitService(repo_path=repo_path)
    deal_payload = _build_minimal_deal_payload(deal_name="sdpm2-m2-staged", coupon=6.4)
    sidecar_payload = _build_sidecar_payload()

    sha = service.commit_deal(
        deal_payload,
        author="Tester <tester@example.com>",
        message="commit with valid sidecar; staged broken must not be in tree",
        parent_sha=None,
        sidecar_payload=sidecar_payload,
    )

    with pytest.raises(Exception):
        service.show(sha, "sidecar.broken.json")

    assert service.show(sha, "sidecar.json") == _canonical_sidecar_bytes(sidecar_payload)
