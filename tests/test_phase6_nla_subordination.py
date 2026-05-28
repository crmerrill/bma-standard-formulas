"""Phase 6: Nominal Liquidation Amount (NLA), Required/Available Subordination,
and Principal-to-Interest Reallocation — end-to-end tests for credit-card style
master trust mechanics.

Covers:
- NLA depletion when principal is reallocated to cover senior interest
- Required/Available subordination expression variables gate reallocation
- REIMBURSE_NLA restores NLA balance from excess spread
- REIMBURSE_NLA respects nla_starting_balance cap (cannot inflate beyond original)
- REIMBURSE_NLA validator requires bond targets
"""
from __future__ import annotations

import numpy as np
import pytest

from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.common import CoverageMode, RuleType, TrancheKind
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows,
    DealRunInput,
    PooledCollateralInput,
)
from bma_standard_formulas.deals.schemas.ir import (
    AccountDef,
    BondDef,
    DealDefinition,
    RuleNode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _constant_collateral(
    *,
    balance: float,
    monthly_interest: float,
    monthly_principal: float,
    n: int = 10,
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


def _zero_collateral(n: int = 10) -> DealRunInput:
    return _constant_collateral(balance=0.0, monthly_interest=0.0, monthly_principal=0.0, n=n)


# ---------------------------------------------------------------------------
# NLA depletion via P-to-I reallocation
# ---------------------------------------------------------------------------


def test_nla_depletes_when_p_to_i_coverage_draws_from_subordinate():
    """NLA on a subordinate bond (B) is reduced when B's balance funds senior (A) interest."""
    deal = DealDefinition(
        deal_name="PtoIDeplete",
        bonds=[
            BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=12.0, notional=100.0, seniority=1),
            BondDef(name="B", kind=TrancheKind.CASH_PAY, coupon=0.0, notional=50.0,
                    nla_starting_balance=50.0, seniority=2),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        waterfall_rules=[
            RuleNode(rule_id="p_to_i", rule_type=RuleType.PAY_INTEREST, order=0,
                     from_sources=["B"], to_targets=["A"],
                     coverage_mode=CoverageMode.INTEREST_SHORTFALL),
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=1,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    run_input = _zero_collateral(n=8)
    result = run_deal(deal, run_input)

    # Period 1: no prior shortfall — coverage rule pays 0. B NLA unchanged.
    b_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "B" and r.period == 1)
    assert b_p1.end_balance == pytest.approx(50.0, abs=0.01), "B balance unchanged in period 1"

    # Period 2: prior shortfall = 1.0 (A coupon 12%/12 on 100 = 1.0).
    # B's balance is debited 1.0 and B's NLA balance is also debited 1.0.
    b_p2 = next(r for r in result.bond_cashflows if r.tranche_id == "B" and r.period == 2)
    assert b_p2.end_balance == pytest.approx(49.0, abs=0.01), "B balance debited 1.0 per period"
    assert b_p2.nla_balance == pytest.approx(49.0, abs=0.01), (
        "B NLA balance must also be 49.0 after first P-to-I payment"
    )

    # By period 4, B has been debited 3 times (periods 2, 3, 4).
    b_p4 = next(r for r in result.bond_cashflows if r.tranche_id == "B" and r.period == 4)
    assert b_p4.end_balance == pytest.approx(47.0, abs=0.01), "B balance 47.0 at period 4"
    assert b_p4.nla_balance == pytest.approx(47.0, abs=0.01), "B NLA 47.0 at period 4"


# ---------------------------------------------------------------------------
# REIMBURSE_NLA — basic reimbursement from excess spread
# ---------------------------------------------------------------------------


def test_reimburse_nla_credits_nla_balance_from_cash():
    """REIMBURSE_NLA must debit the cash source and credit B's NLA balance."""
    deal = DealDefinition(
        deal_name="ReimburseNLA",
        bonds=[
            BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=12.0, notional=100.0, seniority=1),
            BondDef(name="B", kind=TrancheKind.CASH_PAY, coupon=0.0, notional=50.0,
                    nla_starting_balance=50.0, seniority=2),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        accounts=[AccountDef(name="SPREAD_ACCT", starting_amount=5.0)],
        waterfall_rules=[
            # P-to-I: B funds A interest shortfall (depletes B NLA)
            RuleNode(rule_id="p_to_i", rule_type=RuleType.PAY_INTEREST, order=0,
                     from_sources=["B"], to_targets=["A"],
                     coverage_mode=CoverageMode.INTEREST_SHORTFALL),
            # Reimburse B's NLA from spread account
            RuleNode(rule_id="reimb", rule_type=RuleType.REIMBURSE_NLA, order=1,
                     from_sources=["SPREAD_ACCT"], to_targets=["B"]),
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=2,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    # No collateral cash — NLA reimbursement comes only from SPREAD_ACCT (5.0 initial).
    run_input = _zero_collateral(n=8)
    result = run_deal(deal, run_input)

    # Timeline:
    #  Period 1: A shortfall accrues 1.0 (no source). B unchanged.
    #  Period 2: P-to-I pays 1.0 from B. B.balance=49; B.nla=49.
    #            Reimburse: deficit=1.0, spread=5.0 → reimburse 1.0. B.nla=50. Spread=4.0.
    #  Period 3: same pattern. B.balance=48; B.nla→49→50. Spread=3.0.
    #  ...
    #  Period 6: 5th reimbursement. B.balance=44; B.nla→49→50. Spread=0.0.
    #  Period 7: P-to-I pays 1.0. B.balance=43; B.nla=49. Spread exhausted, no reimburse.

    b_p2 = next(r for r in result.bond_cashflows if r.tranche_id == "B" and r.period == 2)
    assert b_p2.end_balance == pytest.approx(49.0, abs=0.01), "B balance 49 after P-to-I"
    # NLA is restored by reimburse in the same period.
    assert b_p2.nla_balance == pytest.approx(50.0, abs=0.01), (
        "B NLA must be restored to 50.0 after reimburse fires in period 2"
    )

    # Period 7: P-to-I still fires (A shortfall). B.balance = 50 - 5 debits = 44.
    # (Periods 2-6: 5 debits × 1.0 = 5.0 total from B balance).
    # Spread exhausted after period 6; no reimbursement in period 7.
    b_p7 = next(r for r in result.bond_cashflows if r.tranche_id == "B" and r.period == 7)
    assert b_p7.end_balance == pytest.approx(44.0, abs=0.01), "B balance 44 at period 7"
    assert b_p7.nla_balance == pytest.approx(49.0, abs=0.01), (
        "B NLA 49 at period 7 (spread exhausted after period 6, no reimburse)"
    )


def test_reimburse_nla_cannot_exceed_starting_balance():
    """REIMBURSE_NLA must not inflate NLA above the period-0 starting balance."""
    deal = DealDefinition(
        deal_name="NLACap",
        bonds=[
            BondDef(name="B", kind=TrancheKind.CASH_PAY, coupon=0.0, notional=50.0,
                    nla_starting_balance=50.0, seniority=1),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        accounts=[AccountDef(name="SPREAD_ACCT", starting_amount=100.0)],
        waterfall_rules=[
            # Reimburse with large spread — NLA must cap at starting balance.
            RuleNode(rule_id="reimb", rule_type=RuleType.REIMBURSE_NLA, order=0,
                     from_sources=["SPREAD_ACCT"], to_targets=["B"]),
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=1,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    run_input = _constant_collateral(balance=0.0, monthly_interest=0.0, monthly_principal=0.0, n=5)
    result = run_deal(deal, run_input)
    # Period 1: B NLA starts at 50.0 (nla_balance[0]); no depletion has occurred;
    # reimburse deficit = 0 → no cash drawn; NLA stays at 50, spread stays at 100.
    b_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "B" and r.period == 1)
    assert b_p1.end_balance == pytest.approx(50.0, abs=0.01), "B balance must remain 50.0"
    assert b_p1.nla_balance == pytest.approx(50.0, abs=0.01), (
        "B NLA must remain at starting value when no depletion has occurred"
    )


# ---------------------------------------------------------------------------
# REIMBURSE_NLA validator
# ---------------------------------------------------------------------------


def test_reimburse_nla_requires_bond_targets():
    """REIMBURSE_NLA must be rejected if target is an account, not a bond."""
    with pytest.raises(Exception, match="REIMBURSE_NLA targets must be bond names"):
        DealDefinition(
            deal_name="BadReimburse",
            bonds=[
                BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            accounts=[AccountDef(name="SPREAD_ACCT")],
            waterfall_rules=[
                RuleNode(rule_id="bad", rule_type=RuleType.REIMBURSE_NLA, order=0,
                         from_sources=["CASH"], to_targets=["SPREAD_ACCT"]),
                RuleNode(rule_id="r", rule_type=RuleType.PAY_RESIDUAL, order=1,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )


# ---------------------------------------------------------------------------
# Full cycle: P-to-I → subordination cap → reimbursement
# ---------------------------------------------------------------------------


def test_full_cc_cycle_p_to_i_cap_reimbursement():
    """End-to-end credit-card style test:
    1. Finance charge collections (FCC) fund senior A interest.
    2. If FCC insufficient, P-to-I reallocation from B funds shortfall.
    3. P-to-I is capped by (A_available_subordination - A_required_subordination).
    4. Excess spread reimburses B NLA each period.
    """
    # Configuration:
    # A: senior, 12% coupon, 100 face, requires 39.5% subordination (= 39.5 on B NLA ≥ 39.5)
    # B: subordinate, 0% coupon, 50 face, NLA starts at 50
    # Spread account: 2.0/period available for NLA reimbursement
    # Collateral: delivers 0.5/period interest only — not enough to pay A's 1.0 coupon
    deal = DealDefinition(
        deal_name="FullCCCycle",
        bonds=[
            BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=12.0, notional=100.0,
                    seniority=1, required_subordination_pct=39.5),
            BondDef(name="B", kind=TrancheKind.CASH_PAY, coupon=0.0, notional=50.0,
                    nla_starting_balance=50.0, seniority=2),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        accounts=[AccountDef(name="SPREAD_ACCT", starting_amount=20.0)],
        waterfall_rules=[
            # Step 1: Pay A interest from FCC (collateral interest)
            RuleNode(rule_id="fcc_int", rule_type=RuleType.PAY_INTEREST, order=0,
                     from_sources=["ACT_INT"], to_targets=["A"]),
            # Step 2: P-to-I from B (capped by subordination headroom)
            RuleNode(
                rule_id="p_to_i",
                rule_type=RuleType.PAY_INTEREST,
                order=1,
                from_sources=["B"],
                to_targets=["A"],
                coverage_mode=CoverageMode.INTEREST_SHORTFALL,
                max_amount_expr=(
                    "A_available_subordination - A_required_subordination "
                    "if A_available_subordination > A_required_subordination else 0"
                ),
            ),
            # Step 3: Reimburse B NLA from spread
            RuleNode(rule_id="reimb", rule_type=RuleType.REIMBURSE_NLA, order=2,
                     from_sources=["SPREAD_ACCT"], to_targets=["B"]),
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=3,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    # Collateral delivers 0.5 interest/period — not enough to cover A's 1.0 coupon.
    run_input = _constant_collateral(balance=0.0, monthly_interest=0.5, monthly_principal=0.0, n=12)
    result = run_deal(deal, run_input)

    # Period 2 mechanics:
    #   - Accumulated shortfall entering period 2 = 1.0 (period 1: 0 FCC, 0 P-to-I)
    #   - FCC = 0.5 → fcc_int pays 0.5 toward shortfall
    #   - Remaining shortfall = 0.5 → P-to-I from B (headroom = B_nla - A_required = 50 - 39.5 = 10.5 >> 0.5)
    #   - Total interest paid in period 2 = 1.0
    a_p2 = next(r for r in result.bond_cashflows if r.tranche_id == "A" and r.period == 2)
    assert a_p2.interest_paid == pytest.approx(1.0, abs=0.01), (
        f"Period 2: FCC (0.5) + P-to-I (0.5) must pay 1.0 total — got {a_p2.interest_paid:.4f}"
    )

    # Period 2: B balance debited 0.5 (P-to-I); SPREAD_ACCT reimburses 0.5 → B NLA restored.
    b_p2 = next(r for r in result.bond_cashflows if r.tranche_id == "B" and r.period == 2)
    assert b_p2.end_balance == pytest.approx(49.5, abs=0.01), (
        f"B balance should be 49.5 after P-to-I debit — got {b_p2.end_balance:.4f}"
    )
    # B NLA restored by REIMBURSE_NLA (spread reimburses 0.5 deficit).
    assert b_p2.nla_balance == pytest.approx(50.0, abs=0.01), (
        f"B NLA must be restored to 50.0 after reimburse — got {b_p2.nla_balance}"
    )

    # All 11 active periods produce rows.
    a_rows = [r for r in result.bond_cashflows if r.tranche_id == "A" and r.period > 0]
    assert len(a_rows) == 11, "A must have cashflow rows for all 11 active periods"
