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
from bma_standard_formulas.deals.schemas.ir import BondDef, DealDefinition, RuleNode


def _flat_collateral(
    *,
    initial_balance: float,
    annual_coupon: float,
    n_periods: int,
) -> DealRunInput:
    bal = np.zeros(n_periods)
    principal = np.zeros(n_periods)
    interest = np.zeros(n_periods)
    bal[0] = initial_balance
    for i in range(1, n_periods):
        interest[i] = bal[i - 1] * annual_coupon / 1200.0
        bal[i] = bal[i - 1]
    cf = CollateralCashflows(
        cfdate=list(range(n_periods)),
        balance=bal.tolist(),
        principal=principal.tolist(),
        interest=interest.tolist(),
        cashflow=(principal + interest).tolist(),
        loss=[0.0] * n_periods,
        prepbal=[0.0] * n_periods,
        defbal=[0.0] * n_periods,
        recovery=[0.0] * n_periods,
        principal_sched=principal.tolist(),
        principal_unsched=[0.0] * n_periods,
        cpr=[0.0] * n_periods,
        cdr=[0.0] * n_periods,
        sev=[0.0] * n_periods,
        dq=[0.0] * n_periods,
        surv_fac=[1.0] * n_periods,
        sched_coupon=[annual_coupon] * n_periods,
        sched_netcoupon=[annual_coupon] * n_periods,
        coupon=[annual_coupon] * n_periods,
        effcoupon=[annual_coupon] * n_periods,
        sched_balance=bal.tolist(),
        discount_factor=[1.0] * n_periods,
    )
    return DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        original_collateral_balance=initial_balance,
        loan_count=1,
    )


