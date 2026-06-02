from __future__ import annotations

import inspect
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from bma_cfengine_app.orchestrator.deals import git_service as git_service_module
from bma_cfengine_app.orchestrator.deals.git_service import (
    GitService,
    InvalidBranchNameError,
    StaleParentShaError,
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


def _make_service(repo_path: Path, use_cli: bool) -> GitService:
    """Return a GitService forced to the requested backend."""
    if use_cli:
        if shutil.which("git") is None:
            pytest.skip("git CLI not available on PATH")
        # Monkeypatching at module level isn't safe here because tests may run
        # concurrently; instead we instantiate with pygit2 unavailable by
        # temporarily patching the module attribute before construction.
        # We rely on the fact that GitService reads _use_pygit2 once at __init__
        # time from the module-level pygit2 symbol.
        saved = git_service_module.pygit2
        git_service_module.pygit2 = None  # type: ignore[assignment]
        try:
            svc = GitService(repo_path=repo_path)
        finally:
            git_service_module.pygit2 = saved
        return svc
    return GitService(repo_path=repo_path)


# ---------------------------------------------------------------------------
# Parametrize over both backends
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("use_cli", [False, True], ids=["pygit2", "cli"])
def test_commit_deal_writes_to_supplied_commit_target_branch_only(
    tmp_path: Path, use_cli: bool
) -> None:
    """AC 4, 6: commit_target branch advances while main stays byte-identical."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    main_tip = _seed_repo_with_initial_commit(repo_path)
    service = _make_service(repo_path, use_cli)

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


@pytest.mark.parametrize("use_cli", [False, True], ids=["pygit2", "cli"])
def test_commit_deal_default_commit_target_remains_main_for_backward_compat(
    tmp_path: Path, use_cli: bool
) -> None:
    """AC 4, 5: omitted commit_target keeps legacy main behavior."""
    signature = inspect.signature(GitService.commit_deal)
    assert "commit_target" in signature.parameters
    assert signature.parameters["commit_target"].default == "main"

    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    main_tip = _seed_repo_with_initial_commit(repo_path)
    service = _make_service(repo_path, use_cli)

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


@pytest.mark.parametrize("use_cli", [False, True], ids=["pygit2", "cli"])
def test_commit_deal_invalid_commit_target_raises_invalid_branch_name(
    tmp_path: Path, use_cli: bool
) -> None:
    """AC 4: invalid commit_target names are rejected by branch validator."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    main_tip = _seed_repo_with_initial_commit(repo_path)
    service = _make_service(repo_path, use_cli)

    for invalid in ["Invalid/Name!", "../escape", "UPPERCASE", "main with spaces"]:
        with pytest.raises(InvalidBranchNameError):
            service.commit_deal(
                _payload(f"invalid-{invalid}"),
                author="Tester <tester@example.com>",
                message=f"invalid target {invalid}",
                parent_sha=main_tip,
                commit_target=invalid,
            )


@pytest.mark.parametrize("use_cli", [False, True], ids=["pygit2", "cli"])
def test_commit_deal_parent_sha_validated_against_supplied_branch_tip_not_main(
    tmp_path: Path, use_cli: bool
) -> None:
    """AC 4: parent_sha is checked against commit_target tip, not main tip."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    base_sha = _seed_repo_with_initial_commit(repo_path)
    service = _make_service(repo_path, use_cli)

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

    with pytest.raises(StaleParentShaError):
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


# ---------------------------------------------------------------------------
# Fix Major #2 — parent_sha nullability matrix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("use_cli", [False, True], ids=["pygit2", "cli"])
def test_commit_deal_parent_sha_none_rejected_on_existing_branch_tip(
    tmp_path: Path, use_cli: bool
) -> None:
    """AC 4, AC 13: parent_sha=None is rejected when the target branch already has a tip.

    An existing branch cannot be advanced with parent_sha=None because that
    would create a disconnected root commit and sever branch history.
    """
    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    main_tip = _seed_repo_with_initial_commit(repo_path)
    service = _make_service(repo_path, use_cli)

    # Give the ephemeral branch a tip by committing once.
    service.branch_create("ai/turn-null-test", from_sha=main_tip)
    e1 = service.commit_deal(
        _payload("ephemeral-e1"),
        author="Tester <tester@example.com>",
        message="initial ephemeral commit",
        parent_sha=main_tip,
        commit_target="ai/turn-null-test",
    )
    assert _branch_tip(service, "ai/turn-null-test") == e1

    # parent_sha=None on an existing-tip branch must raise StaleParentShaError.
    with pytest.raises(StaleParentShaError) as exc_info:
        service.commit_deal(
            _payload("root-on-existing"),
            author="Tester <tester@example.com>",
            message="illegal root on existing branch",
            parent_sha=None,
            commit_target="ai/turn-null-test",
        )

    # The error must carry the current tip so the caller can resolve the conflict.
    assert exc_info.value.head_sha == e1


@pytest.mark.parametrize("use_cli", [False, True], ids=["pygit2", "cli"])
def test_commit_deal_non_null_parent_sha_rejected_on_unborn_branch(
    tmp_path: Path, use_cli: bool
) -> None:
    """AC 4, AC 13: non-null parent_sha is rejected when the target branch is unborn.

    An unborn branch (no ref in refs/heads/) must only be created with
    parent_sha=None.  Supplying any SHA value is invalid because there is no
    existing tip to match against — the invariant target_tip == parent_sha
    fails because target_tip is None.

    Note: the public branch_create() API always sets a tip equal to from_sha,
    so a truly unborn branch is accessed by using a branch name that has never
    been created via branch_create or committed to.  We use a fresh namespace
    "ai/turn-unborn-<suffix>" that is guaranteed unused in this tmp_path repo.
    """
    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    main_tip = _seed_repo_with_initial_commit(repo_path)
    service = _make_service(repo_path, use_cli)

    # The branch "ai/turn-unborn" has never been created — it is unborn (no ref).
    # Supplying main_tip as parent_sha must fail: target_tip (None) != parent_sha.
    with pytest.raises(StaleParentShaError) as exc_info:
        service.commit_deal(
            _payload("non-null-on-unborn"),
            author="Tester <tester@example.com>",
            message="illegal non-null parent on unborn branch",
            parent_sha=main_tip,
            commit_target="ai/turn-unborn",
        )

    # The error must report the current tip of the branch (None for unborn).
    assert exc_info.value.head_sha is None
