"""Ford Credit Auto Owner Trust 2024-C structural fixture.

Source: Ford Credit Auto Owner Trust 2024-C. Prospectus dated
September 2024. CUSIP group: 34531W-XX-X.

Structure summary (from waterfall_ir_design.md research, Round 3 May 2026):
  - Prime auto ABS, single pool (Ford dealer-originated auto loans).
  - Classes A-1 (money market), A-2, A-3, A-4: sequential senior notes.
  - Class B: subordinate.
  - Reserve account: 0.25% of initial pool balance.
  - Interleaved interest/principal: trustee fee → interest → principal
    (named priority principal amounts, target OC build).
  - Capped trustee fee with overflow to later step.

TODO (Stage 7 / real tie-out):
  - Extract Class A-2 through B decrement table (1.0 ABS / 1.5 ABS / 2.0 ABS).
  - Extract yield table from prospectus Exhibit A.
  - Build representative collateral tape (single repline: WAC, WALA, remaining term).
  - Tie out A-2 WAL within 0.05 years at 1.5 ABS base case.
"""
from __future__ import annotations

from bma_standard_formulas.deals.schemas.common import AccountCategory, RuleType, TrancheKind
from bma_standard_formulas.deals.schemas.ir import (
    AccountDef,
    BondDef,
    DealDefinition,
    FeeDef,
    RuleNode,
)

DEAL_CITATION = (
    "Ford Credit Auto Owner Trust 2024-C. "
    "Prospectus dated September 2024."
)


def build_ford_2024_c_deal() -> DealDefinition:
    """Structural Ford 2024-C deal — interleaved interest/principal, reserve account.

    Face values are placeholders. Replace with actual Exhibit A figures.
    """
    return DealDefinition(
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
            BondDef(name="B",  kind=TrancheKind.CASH_PAY, coupon=5.50, notional=50_000_000.0),
            BondDef(name="R",  kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        accounts=[
            AccountDef(
                name="RESERVE",
                account_category=AccountCategory.RESERVE,
                # 0.25% of initial pool balance (~1.45B) = ~3.6M
                starting_amount=3_625_000.0,
            ),
        ],
        fees=[
            FeeDef(
                name="TRUSTEE_FEE",
                basis_type="COLLATERAL_BALANCE",
                rate=0.0025 / 12,  # ~3 bps/month; capped at $375K/year = $31,250/month
                frequency="MONTHLY",
            ),
        ],
        waterfall_rules=[
            # Auto ABS waterfall: trustee fee → interest (all classes) → principal (sequential)
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
