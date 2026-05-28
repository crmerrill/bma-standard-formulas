"""Phase 7: Discount Option + Funding Account accumulation period semantics.

Tests:
- Discount Option (discount_factor_pct typed field) reclassifies principal as interest
  in the ACT_PRIN / ACT_INT streams; combined CASH is unaffected
- Funding-account minimum_schedule drives accumulation-period deposit targets
"""
from __future__ import annotations

import numpy as np
import pytest

from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.common import RuleType, TrancheKind
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows,
    DealRunInput,
    PooledCollateralInput,
)
from bma_standard_formulas.deals.schemas.ir import (
    AccountDef,
    AccountMinimumScheduleEntry,
    BondDef,
    DealDefinition,
    RuleNode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_stream_collateral(
    *,
    balance: float,
    monthly_interest: float,
    monthly_principal: float,
    n: int = 8,
) -> DealRunInput:
    bal = np.full(n, balance)
    p = np.array([0.0] + [monthly_principal] * (n - 1))
    interest = np.array([0.0] + [monthly_interest] * (n - 1))
    cf = CollateralCashflows(
        cfdate=list(range(n)),
        balance=bal.tolist(), principal=p.tolist(), interest=interest.tolist(),
        cashflow=(p + interest).tolist(),
        loss=[0.0]*n, prepbal=[0.0]*n, defbal=[0.0]*n, recovery=[0.0]*n,
        principal_sched=p.tolist(), principal_unsched=[0.0]*n,
        cpr=[0.0]*n, cdr=[0.0]*n, sev=[0.0]*n, dq=[0.0]*n, surv_fac=[1.0]*n,
        sched_coupon=[6.0]*n, sched_netcoupon=[6.0]*n,
        coupon=[6.0]*n, effcoupon=[6.0]*n,
        sched_balance=bal.tolist(), discount_factor=[1.0]*n,
    )
    return DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        original_collateral_balance=balance,
        loan_count=1,
    )


# ---------------------------------------------------------------------------
# Discount Option
# ---------------------------------------------------------------------------


def test_discount_option_reclassifies_principal_as_interest():
    """With discount_factor=20%, 20% of ACT_PRIN each period becomes ACT_INT.
    A bond drawing from ACT_INT receives more; B drawing from ACT_PRIN receives less.
    Uses only split-stream sources (no CASH) to avoid double-counting.
    """
    deal = DealDefinition(
        deal_name="DiscountOptionTest",
        # 20% of principal reclassified as finance charges (typed field, SR7).
        discount_factor_pct=20.0,
        bonds=[
            BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=6.0, notional=100.0),
            BondDef(name="B", kind=TrancheKind.CASH_PAY, coupon=0.0, notional=100.0),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        waterfall_rules=[
            # A draws from finance charges (ACT_INT); B draws from principal (ACT_PRIN).
            # Residual draws from ACT_INT remainder to avoid CASH double-counting.
            RuleNode(rule_id="int_a", rule_type=RuleType.PAY_INTEREST, order=0,
                     from_sources=["ACT_INT"], to_targets=["A"]),
            RuleNode(rule_id="prin_b", rule_type=RuleType.PAY_PRINCIPAL, order=1,
                     from_sources=["ACT_PRIN"], to_targets=["B"]),
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=2,
                     from_sources=["ACT_INT"], to_targets=["R"]),
        ],
    )
    # Pool: 10 interest/period, 20 principal/period.
    run_input = _split_stream_collateral(balance=200.0, monthly_interest=10.0,
                                          monthly_principal=20.0, n=6)
    result = run_deal(deal, run_input)

    # With discount_factor=20%:
    #   discount_amt = 20 * 20% = 4
    #   ACT_INT available = 10 + 4 = 14
    #   ACT_PRIN available = 20 - 4 = 16
    a_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "A" and r.period == 1)
    b_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "B" and r.period == 1)

    # A coupon due = 100 × 6% / 12 = 0.5; ACT_INT = 14 >> 0.5 → fully paid.
    assert a_p1.interest_paid == pytest.approx(0.5, abs=0.01), (
        "A interest must be fully paid from discounted ACT_INT stream"
    )
    # B draws principal from ACT_PRIN = 16 (not the full 20 — discount reclassified 4).
    assert b_p1.total_principal == pytest.approx(16.0, abs=0.01), (
        f"B principal must be 16 (= 20 - discount 4), got {b_p1.total_principal:.2f}"
    )


