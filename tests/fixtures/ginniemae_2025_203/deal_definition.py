"""Canonical deal_definition export for the fixture emitter."""
from bma_standard_formulas.deals.schemas.common import (
    PayMode,
    RuleType,
    TrancheKind,
    TrancheRelationType,
)
from bma_standard_formulas.deals.schemas.ir import (
    BondDef,
    DealDefinition,
    RuleNode,
    TrancheRelation,
)

pac_schedule_placeholder = [
    {"period": i, "target_balance": max(0.0, 1_000_000 - i * 3_000)}
    for i in range(1, 334)
]

deal_definition = DealDefinition(
    deal_name="GNMA 2025-203",
    description=(
        "Ginnie Mae REMIC Trust 2025-203 — structural fixture. "
        "TODO: Extract Exhibit A (decrement tables at 300/400/600 PSA) and "
        "Exhibit B (yield tables) from the offering circular and add as "
        "machine-readable arrays before marking this fixture complete."
    ),
    bonds=[
        BondDef(
            name="PA",
            kind=TrancheKind.PAC,
            coupon=5.50,
            notional=1_000_000.0,
            schedule_model_type=None,
            schedule_contract=pac_schedule_placeholder,
            schedule_tolerance_bps=25,
            relations=[TrancheRelation(
                relation_type=TrancheRelationType.SUPPORTED_BY,
                targets=["WA", "WB"],
            )],
            group_id=None,
        ),
        BondDef(
            name="PB",
            kind=TrancheKind.PAC,
            coupon=5.50,
            notional=500_000.0,
            schedule_model_type=None,
            schedule_contract=[
                {"period": i, "target_balance": max(0.0, 500_000 - i * 1_500)}
                for i in range(1, 334)
            ],
            schedule_tolerance_bps=25,
            relations=[TrancheRelation(
                relation_type=TrancheRelationType.SUPPORTED_BY,
                targets=["WA", "WB"],
            )],
        ),
        BondDef(
            name="Z",
            kind=TrancheKind.Z,
            coupon=5.50,
            notional=200_000.0,
            pay_mode=PayMode.PIK,
            z_accrual_enabled=True,
            relations=[TrancheRelation(
                relation_type=TrancheRelationType.ACCRETES_TO,
                targets=["WA", "WB"],
            )],
        ),
        BondDef(name="WA", kind=TrancheKind.CASH_PAY, coupon=5.50, notional=300_000.0),
        BondDef(name="WB", kind=TrancheKind.CASH_PAY, coupon=5.50, notional=200_000.0),
        BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
    ],
    waterfall_rules=[
        RuleNode(rule_id="int_pac", rule_type=RuleType.PAY_INTEREST, order=0,
                 from_sources=["CASH"], to_targets=["PA", "PB"]),
        RuleNode(rule_id="int_sup", rule_type=RuleType.PAY_INTEREST, order=1,
                 from_sources=["CASH"], to_targets=["WA", "WB"]),
        RuleNode(rule_id="prin_pac", rule_type=RuleType.PAY_PRINCIPAL, order=2,
                 from_sources=["CASH"], to_targets=["PA"]),
        RuleNode(rule_id="prin_pac_b", rule_type=RuleType.PAY_PRINCIPAL, order=3,
                 from_sources=["CASH"], to_targets=["PB"]),
        RuleNode(rule_id="prin_sup", rule_type=RuleType.PAY_PRINCIPAL, order=4,
                 from_sources=["CASH"], to_targets=["WA", "WB"]),
        RuleNode(rule_id="cleanup_pa", rule_type=RuleType.PAY_PRINCIPAL, order=5,
                 from_sources=["CASH"], to_targets=["PA"], cap_mode="NONE"),
        RuleNode(rule_id="cleanup_pb", rule_type=RuleType.PAY_PRINCIPAL, order=6,
                 from_sources=["CASH"], to_targets=["PB"], cap_mode="NONE"),
        RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=7,
                 from_sources=["CASH"], to_targets=["R"]),
    ],
)
