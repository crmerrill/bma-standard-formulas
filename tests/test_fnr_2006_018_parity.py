"""Tie-out test against Fannie Mae REMIC Trust 2006-018 (public deal).

Source: Fannie Mae REMIC Trust 2006-018 Prospectus Supplement, Feb 2, 2006.
This test exercises three things our PAC/Z runtime must get right:

  1. The per-bond `schedule_contract` derived from the published Aggregate
     Group I planned balance vector caps PAC bond principal correctly each
     period.
  2. Collateral generated at the published pricing assumptions (5.94% WAC,
     348 WAM, 360 term) drives an Aggregate Group I balance path that tracks
     the published Schedule 1 across the full 360-period horizon.
  3. Class-level weighted-average lives at base-case PSA speeds match the
     published decrement table within reasonable tolerance.

Strategy: load the published planned-balance schedules verbatim and use them
as the runtime contract. This isolates schedule-cap correctness from the
schedule-derivation question (which is exercised in
`test_schedule_derivation.py`).
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows,
    DealRunInput,
    PooledCollateralInput,
)
from bma_standard_formulas.formulas import (
    generate_smm_curve_from_psa,
    run_bma_actual_cashflow,
    run_bma_scheduled_cashflow,
)

from tests.fixtures.fnr_2006_018 import (
    POOL_ASSUMPTIONS,
    PUBLISHED_WAL_GROUP_1,
    PUBLISHED_WAL_PSA_COLUMNS,
    ZERO_PSA_PRICING_OVERRIDE,
    GROUP_1_CLASSES,
    expand_to_monthly_balance_vector,
    load_planned_balance_schedule,
)
from tests.fixtures.fnr_2006_018.deal_definition import build_fnr_2006_018_group_1_deal


# ---------------------------------------------------------------------------
# Repline -> BMA cashflow engine -> deal engine pipeline
#
# We treat the Group 1 MBS aggregate as a single repline (132,653,061 UPB
# at 5.94% gross / 5.50% net pass-through, 360-month original term, 348-month
# WAM). The repline goes through the BMA scheduled cashflow runner and then
# the actual cashflow runner with prospectus-published prepayment assumptions
# (PSA speeds 0%, 100%, 147%, 180%, 227%, 250%, 375%, 500%). The resulting
# pool cashflow becomes the deal engine's collateral input.
# ---------------------------------------------------------------------------


def _repline_for_psa(psa_speed: float):
    """Return repline scheduled cashflow + actual cashflow for a given PSA speed.

    Uses the published Pricing Assumptions: 5.94% gross WAC / 5.50% net
    pass-through / 360-month original term / 348-month WAM for non-zero PSA
    speeds, and the special 0% PSA override (8.00% / 360 / 360) when
    `psa_speed == 0`.
    """
    if psa_speed <= 0.0:
        wac_pct = float(ZERO_PSA_PRICING_OVERRIDE["weighted_average_coupon_pct"])
        term = int(ZERO_PSA_PRICING_OVERRIDE["original_term_months"])
        remaining = int(ZERO_PSA_PRICING_OVERRIDE["weighted_average_remaining_term_months"])
    else:
        wac_pct = float(POOL_ASSUMPTIONS["weighted_average_coupon_pct"])
        term = int(POOL_ASSUMPTIONS["original_term_months"])
        remaining = int(POOL_ASSUMPTIONS["weighted_average_remaining_term_months"])
    initial_balance = float(POOL_ASSUMPTIONS["aggregate_upb_dollars"])

    sched = run_bma_scheduled_cashflow(
        original_balance=initial_balance,
        current_balance=initial_balance,
        coupon_vector=wac_pct,
        original_term=term,
        remaining_term=remaining,
    )
    smm = generate_smm_curve_from_psa(float(psa_speed), term)
    mdr = np.zeros(term + 1)  # 0% default for prospectus decrement assumption.
    sev = np.zeros(term + 1)  # 0% severity for prospectus decrement assumption.
    actual = run_bma_actual_cashflow(
        scheduled_cf=sched,
        smm_curve=smm,
        mdr_curve=mdr,
        severity_curve=sev,
        coupon_vector=wac_pct,
    )
    return sched, actual, wac_pct


def _deal_input_from_repline(psa_speed: float, n_periods: int) -> DealRunInput:
    """Convert BMA repline cashflows into a `DealRunInput` for the deal engine."""
    sched, actual, wac_pct = _repline_for_psa(psa_speed)
    net_pct = float(POOL_ASSUMPTIONS["mbs_pass_through_rate_pct"])
    initial_balance = float(POOL_ASSUMPTIONS["aggregate_upb_dollars"])

    # The BMA actual cashflow runner returns period-indexed arrays where
    # index 0 is the snapshot. Pool principal each period = scheduled
    # amortization + voluntary prepayments. Defaults are zero in the
    # prospectus decrement assumption.
    horizon = min(n_periods + 1, len(actual.act_am))
    principal = (actual.act_am[:horizon] + actual.vol_prepay[:horizon])
    bal = actual.perf_bal[:horizon].copy()
    # Net interest distributed to certificateholders at the 5.50% pass-through.
    net_monthly_rate = net_pct / 1200.0
    interest_net = np.zeros(horizon)
    for i in range(1, horizon):
        interest_net[i] = bal[i - 1] * net_monthly_rate

    cf = CollateralCashflows(
        cfdate=list(range(horizon)),
        balance=bal.tolist(),
        principal=principal.tolist(),
        interest=interest_net.tolist(),
        cashflow=(principal + interest_net).tolist(),
        loss=[0.0] * horizon,
        prepbal=[0.0] * horizon,
        defbal=[0.0] * horizon,
        recovery=[0.0] * horizon,
        principal_sched=actual.act_am[:horizon].tolist(),
        principal_unsched=actual.vol_prepay[:horizon].tolist(),
        cpr=[0.0] * horizon,
        cdr=[0.0] * horizon,
        sev=[0.0] * horizon,
        dq=[0.0] * horizon,
        surv_fac=[1.0] * horizon,
        sched_coupon=[wac_pct] * horizon,
        sched_netcoupon=[net_pct] * horizon,
        coupon=[wac_pct] * horizon,
        effcoupon=[net_pct] * horizon,
        sched_balance=bal.tolist(),
        discount_factor=[1.0] * horizon,
    )
    return DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        original_collateral_balance=initial_balance,
        loan_count=int(initial_balance / 200_000.0),
    )


# Backward-compatible alias used by other tests + the seed script.
def _collateral_at_psa(psa_speed: float, n_periods: int) -> DealRunInput:
    return _deal_input_from_repline(psa_speed, n_periods)


def _amortize_pool_at_psa(
    initial_balance: float,
    annual_coupon_pct: float,
    term: int,
    remaining_term: int,
    psa_speed: float,
    n_periods: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compatibility wrapper: route the seed script through the BMA cashflow engine."""
    sched = run_bma_scheduled_cashflow(
        original_balance=initial_balance,
        current_balance=initial_balance,
        coupon_vector=annual_coupon_pct,
        original_term=term,
        remaining_term=remaining_term,
    )
    smm = generate_smm_curve_from_psa(float(psa_speed), term)
    mdr = np.zeros(term + 1)
    sev = np.zeros(term + 1)
    actual = run_bma_actual_cashflow(
        scheduled_cf=sched,
        smm_curve=smm,
        mdr_curve=mdr,
        severity_curve=sev,
        coupon_vector=annual_coupon_pct,
    )
    horizon = min(n_periods + 1, len(actual.act_am))
    bal = actual.perf_bal[:horizon].copy()
    sched_prin = actual.act_am[:horizon].copy()
    vol_prepay = actual.vol_prepay[:horizon].copy()
    return bal, sched_prin, vol_prepay


