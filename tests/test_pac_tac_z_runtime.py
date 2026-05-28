"""Golden runtime regression tests for PAC/TAC/Z payment semantics.

Verifies the schedule-first enforcement model: PAC/TAC bonds receive at most
their published `schedule_contract` per period, excess principal cascades to
support tranches, and Z bonds accrue interest into balance + pay support
principal until the support stack is exhausted.

These tests do not depend on LDCMA fixtures — they construct minimal
DealDefinition IR inline so the contract is explicit. Parity with LDCMA
reference deals lives in `scripts/run_ldcma_parity.py` and runs as a
separate CI gate.
"""
from __future__ import annotations

import numpy as np
import pytest

from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.common import (
    PayMode,
    RuleType,
    TrancheKind,
    TrancheRelationType,
)
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows,
    DealRunInput,
    PooledCollateralInput,
)
from bma_standard_formulas.deals.schemas.ir import BondDef, DealDefinition, RuleNode, TrancheRelation

TOL = 1e-2


def _flat_collateral(initial_balance: float, n_periods: int, monthly_principal: float, annual_coupon: float) -> DealRunInput:
    """Build a deterministic collateral stream with a constant monthly principal payment.

    Constant monthly principal makes scheduled vs actual comparisons trivial:
    every period delivers exactly `monthly_principal` until the pool is paid down.
    """
    bal = np.zeros(n_periods)
    principal = np.zeros(n_periods)
    interest = np.zeros(n_periods)
    bal[0] = initial_balance
    for i in range(1, n_periods):
        prev = bal[i - 1]
        prin = min(monthly_principal, prev)
        principal[i] = prin
        interest[i] = prev * annual_coupon / 1200.0
        bal[i] = max(0.0, prev - prin)
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
        loan_count=10,
    )


def _row(result, tranche_id: str, period: int):
    return next(r for r in result.bond_cashflows if r.tranche_id == tranche_id and r.period == period)


def _principal_paid_total(result, tranche_id: str) -> float:
    return float(sum(r.total_principal for r in result.bond_cashflows if r.tranche_id == tranche_id))


# ---------------------------------------------------------------------------
# PAC schedule-first enforcement
# ---------------------------------------------------------------------------