def test_step_up_coupon_schedule_changes_runtime_interest_due():
    deal = DealDefinition(
        deal_name="StepUpCoupon",
        bonds=[
            BondDef(
                name="A",
                kind=TrancheKind.CASH_PAY,
                notional=100.0,
                coupon=[
                    {"from_period": 1, "rate": 6.0},
                    {"from_period": 3, "rate": 12.0},
                ],
            ),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        waterfall_rules=[
            RuleNode(
                rule_id="int_a",
                rule_type=RuleType.PAY_INTEREST,
                order=0,
                from_sources=["CASH"],
                to_targets=["A"],
            ),
            RuleNode(
                rule_id="resid",
                rule_type=RuleType.PAY_RESIDUAL,
                order=1,
                from_sources=["CASH"],
                to_targets=["R"],
            ),
        ],
    )
    run_input = _flat_collateral(initial_balance=100.0, annual_coupon=200.0, n_periods=6)
    result = run_deal(deal, run_input)

    rows = {
        row.period: row
        for row in result.bond_cashflows
        if row.tranche_id == "A"
    }
    # Period 1-2: 6% coupon on 100 face -> 0.5 monthly.
    assert rows[1].interest_paid == pytest.approx(0.5, abs=1e-6)
    assert rows[2].interest_paid == pytest.approx(0.5, abs=1e-6)
    # Period 3 onward: 12% coupon on 100 face -> 1.0 monthly.
    assert rows[3].interest_paid == pytest.approx(1.0, abs=1e-6)
    assert rows[4].interest_paid == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# SR4: Floating-rate margin, cap, and floor as RateOrSchedule
# ---------------------------------------------------------------------------

from bma_standard_formulas.deals.schemas.common import CouponType  # noqa: E402


def _floating_deal(
    *,
    margin,
    cap=None,
    floor=None,
    index_rate: float = 5.0,
    notional: float = 1200.0,
    n_periods: int = 6,
) -> tuple["DealDefinition", "DealRunInput"]:
    """Build a floating-rate deal with the given margin/cap/floor (scalar or schedule)."""
    from bma_standard_formulas.deals.schemas.ir import BondDef, DealDefinition, RuleNode  # noqa: F811

    deal = DealDefinition(
        deal_name="FloatingTest",
        deal_knobs={"index_rate": index_rate},
        bonds=[
            BondDef(
                name="F",
                kind=TrancheKind.CASH_PAY,
                coupon_type=CouponType.FLOATING,
                notional=notional,
                margin=margin,
                cap=cap,
                floor=floor,
                index_name="index_rate",
            ),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        waterfall_rules=[
            RuleNode(rule_id="int_f", rule_type=RuleType.PAY_INTEREST, order=0,
                     from_sources=["CASH"], to_targets=["F"]),
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=1,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    run_input = _flat_collateral(initial_balance=notional, annual_coupon=200.0, n_periods=n_periods)
    return deal, run_input


def test_floating_scalar_margin():
    """FLOATING bond with scalar margin = index + margin each period."""
    deal, run_input = _floating_deal(margin=1.5, index_rate=5.0, n_periods=4)
    result = run_deal(deal, run_input)
    rows = {r.period: r for r in result.bond_cashflows if r.tranche_id == "F"}
    # coupon = 5.0 + 1.5 = 6.5% annual → 6.5/1200 × 1200 = 6.5 monthly
    for p in range(1, 4):
        assert rows[p].interest_paid == pytest.approx(6.5, abs=1e-4), (
            f"Period {p}: expected 6.5, got {rows[p].interest_paid}"
        )


def test_floating_margin_step_up_schedule():
    """FLOATING bond: margin schedule steps up at period 3 (e.g. Verus-style)."""
    deal, run_input = _floating_deal(
        margin=[{"from_period": 1, "rate": 1.0}, {"from_period": 3, "rate": 2.0}],
        index_rate=5.0,
        n_periods=6,
    )
    result = run_deal(deal, run_input)
    rows = {r.period: r for r in result.bond_cashflows if r.tranche_id == "F"}
    # Periods 1-2: 5.0 + 1.0 = 6.0% → 6.0 monthly on 1200 face
    assert rows[1].interest_paid == pytest.approx(6.0, abs=1e-4)
    assert rows[2].interest_paid == pytest.approx(6.0, abs=1e-4)
    # Periods 3-5: 5.0 + 2.0 = 7.0% → 7.0 monthly
    assert rows[3].interest_paid == pytest.approx(7.0, abs=1e-4)
    assert rows[5].interest_paid == pytest.approx(7.0, abs=1e-4)


def test_floating_scalar_cap_binds():
    """FLOATING bond: scalar cap limits rate when index + margin would exceed it."""
    # index=8, margin=2 → uncapped would be 10%; cap at 8.0% should bind.
    deal, run_input = _floating_deal(margin=2.0, cap=8.0, index_rate=8.0, n_periods=4)
    result = run_deal(deal, run_input)
    rows = {r.period: r for r in result.bond_cashflows if r.tranche_id == "F"}
    # Cap 8.0% → 8.0 monthly on 1200 face
    for p in range(1, 4):
        assert rows[p].interest_paid == pytest.approx(8.0, abs=1e-4), (
            f"Period {p}: cap should bind at 8.0, got {rows[p].interest_paid}"
        )


def test_floating_scheduled_cap_relaxes_then_tightens():
    """FLOATING bond: cap schedule — tight in P1-2, relaxed in P3+."""
    # index=6, margin=2 → uncapped rate = 8%.
    # Cap: P1-2 = 7.0 (binds), P3+ = 9.0 (does not bind).
    deal, run_input = _floating_deal(
        margin=2.0,
        cap=[{"from_period": 1, "rate": 7.0}, {"from_period": 3, "rate": 9.0}],
        index_rate=6.0,
        n_periods=5,
    )
    result = run_deal(deal, run_input)
    rows = {r.period: r for r in result.bond_cashflows if r.tranche_id == "F"}
    # P1-2: cap binds at 7.0 → 7.0 monthly
    assert rows[1].interest_paid == pytest.approx(7.0, abs=1e-4)
    assert rows[2].interest_paid == pytest.approx(7.0, abs=1e-4)
    # P3+: cap 9.0 does not bind; actual rate = 8.0 → 8.0 monthly
    assert rows[3].interest_paid == pytest.approx(8.0, abs=1e-4)
    assert rows[4].interest_paid == pytest.approx(8.0, abs=1e-4)


def test_floating_scalar_floor_binds():
    """FLOATING bond: scalar floor provides minimum rate when index collapses."""
    # index=1, margin=0.5 → 1.5% uncapped; floor at 4.0% should bind.
    deal, run_input = _floating_deal(margin=0.5, floor=4.0, index_rate=1.0, n_periods=4)
    result = run_deal(deal, run_input)
    rows = {r.period: r for r in result.bond_cashflows if r.tranche_id == "F"}
    for p in range(1, 4):
        assert rows[p].interest_paid == pytest.approx(4.0, abs=1e-4), (
            f"Period {p}: floor should bind at 4.0, got {rows[p].interest_paid}"
        )


def test_floating_backward_compat_scalar_coupon_zero():
    """Backward-compat: FLOATING bond with scalar margin=0 and no cap/floor."""
    # index=5, margin=0 → flat 5% coupon each period.
    deal, run_input = _floating_deal(margin=0.0, index_rate=5.0, n_periods=3)
    result = run_deal(deal, run_input)
    rows = {r.period: r for r in result.bond_cashflows if r.tranche_id == "F"}
    for p in range(1, 3):
        assert rows[p].interest_paid == pytest.approx(5.0, abs=1e-4)

