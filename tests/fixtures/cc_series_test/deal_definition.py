"""Canonical deal_definition export for the fixture emitter."""
from bma_standard_formulas.deals.schemas.common import (
    AccountCategory,
    CoverageMode,
    RuleType,
    TrancheKind,
)
from bma_standard_formulas.deals.schemas.ir import (
    AccountDef,
    AccountMinimumScheduleEntry,
    BondDef,
    DealDefinition,
    RuleNode,
)

_n_periods = 24
_pfa_schedule = [
    AccountMinimumScheduleEntry(
        period=p,
        minimum_balance=50_000_000.0 * p / 12,
    )
    for p in range(1, 13)
] + [
    AccountMinimumScheduleEntry(period=p, minimum_balance=50_000_000.0)
    for p in range(13, _n_periods)
]

deal_definition = DealDefinition(
    deal_name="CC Series 2024-A",
    series_id="CC-MASTER-TRUST-2024-A",
    description=(
        "Representative CC master trust single series. "
        "Representative single-series CC master trust (composite model). "
        "TODO: cite specific COMET, Chase, Citi, Discover, or AmEx series supplement."
    ),
    discount_factor_pct=2.0,
    bonds=[
        BondDef(
            name="A",
            kind=TrancheKind.CASH_PAY,
            coupon=6.0,
            notional=500_000_000.0,
            seniority=1,
            required_subordination_pct=20.0,
        ),
        BondDef(
            name="B",
            kind=TrancheKind.CASH_PAY,
            coupon=0.0,
            notional=75_000_000.0,
            nla_starting_balance=75_000_000.0,
            seniority=2,
        ),
        BondDef(
            name="C",
            kind=TrancheKind.CASH_PAY,
            coupon=0.0,
            notional=25_000_000.0,
            nla_starting_balance=25_000_000.0,
            seniority=3,
        ),
        BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
    ],
    accounts=[
        AccountDef(
            name="PFA",
            account_category=AccountCategory.PREFUNDING,
            starting_amount=0.0,
            minimum_schedule=_pfa_schedule,
        ),
        AccountDef(
            name="SPREAD_ACCT",
            account_category=AccountCategory.SPREAD_ACCOUNT,
            starting_amount=5_000_000.0,
        ),
    ],
    waterfall_rules=[
        RuleNode(rule_id="a_int", rule_type=RuleType.PAY_INTEREST, order=0,
                 from_sources=["ACT_INT"], to_targets=["A"]),
        RuleNode(rule_id="pfa_dep", rule_type=RuleType.PAY_TO_ACCOUNT, order=1,
                 from_sources=["ACT_PRIN"], to_targets=["PFA"],
                 max_amount_fixed=5_000_000.0),
        RuleNode(
            rule_id="p_to_i",
            rule_type=RuleType.PAY_INTEREST,
            order=2,
            from_sources=["B"],
            to_targets=["A"],
            coverage_mode=CoverageMode.INTEREST_SHORTFALL,
            max_amount_expr=(
                "A_available_subordination - A_required_subordination "
                "if A_available_subordination > A_required_subordination else 0"
            ),
        ),
        RuleNode(rule_id="reimb_b", rule_type=RuleType.REIMBURSE_NLA, order=3,
                 from_sources=["SPREAD_ACCT"], to_targets=["B"]),
        RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=4,
                 from_sources=["ACT_INT"], to_targets=["R"]),
    ],
)
