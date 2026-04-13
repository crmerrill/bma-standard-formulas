from bma_cfengine_app.orchestrator.deals.structuring_verification import verify_structure
from bma_standard_formulas.deals.schemas.common import (
    PayMode,
    PrepayModelType,
    RuleType,
    TrancheBehavior,
    TrancheType,
)
from bma_standard_formulas.deals.schemas.ir import BondDef, DealDefinition, FeeDef, RuleNode
import pytest


def test_verification_passes_for_pac_with_support():
    deal = DealDefinition(
        deal_name="VerifyPAC",
        bonds=[
            BondDef(name="A", tranche_type=TrancheType.SEQUENTIAL),
            BondDef(name="B", tranche_type=TrancheType.SEQUENTIAL),
            BondDef(
                name="PAC",
                tranche_type=TrancheType.SEQUENTIAL,
                tranche_behavior=TrancheBehavior.PAC,
                schedule_contract=[{"period": 1, "target_principal": 10.0}],
                support_tranches=["B"],
            ),
        ],
        waterfall_rules=[
            RuleNode(rule_id="r1", rule_type=RuleType.PAY_PRINCIPAL, order=0, from_sources=["CASH"], to_targets=["PAC"])
        ],
    )
    out = verify_structure(deal)
    assert out["valid"] is True


def test_verification_flags_invalid_z_support():
    deal = DealDefinition(
        deal_name="VerifyZ",
        bonds=[
            BondDef(name="A", tranche_type=TrancheType.SEQUENTIAL),
            BondDef(
                name="Z",
                tranche_type=TrancheType.Z_BOND,
                tranche_behavior=TrancheBehavior.Z,
                pay_mode=PayMode.PIK,
                z_accrual_enabled=True,
                supported_by_tranches=["A"],
            ),
        ],
        waterfall_rules=[
            RuleNode(rule_id="r1", rule_type=RuleType.PAY_PRINCIPAL, order=0, from_sources=["CASH"], to_targets=["A"])
        ],
    )
    out = verify_structure(deal)
    assert "suggestions" in out


def test_verification_fails_for_pac_without_support():
    with pytest.raises(Exception):
        DealDefinition(
            deal_name="VerifyPACNoSupport",
            bonds=[
                BondDef(name="A", tranche_type=TrancheType.SEQUENTIAL),
                BondDef(
                    name="PAC",
                    tranche_type=TrancheType.SEQUENTIAL,
                    tranche_behavior=TrancheBehavior.PAC,
                    schedule_contract=[{"period": 1, "target_principal": 10.0}],
                    support_tranches=[],
                ),
            ],
            waterfall_rules=[
                RuleNode(rule_id="r1", rule_type=RuleType.PAY_PRINCIPAL, order=0, from_sources=["CASH"], to_targets=["PAC"])
            ],
        )


def test_verification_passes_for_pac_model_driven_schedule():
    deal = DealDefinition(
        deal_name="VerifyPACModel",
        bonds=[
            BondDef(name="A", tranche_type=TrancheType.SEQUENTIAL),
            BondDef(name="SUP", tranche_type=TrancheType.SEQUENTIAL),
            BondDef(
                name="PAC",
                tranche_type=TrancheType.SEQUENTIAL,
                tranche_behavior=TrancheBehavior.PAC,
                schedule_model_type=PrepayModelType.PSA,
                schedule_speed_low=100.0,
                schedule_speed_high=275.0,
                support_tranches=["SUP"],
            ),
        ],
        waterfall_rules=[
            RuleNode(rule_id="r1", rule_type=RuleType.PAY_PRINCIPAL, order=0, from_sources=["CASH"], to_targets=["PAC"])
        ],
    )
    out = verify_structure(deal)
    assert out["valid"] is True


def test_verification_allows_fee_name_alias_with_pseudo_bond():
    deal = DealDefinition(
        deal_name="VerifyFeeAlias",
        bonds=[
            BondDef(name="A", tranche_type=TrancheType.SEQUENTIAL),
            BondDef(name="SERVICER", tranche_type=TrancheType.PSEUDO, is_bond=False, is_pseudo=True),
        ],
        fees=[FeeDef(name="SERVICER", basis_type="FIXED_DOLLAR", amount=100.0)],
        waterfall_rules=[
            RuleNode(rule_id="r1", rule_type=RuleType.PAY_INTEREST, order=0, from_sources=["CASH"], to_targets=["A"]),
            RuleNode(rule_id="r2", rule_type=RuleType.PAY_FEE, order=1, from_sources=["CASH"], to_targets=["SERVICER"]),
        ],
    )
    out = verify_structure(deal)
    assert out["valid"] is True

