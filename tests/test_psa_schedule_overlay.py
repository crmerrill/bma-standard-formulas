"""Unit tests for PSA schedule overlay builder (Phase 1i)."""
from __future__ import annotations

from bma_cfengine_app.orchestrator.deals.psa_schedule_overlay import (
    PoolDerivationInputs,
    build_psa_schedule_overlay,
)
from bma_standard_formulas.deals.schemas.common import (
    CapMode,
    PaymentStyle,
    PrepayModelType,
    RuleType,
    TrancheBehavior,
    TrancheType,
)
from bma_standard_formulas.deals.schemas.ir import BondDef, DealDefinition, RuleNode


def _support_bond(name: str = "SUP") -> BondDef:
    return BondDef(
        name=name,
        tranche_type=TrancheType.SUPPORT,
        size_dollars=1_000_000.0,
        size_pct=0.0,
    )


def _one_rule_deal(bonds: list[BondDef]) -> DealDefinition:
    """Minimal valid ``DealDefinition`` for overlay unit tests."""
    tgt = bonds[0].name if bonds else "X"
    return DealDefinition(
        deal_name="T",
        bonds=bonds,
        accounts=[],
        fees=[],
        triggers=[],
        waterfall_rules=[
            RuleNode(
                rule_id="p1",
                rule_type=RuleType.PAY_PRINCIPAL,
                order=0,
                from_sources=["CASH"],
                to_targets=[tgt],
                payment_style=PaymentStyle.SEQUENTIAL,
                cap_mode=CapMode.SCHEDULED,
            ),
        ],
    )


def test_build_overlay_pac_populates_schedule():
    sup = _support_bond()
    pac = BondDef(
        name="PAC_A",
        tranche_behavior=TrancheBehavior.PAC,
        schedule_model_type=PrepayModelType.PSA,
        schedule_speed_low=100.0,
        schedule_speed_high=250.0,
        size_dollars=4_000_000.0,
        support_tranches=[sup.name],
    )
    deal = _one_rule_deal([pac, sup])
    pool = PoolDerivationInputs(
        balance=10_000_000.0,
        wac_pct=6.0,
        term_months=360,
        horizon_months=60,
    )
    overlay = build_psa_schedule_overlay(deal, pool)
    assert "PAC_A" in overlay
    assert len(overlay["PAC_A"]["schedule_contract"]) > 0
    prov = overlay["PAC_A"]["schedule_derivation"]
    assert prov["method"] == "PSA_RANGE"
    assert prov["inputs"]["psa_low"] == 100.0
    assert prov["inputs"]["psa_high"] == 250.0


def test_build_overlay_skips_non_psa_model():
    sup = _support_bond()
    bond = BondDef(
        name="X",
        tranche_behavior=TrancheBehavior.PAC,
        schedule_model_type=PrepayModelType.CPR,
        schedule_speed_low=50.0,
        schedule_speed_high=100.0,
        size_dollars=1_000_000.0,
        support_tranches=[sup.name],
    )
    deal = _one_rule_deal([bond, sup])
    overlay = build_psa_schedule_overlay(
        deal,
        PoolDerivationInputs(10_000_000.0, 6.0, 360, 60),
    )
    assert overlay == {}


def test_build_overlay_empty_pool_returns_empty():
    sup = _support_bond()
    bond = BondDef(
        name="P",
        tranche_behavior=TrancheBehavior.PAC,
        schedule_model_type=PrepayModelType.PSA,
        schedule_speed_low=100.0,
        schedule_speed_high=250.0,
        size_dollars=1.0,
        support_tranches=[sup.name],
    )
    deal = _one_rule_deal([bond, sup])
    assert (
        build_psa_schedule_overlay(
            deal,
            PoolDerivationInputs(0.0, 6.0, 360, 60),
        )
        == {}
    )
