"""Regression: export_deal() strictly excludes sidecar + sidecar.broken (sdpm-6 AC 1, 2).

These tests pin the irvc-5a export isolation boundary: export_deal() is
hardcoded to retrieve only deal.json via git show <sha>:deal.json; no
working-tree file (sidecar.json, sidecar.broken.json, scenarios.json,
turn_transcripts/, discarded_branches/, .git/) can leak into the export.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bma_cfengine_app.orchestrator.deals import deal_store
from bma_cfengine_app.orchestrator.deals.git_service import GitService
from bma_cfengine_app.orchestrator.deals.operational import export_deal
from bma_standard_formulas.deals.schemas.common import RuleType
from bma_standard_formulas.deals.schemas.ir import (
    AccountDef,
    BondDef,
    DealDefinition,
    FeeDef,
    RuleNode,
)


@pytest.fixture
def redirected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)
    deal_store.init_deals_workspace()
    return tmp_path


def _build_minimal_deal(*, deal_name: str) -> DealDefinition:
    return DealDefinition(
        deal_name=deal_name,
        bonds=[BondDef(name="A1", coupon=5.0, notional=1_000_000.0)],
        accounts=[AccountDef(name="Reserve", starting_amount=100.0)],
        fees=[FeeDef(name="Servicing", amount=10.0)],
        waterfall_rules=[
            RuleNode(
                rule_id="pay-principal",
                rule_type=RuleType.PAY_PRINCIPAL,
                order=0,
                from_sources=["CASH"],
                to_targets=["A1"],
            )
        ],
    )


def test_export_deal_strictly_excludes_sidecar_and_broken_archives(
    redirected: Path,
) -> None:
    """AC 1, 2: export_deal() returns exactly deal.json bytes; sidecar.json,
    sidecar.broken.json, scenarios.json, turn_transcripts/, and
    discarded_branches/ content are unreachable through export_deal().
    """
    deal_id = "deal_export_sidecar_regression"
    deal_store.save_deal(deal_id, _build_minimal_deal(deal_name="sidecar-regression"))

    repo = deal_store.deal_dir(deal_id)
    service = GitService(repo_path=repo)
    head = service.log(branch="main", limit=1)
    assert head, "save_deal must create at least one commit"
    sha = head[0].sha

    # Plant sidecar.json and sidecar.broken.json in the working tree (not committed).
    # These simulate the artifacts that must be excluded from the canonical export.
    sidecar_content = {"layout_overrides": {"node_export_test": {"x": 10, "y": 20}}}
    broken_content = {"__corrupt__": True, "raw": "invalid sidecar bytes"}
    (repo / "sidecar.json").write_text(json.dumps(sidecar_content), encoding="utf-8")
    (repo / "sidecar.broken.json").write_text(json.dumps(broken_content), encoding="utf-8")
    (repo / "scenarios.json").write_text('{"scenarios": []}', encoding="utf-8")

    turn_dir = repo / "turn_transcripts"
    turn_dir.mkdir(parents=True, exist_ok=True)
    (turn_dir / "turn_abc.json").write_text('{"turn_id": "turn_abc"}', encoding="utf-8")

    discarded_dir = repo / "discarded_branches" / "branch_sdpm6"
    discarded_dir.mkdir(parents=True, exist_ok=True)
    (discarded_dir / "some.txt").write_text("discarded", encoding="utf-8")

    # export_deal must return exactly service.show(sha, "deal.json") bytes.
    expected_bytes = service.show(sha, "deal.json")
    actual_bytes = export_deal(deal_id, sha)

    assert isinstance(actual_bytes, (bytes, bytearray))
    assert bytes(actual_bytes) == bytes(expected_bytes), (
        "export_deal() must return exactly the git-backed deal.json content"
    )

    # The export result must not contain any sidecar or sidecar.broken content.
    actual_text = bytes(actual_bytes).decode("utf-8")
    assert "layout_overrides" not in actual_text, (
        "sidecar.json content (layout_overrides) must not appear in export_deal() output"
    )
    assert "node_export_test" not in actual_text, (
        "sidecar.json node key must not appear in export_deal() output"
    )
    assert "__corrupt__" not in actual_text, (
        "sidecar.broken.json sentinel key must not appear in export_deal() output"
    )
    assert "turn_id" not in actual_text, (
        "turn_transcripts content must not appear in export_deal() output"
    )

    # Confirm the exported payload is valid deal.json, not a sidecar derivative.
    exported_payload = json.loads(actual_text)
    assert "deal_name" in exported_payload, "Exported content must be a deal.json payload"
    assert exported_payload.get("deal_name") == "sidecar-regression"

    # The forbidden artifacts remain on disk — export_deal must not delete them.
    assert (repo / "sidecar.json").exists(), "sidecar.json must remain on disk after export"
    assert (repo / "sidecar.broken.json").exists(), (
        "sidecar.broken.json must remain on disk after export"
    )
