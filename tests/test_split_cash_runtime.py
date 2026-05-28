"""Runtime tests for the SPLIT_CASH IR primitive.

`SPLIT_CASH` is the cash-plumbing Lego block: it drains cash from one or
more input streams (`from_sources`) and writes it into one or more named
target streams (`to_targets`) according to per-target weights. Targets
that are not built-in stream names (CASH/ACT_INT/ACT_PRIN) are virtual
streams that subsequent rules can reference via `from_sources`.

These tests verify three usage shapes:

1. **1 -> N split** (the standard support-split pattern). One input stream
   feeds two virtual streams in face-weighted ratio; downstream rules pay
   different bonds from each.

2. **N -> 1 merge** (sweep-back pattern). Two leftover virtual streams
   merge into a single downstream stream so a cleanup cascade can drain
   any residual.

3. **Conservation under decrement**. Total dollars consumed from inputs
   equals total dollars written into outputs (modulo rounding).
"""
from __future__ import annotations

import numpy as np
import pytest

from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.common import (
    CapMode,
    CouponType,
    PaymentStyle,
    RuleType,
    TrancheKind,
)
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows,
    DealRunInput,
    PooledCollateralInput,
)
from bma_standard_formulas.deals.schemas.ir import BondDef, DealDefinition, RuleNode


N_PERIODS = 12


def _constant_collateral(
    initial_balance: float = 1_000_000.0,
    monthly_principal: float = 100_000.0,
    monthly_interest: float = 0.0,
) -> DealRunInput:
    """Deterministic constant-paydown pool used to make hand-checks simple."""
    bal = np.zeros(N_PERIODS)
    principal = np.zeros(N_PERIODS)
    interest = np.zeros(N_PERIODS)
    bal[0] = initial_balance
    for i in range(1, N_PERIODS):
        prev = bal[i - 1]
        prin = min(monthly_principal, prev)
        principal[i] = prin
        interest[i] = monthly_interest
        bal[i] = max(0.0, prev - prin)
    cf = CollateralCashflows(
        cfdate=list(range(N_PERIODS)),
        balance=bal.tolist(),
        principal=principal.tolist(),
        interest=interest.tolist(),
        cashflow=(principal + interest).tolist(),
        loss=[0.0] * N_PERIODS,
        prepbal=[0.0] * N_PERIODS,
        defbal=[0.0] * N_PERIODS,
        recovery=[0.0] * N_PERIODS,
        principal_sched=principal.tolist(),
        principal_unsched=[0.0] * N_PERIODS,
        cpr=[0.0] * N_PERIODS,
        cdr=[0.0] * N_PERIODS,
        sev=[0.0] * N_PERIODS,
        dq=[0.0] * N_PERIODS,
        surv_fac=[1.0] * N_PERIODS,
        sched_coupon=[0.0] * N_PERIODS,
        sched_netcoupon=[0.0] * N_PERIODS,
        coupon=[0.0] * N_PERIODS,
        effcoupon=[0.0] * N_PERIODS,
        sched_balance=bal.tolist(),
        discount_factor=[1.0] * N_PERIODS,
    )
    return DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        original_collateral_balance=initial_balance,
        loan_count=1,
    )


def _two_zero_coupon_bonds(
    name_a: str = "A",
    face_a: float = 600_000.0,
    name_b: str = "B",
    face_b: float = 400_000.0,
) -> list[BondDef]:
    return [
        BondDef(
            name=name_a,
            kind=TrancheKind.CASH_PAY,
            coupon_type=CouponType.ZERO,
            notional=face_a,
        ),
        BondDef(
            name=name_b,
            kind=TrancheKind.CASH_PAY,
            coupon_type=CouponType.ZERO,
            notional=face_b,
        ),
        BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
    ]


# ---------------------------------------------------------------------------
# 1 -> N split: support-style face-weighted distribution
# ---------------------------------------------------------------------------


