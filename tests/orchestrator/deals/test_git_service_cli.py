from __future__ import annotations

import json
import os
import re
import shutil
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


def test_cli_fallback_parity_when_pygit2_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC 1, 3: CLI fallback implements commit/branch/log/show/diff/merge-base operations."""
    if shutil.which("git") is None:
        pytest.skip("git CLI not available on PATH")

    from bma_cfengine_app.orchestrator.deals import git_service as git_service_module

    monkeypatch.setattr(git_service_module, "pygit2", None, raising=False)

    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    seed_sha = _seed_repo_with_initial_commit(repo_path)
    service = git_service_module.GitService(repo_path=repo_path)

    payload_a = {
        "schema_version": "2.0.0",
        "deal_name": "CLI Path A",
        "bonds": [],
        "accounts": [],
        "fees": [],
        "waterfall_rules": [],
    }
    sha_a = service.commit_deal(
        deal_payload=payload_a,
        author="CLI Tester <cli@test.local>",
        message="CLI commit A",
        parent_sha=seed_sha,
    )
    assert re.fullmatch(r"[0-9a-f]{40}", sha_a), f"Expected 40-char SHA, got {sha_a!r}"

    service.branch_create("what-if/x", from_sha=sha_a)
    branches = service.branch_list()
    assert isinstance(branches, list)
    created_branch = next((b for b in branches if b["name"] == "what-if/x"), None)
    assert created_branch is not None
    assert created_branch["tip_sha"] == sha_a

    payload_b = {
        "schema_version": "2.0.0",
        "deal_name": "CLI Path B",
        "bonds": [],
        "accounts": [],
        "fees": [],
        "waterfall_rules": [],
    }
    sha_b = service.commit_deal(
        deal_payload=payload_b,
        author="CLI Tester <cli@test.local>",
        message="CLI commit B",
        parent_sha=sha_a,
    )
    assert re.fullmatch(r"[0-9a-f]{40}", sha_b), f"Expected 40-char SHA, got {sha_b!r}"

    log_entries = service.log("main")
    assert isinstance(log_entries, list)
    assert len(log_entries) >= 2
    assert log_entries[0]["sha"] == sha_b
    assert log_entries[1]["sha"] == sha_a

    shown = service.show(sha_b, "deal.json")
    assert isinstance(shown, (bytes, bytearray))
    assert json.loads(bytes(shown).decode("utf-8")) == payload_b

    diff_result = service.diff(sha_a, sha_b)
    assert diff_result is not None

    merge_base_sha = service.merge_base("main", "what-if/x")
    assert merge_base_sha == sha_a

    service.branch_delete("what-if/x")
    remaining_branches = service.branch_list()
    assert all(branch["name"] != "what-if/x" for branch in remaining_branches)


def test_cli_log_empty_repo_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M1: log on an empty repo (no commits) returns [] instead of raising."""
    if shutil.which("git") is None:
        pytest.skip("git CLI not available on PATH")

    from bma_cfengine_app.orchestrator.deals import git_service as git_service_module

    monkeypatch.setattr(git_service_module, "pygit2", None, raising=False)

    repo_path = tmp_path / "empty_repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    _run_git(repo_path, "init", "-b", "main")

    service = git_service_module.GitService(repo_path=repo_path)
    entries = service.log("main")
    assert entries == []


def test_cli_log_first_parent_for_merge_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M1: log returns the first parent (integration target) for merge commits."""
    if shutil.which("git") is None:
        pytest.skip("git CLI not available on PATH")

    from bma_cfengine_app.orchestrator.deals import git_service as git_service_module

    monkeypatch.setattr(git_service_module, "pygit2", None, raising=False)

    repo_path = tmp_path / "merge_repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    seed_sha = _seed_repo_with_initial_commit(repo_path)

    commit_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Merge Tester",
        "GIT_AUTHOR_EMAIL": "merge@test.local",
        "GIT_COMMITTER_NAME": "Merge Tester",
        "GIT_COMMITTER_EMAIL": "merge@test.local",
    }
    _run_git(repo_path, "checkout", "-b", "what-if/feature", env=commit_env)
    (repo_path / "feature.txt").write_text("feature content", encoding="utf-8")
    _run_git(repo_path, "add", "feature.txt", env=commit_env)
    _run_git(repo_path, "commit", "-m", "feature commit", env=commit_env)

    _run_git(repo_path, "checkout", "main", env=commit_env)
    (repo_path / "main-only.txt").write_text("main content", encoding="utf-8")
    _run_git(repo_path, "add", "main-only.txt", env=commit_env)
    _run_git(repo_path, "commit", "-m", "main update", env=commit_env)
    main_before_merge = _run_git(repo_path, "rev-parse", "HEAD")

    _run_git(repo_path, "merge", "what-if/feature", "--no-ff", "--no-edit", env=commit_env)
    merge_sha = _run_git(repo_path, "rev-parse", "HEAD")

    service = git_service_module.GitService(repo_path=repo_path)
    log_entries = service.log("main", limit=5)

    merge_entry = next(e for e in log_entries if e["sha"] == merge_sha)
    assert merge_entry["parent_sha"] == main_before_merge
