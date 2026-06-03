"""sdpm-3: first-open behavior tests.

AC 1 — missing .git/: git init + system:migration commit.
AC 2 — missing sidecar.json in commit: empty StudioSidecar, no error diagnostic.
"""
from __future__ import annotations

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
from bma_standard_formulas.deals.schemas.studio_sidecar import StudioSidecar


def _run_git(repo_path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _minimal_deal() -> DealDefinition:
    return DealDefinition(
        deal_name="sdpm-3-test-deal",
        bonds=[BondDef(name="A1", coupon=5.0, notional=1_000_000.0)],
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


def _redirect_deal_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)


def test_missing_git_dir_triggers_git_init_and_system_migration_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC 1: deal dir with deal.json but no .git/ → git init + single migration commit."""
    _redirect_deal_dirs(monkeypatch, tmp_path)

    deal_id = "deal_sdpm3_no_git"
    deal_path = tmp_path / deal_id
    deal_path.mkdir(parents=True, exist_ok=True)

    original_payload: dict[str, Any] = _minimal_deal().model_dump(mode="json")
    original_bytes = json.dumps(original_payload, indent=2).encode("utf-8")
    (deal_path / "deal.json").write_bytes(original_bytes)

    assert not (deal_path / ".git").exists()

    result = deal_store.load_deal(deal_id)
    assert result is not None

    # .git/ now exists
    assert (deal_path / ".git").exists()

    # Exactly ONE commit
    commit_count = int(_run_git(deal_path, "rev-list", "--count", "main"))
    assert commit_count == 1

    # Author name = "system:migration"; subject = "Migrate deal.json"
    log_line = _run_git(deal_path, "log", "--format=%an%x00%s", "HEAD")
    author_name, subject = log_line.split("\x00")
    assert author_name == "system:migration"
    assert subject == "Migrate deal.json"

    # Commit body is empty (no sdpm-4 provenance)
    body = _run_git(deal_path, "log", "--format=%b", "HEAD").strip()
    assert body == ""

    # Committed deal.json content matches original
    committed_json = _run_git(deal_path, "show", "HEAD:deal.json")
    committed_payload = json.loads(committed_json)
    assert committed_payload["deal_name"] == original_payload["deal_name"]
    assert committed_payload["bonds"] == original_payload["bonds"]


def test_missing_sidecar_yields_empty_sidecar_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC 2: git repo with deal.json but no sidecar.json → default StudioSidecar, no error diagnostic."""
    _redirect_deal_dirs(monkeypatch, tmp_path)

    deal_id = "deal_sdpm3_no_sidecar"
    deal = _minimal_deal()

    # save_deal commits deal.json only (no sidecar), producing a clean git repo
    deal_store.save_deal(deal_id, deal)

    # Verify no sidecar.json in the HEAD commit
    deal_path = tmp_path / deal_id
    try:
        _run_git(deal_path, "show", "HEAD:sidecar.json")
        has_sidecar = True
    except subprocess.CalledProcessError:
        has_sidecar = False
    assert not has_sidecar, "Fixture should have no sidecar.json in HEAD commit"

    result = deal_store.load_deal(deal_id)
    assert result is not None
    _, sidecar, diagnostics = result

    # Returns a default empty StudioSidecar
    assert isinstance(sidecar, StudioSidecar)
    assert sidecar.layout_overrides == {}
    assert sidecar.ui_preferences == {}
    assert sidecar.schema_version == "1.0.0"

    # No SIDECAR_LOAD_FAILED diagnostic
    fail_codes = [d.code for d in diagnostics if d.code == "SIDECAR_LOAD_FAILED"]
    assert fail_codes == []