class TestSplitOneToMany:
    """Drain ACT_PRIN into two virtual buckets in 60/40 ratio, pay bonds from each."""

    def _build_deal(self) -> DealDefinition:
        return DealDefinition(
            deal_name="split_1_to_N",
            bonds=_two_zero_coupon_bonds(),
            waterfall_rules=[
                # Step 1: split ACT_PRIN 60/40 into two named buckets.
                RuleNode(
                    rule_id="r_split",
                    rule_type=RuleType.SPLIT_CASH,
                    order=0,
                    from_sources=["ACT_PRIN"],
                    to_targets=["BUCKET_A", "BUCKET_B"],
                    target_weights=[0.60, 0.40],
                ),
                # Step 2: pay A from BUCKET_A and B from BUCKET_B.
                RuleNode(
                    rule_id="r_pay_a",
                    rule_type=RuleType.PAY_PRINCIPAL,
                    order=1,
                    from_sources=["BUCKET_A"],
                    to_targets=["A"],
                    cap_mode=CapMode.NONE,
                ),
                RuleNode(
                    rule_id="r_pay_b",
                    rule_type=RuleType.PAY_PRINCIPAL,
                    order=2,
                    from_sources=["BUCKET_B"],
                    to_targets=["B"],
                    cap_mode=CapMode.NONE,
                ),
                # Step 3: residual sweeps any unsplit cash from ACT_PRIN/ACT_INT
                # plus anything left in the buckets via N->1 merge.
                RuleNode(
                    rule_id="r_sweep_back",
                    rule_type=RuleType.SPLIT_CASH,
                    order=3,
                    from_sources=["BUCKET_A", "BUCKET_B"],
                    to_targets=["ACT_PRIN"],
                    target_weights=[1.0],
                ),
                RuleNode(
                    rule_id="r_resid_prin",
                    rule_type=RuleType.PAY_RESIDUAL,
                    order=4,
                    from_sources=["ACT_PRIN"],
                    to_targets=["R"],
                ),
                RuleNode(
                    rule_id="r_resid_int",
                    rule_type=RuleType.PAY_RESIDUAL,
                    order=5,
                    from_sources=["ACT_INT"],
                    to_targets=["R"],
                ),
            ],
        )

    def test_period_1_split_sends_60_40(self):
        """First period: $100K of pool prin splits 60/40 between A and B."""
        run_input = _constant_collateral()
        deal = self._build_deal()
        result = run_deal(deal, run_input, scenario_name="split")
        a_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "A" and r.period == 1)
        b_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "B" and r.period == 1)
        assert a_p1.total_principal == pytest.approx(60_000.0, abs=1.0)
        assert b_p1.total_principal == pytest.approx(40_000.0, abs=1.0)

    def test_total_split_proportional_until_a_retires(self):
        """A retires when cumulative split to A reaches 600K (after 10 periods)."""
        run_input = _constant_collateral()
        deal = self._build_deal()
        result = run_deal(deal, run_input, scenario_name="split")
        a_total = sum(r.total_principal for r in result.bond_cashflows if r.tranche_id == "A")
        b_total = sum(r.total_principal for r in result.bond_cashflows if r.tranche_id == "B")
        assert a_total == pytest.approx(600_000.0, abs=1.0)
        assert b_total == pytest.approx(400_000.0, abs=1.0)

    def test_no_double_count_after_sweep_back(self):
        """Sweep-back N->1 merge must not double-count cash already paid."""
        run_input = _constant_collateral()
        deal = self._build_deal()
        result = run_deal(deal, run_input, scenario_name="split")
        # Total paid out + residual must equal pool principal exactly.
        bond_paid = sum(
            r.total_principal for r in result.bond_cashflows if r.tranche_id != "R"
        )
        residual = sum(
            r.cashflow_total for r in result.bond_cashflows if r.tranche_id == "R"
        )
        pool_principal = sum(run_input.collateral.collateral.principal)
        assert bond_paid + residual == pytest.approx(pool_principal, abs=1.0)


# ---------------------------------------------------------------------------
# N -> 1 merge: sweep-back of leftover virtual streams
# ---------------------------------------------------------------------------


class TestSplitManyToOne:
    """Verify N->1 merge drains all input streams and accumulates into target."""

    def _build_deal(self, weight_a: float, weight_b: float) -> DealDefinition:
        # Bond A is small ($100K) so its bucket will overflow; Bond B is large.
        return DealDefinition(
            deal_name="merge_sweep",
            bonds=[
                BondDef(
                    name="A",
                    kind=TrancheKind.CASH_PAY,
                    coupon_type=CouponType.ZERO,
                    notional=100_000.0,
                ),
                BondDef(
                    name="B",
                    kind=TrancheKind.CASH_PAY,
                    coupon_type=CouponType.ZERO,
                    notional=900_000.0,
                ),
                BondDef(
                    name="R",
                    kind=TrancheKind.RESIDUAL,
                    is_bond=False,
                    is_pseudo=True,
                ),
            ],
            waterfall_rules=[
                RuleNode(
                    rule_id="r_split",
                    rule_type=RuleType.SPLIT_CASH,
                    order=0,
                    from_sources=["ACT_PRIN"],
                    to_targets=["BUCKET_A", "BUCKET_B"],
                    target_weights=[weight_a, weight_b],
                ),
                RuleNode(
                    rule_id="r_pay_a",
                    rule_type=RuleType.PAY_PRINCIPAL,
                    order=1,
                    from_sources=["BUCKET_A"],
                    to_targets=["A"],
                    cap_mode=CapMode.NONE,
                ),
                # Sweep BUCKET_A leftover back to BUCKET_B before paying B.
                # This is the merge case: when A retires with cash left in
                # BUCKET_A, that residual must be available to B.
                RuleNode(
                    rule_id="r_merge",
                    rule_type=RuleType.SPLIT_CASH,
                    order=2,
                    from_sources=["BUCKET_A"],
                    to_targets=["BUCKET_B"],
                    target_weights=[1.0],
                ),
                RuleNode(
                    rule_id="r_pay_b",
                    rule_type=RuleType.PAY_PRINCIPAL,
                    order=3,
                    from_sources=["BUCKET_B"],
                    to_targets=["B"],
                    cap_mode=CapMode.NONE,
                ),
                RuleNode(
                    rule_id="r_resid_prin",
                    rule_type=RuleType.PAY_RESIDUAL,
                    order=4,
                    from_sources=["ACT_PRIN", "BUCKET_A", "BUCKET_B"],
                    to_targets=["R"],
                ),
                RuleNode(
                    rule_id="r_resid_int",
                    rule_type=RuleType.PAY_RESIDUAL,
                    order=5,
                    from_sources=["ACT_INT"],
                    to_targets=["R"],
                ),
            ],
        )

    def test_a_overfunded_overflow_reaches_b(self):
        """A bucket gets 60% of cash but A only needs ~10% face; overflow -> B via merge."""
        run_input = _constant_collateral()
        deal = self._build_deal(weight_a=0.60, weight_b=0.40)
        result = run_deal(deal, run_input, scenario_name="merge")
        a_total = sum(r.total_principal for r in result.bond_cashflows if r.tranche_id == "A")
        b_total = sum(r.total_principal for r in result.bond_cashflows if r.tranche_id == "B")
        assert a_total == pytest.approx(100_000.0, abs=1.0)
        # B receives what's left = pool principal $1MM - A's $100K = $900K.
        assert b_total == pytest.approx(900_000.0, abs=1.0)
