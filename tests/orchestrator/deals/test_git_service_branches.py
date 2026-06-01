from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "name",
    [
        "main",
        "ai/turn-a",
        "ai/turn-" + ("a" * 64),
        "ai/turn-foo-bar-baz",
        "solver/run-x1",
        "what-if/scenario-2",
    ],
)
def test_branch_name_validation_accepts_canonical_patterns(tmp_path: Path, name: str) -> None:
    """AC 5: canonical main/ai/solver/what-if branch name patterns are accepted."""
    from bma_cfengine_app.orchestrator.deals.git_service import GitService

    service = GitService(repo_path=tmp_path)
    service._validate_branch_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "../foo",
        "..\\foo",
        "ai/turn-../escape",
        "ai/turn-FOO",
        "ai/turn--leading-hyphen",
        "ai/turn-with.dot",
        "ai/turn-" + ("a" * 65),
        "ai/turn-",
        "random/branch-name",
        "MAIN",
        "",
    ],
)
def test_branch_name_validation_rejects_path_traversal_and_invalid_slugs(
    tmp_path: Path, name: str
) -> None:
    """AC 5: invalid branch names raise INVALID_BRANCH_NAME for traversal and slug violations."""
    from bma_cfengine_app.orchestrator.deals.git_service import GitService

    service = GitService(repo_path=tmp_path)
    with pytest.raises(Exception) as exc:
        service._validate_branch_name(name)
    assert "INVALID_BRANCH_NAME" in str(exc.value)


def test_branch_delete_main_raises_protected_branch_error(tmp_path: Path) -> None:
    """C1: branch_delete('main') raises GitServiceError with PROTECTED_BRANCH
    before touching the git backend, regardless of whether the repo exists."""
    from bma_cfengine_app.orchestrator.deals.git_service import GitService, GitServiceError

    service = GitService(repo_path=tmp_path)
    with pytest.raises(GitServiceError) as exc_info:
        service.branch_delete("main")
    assert "PROTECTED_BRANCH" in str(exc_info.value)