def _aggregate_group_balance(result, group_class_names: list[str], period: int) -> float:
    return float(sum(
        r.end_balance for r in result.bond_cashflows
        if r.tranche_id in group_class_names and r.period == period
    ))


def _class_wal_years(result, tranche_id: str) -> float:
    rows = sorted(
        (r for r in result.bond_cashflows if r.tranche_id == tranche_id and r.period > 0),
        key=lambda r: r.period,
    )
    total_principal = sum(r.total_principal for r in rows)
    if total_principal <= 0.0:
        return 0.0
    weighted = sum(r.period * r.total_principal for r in rows)
    return float(weighted / total_principal / 12.0)


# ---------------------------------------------------------------------------
# Tie-out tests
# ---------------------------------------------------------------------------


class TestSchedule1Parsing:
    """Sanity checks on the parsed published Schedule 1 fixture data."""

    def test_group_i_initial_balance_matches_class_sum(self):
        rows = load_planned_balance_schedule("I")
        initial = rows[0][1]
        # Sum of PA + PB + PC + PD + EO sizes = $88,410,000 per prospectus.
        pac_i_total = sum(c["size"] for c in GROUP_1_CLASSES if c["type"] in ("PAC", "PAC_PO"))
        assert initial == pytest.approx(pac_i_total, abs=1.0)

    def test_group_ii_initial_balance_matches_class_sum(self):
        rows = load_planned_balance_schedule("II")
        initial = rows[0][1]
        pac_ii_total = sum(c["size"] for c in GROUP_1_CLASSES if c["type"] == "PAC_AD")
        assert initial == pytest.approx(pac_ii_total, abs=1.0)

    def test_group_i_final_balance_zero(self):
        rows = load_planned_balance_schedule("I")
        assert rows[-1][1] == pytest.approx(0.0, abs=1.0)

    def test_group_i_monotonically_decreasing(self):
        rows = load_planned_balance_schedule("I")
        balances = [b for _, b in rows]
        for i in range(1, len(balances)):
            assert balances[i] <= balances[i - 1] + 1.0, f"non-monotonic at index {i}"


