from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

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


def _seed_git_backed_deal(*, deal_id: str) -> Path:
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


def test_repo_corrupt_diagnostic_invokes_restore_from_bundle_end_to_end(
    redirected_deals_dir: Path,
) -> None:
    from bma_cfengine_app.orchestrator.deals.operational import restore_deal

    deal_id = "deal_restore_e2e"
    repo_dir = _seed_git_backed_deal(deal_id=deal_id)
    service = GitService(repo_path=repo_dir)
    commits_before_corruption = service.log(branch="main", limit=20)
    assert commits_before_corruption, "Expected seeded repo to have at least one commit"
    head_before_corruption = commits_before_corruption[0].sha

    backups_dir = redirected_deals_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = backups_dir / f"{deal_id}.bundle"
    subprocess.run(
        ["git", "bundle", "create", str(bundle_path), "--all"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    assert bundle_path.exists(), "Expected backup bundle to be created"

    _corrupt_first_loose_object(repo_dir)

    with pytest.raises(Exception) as exc_info:
        deal_store.load_deal(deal_id)
    _assert_repo_corrupt_diagnostic(exc_info.value)

    restore_deal(deal_id, bundle_path)

    restored_service = GitService(repo_path=repo_dir)
    commits_after_restore = restored_service.log(branch="main", limit=20)
    assert commits_after_restore, "Expected restored repo to have commits"
    assert commits_after_restore[0].sha == head_before_corruption
    assert [entry.sha for entry in commits_after_restore] == [
        entry.sha for entry in commits_before_corruption
    ]

    loaded = deal_store.load_deal(deal_id)
    assert loaded is not None
    assert loaded.deal_name == f"{deal_id}-canonical"

    events = [
        event
        for event in _read_audit_log_events(deal_id)
        if event.get("deal_id") == deal_id
    ]
    event_types = [event.get("event_type") for event in events]

    assert "corruption_detected" in event_types
    assert "restore_attempt" in event_types
    assert "restore_result" in event_types

    assert event_types.index("corruption_detected") < event_types.index("restore_attempt")
    assert event_types.index("restore_attempt") < event_types.index("restore_result")

    assert any(
        event.get("event_type") == "restore_result" and event.get("outcome") == "success"
        for event in events
    )
