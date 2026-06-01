from __future__ import annotations

import json
import subprocess
import sys
import tarfile
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


@pytest.fixture
def scripts_import_path() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    original_sys_path = list(sys.path)
    sys.path.insert(0, str(repo_root))
    try:
        yield
    finally:
        sys.path[:] = original_sys_path
        for module_name in (
            "scripts.backup_deals",
            "scripts.restore_deal",
            "backup_deals",
            "restore_deal",
        ):
            sys.modules.pop(module_name, None)


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


def _git_stdout(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _bundle_commit_count(bundle_path: Path, clone_dir: Path) -> int:
    subprocess.run(
        ["git", "clone", str(bundle_path), str(clone_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    return int(_git_stdout(["rev-list", "--count", "HEAD"], clone_dir))


def _locate_bundle(out_dir: Path, deal_id: str) -> Path:
    expected = out_dir / f"deal_{deal_id}.bundle"
    if expected.exists():
        return expected

    matches = sorted(out_dir.glob(f"*{deal_id}*.bundle"))
    assert matches, f"Expected a bundle for deal {deal_id} under {out_dir}"
    assert len(matches) == 1, f"Expected exactly one bundle for {deal_id}, got {matches}"
    return matches[0]


def _locate_tenant_tar(out_dir: Path, tenant_id: str) -> Path:
    expected = out_dir / f"tenant_{tenant_id}.tar"
    if expected.exists():
        return expected

    matches = sorted(out_dir.glob(f"*{tenant_id}*.tar"))
    assert matches, f"Expected a tenant tar for {tenant_id} under {out_dir}"
    return matches[-1]


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


def test_per_deal_backup_bundle_is_self_contained(
    redirected_deals_dir: Path,
    scripts_import_path: None,
) -> None:
    import scripts.backup_deals as backup_deals

    deal_id = "deal_backup_self_contained"
    deal_store.save_deal(
        deal_id,
        _build_minimal_deal(deal_name="self-contained", coupon=5.0),
    )

    repo_dir = deal_store.deal_dir(deal_id)
    original_commit_count = int(_git_stdout(["rev-list", "--count", "HEAD"], repo_dir))
    original_head_deal_json = json.loads(_git_stdout(["show", "HEAD:deal.json"], repo_dir))

    out_dir = redirected_deals_dir / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    backup_deals.main(["--deal", deal_id, "--out", str(out_dir)])

    bundle_path = _locate_bundle(out_dir, deal_id)
    assert bundle_path.exists(), f"Expected backup bundle at {bundle_path}"

    clone_dir = redirected_deals_dir / "restore_probe_single"
    cloned_commit_count = _bundle_commit_count(bundle_path, clone_dir)
    cloned_head_deal_json = json.loads(_git_stdout(["show", "HEAD:deal.json"], clone_dir))

    assert cloned_commit_count == original_commit_count
    assert cloned_head_deal_json == original_head_deal_json


def test_tenant_level_backup_orchestrates_all_deals(
    redirected_deals_dir: Path,
    scripts_import_path: None,
) -> None:
    """Assumes --tenant means "all deals under _DEALS_DIR" for this environment."""
    import scripts.backup_deals as backup_deals

    tenant_id = "tenant_demo"
    deal_ids = ["deal_tenant_backup_1", "deal_tenant_backup_2", "deal_tenant_backup_3"]

    expected_commit_counts: dict[str, int] = {}
    for idx, deal_id in enumerate(deal_ids, start=1):
        deal_store.save_deal(
            deal_id,
            _build_minimal_deal(
                deal_name=f"tenant-backup-{idx}",
                coupon=5.0 + idx,
            ),
        )
        repo_dir = deal_store.deal_dir(deal_id)
        expected_commit_counts[deal_id] = int(
            _git_stdout(["rev-list", "--count", "HEAD"], repo_dir)
        )

    out_dir = redirected_deals_dir / "tenant_backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    backup_deals.main(["--tenant", tenant_id, "--out", str(out_dir)])

    tenant_tar = _locate_tenant_tar(out_dir, tenant_id)
    assert tenant_tar.exists(), f"Expected tenant archive at {tenant_tar}"

    extract_root = redirected_deals_dir / "tenant_extract"
    extract_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tenant_tar, mode="r") as tar:
        members = [m for m in tar.getmembers() if m.isfile() and m.name.endswith(".bundle")]
        assert len(members) == len(deal_ids)
        for member in members:
            tar.extract(member, path=extract_root)

    for deal_id in deal_ids:
        bundle_candidates = sorted(
            p for p in extract_root.rglob("*.bundle") if deal_id in p.name
        )
        assert bundle_candidates, f"No bundle in tenant tar for {deal_id}"
        assert len(bundle_candidates) == 1

        clone_dir = redirected_deals_dir / f"tenant_restore_probe_{deal_id}"
        bundled_count = _bundle_commit_count(bundle_candidates[0], clone_dir)
        assert bundled_count == expected_commit_counts[deal_id]


def test_restore_cli_locates_latest_bundle_and_unbundles(
    redirected_deals_dir: Path,
    scripts_import_path: None,
) -> None:
    import scripts.backup_deals as backup_deals
    import scripts.restore_deal as restore_cli

    deal_id = "deal_restore_cli_roundtrip"
    deal_store.save_deal(
        deal_id,
        _build_minimal_deal(deal_name="restore-cli-roundtrip", coupon=7.5),
    )

    backups_dir = redirected_deals_dir / "restore_backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    backup_deals.main(["--deal", deal_id, "--out", str(backups_dir)])
    bundle_path = _locate_bundle(backups_dir, deal_id)
    assert bundle_path.exists()

    repo_dir = deal_store.deal_dir(deal_id)
    _corrupt_first_loose_object(repo_dir)

    with pytest.raises(Exception):
        deal_store.load_deal(deal_id)

    restore_cli.main(["--deal", deal_id, "--backups", str(backups_dir)])

    restored = deal_store.load_deal(deal_id)
    assert restored is not None
    assert restored.deal_name == "restore-cli-roundtrip"

    events = _read_audit_log_events(deal_id)
    assert any(event.get("event_type") == "restore_attempt" for event in events)
    assert any(
        event.get("event_type") == "restore_result" and event.get("outcome") == "success"
        for event in events
    )
