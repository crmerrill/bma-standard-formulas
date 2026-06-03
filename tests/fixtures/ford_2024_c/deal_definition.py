"""Canonical deal_definition export for the fixture emitter."""
from bma_standard_formulas.deals.schemas.common import AccountCategory, RuleType, TrancheKind
from bma_standard_formulas.deals.schemas.ir import (
    AccountDef,
    BondDef,
    DealDefinition,
    FeeDef,
    RuleNode,
)

deal_definition = DealDefinition(
    deal_name="Ford 2024-C",
    description=(
        "Ford Credit Auto Owner Trust 2024-C — structural fixture. "
        "TODO: Extract Exhibit A decrement table before declaring tie-out complete."
    ),
    bonds=[
        BondDef(name="A1", kind=TrancheKind.CASH_PAY, coupon=5.35, notional=300_000_000.0),
        BondDef(name="A2", kind=TrancheKind.CASH_PAY, coupon=5.20, notional=500_000_000.0),
        BondDef(name="A3", kind=TrancheKind.CASH_PAY, coupon=5.10, notional=400_000_000.0),
        BondDef(name="A4", kind=TrancheKind.CASH_PAY, coupon=5.00, notional=200_000_000.0),
        BondDef(name="B", kind=TrancheKind.CASH_PAY, coupon=5.50, notional=50_000_000.0),
        BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
    ],
    accounts=[
        AccountDef(
            name="RESERVE",
            account_category=AccountCategory.RESERVE,
            starting_amount=3_625_000.0,
        ),
    ],
    fees=[
        FeeDef(
            name="TRUSTEE_FEE",
            basis_type="COLLATERAL_BALANCE",
            rate=0.0025 / 12,
            frequency="MONTHLY",
        ),
    ],
    waterfall_rules=[
        RuleNode(rule_id="fee", rule_type=RuleType.PAY_FEE, order=0,
                 from_sources=["CASH"], to_targets=["TRUSTEE_FEE"],
                 max_amount_fixed=31_250.0),
        RuleNode(rule_id="int_all", rule_type=RuleType.PAY_INTEREST, order=1,
                 from_sources=["CASH"], to_targets=["A1", "A2", "A3", "A4", "B"]),
        RuleNode(rule_id="prin_a1", rule_type=RuleType.PAY_PRINCIPAL, order=2,
                 from_sources=["CASH"], to_targets=["A1"]),
        RuleNode(rule_id="prin_a2", rule_type=RuleType.PAY_PRINCIPAL, order=3,
                 from_sources=["CASH"], to_targets=["A2"]),
        RuleNode(rule_id="prin_a3", rule_type=RuleType.PAY_PRINCIPAL, order=4,
                 from_sources=["CASH"], to_targets=["A3"]),
        RuleNode(rule_id="prin_a4", rule_type=RuleType.PAY_PRINCIPAL, order=5,
                 from_sources=["CASH"], to_targets=["A4"]),
        RuleNode(rule_id="prin_b", rule_type=RuleType.PAY_PRINCIPAL, order=6,
                 from_sources=["CASH"], to_targets=["B"]),
        RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=7,
                 from_sources=["CASH"], to_targets=["R"]),
    ],
)
