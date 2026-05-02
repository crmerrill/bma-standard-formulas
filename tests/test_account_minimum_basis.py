"""Verifies that AccountDef.minimum_basis and starting_basis are honored
at runtime.

Pre-fix behavior (silently buggy):
    The runtime always treated `minimum_basis` as ORIGINAL_COLLATERAL — it
    computed `required_minimum` once at period 0 against
    `collateral_balance_0` and broadcast that single value across every
    period. Same for `starting_basis`. The IR accepted any enum value but
    the runtime ignored the choice.

Post-fix behavior (proposal Q in waterfall_ir_design.md):
    The runtime honors all four basis values and recomputes per-period
    floors for COLLATERAL_BALANCE (steps down with pool amortization) and
    NOTE_BALANCE (steps down with bond amortization).

Each test below builds a minimal three-bond deal that uses the FNR
Group 2 collateral input (real amortizing pool with known monotonic
decline at 100% PSA over 240 months) so we can verify the floor actually
moves with the underlying balance.
"""
from __future__ import annotations

import numpy as np
import pytest

from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.common import (
    AccountType,
    CouponType,
    MinimumBasis,
    RuleType,
    TrancheType,
)
from bma_standard_formulas.deals.schemas.ir import (
    AccountDef,
    BondDef,
    DealDefinition,
    RuleNode,
)

from tests.test_fnr_2006_018_group_2_decrement_table import (
    _group_2_collateral_input,
)

GROUP_2_FACE = 128_600_000.0


def _make_test_deal(
    *,
    starting_amount: float = 0.0,
    starting_pct: float | None = None,
    starting_basis: MinimumBasis = MinimumBasis.FIXED_DOLLAR,
    minimum_amount: float = 0.0,
    minimum_pct: float | None = None,
    minimum_basis: MinimumBasis = MinimumBasis.FIXED_DOLLAR,
) -> DealDefinition:
    """A tiny deal: one cash-pay bond, one reserve account, one residual.

    The bond is sized to absorb the entire pool so the note stack
    amortizes monotonically with the pool, making `NOTE_BALANCE`
    behavior easy to verify.
    """
    return DealDefinition(
        deal_name="MinimumBasisTest",
        bonds=[
            BondDef(
                name="A",
                tranche_type=TrancheType.SEQUENTIAL,
                coupon_type=CouponType.FIXED,
                coupon=5.5,
                size_pct=100.0,
            ),
            BondDef(
                name="R",
                tranche_type=TrancheType.RESIDUAL,
                is_bond=False,
                is_pseudo=True,
            ),
        ],
        accounts=[
            AccountDef(
                name="ReserveAcct",
                account_type=AccountType.RESERVE,
                starting_amount=starting_amount,
                starting_pct=starting_pct,
                starting_basis=starting_basis,
                minimum_amount=minimum_amount,
                minimum_pct=minimum_pct,
                minimum_basis=minimum_basis,
            ),
        ],
        waterfall_rules=[
            RuleNode(rule_id="r_int", rule_type=RuleType.PAY_INTEREST,
                     order=0, from_sources=["INT_CASH"], to_targets=["A"]),
            RuleNode(rule_id="r_prin", rule_type=RuleType.PAY_PRINCIPAL,
                     order=1, from_sources=["PRIN_CASH"], to_targets=["A"]),
            RuleNode(rule_id="r_resid", rule_type=RuleType.PAY_RESIDUAL,
                     order=2, from_sources=["CASH"], to_targets=["R"]),
        ],
    )


@pytest.fixture(scope="module")
def run_input():
    return _group_2_collateral_input(100.0, 240)


def _account_required_minimum(deal: DealDefinition, run_input) -> np.ndarray:
    result = run_deal(deal, run_input, scenario_name="100PSA")
    rows = [r for r in result.deal_accounts if r.account_id == "ReserveAcct"]
    rows.sort(key=lambda r: r.period)
    return np.array([r.required_minimum for r in rows])


# ---------------------------------------------------------------------------
# minimum_basis
# ---------------------------------------------------------------------------


def test_fixed_dollar_minimum_is_constant(run_input):
    """FIXED_DOLLAR uses minimum_amount, ignoring any pct."""
    deal = _make_test_deal(
        minimum_amount=1_000_000.0,
        minimum_pct=99.0,  # should be ignored under FIXED_DOLLAR
        minimum_basis=MinimumBasis.FIXED_DOLLAR,
    )
    floors = _account_required_minimum(deal, run_input)
    assert floors[0] == pytest.approx(1_000_000.0)
    assert floors[-1] == pytest.approx(1_000_000.0)
    # Must be exactly constant
    assert np.allclose(floors, 1_000_000.0)


def test_original_collateral_is_constant_pct_of_initial_pool(run_input):
    """ORIGINAL_COLLATERAL uses pct × period-0 pool balance, held constant."""
    deal = _make_test_deal(
        minimum_pct=0.5,
        minimum_basis=MinimumBasis.ORIGINAL_COLLATERAL,
    )
    floors = _account_required_minimum(deal, run_input)
    expected = 0.5 / 100.0 * GROUP_2_FACE
    assert floors[0] == pytest.approx(expected, rel=1e-3)
    assert floors[-1] == pytest.approx(expected, rel=1e-3)
    assert np.allclose(floors, expected, rtol=1e-3)


