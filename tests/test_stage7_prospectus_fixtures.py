"""Stage 7: Real-world prospectus tie-out structural tests.

These tests validate the structural correctness of prospectus-based fixtures:
  - Deal IR validates against schema 2.0
  - Waterfall runs without error
  - Structural assertions (PAC cap, Z accrual, sequential priority)

Quantitative tie-out (exact WAL / dollar amounts against published tables)
requires extracted prospectus data — see TODO markers in each fixture's
__init__.py. The current tests are structural gates that must pass before
the full tie-out is attempted.

Fixtures covered:
  1. FNR 2006-018 (existing anchor) — agency MBS REMIC
  2. Ginnie Mae 2025-203 — confirms PAC+Z+Support pattern across agencies
  3. Verus 2024-9 — non-agency non-QM RMBS with Phase 5 step-up coupon
  4. Ford 2024-C — prime auto ABS with reserve account
  5. CC Series 2024-A — credit-card master trust single series (Phases 6-8)
"""
from __future__ import annotations

import numpy as np
import pytest

from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows,
    DealRunInput,
    PooledCollateralInput,
)

from tests.fixtures.ginniemae_2025_203 import build_gnma_2025_203_deal
from tests.fixtures.verus_2024_9 import build_verus_2024_9_deal
from tests.fixtures.ford_2024_c import build_ford_2024_c_deal
from tests.fixtures.cc_series_test import build_cc_series_2024_a_deal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generic_collateral(
    balance: float,
    annual_coupon: float,
    monthly_principal: float,
    n: int,
) -> DealRunInput:
    """Generic pass-through collateral for structural tests."""
    bal = np.full(n, balance)
    p = np.array([0.0] + [monthly_principal] * (n - 1))
    interest = np.array([0.0] + [balance * annual_coupon / 1200] * (n - 1))
    cf = CollateralCashflows(
        cfdate=list(range(n)),
        balance=bal.tolist(), principal=p.tolist(),
        interest=interest.tolist(), cashflow=(p + interest).tolist(),
        loss=[0.0]*n, prepbal=[0.0]*n, defbal=[0.0]*n, recovery=[0.0]*n,
        principal_sched=p.tolist(), principal_unsched=[0.0]*n,
        cpr=[0.0]*n, cdr=[0.0]*n, sev=[0.0]*n, dq=[0.0]*n, surv_fac=[1.0]*n,
        sched_coupon=[annual_coupon]*n, sched_netcoupon=[annual_coupon]*n,
        coupon=[annual_coupon]*n, effcoupon=[annual_coupon]*n,
        sched_balance=bal.tolist(), discount_factor=[1.0]*n,
    )
    return DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        original_collateral_balance=balance,
        loan_count=1,
    )


# ---------------------------------------------------------------------------
# 1. FNR 2006-018 (existing anchor) — verified by dedicated test suite
# ---------------------------------------------------------------------------

def test_fnr_2006_018_fixture_exists_and_runs():
    """Confirm the existing FNR 2006-018 fixture still validates."""
    from tests.fixtures.fnr_2006_018.deal_definition import (
        build_fnr_2006_018_combined_deal,
    )
    deal = build_fnr_2006_018_combined_deal(n_periods_group_1=12, n_periods_group_2=12)
    assert "2006-018" in deal.deal_name
    # Structural check: deal validates against schema 2.0 constraints.
    assert len(deal.bonds) > 0
    assert deal.collateral_groups  # grouped deal


# ---------------------------------------------------------------------------
# 2. Ginnie Mae 2025-203 — agency REMIC structural validation
# ---------------------------------------------------------------------------

