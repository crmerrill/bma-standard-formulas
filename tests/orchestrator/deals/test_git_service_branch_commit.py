from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from bma_cfengine_app.orchestrator.deals.git_service import (
    GitService,
    InvalidBranchNameError,
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


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
    (repo_path / "deal.json").write_text(
        json.dumps({"deal_name": "seed"}, indent=2),
        encoding="utf-8",
    )
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


def _branch_tip(service: GitService, branch: str) -> str:
    tips = {entry.name: entry.tip_sha for entry in service.branch_list()}
    assert branch in tips, f"Expected branch {branch!r} to exist"
    return tips[branch]


def test_commit_deal_writes_to_supplied_commit_target_branch_only(tmp_path: Path) -> None:
    """AC 4, 6: commit_target branch advances while main stays byte-identical."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    main_tip = _seed_repo_with_initial_commit(repo_path)
    service = GitService(repo_path=repo_path)

    service.branch_create("ai/turn-test", from_sha=main_tip)
    ephemeral_tip_before = _branch_tip(service, "ai/turn-test")
    main_bytes_before = service.show(main_tip, "deal.json")

    new_sha = service.commit_deal(
        _payload("ephemeral-commit"),
        author="Tester <tester@example.com>",
        message="commit onto ephemeral branch",
        parent_sha=ephemeral_tip_before,
        commit_target="ai/turn-test",
    )

    assert _SHA_RE.fullmatch(new_sha)
    assert _branch_tip(service, "ai/turn-test") == new_sha
    assert _branch_tip(service, "main") == main_tip
    assert service.show(main_tip, "deal.json") == main_bytes_before

    branch_log = service.log(branch="ai/turn-test", limit=2)
    assert len(branch_log) >= 2
    assert branch_log[0].sha == new_sha
    assert branch_log[0].parent_sha == ephemeral_tip_before
    assert branch_log[1].sha == ephemeral_tip_before


def test_commit_deal_default_commit_target_remains_main_for_backward_compat(
    tmp_path: Path,
) -> None:
    """AC 4, 5: omitted commit_target keeps legacy main behavior."""
    signature = inspect.signature(GitService.commit_deal)
    assert "commit_target" in signature.parameters
    assert signature.parameters["commit_target"].default == "main"

    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    main_tip = _seed_repo_with_initial_commit(repo_path)
    service = GitService(repo_path=repo_path)

    legacy_sha = service.commit_deal(
        _payload("legacy-default-target"),
        author="Tester <tester@example.com>",
        message="legacy kwargs call",
        parent_sha=main_tip,
    )
    assert _SHA_RE.fullmatch(legacy_sha)
    assert _branch_tip(service, "main") == legacy_sha

    explicit_sha = service.commit_deal(
        _payload("explicit-main-target"),
        author="Tester <tester@example.com>",
        message="explicit main target call",
        parent_sha=legacy_sha,
        commit_target="main",
    )
    assert _SHA_RE.fullmatch(explicit_sha)
    assert explicit_sha != legacy_sha
    assert _branch_tip(service, "main") == explicit_sha


def test_commit_deal_invalid_commit_target_raises_invalid_branch_name(
    tmp_path: Path,
) -> None:
    """AC 4: invalid commit_target names are rejected by branch validator."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    main_tip = _seed_repo_with_initial_commit(repo_path)
    service = GitService(repo_path=repo_path)

    for invalid in ["Invalid/Name!", "../escape", "UPPERCASE", "main with spaces"]:
        with pytest.raises(InvalidBranchNameError):
            service.commit_deal(
                _payload(f"invalid-{invalid}"),
                author="Tester <tester@example.com>",
                message=f"invalid target {invalid}",
                parent_sha=main_tip,
                commit_target=invalid,
            )


def test_commit_deal_parent_sha_validated_against_supplied_branch_tip_not_main(
    tmp_path: Path,
) -> None:
    """AC 4: parent_sha is checked against commit_target tip, not main tip."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    base_sha = _seed_repo_with_initial_commit(repo_path)
    service = GitService(repo_path=repo_path)

    m1 = service.commit_deal(
        _payload("main-m1"),
        author="Tester <tester@example.com>",
        message="main baseline commit",
        parent_sha=base_sha,
    )
    service.branch_create("ai/turn-test", from_sha=m1)
    e1 = service.commit_deal(
        _payload("ephemeral-e1"),
        author="Tester <tester@example.com>",
        message="ephemeral baseline commit",
        parent_sha=m1,
        commit_target="ai/turn-test",
    )
    assert _branch_tip(service, "main") == m1
    assert _branch_tip(service, "ai/turn-test") == e1

    with pytest.raises(Exception):
        service.commit_deal(
            _payload("stale-parent-on-ephemeral"),
            author="Tester <tester@example.com>",
            message="stale parent mismatch",
            parent_sha=m1,
            commit_target="ai/turn-test",
        )

    success_sha = service.commit_deal(
        _payload("fresh-parent-on-ephemeral"),
        author="Tester <tester@example.com>",
        message="fresh parent match",
        parent_sha=e1,
        commit_target="ai/turn-test",
    )
    assert _SHA_RE.fullmatch(success_sha)
    assert _branch_tip(service, "ai/turn-test") == success_sha
    assert _branch_tip(service, "main") == m1