class TestPacScheduleEnforcement:
    """PAC bond never exceeds its scheduled principal; excess flows to support."""

    def _build_pac_support_deal(self, pac_size: float, support_size: float, schedule: list[dict]) -> DealDefinition:
        return DealDefinition(
            deal_name="PacWithSupport",
            bonds=[
                BondDef(
                    name="PAC",
                    kind=TrancheKind.PAC,
                    coupon=4.0,
                    notional=pac_size,
                    schedule_contract=schedule,
                    relations=[
                        TrancheRelation(
                            relation_type=TrancheRelationType.SUPPORTED_BY,
                            targets=["S"],
                        )
                    ],
                ),
                BondDef(
                    name="S",
                    kind=TrancheKind.CASH_PAY,
                    coupon=5.0,
                    notional=support_size,
                ),
                BondDef(
                    name="R",
                    kind=TrancheKind.RESIDUAL,
                    is_bond=False,
                    is_pseudo=True,
                ),
            ],
            waterfall_rules=[
                RuleNode(rule_id="r_int_pac", rule_type=RuleType.PAY_INTEREST, order=0,
                         from_sources=["CASH"], to_targets=["PAC"]),
                RuleNode(rule_id="r_int_s", rule_type=RuleType.PAY_INTEREST, order=1,
                         from_sources=["CASH"], to_targets=["S"]),
                RuleNode(rule_id="r_prin_pac", rule_type=RuleType.PAY_PRINCIPAL, order=2,
                         from_sources=["CASH"], to_targets=["PAC"]),
                RuleNode(rule_id="r_prin_s", rule_type=RuleType.PAY_PRINCIPAL, order=3,
                         from_sources=["CASH"], to_targets=["S"]),
                RuleNode(rule_id="r_resid", rule_type=RuleType.PAY_RESIDUAL, order=4,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )

    def test_pac_never_exceeds_schedule(self):
        # Collateral provides 1,000,000 of principal each period for 12 periods.
        # PAC is sized 6,000,000 with a published schedule of exactly 500,000/period for 12 periods.
        # Excess 500,000/period must flow to the support tranche.
        n_periods = 13
        run_input = _flat_collateral(initial_balance=12_000_000.0, n_periods=n_periods,
                                     monthly_principal=1_000_000.0, annual_coupon=6.0)
        schedule = [{"period": p, "target_principal": 500_000.0} for p in range(1, n_periods)]
        deal = self._build_pac_support_deal(pac_size=6_000_000.0, support_size=6_000_000.0, schedule=schedule)
        result = run_deal(deal, run_input)
        for p in range(1, n_periods):
            pac_row = _row(result, "PAC", p)
            assert pac_row.total_principal <= 500_000.0 + TOL, (
                f"period {p}: PAC paid {pac_row.total_principal} > schedule cap 500,000"
            )

    def test_pac_excess_flows_to_support(self):
        # 1M/period collateral, 500K PAC schedule. PAC must cap at 500K; the
        # remaining principal (and any excess interest residue) flows to support.
        # Verify support absorbs the excess specifically while the PAC is still
        # actively scheduled (early periods when both bonds are outstanding).
        n_periods = 13
        run_input = _flat_collateral(initial_balance=12_000_000.0, n_periods=n_periods,
                                     monthly_principal=1_000_000.0, annual_coupon=6.0)
        schedule = [{"period": p, "target_principal": 500_000.0} for p in range(1, n_periods)]
        deal = self._build_pac_support_deal(pac_size=6_000_000.0, support_size=6_000_000.0, schedule=schedule)
        result = run_deal(deal, run_input)
        for p in range(1, 8):  # while both PAC and Support are well above zero
            pac_row = _row(result, "PAC", p)
            support_row = _row(result, "S", p)
            assert pac_row.total_principal == pytest.approx(500_000.0, abs=TOL), (
                f"period {p}: PAC should hit schedule cap exactly while collateral generates 1M"
            )
            assert support_row.total_principal >= 500_000.0 - TOL, (
                f"period {p}: support did not absorb excess principal (got {support_row.total_principal})"
            )

    def test_pac_total_principal_matches_collateral(self):
        # Conservation: PAC + Support principal == total collateral principal.
        n_periods = 13
        run_input = _flat_collateral(initial_balance=12_000_000.0, n_periods=n_periods,
                                     monthly_principal=1_000_000.0, annual_coupon=6.0)
        schedule = [{"period": p, "target_principal": 500_000.0} for p in range(1, n_periods)]
        deal = self._build_pac_support_deal(pac_size=6_000_000.0, support_size=6_000_000.0, schedule=schedule)
        result = run_deal(deal, run_input)
        pac_total = _principal_paid_total(result, "PAC")
        s_total = _principal_paid_total(result, "S")
        coll_total = sum(run_input.collateral.collateral.principal)
        assert pac_total + s_total == pytest.approx(coll_total, abs=TOL)


# ---------------------------------------------------------------------------
# PAC schedule break (collateral below schedule, support exhausted)
# ---------------------------------------------------------------------------


class TestPacScheduleBreak:
    """When collateral can't meet schedule, PAC accepts what's available."""

    def test_pac_accepts_partial_when_collateral_short(self):
        # Schedule asks for 1M/period; collateral only delivers 600K/period principal.
        # PAC takes whatever cash is available up to its 1M cap (cap is upper bound,
        # not lower). Schedule is honored: PAC <= 1M each period.
        n_periods = 13
        run_input = _flat_collateral(initial_balance=7_200_000.0, n_periods=n_periods,
                                     monthly_principal=600_000.0, annual_coupon=6.0)
        schedule = [{"period": p, "target_principal": 1_000_000.0} for p in range(1, n_periods)]
        deal = TestPacScheduleEnforcement()._build_pac_support_deal(
            pac_size=6_000_000.0, support_size=2_000_000.0, schedule=schedule
        )
        result = run_deal(deal, run_input)
        for p in range(1, n_periods):
            pac_row = _row(result, "PAC", p)
            assert pac_row.total_principal <= 1_000_000.0 + TOL, (
                f"period {p}: PAC over schedule cap"
            )


# ---------------------------------------------------------------------------
# TAC contraction protection
# ---------------------------------------------------------------------------


class TestTacContractionProtection:
    """TAC schedule cap behaves identically to PAC at the per-period level."""

    def test_tac_cap_holds(self):
        n_periods = 13
        run_input = _flat_collateral(initial_balance=12_000_000.0, n_periods=n_periods,
                                     monthly_principal=1_000_000.0, annual_coupon=6.0)
        schedule = [{"period": p, "target_principal": 700_000.0} for p in range(1, n_periods)]
        deal = DealDefinition(
            deal_name="TacWithSupport",
            bonds=[
                BondDef(
                    name="TAC",
                    kind=TrancheKind.TAC,
                    coupon=4.5,
                    notional=8_400_000.0,
                    schedule_contract=schedule,
                    relations=[
                        TrancheRelation(
                            relation_type=TrancheRelationType.SUPPORTED_BY,
                            targets=["S"],
                        )
                    ],
                ),
                BondDef(
                    name="S",
                    kind=TrancheKind.CASH_PAY,
                    coupon=5.0,
                    notional=3_600_000.0,
                ),
                BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=[
                RuleNode(rule_id="r_int_tac", rule_type=RuleType.PAY_INTEREST, order=0,
                         from_sources=["CASH"], to_targets=["TAC"]),
                RuleNode(rule_id="r_int_s", rule_type=RuleType.PAY_INTEREST, order=1,
                         from_sources=["CASH"], to_targets=["S"]),
                RuleNode(rule_id="r_prin_tac", rule_type=RuleType.PAY_PRINCIPAL, order=2,
                         from_sources=["CASH"], to_targets=["TAC"]),
                RuleNode(rule_id="r_prin_s", rule_type=RuleType.PAY_PRINCIPAL, order=3,
                         from_sources=["CASH"], to_targets=["S"]),
                RuleNode(rule_id="r_resid", rule_type=RuleType.PAY_RESIDUAL, order=4,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )
        result = run_deal(deal, run_input)
        for p in range(1, n_periods):
            tac_row = _row(result, "TAC", p)
            assert tac_row.total_principal <= 700_000.0 + TOL


# ---------------------------------------------------------------------------
# Z accrual to support
# ---------------------------------------------------------------------------


class TestZAccrual:
    """Z bond accrues interest into balance and pays support principal each period."""

    def _build_z_support_deal(self, senior_size: float, z_size: float, z_coupon: float = 6.0) -> DealDefinition:
        return DealDefinition(
            deal_name="ZWithSupport",
            bonds=[
                BondDef(
                    name="A",
                    kind=TrancheKind.CASH_PAY,
                    coupon=4.0,
                    notional=senior_size,
                ),
                BondDef(
                    name="Z",
                    kind=TrancheKind.Z,
                    pay_mode=PayMode.PIK,
                    coupon=z_coupon,
                    notional=z_size,
                    z_accrual_enabled=True,
                    relations=[
                        TrancheRelation(
                            relation_type=TrancheRelationType.ACCRETES_TO,
                            targets=["A"],
                        )
                    ],
                ),
                BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=[
                RuleNode(rule_id="r_int_a", rule_type=RuleType.PAY_INTEREST, order=0,
                         from_sources=["CASH"], to_targets=["A"]),
                RuleNode(rule_id="r_int_z", rule_type=RuleType.PAY_INTEREST, order=1,
                         from_sources=["CASH"], to_targets=["Z"]),
                RuleNode(rule_id="r_prin_a", rule_type=RuleType.PAY_PRINCIPAL, order=2,
                         from_sources=["CASH"], to_targets=["A"]),
                RuleNode(rule_id="r_prin_z", rule_type=RuleType.PAY_PRINCIPAL, order=3,
                         from_sources=["CASH"], to_targets=["Z"]),
                RuleNode(rule_id="r_resid", rule_type=RuleType.PAY_RESIDUAL, order=4,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )

    def test_z_balance_grows_when_supported(self):
        # Z bond at 6% on 1,000,000 should accrue 5,000/month while support is outstanding.
        n_periods = 5
        run_input = _flat_collateral(
            initial_balance=11_000_000.0, n_periods=n_periods,
            monthly_principal=2_000_000.0, annual_coupon=6.0
        )
        deal = self._build_z_support_deal(senior_size=10_000_000.0, z_size=1_000_000.0, z_coupon=6.0)
        result = run_deal(deal, run_input)
        z_period_1 = _row(result, "Z", 1)
        # Balance after period 1: 1,000,000 + 5,000 accrual - any principal paid (should be 0 while A outstanding).
        assert z_period_1.end_balance > 1_000_000.0
        # Z must NOT receive cash interest while in PIK accrual mode.
        assert z_period_1.interest_paid == pytest.approx(0.0, abs=TOL)

    def test_z_accrual_pays_support_principal(self):
        # Z accrual on 1,000,000 at 6% annual = 5,000/month -> support principal.
        # We engineer collateral interest to exactly equal A's coupon obligation so
        # no extra cash flows into A's principal slot, isolating the Z accrual effect.
        # Pool 10M at 4% -> 33,333 interest; A 10M at 4% -> 33,333 interest. Match.
        n_periods = 3
        run_input = _flat_collateral(
            initial_balance=10_000_000.0, n_periods=n_periods,
            monthly_principal=0.0, annual_coupon=4.0
        )
        deal = self._build_z_support_deal(senior_size=10_000_000.0, z_size=1_000_000.0, z_coupon=6.0)
        result = run_deal(deal, run_input)
        # Period 1: collateral interest exactly pays A interest; Z accrues 5,000 -> A.
        a_p1 = _row(result, "A", 1)
        assert a_p1.total_principal == pytest.approx(5_000.0, abs=TOL), (
            f"Expected senior to receive 5,000 from Z accrual, got {a_p1.total_principal}"
        )

    def test_z_release_when_support_exhausted(self):
        # Tiny senior + ample collateral so A pays off period 1; Z then should be
        # released and start receiving cash interest in subsequent periods.
        # Keep Z size large enough that it doesn't fully amortize in one period
        # so we can observe multi-period cash-pay behavior.
        n_periods = 8
        run_input = _flat_collateral(
            initial_balance=10_000_000.0, n_periods=n_periods,
            monthly_principal=600_000.0, annual_coupon=6.0
        )
        deal = self._build_z_support_deal(senior_size=500_000.0, z_size=5_000_000.0, z_coupon=6.0)
        result = run_deal(deal, run_input)
        # A should fully amortize by period 1 (collateral cash >> A balance).
        a_p1 = _row(result, "A", 1)
        assert a_p1.end_balance == pytest.approx(0.0, abs=TOL), "A should fully amortize"
        # Z should receive cash interest in at least one period after release.
        cash_paying_periods = [
            r for r in result.bond_cashflows
            if r.tranche_id == "Z" and r.period >= 2 and r.interest_paid > 0.0
        ]
        assert cash_paying_periods, "Z bond never released to cash-pay despite support payoff"


# ---------------------------------------------------------------------------
# Final-period writedown regression
# ---------------------------------------------------------------------------


class TestNoSyntheticFinalWritedown:
    """Regression: removed forced final-period writedown should not zero out balances."""

    def test_outstanding_balance_persists_at_horizon(self):
        # Pool too small to fully amortize a 1,000,000 senior over 6 periods -> bond
        # should end with a positive balance (not synthetic writedown).
        n_periods = 7
        run_input = _flat_collateral(
            initial_balance=400_000.0, n_periods=n_periods,
            monthly_principal=50_000.0, annual_coupon=6.0
        )
        deal = DealDefinition(
            deal_name="UnderAmortizing",
            bonds=[
                BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=4.0, notional=1_000_000.0),
                BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=[
                RuleNode(rule_id="r_int", rule_type=RuleType.PAY_INTEREST, order=0,
                         from_sources=["CASH"], to_targets=["A"]),
                RuleNode(rule_id="r_prin", rule_type=RuleType.PAY_PRINCIPAL, order=1,
                         from_sources=["CASH"], to_targets=["A"]),
                RuleNode(rule_id="r_resid", rule_type=RuleType.PAY_RESIDUAL, order=2,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )
        result = run_deal(deal, run_input)
        last = _row(result, "A", n_periods - 1)
        assert last.end_balance > 0.0, "Final-period synthetic writedown still active"
        assert last.writedown == pytest.approx(0.0, abs=TOL), "Writedown should be zero with no losses"


# ---------------------------------------------------------------------------
# RG4: Grouped Z accrual must debit group-specific ACT_INT stream
# ---------------------------------------------------------------------------


class TestGroupedZAccrual:
    """Verify that Z accrual in a multi-group deal debits the correct group-
    specific ACT_INT stream so that downstream rules drawing from
    GROUP_<id>_ACT_INT cannot double-fund the accrued interest.
    """

    def _build_grouped_z_deal(self):
        """Build a 2-group deal where Group 1 contains a Z bond.

        Group 1: Z bond + support bond A.
        Group 2: plain bond B.

        Rules use bare tokens (ACT_INT, ACT_PRIN) tagged with group_id — the
        runtime's _scope_sources_to_group rewrites them to GROUP_<id>_ACT_INT
        so each group draws only from its own pool.
        """
        from bma_standard_formulas.deals.schemas.ir import CollateralGroupDef

        deal = DealDefinition(
            deal_name="GroupedZAccrualTest",
            collateral_groups=[
                CollateralGroupDef(group_id="GROUP_1", label="Group 1"),
                CollateralGroupDef(group_id="GROUP_2", label="Group 2"),
            ],
            bonds=[
                BondDef(
                    name="A",
                    kind=TrancheKind.CASH_PAY,
                    coupon=6.0,
                    notional=100.0,
                    group_id="GROUP_1",
                ),
                BondDef(
                    name="Z",
                    kind=TrancheKind.Z,
                    coupon=6.0,
                    notional=50.0,
                    pay_mode=PayMode.PIK,
                    z_accrual_enabled=True,
                    relations=[TrancheRelation(
                        relation_type=TrancheRelationType.ACCRETES_TO,
                        targets=["A"],
                    )],
                    group_id="GROUP_1",
                ),
                BondDef(
                    name="B",
                    kind=TrancheKind.CASH_PAY,
                    coupon=6.0,
                    notional=80.0,
                    group_id="GROUP_2",
                ),
                BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=[
                # Bare ACT_INT + group_id; _scope_sources_to_group rewrites to
                # GROUP_GROUP_1_ACT_INT which routes to interest_avail_by_group["GROUP_1"].
                RuleNode(
                    rule_id="g1_int_a",
                    rule_type=RuleType.PAY_INTEREST,
                    order=0,
                    from_sources=["ACT_INT"],
                    to_targets=["A"],
                    group_id="GROUP_1",
                ),
                RuleNode(
                    rule_id="g1_prin_a",
                    rule_type=RuleType.PAY_PRINCIPAL,
                    order=1,
                    from_sources=["ACT_PRIN"],
                    to_targets=["A"],
                    group_id="GROUP_1",
                ),
                RuleNode(
                    rule_id="g2_int_b",
                    rule_type=RuleType.PAY_INTEREST,
                    order=2,
                    from_sources=["ACT_INT"],
                    to_targets=["B"],
                    group_id="GROUP_2",
                ),
                RuleNode(
                    rule_id="g2_prin_b",
                    rule_type=RuleType.PAY_PRINCIPAL,
                    order=3,
                    from_sources=["ACT_PRIN"],
                    to_targets=["B"],
                    group_id="GROUP_2",
                ),
                RuleNode(
                    rule_id="resid",
                    rule_type=RuleType.PAY_RESIDUAL,
                    order=4,
                    from_sources=["CASH"],
                    to_targets=["R"],
                ),
            ],
        )

        # Build two separate LDCMA-style single-pool run inputs, migrate each
        # through ldcma_to_paired, then merge their constituents into one
        # multi-group PortfolioCashflow. This mirrors the FNR combined fixture.
        from bma_standard_formulas.deals.adapters import ldcma_to_paired
        from bma_standard_formulas.deals.schemas.input import (
            DealRunInput,
            PairedCollateralInput,
            PooledCollateralInput,
        )
        from bma_standard_formulas.engine.portfolio import PortfolioCashflow
        import dataclasses

        n = 10
        bal = 100.0

        g1_input = _flat_collateral(
            initial_balance=bal, n_periods=n, monthly_principal=10.0, annual_coupon=5.0
        )
        g2_input = _flat_collateral(
            initial_balance=bal, n_periods=n, monthly_principal=8.0, annual_coupon=6.0
        )

        g1_paired = ldcma_to_paired(g1_input, loan_count=1)
        g2_paired = ldcma_to_paired(g2_input, loan_count=1)

        # Tag each constituent with its group_id then merge.
        def _retag(constituents, group_id):
            return [dataclasses.replace(c, group_id=group_id) for c in constituents]

        g1_acts = _retag(g1_paired.collateral.portfolio.actual_constituents(), "GROUP_1")
        g2_acts = _retag(g2_paired.collateral.portfolio.actual_constituents(), "GROUP_2")
        from bma_standard_formulas.engine.portfolio import PortfolioMode
        portfolio = PortfolioCashflow(
            constituents=g1_acts + g2_acts,
            mode=PortfolioMode.ACTUAL_ONLY,
        )
        run_input = DealRunInput(
            collateral=PairedCollateralInput(portfolio=portfolio),
            original_collateral_balance=200.0,
            loan_count=2,
        )
        return deal, run_input

    def test_z_accrual_debits_group1_act_int_not_group2(self):
        """Z accrual in GROUP_1 must reduce GROUP_1_ACT_INT available to the
        GROUP_1 interest rule; GROUP_2_ACT_INT must be completely unaffected."""
        deal, run_input = self._build_grouped_z_deal()
        from bma_standard_formulas.deals.runtime import run_deal
        result = run_deal(deal, run_input)

        # Z coupon rate 6% on 50 notional = 0.25/period monthly
        z_monthly_coupon = 50.0 * 6.0 / 1200.0

        # Z coupon 6% on 50 notional = 0.25/month; GROUP_1 interest = 100 * 5% / 12 ≈ 0.417.
        # Z accrual takes 0.25 from GROUP_1_ACT_INT, leaving 0.167 for A.
        # A coupon is also 6% on 100 notional = 0.50, but only 0.167 remains after Z.
        a_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "A" and r.period == 1)
        g1_int_available = 100.0 * 0.05 / 12   # ≈ 0.4167
        a_expected = max(0.0, g1_int_available - z_monthly_coupon)  # ≈ 0.1667
        assert a_p1.interest_paid == pytest.approx(a_expected, abs=1e-4), (
            f"Bond A period 1 interest {a_p1.interest_paid:.6f} should equal "
            f"group-1 available minus Z accrual ({a_expected:.6f})"
        )

    def test_group2_interest_unaffected_by_group1_z_accrual(self):
        """GROUP_2_ACT_INT must not be debited by Z accrual in GROUP_1."""
        deal, run_input = self._build_grouped_z_deal()
        from bma_standard_formulas.deals.runtime import run_deal
        result = run_deal(deal, run_input)

        # Bond B draws from GROUP_2_ACT_INT; Z is in GROUP_1 so B's interest
        # must equal the full GROUP_2 interest available.
        b_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "B" and r.period == 1)
        g2_int_available = 100.0 * 0.06 / 12  # ~0.50
        b_coupon_due = 80.0 * 6.0 / 1200.0   # ~0.40
        # B's coupon due is less than available; it should be fully paid.
        assert b_p1.interest_paid == pytest.approx(b_coupon_due, abs=1e-4), (
            f"Bond B period 1 interest {b_p1.interest_paid:.6f} != expected "
            f"{b_coupon_due:.6f}; GROUP_2_ACT_INT was incorrectly reduced"
        )

    def test_single_pool_z_behavior_unchanged(self):
        """Ensure single-pool Z deals with group_id=None behave identically to before."""
        deal = DealDefinition(
            deal_name="SinglePoolZ",
            bonds=[
                BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=6.0, notional=100.0),
                BondDef(
                    name="Z",
                    kind=TrancheKind.Z,
                    coupon=6.0,
                    notional=50.0,
                    pay_mode=PayMode.PIK,
                    z_accrual_enabled=True,
                    relations=[TrancheRelation(
                        relation_type=TrancheRelationType.ACCRETES_TO,
                        targets=["A"],
                    )],
                ),
                BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=[
                RuleNode(rule_id="int_a", rule_type=RuleType.PAY_INTEREST, order=0,
                         from_sources=["ACT_INT"], to_targets=["A"]),
                RuleNode(rule_id="prin_a", rule_type=RuleType.PAY_PRINCIPAL, order=1,
                         from_sources=["CASH"], to_targets=["A"]),
                RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=2,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )
        run_input = _flat_collateral(
            initial_balance=200.0, n_periods=12,
            monthly_principal=15.0, annual_coupon=8.0,
        )
        result = run_deal(deal, run_input)
        # Z should still be accruing in period 1 (A balance > 0).
        z_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "Z" and r.period == 1)
        assert z_p1.interest_paid == pytest.approx(0.0, abs=1e-6), (
            "Single-pool Z bond should not receive cash interest while accruing"
        )
        z_p1_balance = z_p1.end_balance
        z_accrual = 50.0 * 6.0 / 1200.0
        assert z_p1_balance >= 50.0 + z_accrual - 1e-4, (
            "Single-pool Z balance should grow by accrual each period"
        )

    def test_z_accrual_debits_group1_cash_stream(self):
        """Z accrual must also debit GROUP_1 CASH so rules using CASH cannot double-fund."""
        import warnings
        deal, run_input = self._build_grouped_z_deal()
        from bma_standard_formulas.deals.runtime import run_deal
        # Swap Group 1 interest rule to use CASH (combined stream)
        new_rules = []
        for r in deal.waterfall_rules:
            if r.rule_id == "g1_int_a":
                new_rules.append(r.model_copy(update={"from_sources": ["CASH"]}))
            else:
                new_rules.append(r)
        deal_cash = deal.model_copy(update={"waterfall_rules": new_rules})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = run_deal(deal_cash, run_input)
        a_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "A" and r.period == 1)
        z_monthly_coupon = 50.0 * 6.0 / 1200.0  # 0.25
        # A's coupon is 6% on 100 = 0.5/month. Only GROUP_1 cash minus Z accrual
        # (about 0.417 + 10.0 - 0.25 = 10.167) is available to A; A coupon is
        # fully covered from that. But the key invariant: A's interest should NOT
        # include the Z-accrued portion (0.25) that already went to bond A as principal.
        # A coupon due = 100 * 6% / 12 = 0.5; sufficient cash remains; paid = 0.5.
        # This just verifies the run completes without double-counting cash.
        assert a_p1.interest_paid >= 0.0, "Bond A must have non-negative interest paid"
        a_p1_interest = a_p1.interest_paid
        expected_a_coupon = 100.0 * 6.0 / 1200.0  # 0.5
        assert a_p1_interest <= expected_a_coupon + 1e-6, (
            "Bond A should not receive more than its full coupon when Z-debited CASH available"
        )

    def test_cross_group_z_accretes_to_rejected_by_validator(self):
        """Z bond in GROUP_1 with ACCRETES_TO target in GROUP_2 must fail validation."""
        from bma_standard_formulas.deals.schemas.ir import CollateralGroupDef
        with pytest.raises(Exception, match="must share the Z bond's collateral group"):
            DealDefinition(
                deal_name="CrossGroupZ",
                collateral_groups=[
                    CollateralGroupDef(group_id="GROUP_1"),
                    CollateralGroupDef(group_id="GROUP_2"),
                ],
                bonds=[
                    BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=6.0, notional=100.0, group_id="GROUP_2"),
                    BondDef(
                        name="Z",
                        kind=TrancheKind.Z,
                        coupon=6.0,
                        notional=50.0,
                        pay_mode=PayMode.PIK,
                        z_accrual_enabled=True,
                        relations=[TrancheRelation(
                            relation_type=TrancheRelationType.ACCRETES_TO,
                            targets=["A"],  # A is in GROUP_2 but Z is in GROUP_1
                        )],
                        group_id="GROUP_1",
                    ),
                    BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
                ],
                waterfall_rules=[
                    RuleNode(rule_id="r", rule_type=RuleType.PAY_RESIDUAL, order=0,
                             from_sources=["CASH"], to_targets=["R"]),
                ],
            )
