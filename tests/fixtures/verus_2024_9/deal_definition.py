"""Canonical deal_definition export for the fixture emitter."""
from bma_standard_formulas.deals.schemas.common import RuleType, TrancheKind
from bma_standard_formulas.deals.schemas.ir import BondDef, DealDefinition, RuleNode

deal_definition = DealDefinition(
    deal_name="Verus 2024-9",
    description=(
        "Verus Securitization Trust 2024-9 — structural fixture with Phase 5 "
        "step-up coupon. "
        "TODO: Extract decrement table (10/20/30 CPR) and Class A-1 yield table "
        "from the offering supplement before marking this fixture complete."
    ),
    bonds=[
        BondDef(name="A1", kind=TrancheKind.CASH_PAY,
                coupon=[{"from_period": 1, "rate": 6.00},
                        {"from_period": 61, "rate": 7.00}],
                notional=5_000_000.0),
        BondDef(name="A2", kind=TrancheKind.CASH_PAY,
                coupon=[{"from_period": 1, "rate": 6.50},
                        {"from_period": 61, "rate": 7.50}],
                notional=2_000_000.0),
        BondDef(name="M1", kind=TrancheKind.CASH_PAY,
                coupon=[{"from_period": 1, "rate": 7.00},
                        {"from_period": 61, "rate": 8.00}],
                notional=500_000.0),
        BondDef(name="M2", kind=TrancheKind.CASH_PAY,
                coupon=[{"from_period": 1, "rate": 8.00},
                        {"from_period": 61, "rate": 9.00}],
                notional=250_000.0),
        BondDef(name="XS", kind=TrancheKind.IO, coupon=0.0,
                notional=0.0, is_bond=True, is_pseudo=False),
        BondDef(name="R", kind=TrancheKind.RESIDUAL,
                is_bond=False, is_pseudo=True),
    ],
    waterfall_rules=[
        RuleNode(rule_id="int_a", rule_type=RuleType.PAY_INTEREST, order=0,
                 from_sources=["ACT_INT"], to_targets=["A1", "A2"]),
        RuleNode(rule_id="int_m", rule_type=RuleType.PAY_INTEREST, order=1,
                 from_sources=["ACT_INT"], to_targets=["M1", "M2"]),
        RuleNode(rule_id="prin_a1", rule_type=RuleType.PAY_PRINCIPAL, order=2,
                 from_sources=["CASH"], to_targets=["A1"]),
        RuleNode(rule_id="prin_a2", rule_type=RuleType.PAY_PRINCIPAL, order=3,
                 from_sources=["CASH"], to_targets=["A2"]),
        RuleNode(rule_id="prin_m1", rule_type=RuleType.PAY_PRINCIPAL, order=4,
                 from_sources=["CASH"], to_targets=["M1"]),
        RuleNode(rule_id="prin_m2", rule_type=RuleType.PAY_PRINCIPAL, order=5,
                 from_sources=["CASH"], to_targets=["M2"]),
        RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=6,
                 from_sources=["CASH"], to_targets=["R"]),
    ],
)
