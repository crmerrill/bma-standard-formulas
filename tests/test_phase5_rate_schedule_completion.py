"""Phase 5 completion tests: RateOrSchedule for margin/cap/floor runtime,
floating-rate path, and zero coupon.

Extends test_coupon_schedule.py (fixed step-up coupons) to cover:
- Floating-rate bonds with SOFR index (via deal_knobs)
- Inverse floater coupon formula (cap - index + margin)
- Cap and floor applied to step-up schedule
- Zero-coupon bonds
- Margin as RateOrSchedule (step-up spread)
"""
from __future__ import annotations

import numpy as np
import pytest

from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.common import CouponType, RuleType, TrancheKind
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows,
    DealRunInput,
    PooledCollateralInput,
)
from bma_standard_formulas.deals.schemas.ir import BondDef, DealDefinition, RuleNode

TOL = 1e-4


def _flat_collateral(initial_balance: float, n: int = 8) -> DealRunInput:
    bal = np.full(n, initial_balance)
    interest = np.array([0.0] + [initial_balance * 10.0 / 1200] * (n - 1))  # 10% WAC
    p = np.zeros(n)
    cf = CollateralCashflows(
        cfdate=list(range(n)),
        balance=bal.tolist(), principal=p.tolist(), interest=interest.tolist(),
        cashflow=(p + interest).tolist(),
        loss=[0.0]*n, prepbal=[0.0]*n, defbal=[0.0]*n, recovery=[0.0]*n,
        principal_sched=p.tolist(), principal_unsched=[0.0]*n,
        cpr=[0.0]*n, cdr=[0.0]*n, sev=[0.0]*n, dq=[0.0]*n, surv_fac=[1.0]*n,
        sched_coupon=[10.0]*n, sched_netcoupon=[10.0]*n, coupon=[10.0]*n, effcoupon=[10.0]*n,
        sched_balance=bal.tolist(), discount_factor=[1.0]*n,
    )
    return DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        original_collateral_balance=initial_balance,
        loan_count=1,
    )


def _simple_deal(bonds, deal_knobs=None) -> DealDefinition:
    return DealDefinition(
        deal_name="P5Test",
        deal_knobs=deal_knobs or {},
        bonds=bonds + [BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True)],
        waterfall_rules=[
            RuleNode(rule_id="int", rule_type=RuleType.PAY_INTEREST, order=0,
                     from_sources=["CASH"], to_targets=[b.name for b in bonds]),
            RuleNode(rule_id="r", rule_type=RuleType.PAY_RESIDUAL, order=1,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )


def _row(result, tranche_id: str, period: int):
    return next(r for r in result.bond_cashflows if r.tranche_id == tranche_id and r.period == period)


# ---------------------------------------------------------------------------
# Zero coupon
# ---------------------------------------------------------------------------


def test_zero_coupon_bond_receives_no_interest():
    deal = _simple_deal([
        BondDef(name="PO", kind=TrancheKind.PO, coupon_type=CouponType.ZERO,
                notional=100.0, coupon=None),
    ])
    result = run_deal(deal, _flat_collateral(100.0))
    for p in range(1, 8):
        assert _row(result, "PO", p).interest_paid == pytest.approx(0.0, abs=TOL), \
            f"ZERO bond must receive no interest at period {p}"


# ---------------------------------------------------------------------------
# Floating-rate coupon via deal_knobs index rate
# ---------------------------------------------------------------------------


def test_floating_rate_bond_uses_index_plus_margin():
    """Floating bond: coupon = SOFR + margin (each period, using deal_knobs)."""
    # SOFR = 5.25%, margin = 1.50% → net coupon = 6.75% on 100 notional.
    deal = _simple_deal(
        bonds=[BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon_type=CouponType.FLOATING,
                       index_name="SOFR", margin=1.50, coupon=None, notional=100.0)],
        deal_knobs={"SOFR_rate": 5.25},
    )
    result = run_deal(deal, _flat_collateral(100.0))
    expected_monthly = 100.0 * 6.75 / 1200.0  # 0.5625
    assert _row(result, "A", 1).interest_paid == pytest.approx(expected_monthly, abs=0.01)


def test_floating_rate_with_generic_index_rate():
    """Floating bond: falls back to deal_knobs['index_rate'] when named key absent."""
    deal = _simple_deal(
        bonds=[BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon_type=CouponType.FLOATING,
                       index_name="LIBOR_1M", margin=0.50, coupon=None, notional=100.0)],
        deal_knobs={"index_rate": 4.00},  # generic fallback
    )
    result = run_deal(deal, _flat_collateral(100.0))
    expected_monthly = 100.0 * 4.50 / 1200.0  # (4.0 + 0.5) / 12
    assert _row(result, "A", 1).interest_paid == pytest.approx(expected_monthly, abs=0.01)