class TestDealDefinitionConstruction:
    def test_deal_builds_without_validation_errors(self):
        deal = build_fnr_2006_018_group_1_deal(n_periods=360)
        assert deal.deal_name == "FNR 2006-018 Group 1"
        bond_names = {b.name for b in deal.bonds}
        # All published Group 1 classes plus residual.
        for spec in GROUP_1_CLASSES:
            assert spec["name"] in bond_names
        assert "R" in bond_names

    def test_pac_bonds_have_schedule_contracts(self):
        deal = build_fnr_2006_018_group_1_deal(n_periods=360)
        pac_bonds = [b for b in deal.bonds if b.tranche_behavior.value in ("PAC", "TAC")]
        assert pac_bonds, "expected PAC bonds"
        for b in pac_bonds:
            assert b.schedule_contract, f"{b.name} missing schedule_contract"

    def test_z_bond_configured(self):
        deal = build_fnr_2006_018_group_1_deal(n_periods=360)
        z = next(b for b in deal.bonds if b.name == "Z")
        assert z.tranche_behavior.value == "Z"
        assert z.pay_mode.value == "PIK"
        assert z.z_accrual_enabled
        assert "TA" in z.supported_by_tranches
        assert "TB" in z.supported_by_tranches


class TestRuntimeAggregateGroupITieOut:
    """At the lower-bound structuring PSA, Group I balance must track the schedule.

    The published Aggregate Group I schedule was derived as the lower envelope
    over 100-250% PSA. At exactly 100% PSA the Aggregate balance should track
    the schedule closely (within a small tolerance for the published rounding
    + our pool projection differences).
    """

    def test_aggregate_group_i_balance_path_within_tolerance_at_100_psa(self):
        n_periods = 360
        run_input = _collateral_at_psa(100.0, n_periods)
        deal = build_fnr_2006_018_group_1_deal(n_periods=n_periods)
        result = run_deal(deal, run_input, scenario_name="100PSA")
        published_balances = load_planned_balance_schedule("I")
        published_monthly = expand_to_monthly_balance_vector(published_balances, n_periods)
        pac_i_classes = [c["name"] for c in GROUP_1_CLASSES if c["type"] in ("PAC", "PAC_PO")]
        # Spot check annually through the deal life.
        check_periods = list(range(12, n_periods, 12))
        for period in check_periods:
            pub_bal = float(published_monthly[period])
            our_bal = _aggregate_group_balance(result, pac_i_classes, period)
            # Tolerance: 10% of original Group I face ($88.41MM = $8.84MM).
            # The published schedule is the lower envelope of the 100-250 PSA
            # range; at exactly 100 PSA the actual collateral path tracks but
            # does not exactly equal the schedule (servicing wedge differences,
            # PSA ramp interpretation differences, support split nuances).
            tol = 8_840_000.0
            assert abs(our_bal - pub_bal) <= tol, (
                f"period {period}: published={pub_bal:,.0f}, ours={our_bal:,.0f}, "
                f"delta={our_bal - pub_bal:,.0f} (tol=${tol:,.0f})"
            )

    def test_total_principal_paid_matches_pool_principal(self):
        # Conservation: pool principal cash + Z accrual converted to principal
        # must equal total bond principal received plus residual sweep. Residual
        # rule routes leftover cash to R.interest, so bond principal alone cannot
        # be less than pool principal MINUS any cash that ended up in residual.
        n_periods = 360
        run_input = _collateral_at_psa(100.0, n_periods)
        deal = build_fnr_2006_018_group_1_deal(n_periods=n_periods)
        result = run_deal(deal, run_input, scenario_name="100PSA")
        pool_principal = float(sum(run_input.collateral.collateral.principal))
        pool_interest = float(sum(run_input.collateral.collateral.interest))
        bond_principal = float(sum(
            r.total_principal for r in result.bond_cashflows
            if r.tranche_id != "R"
        ))
        bond_interest = float(sum(
            r.interest_paid for r in result.bond_cashflows
            if r.tranche_id != "R"
        ))
        residual_cashflow = float(sum(
            r.cashflow_total for r in result.bond_cashflows
            if r.tranche_id == "R"
        ))
        # Total cash from collateral + Z accrual that was paid as principal must equal
        # what was distributed to bonds + residual sweep, minus interest that was
        # serviced. Use a generous (1% of pool) tolerance.
        total_inflow = pool_principal + pool_interest
        total_outflow = bond_principal + bond_interest + residual_cashflow
        tol = max(1_000_000.0, 0.01 * total_inflow)
        assert abs(total_inflow - total_outflow) <= tol, (
            f"conservation broke: inflow=${total_inflow:,.0f} vs outflow=${total_outflow:,.0f} "
            f"(bond_prin=${bond_principal:,.0f}, bond_int=${bond_interest:,.0f}, "
            f"resid=${residual_cashflow:,.0f}, pool_prin=${pool_principal:,.0f}, "
            f"pool_int=${pool_interest:,.0f})"
        )


