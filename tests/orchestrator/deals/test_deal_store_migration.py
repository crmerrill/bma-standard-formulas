from __future__ import annotations

import hashlib
import json
import subprocess
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
from bma_standard_formulas.deals.schemas.migrations import migrate_deal_payload


def _run_git(repo_path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _build_deal_payload(*, deal_name: str, coupon: float) -> dict[str, Any]:
    deal = DealDefinition(
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
    return deal.model_dump(mode="json")


def _checksum(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, indent=2)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _write_legacy_fixture(
    *,
    root: Path,
    deal_id: str,
    payloads: list[dict[str, Any]],
    include_studio_fields: bool = False,
) -> Path:
    deal_path = root / deal_id
    deal_path.mkdir(parents=True, exist_ok=True)
    created_at = "2026-01-01T00:00:00+00:00"

    for idx, payload in enumerate(payloads, start=1):
        (deal_path / f"v{idx}.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    manifest: dict[str, Any] = {
        "deal_id": deal_id,
        "deal_name": payloads[-1]["deal_name"],
        "created_at": created_at,
        "current_version": len(payloads),
        "versions": [
            {
                "version": idx,
                "schema_version": payload["schema_version"],
                "checksum": _checksum(payload),
                "created_at": created_at,
            }
            for idx, payload in enumerate(payloads, start=1)
        ],
        "updated_at": created_at,
        "solver_presets_library": [
            {
                "preset_name": "legacy preset",
                "solver_spec": {"iterations": 10},
                "notes": "",
                "created_at": created_at,
                "updated_at": created_at,
            }
        ],
    }
    if include_studio_fields:
        manifest["studio_current_version"] = 3
        manifest["studio_versions"] = [
            {"version": 1, "created_at": created_at},
            {"version": 2, "created_at": created_at},
            {"version": 3, "created_at": created_at},
        ]

    (deal_path / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return deal_path


def _redirect_deal_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)


def test_legacy_migration_creates_linear_history_with_exact_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deal_id = "deal_migrate_linear"
    payloads = [
        _build_deal_payload(deal_name="legacy-migration", coupon=5.0),
        _build_deal_payload(deal_name="legacy-migration", coupon=5.5),
        _build_deal_payload(deal_name="legacy-migration", coupon=6.0),
    ]
    deal_path = _write_legacy_fixture(root=tmp_path, deal_id=deal_id, payloads=payloads)
    _redirect_deal_dirs(monkeypatch, tmp_path)

    loaded = deal_store.load_deal(deal_id)
    assert loaded.bonds[0].coupon == pytest.approx(6.0)

    assert (deal_path / ".git").exists()

    rows = [
        line
        for line in _run_git(
            deal_path,
            "log",
            "--format=%H%x00%P%x00%an%x00%s",
        ).splitlines()
        if line.strip()
    ]
    assert len(rows) == 3

    commits = []
    for row in rows:
        sha, parents, author_name, subject = row.split("\x00")
        commits.append(
            {
                "sha": sha,
                "parent_sha": parents.split()[0] if parents else None,
                "author_name": author_name,
                "subject": subject,
            }
        )

    assert [commit["author_name"] for commit in commits] == [
        "system:migration",
        "system:migration",
        "system:migration",
    ]
    assert [commit["subject"] for commit in commits] == [
        "Migrate v3",
        "Migrate v2",
        "Migrate v1",
    ]
    assert commits[2]["parent_sha"] is None
    assert commits[1]["parent_sha"] == commits[2]["sha"]
    assert commits[0]["parent_sha"] == commits[1]["sha"]

    final_payload = json.loads(_run_git(deal_path, "show", "HEAD:deal.json"))
    v3_payload = json.loads((deal_path / "v3.json").read_text(encoding="utf-8"))
    assert final_payload == migrate_deal_payload(v3_payload)


def test_migration_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deal_id = "deal_migrate_idempotent"
    payloads = [
        _build_deal_payload(deal_name="legacy-idempotent", coupon=5.0),
        _build_deal_payload(deal_name="legacy-idempotent", coupon=5.5),
    ]
    deal_path = _write_legacy_fixture(root=tmp_path, deal_id=deal_id, payloads=payloads)
    _redirect_deal_dirs(monkeypatch, tmp_path)

    deal_store.load_deal(deal_id)
    assert (deal_path / ".git").exists()
    head_after_first_open = _run_git(deal_path, "rev-parse", "HEAD")
    commit_count_after_first_open = int(_run_git(deal_path, "rev-list", "--count", "HEAD"))
    assert commit_count_after_first_open == 2

    deal_store.load_deal(deal_id)
    head_after_second_open = _run_git(deal_path, "rev-parse", "HEAD")
    commit_count_after_second_open = int(_run_git(deal_path, "rev-list", "--count", "HEAD"))

    assert head_after_second_open == head_after_first_open
    assert commit_count_after_second_open == commit_count_after_first_open


def test_manifest_keys_match_allowed_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deal_id = "deal_manifest_keys"
    payloads = [_build_deal_payload(deal_name="legacy-manifest", coupon=5.0)]
    deal_path = _write_legacy_fixture(
        root=tmp_path,
        deal_id=deal_id,
        payloads=payloads,
        include_studio_fields=True,
    )
    _redirect_deal_dirs(monkeypatch, tmp_path)

    pre_migration_manifest = json.loads((deal_path / "manifest.json").read_text(encoding="utf-8"))
    deal_store.load_deal(deal_id)
    post_migration_manifest = json.loads((deal_path / "manifest.json").read_text(encoding="utf-8"))

    allowed_keys = {
        "deal_id",
        "deal_name",
        "asset_class",
        "schema_version_pin",
        "created_at",
        "updated_at",
        "studio_current_version",
        "studio_versions",
    }
    assert set(post_migration_manifest.keys()) == allowed_keys
    assert post_migration_manifest["studio_current_version"] == pre_migration_manifest["studio_current_version"]
    assert post_migration_manifest["studio_versions"] == pre_migration_manifest["studio_versions"]
    assert "current_version" not in post_migration_manifest
    assert "versions" not in post_migration_manifest
    assert "solver_presets_library" not in post_migration_manifest
