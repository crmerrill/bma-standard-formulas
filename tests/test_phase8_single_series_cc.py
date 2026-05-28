"""Phase 8: Single-series credit-card master trust deal.

## Master trust architecture

A CC master trust consists of a revolving pool of receivables and multiple
outstanding series. Cash flows are allocated to each series by the trust
orchestrator BEFORE they reach the series-level waterfall:

    Series A allocation = (Series A Invested Amount / Total Trust Balance)
                        × Total Trust Finance Charge Collections

The `DealDefinition` receives only the SERIES' ALLOCATED SHARE of cash
flows — it never sees the full trust pool. This means a single-series deal
is fully modelable with existing mechanics.

## What Phase 8 adds

- `DealDefinition.series_id`: metadata field labeling which series this
  DealDefinition represents, for the future inter-deal orchestrator.

## What remains deferred

Cross-series sharing requires a trust-level orchestrator (not yet implemented):

1. Pro-rata FCC allocation across all outstanding series
2. Shared Excess Finance Charges: excess from one series flows to shortfalls
   in other series BEFORE returning to the seller
3. Shared Excess Principal: same for principal during amortization
4. Trust-level triggers computed across all series simultaneously

## Single-series model

The single-series deal below represents Series 2024-A of a master trust.
The collateral input is the series' PRE-ALLOCATED share of pool cash flows
(as computed externally by the trust orchestrator).

Series parameters:
  - Invested Amount: $500M (50% of a $1B trust)
  - Series receives 50% of trust FCC and principal each period
  - Class A: senior, receives interest from Finance Charge Collections
  - Class B: subordinate, provides credit support via NLA
  - Class C: subordinate, additional credit support
  - PFA: Principal Funding Account, accumulates for bullet payment
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
    AccountMinimumScheduleEntry,
    BondDef,
    DealDefinition,
    RuleNode,
)


def _series_collateral(
    *,
    fcc_per_period: float,        # Finance Charge Collections allocated to this series
    principal_per_period: float,  # Principal Collections allocated to this series
    series_invested_amount: float = 500.0,  # Series' Invested Amount (constant revolving balance)
    n: int,
) -> DealRunInput:
    """Collateral representing a series' PRE-ALLOCATED share of master trust cashflows.

    This is aggregate (pooled) collateral at the series level — already the
    allocated share, as computed by the external trust orchestrator:
        fcc_per_period = trust_total_fcc × (series_invested_amount / total_trust_balance)

    PAIRED (per-loan) input is not needed here because the trust orchestrator
    works at the aggregate series level, not the individual receivable level.
    """
    interest = np.array([0.0] + [fcc_per_period] * (n - 1))
    principal = np.array([0.0] + [principal_per_period] * (n - 1))
    bal = np.full(n, series_invested_amount)
    cf = CollateralCashflows(
        cfdate=list(range(n)),
        balance=bal.tolist(), principal=principal.tolist(), interest=interest.tolist(),
        cashflow=(principal + interest).tolist(),
        loss=[0.0]*n, prepbal=[0.0]*n, defbal=[0.0]*n, recovery=[0.0]*n,
        principal_sched=principal.tolist(), principal_unsched=[0.0]*n,
        cpr=[0.0]*n, cdr=[0.0]*n, sev=[0.0]*n, dq=[0.0]*n, surv_fac=[1.0]*n,
        sched_coupon=[20.0]*n, sched_netcoupon=[20.0]*n,
        coupon=[20.0]*n, effcoupon=[20.0]*n,
        sched_balance=bal.tolist(), discount_factor=[1.0]*n,
    )
    return DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        original_collateral_balance=float(bal[0]),
        loan_count=50_000,
    )


# ---------------------------------------------------------------------------
# Series identity
# ---------------------------------------------------------------------------


def test_series_id_is_stored_and_round_trips():
    """series_id is a metadata field — stored, dumped, and reloaded correctly."""
    deal = DealDefinition(
        deal_name="SeriesA",
        series_id="COMET-2024-A",
        bonds=[BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True)],
        waterfall_rules=[
            RuleNode(rule_id="r", rule_type=RuleType.PAY_RESIDUAL, order=0,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    assert deal.series_id == "COMET-2024-A"
    dumped = deal.model_dump(mode="json")
    assert dumped["series_id"] == "COMET-2024-A"
    reloaded = DealDefinition.model_validate(dumped)
    assert reloaded.series_id == "COMET-2024-A"


def test_series_id_none_is_valid():
    """series_id is optional; None is the default for non-master-trust deals."""
    deal = DealDefinition(
        deal_name="NonMasterTrust",
        bonds=[BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True)],
        waterfall_rules=[
            RuleNode(rule_id="r", rule_type=RuleType.PAY_RESIDUAL, order=0,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    assert deal.series_id is None


# ---------------------------------------------------------------------------
# Single-series master trust waterfall
# The collateral input represents the series' PRE-ALLOCATED share.
# Priority of Payments follows standard CC master trust structure.
# ---------------------------------------------------------------------------


class TestSingleSeriesMasterTrust:
    """Realistic single-series master trust Priority of Payments test.

    Series 2024-A of a hypothetical master trust:
      - Series Invested Amount: $500M (50% of a $1B trust)
      - Series receives $100/period FCC and $50/period principal
        (pre-allocated by trust orchestrator at 50% of trust totals)

    Classes:
      Class A: $400M, 6% coupon, senior (seniority=1)
      Class B: $75M, 0% coupon, subordinate (seniority=2), NLA tracked
      Class C: $25M, 0% coupon, subordinate (seniority=3), NLA tracked

    Priority of Payments:
      1. Pay Class A interest from Finance Charge Collections (ACT_INT)
      2. Deposit to Principal Funding Account (accumulation)
      3. P-to-I: cover Class A shortfall from Class B if headroom allows
      4. REIMBURSE_NLA from excess spread
      5. Pay Class B interest (zero coupon, so no-op unless PIK)
      6. Residual to excess spread / seller
    """

    def _build_series_deal(
        self,
        n: int = 12,
        fcc_per_period: float = 100.0,
        principal_per_period: float = 50.0,
        series_invested_amount: float = 500.0,
    ) -> tuple[DealDefinition, DealRunInput]:
        deal = DealDefinition(
            deal_name="Series2024A",
            series_id="TEST-TRUST-2024-A",
            discount_factor_pct=2.0,
            bonds=[
                BondDef(
                    name="A",
                    kind=TrancheKind.CASH_PAY,
                    coupon=6.0,
                    notional=400.0,
                    seniority=1,
                    required_subordination_pct=20.0,  # requires 20% of A outstanding as sub
                ),
                BondDef(
                    name="B",
                    kind=TrancheKind.CASH_PAY,
                    coupon=0.0,
                    notional=75.0,
                    nla_starting_balance=75.0,
                    seniority=2,
                ),
                BondDef(
                    name="C",
                    kind=TrancheKind.CASH_PAY,
                    coupon=0.0,
                    notional=25.0,
                    nla_starting_balance=25.0,
                    seniority=3,
                ),
                BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            accounts=[
                # Principal Funding Account: accumulates for bullet payment.
                # Minimum target grows 5/period (simplified schedule).
                AccountDef(
                    name="PFA",
                    account_category="PREFUNDING",
                    starting_amount=0.0,
                    minimum_schedule=[
                        AccountMinimumScheduleEntry(period=p, minimum_balance=5.0 * p)
                        for p in range(1, n)
                    ],
                ),
                # Spread account: funded from excess FCC, used to reimburse NLA.
                AccountDef(name="SPREAD_ACCT", starting_amount=10.0),
            ],
            waterfall_rules=[
                # Step 1: Pay Class A interest from Finance Charge Collections.
                RuleNode(rule_id="a_int", rule_type=RuleType.PAY_INTEREST, order=0,
                         from_sources=["ACT_INT"], to_targets=["A"]),
                # Step 2: Fund PFA from allocated principal collections.
                RuleNode(rule_id="pfa_dep", rule_type=RuleType.PAY_TO_ACCOUNT, order=1,
                         from_sources=["ACT_PRIN"], to_targets=["PFA"],
                         max_amount_fixed=5.0),
                # Step 3: P-to-I coverage — if FCC insufficient, draw from Class B
                # subject to subordination headroom.
                RuleNode(
                    rule_id="p_to_i",
                    rule_type=RuleType.PAY_INTEREST,
                    order=2,
                    from_sources=["B"],
                    to_targets=["A"],
                    coverage_mode=CoverageMode.INTEREST_SHORTFALL,
                    max_amount_expr=(
                        "A_available_subordination - A_required_subordination "
                        "if A_available_subordination > A_required_subordination else 0"
                    ),
                ),
                # Step 4: Reimburse Class B NLA from spread account.
                RuleNode(rule_id="reimb_b", rule_type=RuleType.REIMBURSE_NLA, order=3,
                         from_sources=["SPREAD_ACCT"], to_targets=["B"]),
                # Step 5: Excess to residual (seller interest / excess spread).
                RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=4,
                         from_sources=["ACT_INT"], to_targets=["R"]),
            ],
        )
        run_input = _series_collateral(
            fcc_per_period=fcc_per_period,
            principal_per_period=principal_per_period,
            series_invested_amount=series_invested_amount,
            n=n,
        )
        return deal, run_input

    def test_class_a_interest_paid_from_fcc(self):
        """Class A coupon must be paid from Finance Charge Collections (ACT_INT).

        With 2% discount option:
        - Original principal = 50; after discount: ACT_PRIN = 49, ACT_INT = 101
        - Class A monthly coupon = 400 × 6% / 12 = 2.0
        - ACT_INT = 101 >> 2.0 → fully paid every period
        """
        deal, run_input = self._build_series_deal()
        result = run_deal(deal, run_input)

        a_coupon_expected = 400.0 * 6.0 / 1200.0  # 2.0/month

        # Period 1: A has no prior shortfall; FCC covers coupon fully.
        a_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "A" and r.period == 1)
        assert a_p1.interest_paid == pytest.approx(a_coupon_expected, abs=0.01), (
            f"A must receive full coupon {a_coupon_expected:.4f} from FCC"
        )

        # All periods: A should be fully paid (FCC >> coupon).
        a_rows = [r for r in result.bond_cashflows if r.tranche_id == "A" and r.period > 0]
        for row in a_rows:
            assert row.interest_paid == pytest.approx(a_coupon_expected, abs=0.01), (
                f"Period {row.period}: A should always receive full coupon from FCC"
            )

    def test_pfa_accumulates_principal_collections(self):
        """PFA receives principal deposits; balance grows toward scheduled target."""
        deal, run_input = self._build_series_deal()
        result = run_deal(deal, run_input)

        pfa_rows = {r.period: r for r in result.deal_accounts if r.account_id == "PFA"}

        # Period 1: deposit 5 (min(ACT_PRIN=49 after discount, max_amount=5)).
        assert pfa_rows[1].end_balance == pytest.approx(5.0, abs=0.01), "PFA p1 = 5"
        # PFA balance grows monotonically.
        for p in range(2, 12):
            assert pfa_rows[p].end_balance >= pfa_rows[p - 1].end_balance, (
                f"PFA must not decrease from period {p-1} to {p}"
            )

    def test_class_b_nla_tracked_correctly(self):
        """Class B NLA is tracked. In normal operation (FCC covers A), no P-to-I fires
        and B NLA stays at its starting balance."""
        deal, run_input = self._build_series_deal()
        result = run_deal(deal, run_input)

        b_rows = [r for r in result.bond_cashflows if r.tranche_id == "B" and r.period > 0]
        # FCC is ample (101 >> 2.0 coupon), so P-to-I never fires.
        # B NLA should remain at 75 throughout (no depletion, no reimbursement needed).
        for row in b_rows:
            assert row.nla_balance == pytest.approx(75.0, abs=0.01), (
                f"Period {row.period}: B NLA must remain at starting value when P-to-I never fires"
            )

    def test_p_to_i_fires_when_fcc_is_insufficient(self):
        """Stress test: when FCC does not fully cover Class A coupon, P-to-I draws from B.
        Uses the standard _build_series_deal with reduced FCC (1.0 < A coupon 2.0).
        """
        # A coupon = 400 × 6% / 12 = 2.0; FCC = 1.0 (not enough).
        deal, run_input = self._build_series_deal(
            n=8,
            fcc_per_period=1.0,           # insufficient — forces P-to-I
            principal_per_period=0.0,
            series_invested_amount=500.0,
        )
        result = run_deal(deal, run_input)

        # Period 2 mechanics (FCC=1.0, A coupon=2.0):
        # - A accumulated shortfall from period 1 = 1.0 (FCC covered only 1.0 of 2.0)
        # - Period 2 FCC covers 1.0 of accumulated shortfall
        # - P-to-I from B covers remaining 1.0 shortfall → A gets 2.0 total
        a_p2 = next(r for r in result.bond_cashflows if r.tranche_id == "A" and r.period == 2)
        assert a_p2.interest_paid == pytest.approx(2.0, abs=0.1), (
            f"Period 2: FCC (1.0 shortfall) + P-to-I (1.0) = 2.0 — got {a_p2.interest_paid:.4f}"
        )

        # B's economic balance depletes by P-to-I payments.
        # Note: B's NLA may be restored in the same period by REIMBURSE_NLA (SPREAD_ACCT has 10.0).
        # Economic balance is the right signal here — it reflects the actual debit.
        b_p2 = next(r for r in result.bond_cashflows if r.tranche_id == "B" and r.period == 2)
        assert b_p2.end_balance < 75.0, (
            f"B economic balance must deplete when P-to-I draws from B (got {b_p2.end_balance:.2f})"
        )

    def test_run_deal_accepts_series_id_labelled_deal(self):
        """run_deal must accept a DealDefinition with series_id set without error.
        Note: series_id is metadata-only and does NOT appear in ScenarioOutputBundle;
        it is used by the future TrustOrchestrator to identify series.
        """
        deal, run_input = self._build_series_deal(n=4)
        assert deal.series_id == "TEST-TRUST-2024-A"
        result = run_deal(deal, run_input)
        # Verify the correct bond set is present in output.
        bond_names = {r.tranche_id for r in result.bond_cashflows}
        assert {"A", "B", "C", "R"} == bond_names