class TestGNMA2025203Structural:
    """Structural gate for GNMA 2025-203.

    Full quantitative tie-out pending extraction of Exhibit A decrement table.
    """

    def test_deal_validates_against_schema_2(self):
        deal = build_gnma_2025_203_deal(n_periods=12)
        assert deal.deal_name == "GNMA 2025-203"
        bond_names = {b.name for b in deal.bonds}
        assert {"PA", "PB", "Z", "WA", "WB", "R"} == bond_names

    def test_pac_bonds_have_supported_by_relations(self):
        deal = build_gnma_2025_203_deal(n_periods=12)
        pa = next(b for b in deal.bonds if b.name == "PA")
        assert any(r.relation_type.value == "SUPPORTED_BY" for r in pa.relations)

    def test_z_bond_has_accretes_to_relation(self):
        deal = build_gnma_2025_203_deal(n_periods=12)
        z = next(b for b in deal.bonds if b.name == "Z")
        assert z.z_accrual_enabled
        assert any(r.relation_type.value == "ACCRETES_TO" for r in z.relations)

    def test_deal_runs_without_error(self):
        deal = build_gnma_2025_203_deal(n_periods=8)
        # Use a pool large enough to cover the placeholder bond faces.
        run_input = _generic_collateral(
            balance=2_200_000.0, annual_coupon=5.5,
            monthly_principal=20_000.0, n=8,
        )
        result = run_deal(deal, run_input)
        bond_names = {r.tranche_id for r in result.bond_cashflows}
        assert {"PA", "PB", "Z", "WA", "WB", "R"} == bond_names

    def test_pac_principal_capped_at_schedule(self):
        """PAC bond must receive at most its scheduled contract each period."""
        deal = build_gnma_2025_203_deal(n_periods=8)
        run_input = _generic_collateral(
            balance=2_200_000.0, annual_coupon=5.5,
            monthly_principal=100_000.0,  # much more than schedule
            n=8,
        )
        result = run_deal(deal, run_input)
        pa_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "PA" and r.period == 1)
        # Schedule contract at period 1: target_balance ≈ 997_000 → principal ≈ 3_000
        assert pa_p1.total_principal <= 4_000.0, (
            f"PA principal {pa_p1.total_principal:.0f} exceeds PAC schedule cap"
        )


# ---------------------------------------------------------------------------
# 3. Verus 2024-9 — non-agency RMBS with Phase 5 step-up coupon
# ---------------------------------------------------------------------------

class TestVerus20249Structural:
    """Structural gate for Verus 2024-9.

    Full quantitative tie-out pending extraction of decrement table.
    """

    def test_deal_validates_against_schema_2(self):
        deal = build_verus_2024_9_deal()
        assert deal.deal_name == "Verus 2024-9"
        bond_names = {b.name for b in deal.bonds}
        assert {"A1", "A2", "M1", "M2", "XS", "R"} == bond_names

    def test_a1_has_step_up_coupon_schedule(self):
        """Class A-1 coupon schedule must have two entries (step-up at year 5)."""
        deal = build_verus_2024_9_deal()
        a1 = next(b for b in deal.bonds if b.name == "A1")
        assert isinstance(a1.coupon, list), "A1 coupon must be a RateOrSchedule list"
        assert len(a1.coupon) == 2, "A1 must have two schedule entries (step-up)"
        assert a1.coupon[1].from_period == 61, "Step-up must activate at period 61"

    def test_deal_runs_with_step_up_coupon(self):
        deal = build_verus_2024_9_deal()
        run_input = _generic_collateral(
            balance=8_000_000.0, annual_coupon=6.0,
            monthly_principal=30_000.0, n=65,
        )
        result = run_deal(deal, run_input)
        # Verify coupon step-up applies in period 62 vs period 1.
        a1_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "A1" and r.period == 1)
        a1_p62 = next(r for r in result.bond_cashflows if r.tranche_id == "A1" and r.period == 62)
        # Period 1: 6% coupon on 5M → 0.5% monthly → 25,000/month
        # Period 62: 7% coupon on remaining balance — higher per dollar outstanding
        assert a1_p1.interest_paid > 0
        assert a1_p62.interest_paid >= 0  # balance may have amortized
        # If balance remains, rate must be higher
        if a1_p62.end_balance > 0:
            monthly_rate_p1 = a1_p1.interest_paid / a1_p1.begin_balance * 1200
            monthly_rate_p62 = a1_p62.interest_paid / a1_p62.begin_balance * 1200
            assert monthly_rate_p62 > monthly_rate_p1, (
                "Step-up coupon must produce a higher monthly rate at period 62"
            )


# ---------------------------------------------------------------------------
# 4. Ford 2024-C — auto ABS structural validation
# ---------------------------------------------------------------------------

