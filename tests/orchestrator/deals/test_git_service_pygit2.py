from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

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


def test_commit_deal_creates_commit_with_expected_metadata(tmp_path: Path) -> None:
    """AC 1, 2: commit_deal writes deal.json and commits author/message/parent metadata."""
    pygit2 = pytest.importorskip("pygit2")

    from bma_cfengine_app.orchestrator.deals.git_service import GitService

    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    parent_sha = _seed_repo_with_initial_commit(repo_path)

    service = GitService(repo_path=repo_path)
    deal_payload = {
        "schema_version": "2.0.0",
        "deal_name": "Git Service Test Deal",
        "bonds": [],
        "accounts": [],
        "fees": [],
        "waterfall_rules": [],
    }
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
