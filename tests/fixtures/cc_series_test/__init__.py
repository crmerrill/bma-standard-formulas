"""Credit card master trust single-series structural fixture.

Representative of the single-series CC master trust model described in
waterfall_ir_design.md Phase 8 (May 2026). Based on the composite research
across COMET (Citibank), Chase Issuance Trust, Capital One, and Discover
covered in Round 3 (May 2026, see 'Credit card master trusts' section).

This fixture represents Series 2024-A of a hypothetical master trust.
It exercises all Phase 6-8 mechanics:
  - NLA tracking (Class B subordinate)
  - P-to-I reallocation gated by subordination
  - REIMBURSE_NLA from excess spread
  - Discount Option (DealDefinition.discount_factor_pct)
  - Principal Funding Account (AccountDef.minimum_schedule)
  - series_id metadata

Pre-allocated collateral model:
  The collateral input to run_deal represents the series' PRE-ALLOCATED share
  of master trust FCC and principal (as computed by the external TrustOrchestrator).
  See waterfall_ir_design.md Phase 8 for the architectural boundary.

TODO (Stage 7 / real tie-out):
  - Identify a specific single-series issuance (e.g., COMET 2024-A4).
  - Obtain the Series Supplement from SEC EDGAR.
  - Extract: invested amount, Class A/B/C subordination percentages,
    Required Subordinated Amount ratios, excess spread floor.
  - Replace placeholder face values with actual Supplement figures.
  - Tie out Class A interest payment in period 1 against published coupon.
"""
from __future__ import annotations

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

DEAL_CITATION = (
    "Representative single-series CC master trust (composite model). "
    "TODO: cite specific COMET, Chase, Citi, Discover, or AmEx series supplement."
)


def build_cc_series_2024_a_deal(n_periods: int = 24) -> DealDefinition:
    """Build a representative single-series CC master trust deal.

    All face values are structural placeholders. The waterfall structure
    correctly models FCC → interest, P-to-I shortfall coverage, NLA tracking,
    REIMBURSE_NLA, and PFA accumulation.
    """
    pfa_schedule = [
        AccountMinimumScheduleEntry(
            period=p,
            minimum_balance=50_000_000.0 * p / 12  # ramp over 12 months
        )
        for p in range(1, 13)
    ] + [
        AccountMinimumScheduleEntry(period=p, minimum_balance=50_000_000.0)
        for p in range(13, n_periods)
    ]

    return DealDefinition(
        deal_name="CC Series 2024-A",
        series_id="CC-MASTER-TRUST-2024-A",
        description=(
            "Representative CC master trust single series. "
            f"{DEAL_CITATION}"
        ),
        # 2% discount option: reclassifies 2% of principal as FCC.
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
                minimum_schedule=pfa_schedule,
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