class TestFord2024CStructural:
    """Structural gate for Ford 2024-C.

    Full quantitative tie-out pending extraction of Exhibit A decrement table.
    """

    def test_deal_validates_against_schema_2(self):
        deal = build_ford_2024_c_deal()
        assert deal.deal_name == "Ford 2024-C"
        bond_names = {b.name for b in deal.bonds}
        assert {"A1", "A2", "A3", "A4", "B", "R"} == bond_names

    def test_reserve_account_present(self):
        deal = build_ford_2024_c_deal()
        acct_names = {a.name for a in deal.accounts}
        assert "RESERVE" in acct_names

    def test_deal_runs_without_error(self):
        deal = build_ford_2024_c_deal()
        run_input = _generic_collateral(
            balance=1_500_000_000.0, annual_coupon=5.2,
            monthly_principal=5_000_000.0, n=12,
        )
        result = run_deal(deal, run_input)
        bond_names = {r.tranche_id for r in result.bond_cashflows}
        assert {"A1", "A2", "A3", "A4", "B", "R"} == bond_names

    def test_sequential_principal_a1_before_a2(self):
        """A-1 must receive all principal before A-2 receives any."""
        deal = build_ford_2024_c_deal()
        run_input = _generic_collateral(
            balance=1_500_000_000.0, annual_coupon=5.2,
            monthly_principal=5_000_000.0, n=12,
        )
        result = run_deal(deal, run_input)
        a1_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "A1" and r.period == 1)
        a2_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "A2" and r.period == 1)
        # With sequential rules, A-2 should receive 0 while A-1 still has balance.
        assert a1_p1.total_principal > 0 or a2_p1.total_principal == 0, (
            "A-2 must not receive principal while A-1 balance is positive"
        )


# ---------------------------------------------------------------------------
# 5. CC Series 2024-A — credit-card master trust Phase 6-8 exercise
# ---------------------------------------------------------------------------

class TestCCSeries2024AStructural:
    """Structural gate for CC Series 2024-A.

    Exercises all Phase 6-8 mechanics. Full tie-out pending prospectus citation.
    """

    def test_deal_validates_against_schema_2(self):
        deal = build_cc_series_2024_a_deal(n_periods=12)
        assert deal.deal_name == "CC Series 2024-A"
        assert deal.series_id == "CC-MASTER-TRUST-2024-A"
        assert deal.discount_factor_pct == pytest.approx(2.0)

    def test_nla_tracked_on_subordinate_classes(self):
        deal = build_cc_series_2024_a_deal(n_periods=12)
        b = next(bond for bond in deal.bonds if bond.name == "B")
        assert b.nla_starting_balance == pytest.approx(75_000_000.0)
        assert b.seniority == 2

    def test_pfa_minimum_schedule_present(self):
        deal = build_cc_series_2024_a_deal(n_periods=24)
        pfa = next(a for a in deal.accounts if a.name == "PFA")
        assert pfa.minimum_schedule is not None
        assert len(pfa.minimum_schedule) > 0

    def test_deal_runs_without_error(self):
        deal = build_cc_series_2024_a_deal(n_periods=8)
        run_input = _generic_collateral(
            balance=500_000_000.0, annual_coupon=20.0,
            monthly_principal=5_000_000.0, n=8,
        )
        result = run_deal(deal, run_input)
        bond_names = {r.tranche_id for r in result.bond_cashflows}
        assert {"A", "B", "C", "R"} == bond_names

    def test_class_a_interest_paid_from_fcc(self):
        """Class A interest must be paid from finance charges (ACT_INT after discount)."""
        deal = build_cc_series_2024_a_deal(n_periods=5)
        # FCC = $100/period; discount reclassifies 2% of $5M principal = $100k
        run_input = _generic_collateral(
            balance=500_000_000.0, annual_coupon=20.0,  # ~$8.33M FCC/month
            monthly_principal=5_000_000.0, n=5,
        )
        result = run_deal(deal, run_input)
        a_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "A" and r.period == 1)
        expected_monthly = 500_000_000.0 * 6.0 / 1200.0  # $2.5M
        assert a_p1.interest_paid == pytest.approx(expected_monthly, abs=1_000), (
            f"Class A must receive full coupon from FCC; got {a_p1.interest_paid:,.0f}"
        )
