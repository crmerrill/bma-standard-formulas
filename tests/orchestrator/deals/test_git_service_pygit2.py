from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


def _run_git(repo_path: Path, *args: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout.strip()


def _seed_repo_with_initial_commit(repo_path: Path) -> str:
    _run_git(repo_path, "init", "-b", "main")
    (repo_path / "deal.json").write_text(json.dumps({"deal_name": "seed"}), encoding="utf-8")
    _run_git(repo_path, "add", "deal.json")
    commit_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Seed User",
        "GIT_AUTHOR_EMAIL": "seed@example.com",
        "GIT_COMMITTER_NAME": "Seed User",
        "GIT_COMMITTER_EMAIL": "seed@example.com",
    }
    _run_git(repo_path, "commit", "-m", "seed commit", env=commit_env)
    return _run_git(repo_path, "rev-parse", "HEAD")


def _payload(name: str) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "deal_name": name,
        "bonds": [],
        "accounts": [],
        "fees": [],
        "waterfall_rules": [],
    }


def test_commit_deal_creates_commit_with_expected_metadata(tmp_path: Path) -> None:
    """AC 1, 2: commit_deal writes deal.json and commits author/message/parent metadata."""
    pygit2 = pytest.importorskip("pygit2")

    from bma_cfengine_app.orchestrator.deals.git_service import GitService

    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    parent_sha = _seed_repo_with_initial_commit(repo_path)

    service = GitService(repo_path=repo_path)
    deal_payload = _payload("Git Service Test Deal")
    author = "Git Service Tester <git-service@test.local>"
    message = "Commit deal payload from pygit2 path"

    sha = service.commit_deal(
        deal_payload=deal_payload,
        author=author,
        message=message,
        parent_sha=parent_sha,
    )

    assert re.fullmatch(r"[0-9a-f]{40}", sha), f"Expected 40-char SHA, got {sha!r}"

    repo = pygit2.Repository(str(repo_path / ".git"))
    commit = repo.revparse_single(sha)

    assert commit.author.name == "Git Service Tester"
    assert commit.author.email == "git-service@test.local"
    assert commit.message.strip() == message
    assert len(commit.parent_ids) == 1
    assert str(commit.parent_ids[0]) == parent_sha

    deal_entry = commit.tree["deal.json"]
    deal_blob = repo[deal_entry.id]
    assert json.loads(deal_blob.data.decode("utf-8")) == deal_payload


def test_commit_deal_writes_deal_json_to_working_tree(tmp_path: Path) -> None:
    """B1: pygit2 commit_deal writes deal.json to working tree matching committed blob."""
    pygit2 = pytest.importorskip("pygit2")

    from bma_cfengine_app.orchestrator.deals.git_service import GitService

    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    parent_sha = _seed_repo_with_initial_commit(repo_path)

    service = GitService(repo_path=repo_path)
    deal_payload = _payload("B1 Working Tree Test")
    sha = service.commit_deal(
        deal_payload=deal_payload,
        author="B1 Tester <b1@test.local>",
        message="B1 regression test commit",
        parent_sha=parent_sha,
    )

    deal_path = repo_path / "deal.json"
    assert deal_path.exists(), "deal.json must exist on disk after commit_deal"
    on_disk = deal_path.read_bytes()

    committed = _run_git(repo_path, "show", f"{sha}:deal.json").encode("utf-8")
    assert on_disk == committed


def test_pygit2_errors_raise_git_service_error(tmp_path: Path) -> None:
    """C1: pygit2 backend exceptions are normalized to GitServiceError."""
    pygit2_mod = pytest.importorskip("pygit2")

    from bma_cfengine_app.orchestrator.deals.git_service import GitService, GitServiceError

    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    _seed_repo_with_initial_commit(repo_path)

    service = GitService(repo_path=repo_path)

    original_repo_init = pygit2_mod.Repository

    def broken_repo(*a: Any, **kw: Any) -> None:
        raise pygit2_mod.GitError("simulated libgit2 failure")

    with patch.object(pygit2_mod, "Repository", broken_repo):
        with pytest.raises(GitServiceError, match="simulated libgit2 failure"):
            service.branch_list()


def test_pygit2_full_operation_parity(tmp_path: Path) -> None:
    """M2: pygit2 backend exercises the same journey as the CLI parity test."""
    pytest.importorskip("pygit2")

    from bma_cfengine_app.orchestrator.deals.git_service import GitService

    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    seed_sha = _seed_repo_with_initial_commit(repo_path)
    service = GitService(repo_path=repo_path)

    sha_a = service.commit_deal(
        deal_payload=_payload("Pygit2 Path A"),
        author="PG Tester <pg@test.local>",
        message="pygit2 commit A",
        parent_sha=seed_sha,
    )
    assert re.fullmatch(r"[0-9a-f]{40}", sha_a)

    service.branch_create("what-if/x", from_sha=sha_a)
    branches = service.branch_list()
    assert isinstance(branches, list)
    created = next((b for b in branches if b["name"] == "what-if/x"), None)
    assert created is not None
    assert created["tip_sha"] == sha_a

    sha_b = service.commit_deal(
        deal_payload=_payload("Pygit2 Path B"),
        author="PG Tester <pg@test.local>",
        message="pygit2 commit B",
        parent_sha=sha_a,
    )
    assert re.fullmatch(r"[0-9a-f]{40}", sha_b)

    log_entries = service.log("main")
    assert isinstance(log_entries, list)
    assert len(log_entries) >= 2
    assert log_entries[0]["sha"] == sha_b
    assert log_entries[1]["sha"] == sha_a

    shown = service.show(sha_b, "deal.json")
    assert isinstance(shown, (bytes, bytearray))
    assert json.loads(bytes(shown).decode("utf-8")) == _payload("Pygit2 Path B")

    diff_result = service.diff(sha_a, sha_b)
    assert diff_result is not None

    merge_base_sha = service.merge_base("main", "what-if/x")
    assert merge_base_sha == sha_a

    service.branch_delete("what-if/x")
    remaining = service.branch_list()
    assert all(b["name"] != "what-if/x" for b in remaining)