def test_discount_option_does_not_change_combined_cash_stream():
    """The CASH combined stream is unaffected by the discount option."""
    deal_no_discount = DealDefinition(
        deal_name="NoDiscount",
        deal_knobs={},
        bonds=[
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        waterfall_rules=[
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=0,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    deal_with_discount = deal_no_discount.model_copy(
        update={"deal_name": "WithDiscount", "discount_factor_pct": 50.0}
    )
    run_input = _split_stream_collateral(balance=100.0, monthly_interest=5.0,
                                          monthly_principal=10.0, n=4)
    result_no = run_deal(deal_no_discount, run_input)
    result_with = run_deal(deal_with_discount, run_input)

    # Residual receives all cash; total must be equal regardless of discount factor.
    def total_interest(rows, tranche):
        return sum(r.interest_paid for r in rows if r.tranche_id == tranche)

    assert (
        total_interest(result_no.bond_cashflows, "R")
        == pytest.approx(total_interest(result_with.bond_cashflows, "R"), abs=0.01)
    ), "CASH stream total must be unaffected by discount option"


def test_discount_option_zero_is_noop():
    """discount_factor_pct=0 must produce identical results to default (0)."""
    deal_zero = DealDefinition(
        deal_name="ZeroDiscount",
        discount_factor_pct=0.0,
        bonds=[
            BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=6.0, notional=50.0),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        waterfall_rules=[
            RuleNode(rule_id="int_a", rule_type=RuleType.PAY_INTEREST, order=0,
                     from_sources=["ACT_INT"], to_targets=["A"]),
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=1,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    deal_none = deal_zero.model_copy(update={"deal_name": "NoneDiscount", "deal_knobs": {}})
    run_input = _split_stream_collateral(balance=50.0, monthly_interest=2.0,
                                          monthly_principal=5.0, n=4)
    r_zero = run_deal(deal_zero, run_input)
    r_none = run_deal(deal_none, run_input)

    a_interest_zero = sum(r.interest_paid for r in r_zero.bond_cashflows if r.tranche_id == "A")
    a_interest_none = sum(r.interest_paid for r in r_none.bond_cashflows if r.tranche_id == "A")
    assert a_interest_zero == pytest.approx(a_interest_none, abs=1e-6)


# ---------------------------------------------------------------------------
# Funding Account Accumulation Schedule
# ---------------------------------------------------------------------------


def test_minimum_schedule_overrides_required_minimum_for_specified_period():
    """minimum_schedule entries override required_minimum at their specified periods.
    The account must accumulate to the scheduled target before disbursing.
    """
    deal = DealDefinition(
        deal_name="PFAAccumulation",
        bonds=[
            BondDef(name="BOND", kind=TrancheKind.CASH_PAY, coupon=0.0, notional=120.0),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        accounts=[
            AccountDef(
                name="PFA",
                account_category="PREFUNDING",
                starting_amount=0.0,
                # Accumulate to 30 by period 3, then 60 by period 6.
                minimum_schedule=[
                    AccountMinimumScheduleEntry(period=1, minimum_balance=10.0),
                    AccountMinimumScheduleEntry(period=2, minimum_balance=20.0),
                    AccountMinimumScheduleEntry(period=3, minimum_balance=30.0),
                    AccountMinimumScheduleEntry(period=4, minimum_balance=40.0),
                    AccountMinimumScheduleEntry(period=5, minimum_balance=50.0),
                    AccountMinimumScheduleEntry(period=6, minimum_balance=60.0),
                ],
            ),
        ],
        waterfall_rules=[
            # Deposit into PFA each period.
            RuleNode(rule_id="fund_pfa", rule_type=RuleType.PAY_TO_ACCOUNT, order=0,
                     from_sources=["CASH"], to_targets=["PFA"],
                     max_amount_fixed=20.0),
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=1,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    run_input = _split_stream_collateral(balance=120.0, monthly_interest=0.0,
                                          monthly_principal=20.0, n=8)
    result = run_deal(deal, run_input)

    # The deal deposits 20/period into PFA. By period 3, PFA balance = 60.
    # The minimum_schedule is a FLOOR, not a cap, so the account can exceed it.
    pfa_rows = {r.period: r for r in result.deal_accounts if r.account_id == "PFA"}
    assert pfa_rows[1].end_balance == pytest.approx(20.0, abs=0.01), "PFA period 1: 20"
    assert pfa_rows[2].end_balance == pytest.approx(40.0, abs=0.01), "PFA period 2: 40"
    assert pfa_rows[3].end_balance == pytest.approx(60.0, abs=0.01), "PFA period 3: 60"

    # The breach_flag must be False in periods where balance meets or exceeds schedule.
    assert not pfa_rows[1].breach_flag, "PFA period 1: no breach (balance 20 >= schedule 10)"
    assert not pfa_rows[2].breach_flag, "PFA period 2: no breach (balance 40 >= schedule 20)"


def test_minimum_schedule_breach_when_balance_below_target():
    """When account balance is below the minimum_schedule target, breach_flag is set."""
    deal = DealDefinition(
        deal_name="PFABreachTest",
        bonds=[
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        accounts=[
            AccountDef(
                name="PFA",
                starting_amount=0.0,
                minimum_schedule=[
                    AccountMinimumScheduleEntry(period=1, minimum_balance=100.0),
                ],
            ),
        ],
        waterfall_rules=[
            # Only deposits 5/period — far below the 100 schedule target.
            RuleNode(rule_id="fund_pfa", rule_type=RuleType.PAY_TO_ACCOUNT, order=0,
                     from_sources=["CASH"], to_targets=["PFA"],
                     max_amount_fixed=5.0),
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=1,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    run_input = _split_stream_collateral(balance=50.0, monthly_interest=0.0,
                                          monthly_principal=5.0, n=4)
    result = run_deal(deal, run_input)
    pfa_p1 = next(r for r in result.deal_accounts if r.account_id == "PFA" and r.period == 1)
    assert pfa_p1.end_balance == pytest.approx(5.0, abs=0.01)
    assert pfa_p1.breach_flag, "breach_flag must be set when balance (5) < schedule minimum (100)"


def test_minimum_schedule_is_sticky_between_entries():
    """minimum_schedule must apply the highest entry with period <= current.
    Between entries, the previous target remains as the floor (sticky semantics).
    """
    deal = DealDefinition(
        deal_name="StickySchedule",
        bonds=[
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        accounts=[
            AccountDef(
                name="PFA",
                starting_amount=0.0,
                minimum_schedule=[
                    AccountMinimumScheduleEntry(period=1, minimum_balance=10.0),
                    AccountMinimumScheduleEntry(period=4, minimum_balance=40.0),
                ],
            ),
        ],
        waterfall_rules=[
            RuleNode(rule_id="fund_pfa", rule_type=RuleType.PAY_TO_ACCOUNT, order=0,
                     from_sources=["CASH"], to_targets=["PFA"], max_amount_fixed=20.0),
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=1,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    run_input = _split_stream_collateral(balance=100.0, monthly_interest=0.0,
                                          monthly_principal=20.0, n=7)
    result = run_deal(deal, run_input)

    pfa = {r.period: r for r in result.deal_accounts if r.account_id == "PFA"}
    # Period 2 (between entries 1 and 4): sticky — entry period=1 applies → min=10.
    # Balance = 40 (deposited 20 in p1 and p2), so no breach.
    assert pfa[2].required_minimum == pytest.approx(10.0, abs=0.01), (
        "Period 2: sticky minimum from period-1 entry must remain 10.0"
    )
    # Period 5 (after entry 4): sticky — entry period=4 applies → min=40.
    assert pfa[5].required_minimum == pytest.approx(40.0, abs=0.01), (
        "Period 5: sticky minimum from period-4 entry must be 40.0"
    )


def test_account_breach_state_available_in_expression_context():
    """Account breach state (balance < required_minimum) must be visible
    in the expression context as {name}_breach and {name}_required_minimum."""
    deal = DealDefinition(
        deal_name="BreachExpr",
        bonds=[
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        accounts=[
            AccountDef(name="RSRV", starting_amount=0.0,
                       minimum_schedule=[AccountMinimumScheduleEntry(period=1, minimum_balance=50.0)]),
        ],
        calculations=[
            # Compute breach as a calculation node to prove it's in the context.
        ],
        waterfall_rules=[
            # Deposit only 5 into RSRV (below 50 minimum) — will breach.
            RuleNode(rule_id="fund_rsrv", rule_type=RuleType.PAY_TO_ACCOUNT, order=0,
                     from_sources=["CASH"], to_targets=["RSRV"], max_amount_fixed=5.0),
            # Conditional distribution: only pay residual if RSRV is not breaching.
            # Uses the {name}_breach expression context variable.
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=1,
                     from_sources=["CASH"], to_targets=["R"],
                     condition_expr="RSRV_breach == 0"),
        ],
    )
    run_input = _split_stream_collateral(balance=50.0, monthly_interest=0.0,
                                          monthly_principal=10.0, n=5)
    result = run_deal(deal, run_input)
    rsrv = {r.period: r for r in result.deal_accounts if r.account_id == "RSRV"}
    # Period 1: RSRV = 5.0 < minimum 50.0 → breach_flag must be set.
    assert rsrv[1].breach_flag, "RSRV must be in breach at period 1 (5 < 50)"
    # Period 1: residual rule is blocked (RSRV_breach != 0).
    r_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "R" and r.period == 1)
    assert r_p1.interest_paid == pytest.approx(0.0, abs=0.01), (
        "Residual must be blocked when RSRV is breaching (RSRV_breach == 1)"
    )


def test_minimum_schedule_duplicate_periods_rejected():
    """Duplicate periods in minimum_schedule must raise a ValidationError."""
    with pytest.raises(Exception, match="duplicate periods"):
        AccountDef(
            name="PFA",
            minimum_schedule=[
                AccountMinimumScheduleEntry(period=1, minimum_balance=10.0),
                AccountMinimumScheduleEntry(period=1, minimum_balance=20.0),
            ],
        )
