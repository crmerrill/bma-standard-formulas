from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

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


def _write_legacy_fixture(
    *,
    root: Path,
    deal_id: str,
    payloads: list[dict[str, Any]],
) -> Path:
    deal_path = root / deal_id
    deal_path.mkdir(parents=True, exist_ok=True)
    created_at = "2026-01-01T00:00:00+00:00"

    for idx, payload in enumerate(payloads, start=1):
        (deal_path / f"v{idx}.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    manifest = {
        "deal_id": deal_id,
        "deal_name": payloads[-1]["deal_name"],
        "created_at": created_at,
        "current_version": len(payloads),
        "versions": [
            {
                "version": idx,
                "schema_version": payload["schema_version"],
                "checksum": hashlib.sha256(
                    json.dumps(payload, indent=2).encode("utf-8")
                ).hexdigest()[:16],
                "created_at": created_at,
            }
            for idx, payload in enumerate(payloads, start=1)
        ],
        "updated_at": created_at,
    }
    (deal_path / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return deal_path


def _redirect_deal_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)


def test_save_load_routes_to_git_and_applies_schema_migration_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deal_id = "deal_git_route"
    payloads = [
        _build_deal_payload(deal_name="git-route", coupon=5.0),
        _build_deal_payload(deal_name="git-route", coupon=5.5),
    ]
    deal_path = _write_legacy_fixture(root=tmp_path, deal_id=deal_id, payloads=payloads)
    _redirect_deal_dirs(monkeypatch, tmp_path)

    deal_store.load_deal(deal_id)
    assert (deal_path / ".git").exists()
    commit_count_before_save = int(_run_git(deal_path, "rev-list", "--count", "HEAD"))

    new_deal = DealDefinition.model_validate(
        _build_deal_payload(deal_name="git-route-updated", coupon=6.25)
    )
    deal_store.save_deal(deal_id, new_deal)

    commit_count_after_save = int(_run_git(deal_path, "rev-list", "--count", "HEAD"))
    assert commit_count_after_save == commit_count_before_save + 1

    last_author_name = _run_git(deal_path, "log", "-1", "--format=%an")
    assert last_author_name != "system:migration"

    loaded = deal_store.load_deal(deal_id)
    assert loaded.model_dump(mode="json") == new_deal.model_dump(mode="json")


def build_minimal_deal_definition(*, deal_name: str) -> DealDefinition:
    return DealDefinition.model_validate(
        _build_deal_payload(deal_name=deal_name, coupon=5.0)
    )


def test_load_deal_versioned_lookup_works_for_save_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M1 (R1 fix): load_deal(deal_id, version=N) must work for normal saves,
    not just migration commits."""
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)

    deal_id = "deal_v_lookup_test"
    deal1 = build_minimal_deal_definition(deal_name="v1")
    deal2 = build_minimal_deal_definition(deal_name="v2")
    deal3 = build_minimal_deal_definition(deal_name="v3")

    save_result_1 = deal_store.save_deal(deal_id, deal1)  # version 1
    save_result_2 = deal_store.save_deal(deal_id, deal2)  # version 2
    save_result_3 = deal_store.save_deal(deal_id, deal3)  # version 3

    # Round-trip each version
    loaded_v1 = deal_store.load_deal(deal_id, version=save_result_1["version"])
    assert loaded_v1 is not None
    assert loaded_v1.deal_name == "v1"

    loaded_v2 = deal_store.load_deal(deal_id, version=save_result_2["version"])
    assert loaded_v2 is not None
    assert loaded_v2.deal_name == "v2"

    loaded_v3 = deal_store.load_deal(deal_id, version=save_result_3["version"])
    assert loaded_v3 is not None
    assert loaded_v3.deal_name == "v3"

    # version=None returns HEAD (latest = v3)
    loaded_head = deal_store.load_deal(deal_id, version=None)
    assert loaded_head is not None
    assert loaded_head.deal_name == "v3"


def test_schema_migration_runs_before_pydantic_validation_negative_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deal_id = "deal_schema_negative"
    legacy_payload = _build_deal_payload(deal_name="legacy-z-bond", coupon=5.0)
    legacy_payload["bonds"][0]["kind"] = "Z_BOND"
    deal_path = _write_legacy_fixture(root=tmp_path, deal_id=deal_id, payloads=[legacy_payload])
    _redirect_deal_dirs(monkeypatch, tmp_path)

    with pytest.raises(ValidationError):
        DealDefinition.model_validate(legacy_payload)

    migrated_payload = migrate_deal_payload(legacy_payload)
    migrated_deal = DealDefinition.model_validate(migrated_payload)
    assert migrated_deal.bonds[0].kind.value == "Z"

    loaded = deal_store.load_deal(deal_id)
    assert loaded.bonds[0].kind.value == "Z"
    assert (deal_path / ".git").exists()

    head_payload = json.loads(_run_git(deal_path, "show", "HEAD:deal.json"))
    assert head_payload == migrated_payload
