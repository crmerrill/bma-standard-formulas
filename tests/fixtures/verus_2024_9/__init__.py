"""Verus 2024-9 (non-agency Non-QM RMBS) structural fixture.

Source: Verus Securitization Trust 2024-9. Offering Supplement and
Prospectus Supplement, October 2024. CUSIP group: 92538E-XX-X.

Structure summary (from waterfall_ir_design.md research, Round 3 May 2026):
  - Non-QM / Non-Agency RMBS, single pool.
  - Senior tranches (A-1, A-2, A-3) receive interest pro-rata, principal sequential.
  - Mezz (M-1, M-2) and subordinate classes follow sequential principal.
  - Class XS: excess spread strip.
  - Step-up coupon at year 5 (month 61): each class coupon increases by 1.00%.
  - Phase 5 feature: demonstrated by RateOrSchedule coupon field.
  - Standard RMBS: OC test, excess interest, reserve account.

TODO (Stage 7 / real tie-out):
  - Extract payment priority waterfall from Prospectus Supplement Section 8.
  - Extract collateral tape summary (WAC, WAM, WALA, LTV distribution).
  - Extract Class A-1 decrement table at 10 CPR / 20 CPR / 30 CPR.
  - Build representative repline from tape summary.
  - Tie out A-1 WAL within 0.05 years at base assumption.

Phase 5 step-up coupon:
  Modeled via coupon=[{"from_period": 1, "rate": X}, {"from_period": 61, "rate": X+1}].
"""
from __future__ import annotations

from bma_standard_formulas.deals.schemas.common import RuleType, TrancheKind
from bma_standard_formulas.deals.schemas.ir import BondDef, DealDefinition, RuleNode

DEAL_CITATION = (
    "Verus Securitization Trust 2024-9. "
    "Prospectus Supplement dated October 2024."
)

TODO_TABLE_EXTRACTION = (
    "TODO: Extract decrement table (10/20/30 CPR) and Class A-1 yield table "
    "from the offering supplement before marking this fixture complete."
)


def build_verus_2024_9_deal() -> DealDefinition:
    """Structural Verus 2024-9 deal with Phase 5 step-up coupon.

    Face values are placeholders. The step-up coupon (year 5) is correctly
    modeled using RateOrSchedule — this validates Phase 5 with a real-deal example.
    Replace face values with actual tape-derived figures for quantitative tie-out.
    """
    # Step-up coupon example: class A-1 starts at 6.00%, steps to 7.00% at period 61.
    # TODO: Replace 6.00/7.00 with actual Verus 2024-9 coupon rates from the prospectus.
    a1_coupon_schedule = [
        {"from_period": 1, "rate": 6.00},
        {"from_period": 61, "rate": 7.00},
    ]

    return DealDefinition(
        deal_name="Verus 2024-9",
        description=(
            "Verus Securitization Trust 2024-9 — structural fixture with Phase 5 "
            f"step-up coupon. {TODO_TABLE_EXTRACTION}"
        ),
        bonds=[
            BondDef(name="A1", kind=TrancheKind.CASH_PAY,
                    coupon=a1_coupon_schedule, notional=5_000_000.0),
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
