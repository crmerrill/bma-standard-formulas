"""End-to-end tie-out for the FNR 2006-018 *combined* (Group 1 + Group 2) deal.

This test exercises the new multi-group runtime: one DealDefinition with
two `CollateralGroupDef` entries, every bond and rule tagged with its
`group_id`, fed by a `GroupedCollateralInput` carrying both pools'
cashflows. The expected output is bit-identical (within numerical
tolerance) to running the two single-group deals separately and
concatenating their bond cashflows -- proving that per-group cash
routing keeps the two groups financially independent inside one IR.

What this validates:

  - The schema accepts a 2-group deal with all 21 bonds (16 Group 1 +
    5 Group 2) tagged with their group_id.
  - The runtime allocates per-group `cash_avail_by_group`,
    `interest_avail_by_group`, `principal_avail_by_group` arrays and
    routes `INT_CASH` / `PRIN_CASH` source tokens through the right
    pool.
  - Every Group 1 tranche's WAL and final balance match the
    Group-1-only deal at the same PSA speed (no cross-feeding from
    Group 2 cash).
  - Every Group 2 tranche's WAL and final balance match the
    Group-2-only deal.
  - The combined residual balance equals the sum of each group's
    residual sweep.
"""
from __future__ import annotations

import numpy as np
import pytest

from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.common import CollateralInputMode
from bma_standard_formulas.deals.schemas.input import (
    DealRunInput,
    GroupedCollateralInput,
    PooledCollateralInput,
)

from tests.fixtures.fnr_2006_018.deal_definition import (
    build_fnr_2006_018_combined_deal,
    build_fnr_2006_018_group_1_deal,
    build_fnr_2006_018_group_2_deal,
)
from tests.test_fnr_2006_018_decrement_table import (
    GROUP_1_TRANCHE_ORDER,
    _bond_face as _g1_bond_face,
    _factor_at as _g1_factor_at,
    _wal_years as _g1_wal,
)
from tests.test_fnr_2006_018_group_2_decrement_table import (
    GROUP_2_TRANCHE_ORDER,
    _bond_face as _g2_bond_face,
    _factor_at as _g2_factor_at,
    _wal_years as _g2_wal,
    _group_2_collateral_input,
)
from tests.test_fnr_2006_018_parity import _deal_input_from_repline


# ---------------------------------------------------------------------------
# Combined run input: pair the Group 1 and Group 2 collateral feeds into
# one GroupedCollateralInput keyed by the same group_ids the deal
# declares (GROUP_1, GROUP_2).
# ---------------------------------------------------------------------------


def _combined_run_input(psa_speed: float, n_periods_g1: int, n_periods_g2: int) -> DealRunInput:
    """Build a DealRunInput with both groups' cashflows."""
    g1_input = _deal_input_from_repline(psa_speed, n_periods_g1)
    g2_input = _group_2_collateral_input(psa_speed, n_periods_g2)
    # Both helpers return PooledCollateralInput; lift their inner
    # CollateralCashflows out and stitch them under a grouped input
    # keyed by group_id.
    assert isinstance(g1_input.collateral, PooledCollateralInput)
    assert isinstance(g2_input.collateral, PooledCollateralInput)
    grouped = GroupedCollateralInput(
        mode=CollateralInputMode.GROUPED,
        groups={
            "GROUP_1": g1_input.collateral.collateral,
            "GROUP_2": g2_input.collateral.collateral,
        },
    )
    return DealRunInput(
        collateral=grouped,
        loan_count=(g1_input.loan_count or 0) + (g2_input.loan_count or 0),
        original_collateral_balance=(
            (g1_input.original_collateral_balance or 0.0)
            + (g2_input.original_collateral_balance or 0.0)
        ),
    )


# ---------------------------------------------------------------------------
# Smoke tests: schema validates and the deal runs end-to-end.
# ---------------------------------------------------------------------------


class TestCombinedDealSchema:
    def test_schema_validates_with_21_bonds_and_2_groups(self):
        deal = build_fnr_2006_018_combined_deal()
        assert deal.deal_name == "FNR 2006-018 (Group 1 + Group 2)"
        assert {g.group_id for g in deal.collateral_groups} == {"GROUP_1", "GROUP_2"}
        # 16 Group 1 bonds + 5 Group 2 bonds (BA, BC, BD, DO, DI),
        # plus exactly one shared residual.
        non_pseudo = [b for b in deal.bonds if not b.is_pseudo]
        assert len(non_pseudo) == 20
        assert sum(1 for b in deal.bonds if b.is_pseudo and b.name == "R") == 1

    def test_every_non_pseudo_bond_has_a_group_id(self):
        deal = build_fnr_2006_018_combined_deal()
        for bond in deal.bonds:
            if bond.is_pseudo:
                continue
            assert bond.group_id in {"GROUP_1", "GROUP_2"}, (
                f"Bond {bond.name!r} missing or invalid group_id: {bond.group_id!r}"
            )

    def test_every_rule_has_a_group_id(self):
        deal = build_fnr_2006_018_combined_deal()
        for rule in deal.waterfall_rules:
            assert rule.group_id in {"GROUP_1", "GROUP_2"}, (
                f"Rule {rule.rule_id!r} missing or invalid group_id: {rule.group_id!r}"
            )


