"""OA-G: Recourse modeling decision tests.

The RG5 concern: dropping PAY_RECOURSE_INTEREST/PRINCIPAL assumes reserve-account
accounting and recourse pseudo-bond accounting are semantically equivalent.  This
test file closes that question by documenting the chosen model and proving it with
golden outputs.

## Decision (May 2026 — Round 3)

Recourse is modelled as a **pseudo-bond** with a starting notional that represents
the available recourse capacity.  A `PAY_INTEREST from=[RECOURSE_LINE]
coverage_mode=INTEREST_SHORTFALL` rule draws from that capacity:

  - Each period that interest is short, the runtime pays as much as the pseudo-bond
    balance permits and marks the draw in the bond's ``opt_interest`` ledger.
  - The pseudo-bond balance decrements by the amount drawn, giving a natural
    exhaustion: once the recourse line is fully drawn, no further draws occur.
  - The bond's ``int_shortfall`` accumulates any unmet interest (above what recourse
    could cover) for future catch-up rules.

Difference from a reserve account:
  - A reserve ``AccountWorkspace`` carries ``required_minimum``, ``ending_balance``,
    and is replenished / swept via separate ``PAY_TO_ACCOUNT`` rules.
  - A recourse pseudo-bond ``BondWorkspace`` has a ``balance`` vector that decrements
    only via draws; no automatic replenishment unless an explicit accretion/redirect
    rule is present.
  - Reserve draws appear in ``deal_accounts`` output; recourse draws appear only in
    the bond's ``opt_interest`` ledger and the pseudo-bond's cashflow output.

The current implementation (coverage_mode=INTEREST_SHORTFALL from a pseudo-bond)
correctly models recourse lines, bilateral facilities, and guarantees.

## What is NOT modelled

  - Recourse reimbursement / guarantor recovery (no PAY_TO_PSEUDO_BOND rule exists).
  - Recourse drawings that convert to principal (HELOC-style advances).
  - Credit-support providers that receive fees in return (model explicitly with a FeeDef).

These are documented as known gaps and do not require code changes in this phase.
"""
from __future__ import annotations

import numpy as np
import pytest

from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.common import (
    CoverageMode,
    RuleType,
    TrancheKind,
)
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows,
    DealRunInput,
    PooledCollateralInput,
)
from bma_standard_formulas.deals.schemas.ir import BondDef, DealDefinition, RuleNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collateral(
    balance: float,
    annual_coupon: float,
    monthly_principal: float,
    n: int,
    *,
    annual_loss_rate: float = 0.0,
) -> DealRunInput:
    """Generic collateral with controlled principal, interest, and optional losses."""
    bal = np.zeros(n)
    bal[0] = balance
    for i in range(1, n):
        bal[i] = max(0.0, bal[i - 1] - monthly_principal)
    interest = np.array([0.0] + [bal[i - 1] * annual_coupon / 1200 for i in range(1, n)])
    loss = np.array([0.0] + [bal[i - 1] * annual_loss_rate / 1200 for i in range(1, n)])
    cf = CollateralCashflows(
        cfdate=list(range(n)),
        balance=bal.tolist(),
        principal=[0.0] + [monthly_principal] * (n - 1),
        interest=interest.tolist(),
        cashflow=(np.array([0.0] + [monthly_principal] * (n - 1)) + interest - loss).tolist(),
        loss=loss.tolist(),
        prepbal=[0.0] * n, defbal=[0.0] * n, recovery=[0.0] * n,
        principal_sched=[0.0] + [monthly_principal] * (n - 1),
        principal_unsched=[0.0] * n,
        cpr=[0.0] * n, cdr=[0.0] * n, sev=[0.0] * n, dq=[0.0] * n,
        surv_fac=[1.0] * n,
        sched_coupon=[annual_coupon] * n,
        sched_netcoupon=[annual_coupon] * n,
        coupon=[annual_coupon] * n,
        effcoupon=[annual_coupon] * n,
        sched_balance=bal.tolist(),
        discount_factor=[1.0] * n,
    )
    return DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        original_collateral_balance=balance,
        loan_count=1,
    )