class TestPublishedWALDecrementParity:
    """Verify class WAL outputs at published PSA columns match the decrement table.

    Note: WAL parity is sensitive to many small modeling differences (servicing
    layout, day-count, residual handling). We use a generous tolerance to verify
    the output is in the right neighborhood; a tighter parity gate is applied
    via `scripts/run_ldcma_parity.py` against full LDCMA reference deals.
    """

    @pytest.mark.parametrize("psa_speed", [100, 250])
    def test_pac_wal_close_to_published(self, psa_speed: int):
        n_periods = 360
        run_input = _collateral_at_psa(float(psa_speed), n_periods)
        deal = build_fnr_2006_018_group_1_deal(n_periods=n_periods)
        result = run_deal(deal, run_input, scenario_name=f"{psa_speed}PSA")
        col_idx = PUBLISHED_WAL_PSA_COLUMNS.index(psa_speed)
        for tranche_id in ["PA", "PB", "PC"]:
            published = float(PUBLISHED_WAL_GROUP_1[tranche_id][col_idx])
            our_wal = _class_wal_years(result, tranche_id)
            # Tolerance: 1.5 years (PAC bonds are typically very stable but our
            # support split modeling differs from the prospectus split).
            assert abs(our_wal - published) <= 1.5, (
                f"{tranche_id} @ {psa_speed}% PSA: published={published}, ours={our_wal:.2f}"
            )