def test_collateral_balance_decrements_with_pool(run_input):
    """COLLATERAL_BALANCE: floor steps down as the pool amortizes."""
    deal = _make_test_deal(
        minimum_pct=0.5,
        minimum_basis=MinimumBasis.COLLATERAL_BALANCE,
    )
    floors = _account_required_minimum(deal, run_input)
    # Period 0 same as ORIGINAL_COLLATERAL
    assert floors[0] == pytest.approx(0.5 / 100.0 * GROUP_2_FACE, rel=1e-3)
    # Floor must strictly decrease over the deal life as the pool amortizes
    assert floors[-1] < floors[0] * 0.5, (
        f"Expected floor at end of deal to be much smaller than at start: "
        f"start={floors[0]:.2f}, end={floors[-1]:.2f}"
    )
    # Monotonically non-increasing (allow tiny floating-point wiggles)
    diffs = np.diff(floors)
    assert (diffs <= 1e-6).all(), "COLLATERAL_BALANCE floor should never increase"


def test_note_balance_decrements_with_bonds(run_input):
    """NOTE_BALANCE: floor steps down as the issued notes amortize."""
    deal = _make_test_deal(
        minimum_pct=0.5,
        minimum_basis=MinimumBasis.NOTE_BALANCE,
    )
    floors = _account_required_minimum(deal, run_input)
    # Bond A starts at 100% of pool, so initial floor matches ORIGINAL_COLLATERAL.
    assert floors[0] == pytest.approx(0.5 / 100.0 * GROUP_2_FACE, rel=1e-3)
    # As Bond A amortizes the floor must shrink dramatically.
    # Bond A is sized to absorb 100% of pool; at end of 240-month deal it
    # holds only the residual from discrete amortization timing (a few hundred
    # thousand). Floor of ~$1-2k vs initial ~$643k = >99% reduction.
    reduction = 1.0 - floors[-1] / floors[0]
    assert reduction > 0.99, (
        f"Expected NOTE_BALANCE floor to drop >99% across the deal "
        f"(bond A nearly fully amortized); got {reduction*100:.2f}% drop "
        f"(start={floors[0]:.2f}, end={floors[-1]:.2f})"
    )
    # Monotonically non-increasing
    diffs = np.diff(floors)
    assert (diffs <= 1e-6).all(), "NOTE_BALANCE floor should never increase"


def test_minimum_amount_floor_is_respected_with_pct_basis(run_input):
    """A dollar floor combined with a pct basis takes the max of the two."""
    floor_dollars = 100_000_000.0  # forces the dollar floor to dominate
    deal = _make_test_deal(
        minimum_amount=floor_dollars,
        minimum_pct=0.01,  # pct path produces ~$12.86k, much smaller than $100MM
        minimum_basis=MinimumBasis.COLLATERAL_BALANCE,
    )
    floors = _account_required_minimum(deal, run_input)
    # The dollar floor should win at every period
    assert (floors >= floor_dollars - 1e-6).all()


# ---------------------------------------------------------------------------
# starting_basis (period 0 only)
# ---------------------------------------------------------------------------


def test_starting_basis_fixed_dollar_uses_dollar_amount(run_input):
    deal = _make_test_deal(
        starting_amount=2_500_000.0,
        starting_pct=99.0,  # ignored under FIXED_DOLLAR
        starting_basis=MinimumBasis.FIXED_DOLLAR,
    )
    result = run_deal(deal, _group_2_collateral_input(100.0, 240), scenario_name="100PSA")
    p0 = next(r for r in result.deal_accounts if r.account_id == "ReserveAcct" and r.period == 0)
    assert p0.begin_balance == pytest.approx(2_500_000.0)


def test_starting_basis_original_collateral_uses_pool_balance(run_input):
    deal = _make_test_deal(
        starting_pct=1.0,
        starting_basis=MinimumBasis.ORIGINAL_COLLATERAL,
    )
    result = run_deal(deal, run_input, scenario_name="100PSA")
    p0 = next(r for r in result.deal_accounts if r.account_id == "ReserveAcct" and r.period == 0)
    expected = 1.0 / 100.0 * GROUP_2_FACE
    assert p0.begin_balance == pytest.approx(expected, rel=1e-3)


def test_starting_basis_collateral_balance_uses_pool_at_t0(run_input):
    """At t=0, COLLATERAL_BALANCE and ORIGINAL_COLLATERAL produce the same
    starting amount (pool balance hasn't amortized yet)."""
    deal = _make_test_deal(
        starting_pct=1.0,
        starting_basis=MinimumBasis.COLLATERAL_BALANCE,
    )
    result = run_deal(deal, run_input, scenario_name="100PSA")
    p0 = next(r for r in result.deal_accounts if r.account_id == "ReserveAcct" and r.period == 0)
    expected = 1.0 / 100.0 * GROUP_2_FACE
    assert p0.begin_balance == pytest.approx(expected, rel=1e-3)


def test_starting_basis_note_balance_uses_initial_note_stack(run_input):
    """NOTE_BALANCE at t=0 uses the initial outstanding note balance, which
    in this deal equals the pool (Bond A absorbs 100% of pool)."""
    deal = _make_test_deal(
        starting_pct=1.0,
        starting_basis=MinimumBasis.NOTE_BALANCE,
    )
    result = run_deal(deal, run_input, scenario_name="100PSA")
    p0 = next(r for r in result.deal_accounts if r.account_id == "ReserveAcct" and r.period == 0)
    expected = 1.0 / 100.0 * GROUP_2_FACE
    assert p0.begin_balance == pytest.approx(expected, rel=1e-3)