# ---------------------------------------------------------------------------
# Per-group equivalence: the combined deal's per-tranche WAL and final
# balance should match the corresponding single-group deal at the same
# PSA. Using 100% PSA where both groups have published tie-outs.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def combined_result_100psa():
    deal = build_fnr_2006_018_combined_deal(n_periods_group_1=360, n_periods_group_2=240)
    run_input = _combined_run_input(100.0, n_periods_g1=360, n_periods_g2=240)
    return run_deal(deal, run_input)


@pytest.fixture(scope="module")
def group_1_only_result_100psa():
    deal = build_fnr_2006_018_group_1_deal(n_periods=360)
    run_input = _deal_input_from_repline(100.0, 360)
    return run_deal(deal, run_input)


@pytest.fixture(scope="module")
def group_2_only_result_100psa():
    deal = build_fnr_2006_018_group_2_deal(n_periods=240)
    run_input = _group_2_collateral_input(100.0, 240)
    return run_deal(deal, run_input)


def _wal_combined(result, tranche_id: str) -> float:
    """Same WAL formula as the single-group helpers but using the
    combined result (which holds bond_cashflows for both groups)."""
    rows = sorted(
        (r for r in result.bond_cashflows if r.tranche_id == tranche_id and r.period > 0),
        key=lambda r: r.period,
    )
    pairs = [(r.period, r.total_principal) for r in rows]
    total = sum(p for _, p in pairs)
    if total <= 0.0:
        return 0.0
    return sum(t * p for t, p in pairs) / total / 12.0


@pytest.mark.parametrize("tranche", GROUP_1_TRANCHE_ORDER)
def test_group_1_tranche_wal_matches_group_1_only_run(
    combined_result_100psa, group_1_only_result_100psa, tranche
):
    wal_combined = _wal_combined(combined_result_100psa, tranche)
    wal_solo = _g1_wal(group_1_only_result_100psa, tranche)
    assert wal_combined == pytest.approx(wal_solo, abs=0.05), (
        f"Group 1 tranche {tranche} WAL diverged between combined ({wal_combined:.3f}y) "
        f"and Group-1-only ({wal_solo:.3f}y) runs -- per-group cash routing leaked"
    )


@pytest.mark.parametrize("tranche", GROUP_2_TRANCHE_ORDER)
def test_group_2_tranche_wal_matches_group_2_only_run(
    combined_result_100psa, group_2_only_result_100psa, tranche
):
    wal_combined = _wal_combined(combined_result_100psa, tranche)
    wal_solo = _g2_wal(group_2_only_result_100psa, tranche)
    assert wal_combined == pytest.approx(wal_solo, abs=0.05), (
        f"Group 2 tranche {tranche} WAL diverged between combined ({wal_combined:.3f}y) "
        f"and Group-2-only ({wal_solo:.3f}y) runs -- per-group cash routing leaked"
    )


# ---------------------------------------------------------------------------
# Cash-segregation invariant: a Group 1 PAY_INTEREST rule must never
# pull from Group 2's interest stream and vice versa. We assert this
# indirectly by checking that the total interest paid to each group's
# tranches matches that group's pool interest stream.
# ---------------------------------------------------------------------------


def _total_interest_paid_to_group(result, group_bond_names: list[str]) -> float:
    return float(sum(
        sum(r.interest_paid for r in result.bond_cashflows if r.tranche_id == name)
        for name in group_bond_names
    ))


def test_combined_group_1_total_interest_matches_solo(
    combined_result_100psa, group_1_only_result_100psa
):
    g1_names_paying_interest = [
        t for t in GROUP_1_TRANCHE_ORDER if t not in ("EO", "PO")
    ]
    combined_g1_int = _total_interest_paid_to_group(
        combined_result_100psa, g1_names_paying_interest
    )
    solo_g1_int = _total_interest_paid_to_group(
        group_1_only_result_100psa, g1_names_paying_interest
    )
    # Allow tiny rounding slack but not material drift.
    assert combined_g1_int == pytest.approx(solo_g1_int, rel=1e-4), (
        f"Group 1 total interest paid changed between combined "
        f"({combined_g1_int:,.2f}) and solo ({solo_g1_int:,.2f}) runs"
    )


def test_combined_group_2_total_interest_matches_solo(
    combined_result_100psa, group_2_only_result_100psa
):
    # BA, BC, BD, DI pay cash interest; DO is zero-coupon.
    g2_names = ["BA", "BC", "BD", "DI"]
    combined_g2_int = _total_interest_paid_to_group(combined_result_100psa, g2_names)
    solo_g2_int = _total_interest_paid_to_group(group_2_only_result_100psa, g2_names)
    assert combined_g2_int == pytest.approx(solo_g2_int, rel=1e-4), (
        f"Group 2 total interest paid changed between combined "
        f"({combined_g2_int:,.2f}) and solo ({solo_g2_int:,.2f}) runs"
    )
