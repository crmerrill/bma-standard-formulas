from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from bma_cfengine_app.orchestrator.deals import merge as _merge_module  # noqa: F401
from bma_cfengine_app.orchestrator.deals.git_service import GitService
from bma_standard_formulas.deals.schemas.common import RuleType
from bma_standard_formulas.deals.schemas.ir import AccountDef, BondDef, DealDefinition, FeeDef, RuleNode
from bma_standard_formulas.diagnostics import DiagnosticPayload, Severity


def _run_git(repo_path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _init_repo(repo_path: Path) -> None:
    subprocess.run(
        ["git", "init", str(repo_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    _run_git(repo_path, "branch", "-M", "main")


def _deal_payload(
    *,
    coupon: float,
    notional: float,
    account_starting_amount: float = 100.0,
    fee_amount: float = 10.0,
) -> dict[str, Any]:
    deal = DealDefinition(
        deal_name="typed-field-merge-test",
        bonds=[BondDef(name="A1", coupon=coupon, notional=notional)],
        accounts=[AccountDef(name="Reserve", starting_amount=account_starting_amount)],
        fees=[FeeDef(name="Servicing", amount=fee_amount)],
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


def _extract_merge_sha(result: Any) -> str:
    if isinstance(result, str):
        return result

    if isinstance(result, dict):
        for key in ("sha", "commit_sha", "new_main_sha", "head_sha"):
            value = result.get(key)
            if isinstance(value, str):
                return value

    for attr in ("sha", "commit_sha", "new_main_sha", "head_sha"):
        value = getattr(result, attr, None)
        if isinstance(value, str):
            return value

    raise AssertionError(f"Merge result does not expose a commit SHA: {result!r}")


def _extract_conflict_payload(result: Any) -> tuple[str, Severity, dict[str, Any]]:
    if isinstance(result, DiagnosticPayload):
        code = result.code
        severity = result.severity
        payload = result.payload
    elif isinstance(result, dict):
        code = result.get("code")
        severity = result.get("severity")
        payload = result.get("payload")
    else:
        code = getattr(result, "code", None)
        severity = getattr(result, "severity", None)
        payload = getattr(result, "payload", None)

    assert isinstance(code, str), f"Expected conflict code str, got {type(code).__name__}"
    if isinstance(severity, str):
        severity = Severity(severity)
    assert isinstance(severity, Severity), (
        f"Expected conflict severity Severity, got {type(severity).__name__}"
    )
    assert isinstance(payload, dict), f"Expected conflict payload dict, got {type(payload).__name__}"
    return code, severity, payload


def test_non_overlapping_field_merge_succeeds(tmp_path: Path) -> None:
    """AC 1, 3: merge combines non-overlapping field edits on the same entity."""
    _init_repo(tmp_path)
    service = GitService(repo_path=tmp_path)
    author = "system:test <test@example.com>"

    base_sha = service.commit_deal(
        deal_payload=_deal_payload(coupon=5.0, notional=1_000_000.0),
        author=author,
        message="initial",
    )

    service.branch_create("what-if/branch-a", from_sha=base_sha)
    _run_git(tmp_path, "checkout", "what-if/branch-a")
    branch_a_sha = service.commit_deal(
        deal_payload=_deal_payload(coupon=6.0, notional=1_000_000.0),
        author=author,
        message="branch-a edits coupon",
        parent_sha=base_sha,
    )
    _run_git(tmp_path, "branch", "-f", "what-if/branch-a", branch_a_sha)

    _run_git(tmp_path, "checkout", "main")
    service.branch_create("what-if/branch-b", from_sha=base_sha)
    _run_git(tmp_path, "checkout", "what-if/branch-b")
    branch_b_sha = service.commit_deal(
        deal_payload=_deal_payload(coupon=5.0, notional=1_500_000.0),
        author=author,
        message="branch-b edits notional",
        parent_sha=base_sha,
    )
    _run_git(tmp_path, "branch", "-f", "what-if/branch-b", branch_b_sha)

    _run_git(tmp_path, "checkout", "main")
    _run_git(tmp_path, "reset", "--hard", branch_a_sha)

    result = service.merge(branch="what-if/branch-b", into="main")

    if isinstance(result, dict) and "success" in result:
        assert result["success"] is True
    elif hasattr(result, "success"):
        assert bool(getattr(result, "success")) is True

    new_main_sha = _extract_merge_sha(result)
    assert _run_git(tmp_path, "rev-parse", "main") == new_main_sha

    merged_deal_bytes = service.show(new_main_sha, "deal.json")
    merged_deal = DealDefinition.model_validate_json(merged_deal_bytes)
    assert merged_deal.bonds[0].coupon == pytest.approx(6.0)
    assert merged_deal.bonds[0].notional == pytest.approx(1_500_000.0)


def test_overlapping_field_merge_yields_conflict(tmp_path: Path) -> None:
    """AC 2: merge conflict on same entity field returns MERGE_CONFLICT payload."""
    _init_repo(tmp_path)
    service = GitService(repo_path=tmp_path)
    author = "system:test <test@example.com>"

    base_sha = service.commit_deal(
        deal_payload=_deal_payload(coupon=5.0, notional=1_000_000.0),
        author=author,
        message="initial",
    )

    service.branch_create("what-if/branch-a", from_sha=base_sha)
    _run_git(tmp_path, "checkout", "what-if/branch-a")
    branch_a_sha = service.commit_deal(
        deal_payload=_deal_payload(coupon=6.0, notional=1_000_000.0),
        author=author,
        message="branch-a edits coupon",
        parent_sha=base_sha,
    )
    _run_git(tmp_path, "branch", "-f", "what-if/branch-a", branch_a_sha)

    _run_git(tmp_path, "checkout", "main")
    service.branch_create("what-if/branch-b", from_sha=base_sha)
    _run_git(tmp_path, "checkout", "what-if/branch-b")
    branch_b_sha = service.commit_deal(
        deal_payload=_deal_payload(coupon=7.0, notional=1_000_000.0),
        author=author,
        message="branch-b edits coupon too",
        parent_sha=base_sha,
    )
    _run_git(tmp_path, "branch", "-f", "what-if/branch-b", branch_b_sha)

    _run_git(tmp_path, "checkout", "main")
    _run_git(tmp_path, "reset", "--hard", branch_a_sha)
    main_before_merge = _run_git(tmp_path, "rev-parse", "main")

    result = service.merge(branch="what-if/branch-b", into="main")
    code, severity, payload = _extract_conflict_payload(result)

    assert code == "MERGE_CONFLICT"
    assert severity == Severity.error
    assert payload["entity_kind"] == "bond"
    assert payload["entity_id"] == "A1"
    assert payload["field_path"] == "coupon"
    assert payload["ours_value"] == 6.0
    assert payload["theirs_value"] == 7.0
    assert payload["ancestor_value"] == 5.0
    assert _run_git(tmp_path, "rev-parse", "main") == main_before_merge


# ---------------------------------------------------------------------------
# R1 fix-pass regression tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("backend", ["pygit2", "cli"])
def test_top_level_field_conflict_does_not_emit_merge_conflict_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str,
) -> None:
    """B1 regression: top-level DealDefinition field conflicts must NOT produce
    a MERGE_CONFLICT diagnostic with entity_kind='deal'.  Instead, the merge
    target's value wins (last-writer-wins-on-target)."""
    from bma_cfengine_app.orchestrator.deals import git_service as gs_mod

    if backend == "cli":
        monkeypatch.setattr(gs_mod, "pygit2", None, raising=False)
    else:
        pytest.importorskip("pygit2")

    _init_repo(tmp_path)
    service = GitService(repo_path=tmp_path)
    author = "system:test <test@example.com>"

    base_sha = service.commit_deal(
        deal_payload=_deal_payload(coupon=5.0, notional=1_000_000.0),
        author=author,
        message="initial",
    )

    service.branch_create("what-if/branch-a", from_sha=base_sha)
    _run_git(tmp_path, "checkout", "what-if/branch-a")
    payload_a = _deal_payload(coupon=5.0, notional=1_000_000.0)
    payload_a["deal_name"] = "name-from-branch-a"
    branch_a_sha = service.commit_deal(
        deal_payload=payload_a,
        author=author,
        message="branch-a edits deal_name",
        parent_sha=base_sha,
    )
    _run_git(tmp_path, "update-ref", "refs/heads/what-if/branch-a", branch_a_sha)

    _run_git(tmp_path, "checkout", "main")
    service.branch_create("what-if/branch-b", from_sha=base_sha)
    _run_git(tmp_path, "checkout", "what-if/branch-b")
    payload_b = _deal_payload(coupon=5.0, notional=1_000_000.0)
    payload_b["deal_name"] = "name-from-branch-b"
    branch_b_sha = service.commit_deal(
        deal_payload=payload_b,
        author=author,
        message="branch-b edits deal_name differently",
        parent_sha=base_sha,
    )
    _run_git(tmp_path, "update-ref", "refs/heads/what-if/branch-b", branch_b_sha)

    _run_git(tmp_path, "checkout", "main")
    _run_git(tmp_path, "reset", "--hard", branch_a_sha)

    result = service.merge(branch="what-if/branch-b", into="main")

    assert not isinstance(result, DiagnosticPayload), (
        f"Top-level field conflict must not emit MERGE_CONFLICT; got: {result}"
    )
    merge_sha = _extract_merge_sha(result)
    merged_deal = DealDefinition.model_validate_json(
        service.show(merge_sha, "deal.json"),
    )
    assert merged_deal.deal_name == "name-from-branch-a"


@pytest.mark.parametrize("backend", ["pygit2", "cli"])
def test_squash_apply_drops_ephemeral_branch_commits_from_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str,
) -> None:
    """C1 (R1 fix): apply (squash=True) on an ai/turn-* branch produces a
    single-parent merge commit on main; after branch deletion, the
    ephemeral branch's commits are unreachable via git log --all."""
    import os

    from bma_cfengine_app.orchestrator.deals import git_service as gs_mod

    if backend == "cli":
        monkeypatch.setattr(gs_mod, "pygit2", None, raising=False)
    else:
        pytest.importorskip("pygit2")

    _init_repo(tmp_path)
    service = GitService(repo_path=tmp_path)
    author = "system:test <test@example.com>"

    base_sha = service.commit_deal(
        deal_payload=_deal_payload(coupon=5.0, notional=1_000_000.0),
        author=author,
        message="initial",
    )

    service.branch_create("ai/turn-secret", from_sha=base_sha)
    _run_git(tmp_path, "checkout", "ai/turn-secret")
    sensitive_message = "User said: 'Please add a 5% reserve for my deal ABC-PRIVATE-123'"
    import json
    deal_path = tmp_path / "deal.json"
    deal_path.write_text(json.dumps(_deal_payload(coupon=6.0, notional=1_000_000.0), indent=2))
    commit_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "system",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "system",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    _run_git(tmp_path, "add", "deal.json")
    subprocess.run(
        ["git", "commit", "-m", sensitive_message],
        cwd=tmp_path, check=True, capture_output=True, text=True, env=commit_env,
    )
    _run_git(tmp_path, "checkout", "main")
    _run_git(tmp_path, "reset", "--hard", base_sha)

    result = service.merge("ai/turn-secret", into="main", squash=True)
    merge_sha = _extract_merge_sha(result)

    # Verify single-parent commit
    parent_count = _run_git(tmp_path, "rev-list", "--parents", "-1", merge_sha)
    parents = parent_count.strip().split()
    assert len(parents) == 2, f"Expected single parent (squash), got {len(parents) - 1} parents"

    # Delete the ephemeral branch
    service.branch_delete("ai/turn-secret")

    # Expire reflogs so unreachable commits are truly invisible
    subprocess.run(
        ["git", "reflog", "expire", "--expire=now", "--all"],
        cwd=tmp_path, check=True, capture_output=True, text=True,
    )

    # After deletion, the sensitive message must NOT appear in git log --all
    all_messages = _run_git(tmp_path, "log", "--all", "--format=%B")
    assert "ABC-PRIVATE-123" not in all_messages
    assert sensitive_message not in all_messages

    # The squash commit message should indicate Apply semantics
    merge_msg = _run_git(tmp_path, "log", "-1", "--format=%B", merge_sha)
    assert "Apply" in merge_msg


@pytest.mark.parametrize("backend", ["pygit2", "cli"])
def test_squash_false_preserves_two_parent_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str,
) -> None:
    """C1 backward-compat: squash=False (default) still produces two-parent merges."""
    from bma_cfengine_app.orchestrator.deals import git_service as gs_mod

    if backend == "cli":
        monkeypatch.setattr(gs_mod, "pygit2", None, raising=False)
    else:
        pytest.importorskip("pygit2")

    _init_repo(tmp_path)
    service = GitService(repo_path=tmp_path)
    author = "system:test <test@example.com>"

    base_sha = service.commit_deal(
        deal_payload=_deal_payload(coupon=5.0, notional=1_000_000.0),
        author=author,
        message="initial",
    )

    service.branch_create("what-if/two-parent", from_sha=base_sha)
    _run_git(tmp_path, "checkout", "what-if/two-parent")
    branch_sha = service.commit_deal(
        deal_payload=_deal_payload(coupon=7.0, notional=1_000_000.0),
        author=author,
        message="what-if edit",
        parent_sha=base_sha,
    )
    _run_git(tmp_path, "update-ref", "refs/heads/what-if/two-parent", branch_sha)
    _run_git(tmp_path, "checkout", "main")

    result = service.merge("what-if/two-parent", into="main", squash=False)
    merge_sha = _extract_merge_sha(result)

    parent_count = _run_git(tmp_path, "rev-list", "--parents", "-1", merge_sha)
    parents = parent_count.strip().split()
    assert len(parents) == 3, f"Expected two parents (standard merge), got {len(parents) - 1} parents"


@pytest.mark.parametrize("backend", ["pygit2", "cli"])
def test_merge_works_when_into_is_not_currently_checked_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str,
) -> None:
    """M2 regression: merge must produce a correct commit on ``into`` even when
    a different branch is currently checked out."""
    from bma_cfengine_app.orchestrator.deals import git_service as gs_mod

    if backend == "cli":
        monkeypatch.setattr(gs_mod, "pygit2", None, raising=False)
    else:
        pytest.importorskip("pygit2")

    _init_repo(tmp_path)
    service = GitService(repo_path=tmp_path)
    author = "system:test <test@example.com>"

    base_sha = service.commit_deal(
        deal_payload=_deal_payload(coupon=5.0, notional=1_000_000.0),
        author=author,
        message="initial",
    )

    service.branch_create("what-if/feature", from_sha=base_sha)
    _run_git(tmp_path, "checkout", "what-if/feature")
    feature_sha = service.commit_deal(
        deal_payload=_deal_payload(coupon=5.0, notional=2_000_000.0),
        author=author,
        message="feature edits notional",
        parent_sha=base_sha,
    )
    _run_git(tmp_path, "update-ref", "refs/heads/what-if/feature", feature_sha)

    _run_git(tmp_path, "checkout", "main")

    service.branch_create("what-if/throwaway", from_sha=base_sha)
    _run_git(tmp_path, "checkout", "what-if/throwaway")
    throwaway_sha_before = _run_git(tmp_path, "rev-parse", "what-if/throwaway")

    result = service.merge(branch="what-if/feature", into="main")

    merge_sha = _extract_merge_sha(result)
    merged_bytes = _run_git(tmp_path, "show", f"main:deal.json")
    merged_deal = DealDefinition.model_validate_json(merged_bytes.encode("utf-8"))
    assert merged_deal.bonds[0].notional == pytest.approx(2_000_000.0)

    assert _run_git(tmp_path, "rev-parse", "main") == merge_sha

    assert _run_git(tmp_path, "rev-parse", "what-if/throwaway") == throwaway_sha_before
    current_branch = _run_git(tmp_path, "symbolic-ref", "--short", "HEAD")
    assert current_branch == "what-if/throwaway"
