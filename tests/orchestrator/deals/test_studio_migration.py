"""Tests for sdpm-4: legacy studio_v{N}.json migration.

Verifies that migrate_studio_payload extracts Blockly layout to sidecar
layout_overrides, maps block.data notes to IR description fields, and
formats AI provenance into the migration commit message body.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from bma_cfengine_app.orchestrator.deals import deal_store
from bma_cfengine_app.orchestrator.deals.git_service import GitService
from bma_standard_formulas.deals.schemas.common import RuleType, TrancheRelationType
from bma_standard_formulas.deals.schemas.ir import (
    AccountDef,
    BondDef,
    CalculationNode,
    CollateralGroupDef,
    DealDefinition,
    FeeDef,
    RuleNode,
    TrancheRelation,
    TriggerNode,
)
from bma_standard_formulas.deals.schemas.migrations.studio_migration import migrate_studio_payload
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


def _build_deal_payload(*, deal_name: str = "test-deal", coupon: float = 5.0) -> dict[str, Any]:
    deal = DealDefinition(
        deal_name=deal_name,
        bonds=[BondDef(name="A1", coupon=coupon, notional=1_000_000.0)],
        accounts=[AccountDef(name="Reserve", starting_amount=100.0)],
        fees=[FeeDef(name="Servicing", amount=10.0)],
        calculations=[CalculationNode(name="OC_Test", expression="bonds.A1.balance / collateral.balance")],
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


def _make_blockly_xml(blocks: list[dict[str, Any]]) -> str:
    """Build a minimal Blockly workspace XML with positioned blocks."""
    block_elements = []
    for block in blocks:
        block_elements.append(
            f'  <block type="{block["type"]}" id="{block["id"]}" '
            f'x="{block["x"]}" y="{block["y"]}"></block>'
        )
    return (
        '<xml xmlns="https://developers.google.com/blockly/xml">\n'
        + "\n".join(block_elements)
        + "\n</xml>"
    )


def _make_studio_payload(
    *,
    deal_id: str,
    deal_name: str,
    blockly_xml: str,
    block_data: dict[str, Any] | None = None,
    ai_provenance: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a legacy studio_v{N}.json payload."""
    payload: dict[str, Any] = {
        "deal_id": deal_id,
        "deal_name": deal_name,
        "schema_version": "studio",
        "saved_at": "2026-01-01T00:00:00+00:00",
        "ir": {
            "schema_version": "studio",
            "blockly_xml": blockly_xml,
        },
    }
    if block_data is not None:
        payload["ir"]["block_data"] = block_data
    if ai_provenance is not None:
        payload["ai_provenance"] = ai_provenance
    return payload


def _redirect_deal_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)


