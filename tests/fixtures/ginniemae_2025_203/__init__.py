"""Ginnie Mae REMIC Trust 2025-203 structural fixture.

Source: Ginnie Mae REMIC Trust 2025-203 Offering Circular (February 2025).
CUSIP group: 38378B-XX-X (series).

Structure summary (from waterfall_ir_design.md research, Round 3 May 2026):
  - Confirms the FNR PAC + Z + Support pattern is industry-standard across agencies.
  - "Aggregate Scheduled Principal Balance" abstraction mirrors Fannie's
    "Aggregate Group Planned Balance" for multi-class structures.
  - Single collateral group (plain agency MBS collateral).
  - Classes: PA (PAC I), PB (PAC I), Z (accrual), WA/WB (support).

TODO (Stage 7 / real tie-out):
  - Extract decrement table from prospectus Exhibit A.
  - Extract yield table (300 PSA / 400 PSA / 600 PSA) from Exhibit B.
  - Build ACTUAL repline collateral from Ginnie Mae data file (GN pool).
  - Tie out bond WALs at 300 PSA against prospectus table within 0.01 years.

Structural assertions (current coverage):
  - DealDefinition validates against schema 2.0.
  - PAC schedule cap enforced for PA/PB.
  - Z bond accrues until supports exhausted.
  - Total principal conservation.
"""
from __future__ import annotations

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

# ---------------------------------------------------------------------------
# Structural PAC+Z+Support deal — placeholder face values; actual sizing
# must be verified against the prospectus Exhibit A principal schedule.
# ---------------------------------------------------------------------------

DEAL_CITATION = (
    "Ginnie Mae REMIC Trust 2025-203. "
    "Offering Circular dated February 2025. "
    "Available at https://www.ginniemae.gov/remic/."
)

TODO_TABLE_EXTRACTION = (
    "TODO: Extract Exhibit A (decrement tables at 300/400/600 PSA) and "
    "Exhibit B (yield tables) from the offering circular and add as "
    "machine-readable arrays before marking this fixture complete."
)


def build_gnma_2025_203_deal(n_periods: int = 360) -> DealDefinition:
    """Build a structurally correct GNMA 2025-203 deal definition.

    Face values are placeholders. The waterfall structure (PAC schedule cap,
    Z accrual mechanic, support class priority) matches the offering circular.
    Replace face values with actual Exhibit A figures for quantitative tie-out.
    """
    # Placeholder PAC schedule — replace with Exhibit A decrement table values.
    # TODO: extract actual per-period target balances.
    pac_schedule_placeholder = [
        {"period": i, "target_balance": max(0.0, 1_000_000 - i * 3_000)}
        for i in range(1, min(n_periods + 1, 334))
    ]

    return DealDefinition(
        deal_name="GNMA 2025-203",
        description=(
            "Ginnie Mae REMIC Trust 2025-203 — structural fixture. "
            f"{TODO_TABLE_EXTRACTION}"
        ),
        bonds=[
            BondDef(
                name="PA",
                kind=TrancheKind.PAC,
                coupon=5.50,
                notional=1_000_000.0,  # placeholder — see Exhibit A
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
                notional=500_000.0,  # placeholder
                schedule_model_type=None,
                schedule_contract=[
                    {"period": i, "target_balance": max(0.0, 500_000 - i * 1_500)}
                    for i in range(1, min(n_periods + 1, 334))
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
                notional=200_000.0,  # placeholder
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