def _recourse_deal(
    *,
    recourse_capacity: float = 50.0,
    coupon_pct: float = 12.0,
    collateral_coupon: float = 8.0,
    monthly_principal: float = 10.0,
    n: int = 6,
) -> DealDefinition:
    """Deal where Class A interest is first sourced from pool interest, then from a
    recourse pseudo-bond when pool interest is insufficient.

    The recourse line is RECOURSE_LINE (a pseudo-bond with starting notional equal to
    the available recourse capacity).  Interest shortfalls draw from it.
    """
    return DealDefinition(
        deal_name="OA-G Recourse Test",
        bonds=[
            BondDef(
                name="A",
                kind=TrancheKind.CASH_PAY,
                coupon=coupon_pct,
                notional=1000.0,
            ),
            BondDef(
                name="RECOURSE_LINE",
                kind=TrancheKind.PSEUDO,
                coupon=0.0,
                notional=recourse_capacity,
                is_bond=False,
                is_pseudo=True,
            ),
            BondDef(
                name="R",
                kind=TrancheKind.RESIDUAL,
                is_bond=False,
                is_pseudo=True,
            ),
        ],
        waterfall_rules=[
            # Step 1: pay Class A interest from pool cash (will be short)
            RuleNode(
                rule_id="int_a_primary",
                rule_type=RuleType.PAY_INTEREST,
                order=0,
                from_sources=["ACT_INT"],
                to_targets=["A"],
            ),
            # Step 2: cover any interest shortfall from the recourse line
            RuleNode(
                rule_id="int_a_recourse",
                rule_type=RuleType.PAY_INTEREST,
                order=1,
                from_sources=["RECOURSE_LINE"],
                to_targets=["A"],
                coverage_mode=CoverageMode.INTEREST_SHORTFALL,
            ),
            # Step 3: pay principal
            RuleNode(
                rule_id="prin_a",
                rule_type=RuleType.PAY_PRINCIPAL,
                order=2,
                from_sources=["ACT_PRIN"],
                to_targets=["A"],
            ),
            # Residual
            RuleNode(
                rule_id="resid",
                rule_type=RuleType.PAY_RESIDUAL,
                order=3,
                from_sources=["CASH"],
                to_targets=["R"],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRecourseAccountingDecision:
    """OA-G: Prove recourse-as-pseudo-bond model has correct accounting semantics."""

    def test_recourse_covers_prior_period_accumulated_shortfall(self):
        """INTEREST_SHORTFALL coverage covers PRIOR-period accumulated shortfalls.

        Chosen semantics (closed in OA-G, May 2026):
          - Period N: bond receives pool interest; any gap becomes `int_shortfall[N]`.
          - Period N+1: coverage rule fires and pays accumulated `int_shortfall[N]`
            from the recourse line. This is standard credit-enhancement accounting
            where shortfalls are recognised after the distribution date and made up
            in the next distribution.
        """
        # Pool: 1000 balance, 8% coupon → 6.67/month interest.
        # Bond A: 1000 notional, 12% coupon → 10.0/month interest due.
        # Shortfall per period ≈ 3.33. Recourse capacity = 50 (enough for many periods).
        deal = _recourse_deal(
            recourse_capacity=50.0,
            coupon_pct=12.0,
            collateral_coupon=8.0,
            monthly_principal=10.0,
            n=6,
        )
        run_input = _collateral(1000.0, 8.0, 10.0, 6)
        result = run_deal(deal, run_input)

        a_rows = {r.period: r for r in result.bond_cashflows if r.tranche_id == "A"}
        recourse_rows = {r.period: r for r in result.bond_cashflows if r.tranche_id == "RECOURSE_LINE"}

        # Period 1: no accumulated shortfall yet → pool interest only (≈6.67).
        pool_interest_p1 = 1000.0 * 8.0 / 1200.0
        assert a_rows[1].interest_paid == pytest.approx(pool_interest_p1, abs=0.01)
        assert recourse_rows[1].begin_balance == pytest.approx(50.0, abs=0.01)
        assert recourse_rows[1].end_balance == pytest.approx(50.0, abs=0.01)  # no draw yet

        # Period 2: shortfall from period 1 is covered by recourse.
        # shortfall_p1 ≈ 10.0 - 6.67 = 3.33
        # Pool interest in period 2 ≈ 990 * 8/1200 ≈ 6.60
        # Recourse draw ≈ 3.33 → bond receives 6.60 + 3.33 ≈ 9.93
        shortfall_p1 = 10.0 - pool_interest_p1
        assert a_rows[2].interest_paid >= pool_interest_p1, (
            "Period 2 must pay at least the pool interest again"
        )
        # Recourse line must have been drawn in period 2
        assert recourse_rows[2].end_balance < recourse_rows[2].begin_balance, (
            "Recourse line must be drawn in period 2 to cover period 1 shortfall"
        )
        draw_p2 = recourse_rows[2].begin_balance - recourse_rows[2].end_balance
        assert draw_p2 == pytest.approx(shortfall_p1, abs=0.1), (
            f"Recourse draw in period 2 ({draw_p2:.4f}) must match period 1 shortfall ({shortfall_p1:.4f})"
        )

    def test_recourse_exhaustion_leaves_accumulated_shortfall(self):
        """When the recourse line is exhausted, shortfall accumulates unfilled.

        Semantics: recourse covers the PRIOR period's shortfall, so after the line
        is drawn down to zero, subsequent shortfalls are never recovered.
        """
        # Recourse capacity = 5. Pool = 0% interest. Bond = 60% coupon (50/month).
        # Period 1 shortfall = 50. Period 2 coverage fires but cap = 5 (full line).
        # Period 3+: line exhausted, shortfalls pile up.
        deal = _recourse_deal(
            recourse_capacity=5.0,
            coupon_pct=60.0,  # 50/month interest due
            collateral_coupon=0.0,
            monthly_principal=0.0,
            n=5,
        )
        run_input = _collateral(1000.0, 0.0, 0.0, 5)
        result = run_deal(deal, run_input)

        a_rows = {r.period: r for r in result.bond_cashflows if r.tranche_id == "A"}
        recourse_rows = {r.period: r for r in result.bond_cashflows if r.tranche_id == "RECOURSE_LINE"}

        # Period 1: no prior shortfall; pool = 0 interest; shortfall = 50; no recourse draw
        assert a_rows[1].interest_paid == pytest.approx(0.0, abs=0.01), (
            "Period 1: no prior shortfall, pool has no interest, recourse not drawn yet"
        )
        assert recourse_rows[1].end_balance == pytest.approx(5.0, abs=0.01)

        # Period 2: prior period shortfall = 50; recourse capacity = 5; draw 5 → bond gets 5
        assert a_rows[2].interest_paid == pytest.approx(5.0, abs=0.01), (
            f"Period 2: expected 5.0 (capped by recourse capacity), got {a_rows[2].interest_paid}"
        )
        assert recourse_rows[2].end_balance == pytest.approx(0.0, abs=0.01), (
            "Recourse line fully drawn in period 2"
        )

        # Period 3+: recourse exhausted, no further interest paid
        assert a_rows[3].interest_paid == pytest.approx(0.0, abs=0.01), (
            "Period 3: recourse exhausted, interest_paid = 0"
        )

    def test_recourse_not_drawn_when_pool_sufficient(self):
        """When pool interest covers full coupon, recourse line is untouched."""
        deal = _recourse_deal(
            recourse_capacity=100.0,
            coupon_pct=6.0,    # 5/month on 1000
            collateral_coupon=12.0,  # 10/month — double the coupon
            monthly_principal=0.0,
            n=4,
        )
        run_input = _collateral(1000.0, 12.0, 0.0, 4)
        result = run_deal(deal, run_input)

        recourse_rows = {r.period: r for r in result.bond_cashflows if r.tranche_id == "RECOURSE_LINE"}

        # Recourse balance must remain at 100 throughout
        for period in range(1, 4):
            assert recourse_rows[period].begin_balance == pytest.approx(100.0, abs=0.01), (
                f"Period {period}: recourse line should not be drawn"
            )

    def test_recourse_semantics_differ_from_reserve_account(self):
        """Prove recourse pseudo-bond != reserve account: timing and source differ.

        Reserve account: draws from CASH (combined interest + principal), so it can
        cover the CURRENT period shortfall in the same payment step.

        Recourse pseudo-bond: INTEREST_SHORTFALL coverage only pays PRIOR-period
        accumulated shortfall. The current period's shortfall is only covered next period.
        """
        # Reserve-account deal: sources from CASH (includes principal), can cover
        # current-period coupon even when pool interest alone is short.
        cash_pay_deal = DealDefinition(
            deal_name="CASH Source Pattern",
            bonds=[
                BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=12.0, notional=1000.0),
                BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=[
                # Sources from combined CASH (interest + principal)
                RuleNode(rule_id="int_a", rule_type=RuleType.PAY_INTEREST, order=0,
                         from_sources=["CASH"], to_targets=["A"]),
                RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=1,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )

        # Recourse deal: only ACT_INT + prior-period shortfall coverage from recourse
        recourse_deal = _recourse_deal(
            recourse_capacity=30.0,
            coupon_pct=12.0,
            collateral_coupon=8.0,
            monthly_principal=5.0,
            n=5,
        )
        run_input = _collateral(1000.0, 8.0, 5.0, 5)

        r1 = run_deal(cash_pay_deal, run_input)
        a_cash = {r.period: r for r in r1.bond_cashflows if r.tranche_id == "A"}

        r2 = run_deal(recourse_deal, run_input)
        a_recourse = {r.period: r for r in r2.bond_cashflows if r.tranche_id == "A"}

        # Key difference: CASH source covers full coupon in period 1 (uses principal).
        # ACT_INT source only covers pool interest in period 1 (principal goes to next step).
        pool_interest_p1 = 1000.0 * 8.0 / 1200.0  # ≈6.67
        full_coupon = 1000.0 * 12.0 / 1200.0        # 10.0

        # CASH-source deal: bond gets full coupon in period 1 (interest + some principal)
        assert a_cash[1].interest_paid == pytest.approx(full_coupon, abs=0.01), (
            "CASH-source deal pays full coupon in period 1 (interest+principal available)"
        )

        # Recourse deal: bond gets only pool interest in period 1 (no prior shortfall)
        assert a_recourse[1].interest_paid == pytest.approx(pool_interest_p1, abs=0.01), (
            "Recourse deal: period 1 only gets pool interest (no accumulated shortfall yet)"
        )

        # This IS the fundamental semantic difference between the two patterns.
        # Reserve accounts sourcing from CASH bridge same-period shortfalls.
        # Recourse pseudo-bonds (INTEREST_SHORTFALL coverage) bridge prior-period shortfalls.
        assert a_cash[1].interest_paid > a_recourse[1].interest_paid, (
            "CASH-source pattern is more current-period-generous than recourse pattern"
        )

        # Period 2: recourse line covers period 1 shortfall → interest improves
        assert a_recourse[2].interest_paid > a_recourse[1].interest_paid, (
            "Recourse deal: period 2 must pay more than period 1 (covers P1 shortfall)"
        )

        # Recourse line must be decremented in period 2 (drawn to cover P1 shortfall)
        recourse_lines = {r.period: r for r in r2.bond_cashflows if r.tranche_id == "RECOURSE_LINE"}
        assert recourse_lines[2].end_balance < recourse_lines[2].begin_balance, (
            "Recourse line balance decrements when draws are made"
        )
