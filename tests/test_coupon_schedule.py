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