def _write_legacy_deal_with_studio(
    *,
    root: Path,
    deal_id: str,
    deal_payload: dict[str, Any],
    studio_payload: dict[str, Any],
) -> Path:
    """Set up a legacy deal dir with v1.json + studio_v1.json + manifest."""
    deal_path = root / deal_id
    deal_path.mkdir(parents=True, exist_ok=True)
    created_at = "2026-01-01T00:00:00+00:00"

    (deal_path / "v1.json").write_text(json.dumps(deal_payload, indent=2), encoding="utf-8")
    (deal_path / "studio_v1.json").write_text(json.dumps(studio_payload, indent=2), encoding="utf-8")

    manifest = {
        "deal_id": deal_id,
        "deal_name": deal_payload["deal_name"],
        "created_at": created_at,
        "current_version": 1,
        "versions": [{"version": 1, "schema_version": deal_payload["schema_version"], "created_at": created_at}],
        "studio_current_version": 1,
        "studio_versions": [{"version": 1, "created_at": created_at}],
        "updated_at": created_at,
    }
    (deal_path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return deal_path


class TestMigrateStudioPayloadExtractsLayoutXmlToOverrides:
    """AC 1, 2: Blockly XML layout → sidecar layout_overrides."""

    def test_migrate_studio_payload_extracts_layout_xml_to_overrides(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        deal_id = "deal_layout_migration"
        deal_payload = _build_deal_payload(deal_name="layout-test")

        blockly_xml = _make_blockly_xml([
            {"type": "bond_block", "id": "A1", "x": 120.5, "y": 200.0},
            {"type": "calc_block", "id": "OC_Test", "x": 350.0, "y": 80.25},
        ])
        studio_payload = _make_studio_payload(
            deal_id=deal_id,
            deal_name="layout-test",
            blockly_xml=blockly_xml,
        )
        deal_path = _write_legacy_deal_with_studio(
            root=tmp_path,
            deal_id=deal_id,
            deal_payload=deal_payload,
            studio_payload=studio_payload,
        )
        _redirect_deal_dirs(monkeypatch, tmp_path)

        result = deal_store.load_deal(deal_id)
        assert result is not None
        deal_def, sidecar, diagnostics = result

        assert (deal_path / ".git").exists()

        service = GitService(repo_path=deal_path, _verified_clean=True)
        commits = service.log(branch="main", limit=10)
        assert len(commits) == 1

        commit_tree_has_sidecar = False
        try:
            sidecar_raw = service.show(commits[0].sha, "sidecar.json")
            commit_tree_has_sidecar = True
            committed_sidecar = StudioSidecar.model_validate_json(sidecar_raw)
        except Exception:
            pass

        assert commit_tree_has_sidecar, "Migration commit must contain sidecar.json"
        assert "A1" in committed_sidecar.layout_overrides
        assert "OC_Test" in committed_sidecar.layout_overrides
        assert committed_sidecar.layout_overrides["A1"]["x"] == pytest.approx(120.5)
        assert committed_sidecar.layout_overrides["A1"]["y"] == pytest.approx(200.0)
        assert committed_sidecar.layout_overrides["OC_Test"]["x"] == pytest.approx(350.0)
        assert committed_sidecar.layout_overrides["OC_Test"]["y"] == pytest.approx(80.25)


class TestLegacyNotesAreMappedToIrDescriptionFields:
    """AC 3: block.data notes → IR description fields."""

    def test_legacy_notes_are_mapped_to_ir_description_fields(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        deal_id = "deal_notes_migration"
        deal_payload = _build_deal_payload(deal_name="notes-test")

        blockly_xml = _make_blockly_xml([
            {"type": "rule_block", "id": "pay-principal-a1", "x": 100, "y": 100},
            {"type": "calc_block", "id": "OC_Test", "x": 200, "y": 200},
        ])
        block_data = {
            "pay-principal-a1": {"description": "M-1 sized to absorb 95% of expected losses"},
            "OC_Test": {"description": "OC test for senior tranche protection"},
        }
        studio_payload = _make_studio_payload(
            deal_id=deal_id,
            deal_name="notes-test",
            blockly_xml=blockly_xml,
            block_data=block_data,
        )
        deal_path = _write_legacy_deal_with_studio(
            root=tmp_path,
            deal_id=deal_id,
            deal_payload=deal_payload,
            studio_payload=studio_payload,
        )
        _redirect_deal_dirs(monkeypatch, tmp_path)

        result = deal_store.load_deal(deal_id)
        assert result is not None
        deal_def, sidecar, diagnostics = result

        service = GitService(repo_path=deal_path, _verified_clean=True)
        commits = service.log(branch="main", limit=10)
        committed_deal_raw = service.show(commits[0].sha, "deal.json")
        committed_deal = DealDefinition.model_validate_json(committed_deal_raw)

        rule = next(r for r in committed_deal.waterfall_rules if r.rule_id == "pay-principal-a1")
        assert rule.description == "M-1 sized to absorb 95% of expected losses"

        calc_oc = next(c for c in committed_deal.calculations if c.name == "OC_Test")
        assert calc_oc.description == "OC test for senior tranche protection"


class TestLegacyAiProvenanceIsAddedToMigrationCommitMessage:
    """AC 4: ai_provenance → commit message body."""

    def test_legacy_ai_provenance_is_added_to_migration_commit_message(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        deal_id = "deal_provenance_migration"
        deal_payload = _build_deal_payload(deal_name="provenance-test")

        blockly_xml = _make_blockly_xml([
            {"type": "bond_block", "id": "A1", "x": 100, "y": 100},
        ])
        ai_provenance = [
            {"writer": "claude", "prompt_hash": "abc123", "tool_calls": ["create_bond"]}
        ]
        studio_payload = _make_studio_payload(
            deal_id=deal_id,
            deal_name="provenance-test",
            blockly_xml=blockly_xml,
            ai_provenance=ai_provenance,
        )
        deal_path = _write_legacy_deal_with_studio(
            root=tmp_path,
            deal_id=deal_id,
            deal_payload=deal_payload,
            studio_payload=studio_payload,
        )
        _redirect_deal_dirs(monkeypatch, tmp_path)

        deal_store.load_deal(deal_id)

        full_message = _run_git(deal_path, "log", "--format=%B", "-1")

        expected_provenance = json.dumps(
            {"ai_provenance": ai_provenance},
            sort_keys=True,
            indent=2,
        )
        expected_message = f"Migrate v1\n\nLegacy-Studio-Provenance:\n{expected_provenance}"
        assert full_message.strip() == expected_message.strip()

    def test_no_provenance_means_no_footer(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        deal_id = "deal_no_provenance"
        deal_payload = _build_deal_payload(deal_name="no-provenance-test")

        blockly_xml = _make_blockly_xml([
            {"type": "bond_block", "id": "A1", "x": 100, "y": 100},
        ])
        studio_payload = _make_studio_payload(
            deal_id=deal_id,
            deal_name="no-provenance-test",
            blockly_xml=blockly_xml,
        )
        _write_legacy_deal_with_studio(
            root=tmp_path,
            deal_id=deal_id,
            deal_payload=deal_payload,
            studio_payload=studio_payload,
        )
        _redirect_deal_dirs(monkeypatch, tmp_path)

        deal_store.load_deal(deal_id)

        deal_path = tmp_path / deal_id
        full_message = _run_git(deal_path, "log", "--format=%B", "-1")
        assert "Legacy-Studio-Provenance:" not in full_message
        assert full_message.strip() == "Migrate v1"


def _build_minimal_deal(*, deal_name: str = "test") -> DealDefinition:
    """Minimal valid single-pool deal for direct migration unit tests."""
    return DealDefinition(
        deal_name=deal_name,
        bonds=[BondDef(name="A1", coupon=5.0, notional=1_000_000.0)],
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


class TestApplyBlockNotesEntityCoverage:
    """AC 3: block.data notes populate description on all entity types."""

    def test_migrate_applies_notes_to_trigger_node_description(self) -> None:
        deal = DealDefinition(
            deal_name="trigger-notes-test",
            bonds=[BondDef(name="A1", coupon=5.0, notional=1_000_000.0)],
            waterfall_rules=[
                RuleNode(
                    rule_id="pay-principal-a1",
                    rule_type=RuleType.PAY_PRINCIPAL,
                    order=0,
                    from_sources=["CASH"],
                    to_targets=["A1"],
                )
            ],
            triggers=[TriggerNode(name="OC_Trigger", threshold_value=1.2)],
        )
        payload: dict[str, Any] = {
            "ir": {
                "blockly_xml": "",
                "block_data": {
                    "OC_Trigger": {"description": "Overcollateralization trigger for A1"},
                },
            }
        }
        _, migrated, _ = migrate_studio_payload(payload, deal)
        trigger = next(t for t in migrated.triggers if t.name == "OC_Trigger")
        assert trigger.description == "Overcollateralization trigger for A1"

    def test_migrate_applies_notes_to_collateral_group_description(self) -> None:
        deal = DealDefinition(
            deal_name="cg-notes-test",
            bonds=[BondDef(name="A1", coupon=5.0, notional=1_000_000.0, group_id="GROUP_1")],
            waterfall_rules=[
                RuleNode(
                    rule_id="pay-principal-a1",
                    rule_type=RuleType.PAY_PRINCIPAL,
                    order=0,
                    from_sources=["CASH"],
                    to_targets=["A1"],
                    group_id="GROUP_1",
                )
            ],
            collateral_groups=[CollateralGroupDef(group_id="GROUP_1", label="Senior Pool")],
        )
        payload: dict[str, Any] = {
            "ir": {
                "blockly_xml": "",
                "block_data": {
                    "GROUP_1": {"description": "Senior collateral pool backing A1 tranche"},
                },
            }
        }
        _, migrated, _ = migrate_studio_payload(payload, deal)
        group = next(g for g in migrated.collateral_groups if g.group_id == "GROUP_1")
        assert group.description == "Senior collateral pool backing A1 tranche"

    def test_migrate_applies_notes_to_tranche_relation_description(self) -> None:
        """TrancheRelation.description is populated via synthetic id ``<bond_name>:relation:<index>``.

        The migration helper matches block_data keys of the form ``<bond_name>:relation:<i>``
        (0-based index into ``bond.relations``) to the corresponding ``TrancheRelation`` and
        copies ``description`` into it. This scheme is deterministic and does not require any
        legacy block id field beyond what the Blockly workspace already tracks per entity.
        """
        deal = DealDefinition(
            deal_name="relation-notes-test",
            bonds=[
                BondDef(name="A1", coupon=5.0, notional=800_000.0),
                BondDef(
                    name="B1",
                    coupon=4.0,
                    notional=200_000.0,
                    relations=[
                        TrancheRelation(
                            relation_type=TrancheRelationType.SUPPORTED_BY,
                            targets=["A1"],
                        )
                    ],
                ),
            ],
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
        payload: dict[str, Any] = {
            "ir": {
                "blockly_xml": "",
                "block_data": {
                    "B1:relation:0": {
                        "description": "B1 subordinates to A1, absorbing first-loss up to 20% of pool"
                    },
                },
            }
        }
        _, migrated, _ = migrate_studio_payload(payload, deal)
        b1 = next(b for b in migrated.bonds if b.name == "B1")
        assert b1.relations[0].description == "B1 subordinates to A1, absorbing first-loss up to 20% of pool"

    def test_migrate_unmatched_block_id_no_op(self) -> None:
        deal = _build_minimal_deal(deal_name="no-op-test")
        payload: dict[str, Any] = {
            "ir": {
                "blockly_xml": "",
                "block_data": {
                    "no-such-entity-xyz": {"description": "Should not match anything"},
                },
            }
        }
        _, migrated, _ = migrate_studio_payload(payload, deal)
        assert migrated.deal_name == "no-op-test"
        rule = next(r for r in migrated.waterfall_rules if r.rule_id == "pay-principal-a1")
        assert rule.description == ""
