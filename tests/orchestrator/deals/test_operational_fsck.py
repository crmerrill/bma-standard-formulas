from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bma_cfengine_app.orchestrator.deals import deal_store
from bma_standard_formulas.deals.schemas.common import RuleType
from bma_standard_formulas.deals.schemas.ir import (
    AccountDef,
    BondDef,
    DealDefinition,
    FeeDef,
    RuleNode,
)


@pytest.fixture
def redirected_deals_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)
    deal_store.init_deals_workspace()
    return tmp_path


def _build_minimal_deal(*, deal_name: str, coupon: float) -> DealDefinition:
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


def _seed_git_backed_deal(
    *,
    deal_id: str,
) -> Path:
    deal_store.save_deal(
        deal_id,
        _build_minimal_deal(deal_name=f"{deal_id}-canonical", coupon=5.0),
    )
    return deal_store.deal_dir(deal_id)


def _corrupt_first_loose_object(repo_dir: Path) -> Path:
    objects_root = repo_dir / ".git" / "objects"
    for prefix_dir in objects_root.iterdir():
        if not prefix_dir.is_dir() or len(prefix_dir.name) != 2:
            continue
        for object_file in prefix_dir.iterdir():
            if object_file.is_file():
                object_file.chmod(0o644)
                object_file.write_bytes(b"corrupt")
                return object_file
    raise AssertionError(f"No loose objects found under {objects_root}")


def _assert_repo_corrupt_diagnostic(exc: BaseException) -> None:
    text = str(exc)
    code = getattr(exc, "code", None)
    detail = getattr(exc, "detail", None)
    payload = getattr(exc, "payload", None)

    is_repo_corrupt = code == "REPO_CORRUPT" or "REPO_CORRUPT" in text
    if not is_repo_corrupt and isinstance(detail, dict):
        is_repo_corrupt = detail.get("code") == "REPO_CORRUPT"
    if not is_repo_corrupt and isinstance(payload, dict):
        is_repo_corrupt = payload.get("code") == "REPO_CORRUPT"

    assert is_repo_corrupt, (
        "Expected REPO_CORRUPT diagnostic on fsck failure; "
        f"got exception: {type(exc).__name__}: {text}"
    )

    # Action shape is implementation-defined, but if a payload exists it should
    # carry restore intent in some form.
    if isinstance(payload, dict):
        assert "restore" in json.dumps(payload).lower()


def _read_audit_log_events(deal_id: str) -> list[dict[str, Any]]:
    audit_path = deal_store.deal_dir(deal_id) / "audit.log"
    assert audit_path.exists(), f"Expected audit log at {audit_path}"
    events: list[dict[str, Any]] = []
    for raw_line in audit_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        events.append(json.loads(line))
    return events


def test_fsck_detects_corruption_via_load_deal_entry_point(
    redirected_deals_dir: Path,
) -> None:
    deal_id = "deal_fsck_load_deal"
    repo_dir = _seed_git_backed_deal(deal_id=deal_id)
    _corrupt_first_loose_object(repo_dir)

    with pytest.raises(Exception) as exc_info:
        deal_store.load_deal(deal_id)
    _assert_repo_corrupt_diagnostic(exc_info.value)

    events = _read_audit_log_events(deal_id)
    assert any(
        event.get("event_type") == "corruption_detected"
        and event.get("deal_id") == deal_id
        for event in events
    )


def test_fsck_detects_corruption_via_commit_deal_entry_point(
    redirected_deals_dir: Path,
) -> None:
    deal_id = "deal_fsck_commit"
    repo_dir = _seed_git_backed_deal(deal_id=deal_id)
    _corrupt_first_loose_object(repo_dir)

    with pytest.raises(Exception) as exc_info:
        deal_store.save_deal(
            deal_id,
            _build_minimal_deal(deal_name="commit-entrypoint", coupon=5.5),
        )
    _assert_repo_corrupt_diagnostic(exc_info.value)


def test_fsck_runs_once_per_process_per_deal(
    redirected_deals_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bma_cfengine_app.orchestrator.deals import operational

    deal_id = "deal_fsck_memoized"
    _seed_git_backed_deal(deal_id=deal_id)

    verified_repos = getattr(operational, "_FSCK_VERIFIED_REPOS", None)
    if isinstance(verified_repos, set):
        verified_repos.clear()

    call_counter = {"count": 0}

    def _fake_run_fsck(repo_path: Path) -> None:
        assert repo_path.is_absolute()
        call_counter["count"] += 1

    monkeypatch.setattr(operational, "_run_fsck", _fake_run_fsck)

    deal_store.load_deal(deal_id)
    deal_store.load_deal(deal_id)

    assert call_counter["count"] == 1


def test_fsck_runs_when_gitservice_constructed_directly(
    redirected_deals_dir: Path,
) -> None:
    """B1 regression: direct GitService construction against a corrupt repo
    must raise RepoCorruptError — the fsck guard in __init__ cannot be bypassed."""
    from bma_cfengine_app.orchestrator.deals import operational
    from bma_cfengine_app.orchestrator.deals.git_service import GitService
    from bma_cfengine_app.orchestrator.deals.operational import RepoCorruptError

    deal_id = "deal_fsck_direct_gitservice"
    repo_dir = _seed_git_backed_deal(deal_id=deal_id)

    operational._FSCK_VERIFIED_REPOS.discard(str(repo_dir.resolve()))

    _corrupt_first_loose_object(repo_dir)

    with pytest.raises(RepoCorruptError) as exc_info:
        GitService(repo_path=repo_dir)
    _assert_repo_corrupt_diagnostic(exc_info.value)