def test_floating_rate_margin_step_up_schedule():
    """Floating bond with step-up margin (RateOrSchedule): margin changes at period 3."""
    deal = _simple_deal(
        bonds=[BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon_type=CouponType.FLOATING,
                       index_name="SOFR", notional=100.0,
                       margin=[{"from_period": 1, "rate": 1.0},
                               {"from_period": 3, "rate": 2.0}],
                       coupon=None)],
        deal_knobs={"SOFR_rate": 5.0},
    )
    result = run_deal(deal, _flat_collateral(100.0))
    # Periods 1-2: SOFR(5.0) + margin(1.0) = 6.0% → 0.50/month
    assert _row(result, "A", 1).interest_paid == pytest.approx(100.0 * 6.0 / 1200, abs=0.01)
    assert _row(result, "A", 2).interest_paid == pytest.approx(100.0 * 6.0 / 1200, abs=0.01)
    # Period 3+: SOFR(5.0) + margin(2.0) = 7.0% → 0.583/month
    assert _row(result, "A", 3).interest_paid == pytest.approx(100.0 * 7.0 / 1200, abs=0.01)


# ---------------------------------------------------------------------------
# Cap and floor as RateOrSchedule
# ---------------------------------------------------------------------------


def test_fixed_coupon_with_cap():
    """Fixed bond with step-up coupon capped by a scalar cap."""
    deal = _simple_deal([
        BondDef(name="A", kind=TrancheKind.CASH_PAY, notional=100.0,
                coupon=[{"from_period": 1, "rate": 5.0},
                        {"from_period": 3, "rate": 9.0}],  # step-up
                cap=7.0),  # cap at 7%
    ])
    result = run_deal(deal, _flat_collateral(100.0))
    # Periods 1-2: coupon=5.0 < cap=7.0 → full 5.0%
    assert _row(result, "A", 1).interest_paid == pytest.approx(100.0 * 5.0 / 1200, abs=0.01)
    # Periods 3+: coupon=9.0 but cap=7.0 → 7.0%
    assert _row(result, "A", 3).interest_paid == pytest.approx(100.0 * 7.0 / 1200, abs=0.01)


def test_fixed_coupon_with_floor():
    """Fixed bond with low coupon floored at 3%."""
    deal = _simple_deal([
        BondDef(name="A", kind=TrancheKind.CASH_PAY, notional=100.0,
                coupon=1.0,  # 1% — below floor
                floor=3.0),  # floor at 3%
    ])
    result = run_deal(deal, _flat_collateral(100.0))
    # Floor should lift coupon to 3%
    assert _row(result, "A", 1).interest_paid == pytest.approx(100.0 * 3.0 / 1200, abs=0.01)


def test_cap_as_rate_schedule():
    """Cap as a RateOrSchedule that steps down over time."""
    deal = _simple_deal([
        BondDef(name="A", kind=TrancheKind.CASH_PAY, notional=100.0,
                coupon=10.0,  # fixed 10%
                cap=[{"from_period": 1, "rate": 8.0},    # cap=8 initially
                     {"from_period": 4, "rate": 6.0}]),   # cap steps down to 6 at period 4
    ])
    result = run_deal(deal, _flat_collateral(100.0))
    # Periods 1-3: coupon=10 capped at 8
    assert _row(result, "A", 1).interest_paid == pytest.approx(100.0 * 8.0 / 1200, abs=0.01)
    assert _row(result, "A", 3).interest_paid == pytest.approx(100.0 * 8.0 / 1200, abs=0.01)
    # Period 4+: coupon=10 capped at 6
    assert _row(result, "A", 4).interest_paid == pytest.approx(100.0 * 6.0 / 1200, abs=0.01)


# ---------------------------------------------------------------------------
# Inverse floater
# ---------------------------------------------------------------------------


def test_inverse_floater_coupon_formula():
    """Inverse floater: coupon = cap - index_rate + margin (floors at 0)."""
    # cap=12%, SOFR=5.0%, margin=0.5% → coupon = 12 - 5.0 + 0.5 = 7.5%
    deal = _simple_deal(
        bonds=[BondDef(name="INV", kind=TrancheKind.CASH_PAY,
                       coupon_type=CouponType.INVERSE_FLOATING,
                       index_name="SOFR", notional=100.0,
                       cap=12.0, margin=0.50, coupon=None)],
        deal_knobs={"SOFR_rate": 5.0},
    )
    result = run_deal(deal, _flat_collateral(100.0))
    expected_monthly = 100.0 * 7.5 / 1200.0
    assert _row(result, "INV", 1).interest_paid == pytest.approx(expected_monthly, abs=0.01)


def test_inverse_floater_floors_at_zero():
    """Inverse floater must not go negative when index > cap + margin."""
    # cap=5%, SOFR=10% → 5 - 10 + 0 = -5% → floored at 0
    deal = _simple_deal(
        bonds=[BondDef(name="INV", kind=TrancheKind.CASH_PAY,
                       coupon_type=CouponType.INVERSE_FLOATING,
                       index_name="SOFR", notional=100.0,
                       cap=5.0, margin=0.0, coupon=None)],
        deal_knobs={"SOFR_rate": 10.0},
    )
    result = run_deal(deal, _flat_collateral(100.0))
    assert _row(result, "INV", 1).interest_paid == pytest.approx(0.0, abs=TOL)
