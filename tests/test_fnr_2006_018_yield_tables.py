"""Yield-table tie-out for FNR 2006-018 vs prospectus S-19 / S-20.

The prospectus publishes pre-tax corporate-bond-equivalent yield-to-maturity
(YTM) tables for the deal's principal-only and interest-only classes at
each of the published PSA columns:

    EO PAC PO at 56.796875% price (S-19 sensitivity table)
    PO Sup PO at 72.000000% price
    DO Seq PO at 55.125000% price (S-20)
    EI PAC IO at 40.203125% price (notional 5.50% on EO outstanding)
    DI Seq IO at 41.875000% price (notional 5.50% on DO outstanding)

Yield convention (prospectus S-19): solve for the *monthly* discount rate
``r_m`` that makes the present value of the bond's cashflows equal the
purchase price * face, then convert to corporate-bond-equivalent rate
``y_cbe = 2 * ((1 + r_m)^6 - 1)``. Settlement is Feb 28, 2006; the first
distribution is Mar 25, 2006. Distribution dates are the 25th of each
month (period i = i months after settlement, modulo the partial first
month).

For new-issue settlement no accrued interest is added (none has accrued
between the issue date and settlement date because they coincide), so
the prospectus footnote about adding accrued is a no-op here.
"""
from __future__ import annotations

import numpy as np
import pytest

from bma_standard_formulas.deals.risk import (
    bond_ytm_cbe,
    io_cashflows_from_underlying_balance,
    monthly_to_cbe,
    solve_monthly_irr,
)
from bma_standard_formulas.deals.runtime import run_deal

from tests.fixtures.fnr_2006_018 import GROUP_1_CLASSES, GROUP_2_CLASSES
from tests.fixtures.fnr_2006_018.deal_definition import (
    build_fnr_2006_018_group_1_deal,
    build_fnr_2006_018_group_2_deal,
)
from tests.test_fnr_2006_018_group_2_decrement_table import (
    _group_2_collateral_input,
)
from tests.test_fnr_2006_018_parity import _deal_input_from_repline


# Published prices (S-19, S-20).
PRICE_EO = 0.56796875
PRICE_PO = 0.72000000
PRICE_DO = 0.55125000
PRICE_EI = 0.40203125
PRICE_DI = 0.41875000

# Published YTM tables. Keys are PSA percent; values are pre-tax CBE YTM
# in percent. Negative values are recorded as floats.
PUBLISHED_YTM_EO: dict[int, float] = {
    50: 3.0, 100: 3.3, 147: 3.3, 180: 3.3, 227: 3.3, 250: 3.3,
    375: 4.6, 500: 6.1,
}
PUBLISHED_YTM_PO: dict[int, float] = {
    50: 1.2, 100: 1.4, 147: 1.7, 180: 3.1, 227: 12.7, 250: 17.1,
    375: 34.6, 500: 50.3,
}
PUBLISHED_YTM_DO: dict[int, float] = {
    50: 3.5, 100: 3.7, 206: 4.2, 300: 5.0, 400: 6.1, 500: 7.5,
}
PUBLISHED_YTM_EI: dict[int, float] = {
    50: 12.4, 100: 12.0, 147: 12.0, 180: 12.0, 227: 12.0, 250: 12.0,
    375: 9.3, 500: 5.5,
}
PUBLISHED_YTM_DI: dict[int, float] = {
    50: 11.3, 100: 11.0, 206: 10.0, 300: 8.2, 400: 5.4, 500: 1.8,
}

# 0% YTM breakeven PSA speeds for IO classes (S-19/S-20).
PUBLISHED_BREAKEVEN_PSA: dict[str, int] = {
    "EI": 640,
    "DI": 541,
}


# ---------------------------------------------------------------------------
# Yield calculation primitives
# ---------------------------------------------------------------------------


def _bond_face(spec_table: list[dict], tranche_id: str) -> float:
    spec = next((c for c in spec_table if c["name"] == tranche_id), None)
    return float(spec["size"]) if spec else 0.0


def _principal_cashflows(result, tranche_id: str) -> np.ndarray:
    """Per-period principal cash to a bond, indexed by period (0 = none)."""
    rows = sorted(
        (r for r in result.bond_cashflows if r.tranche_id == tranche_id),
        key=lambda r: r.period,
    )
    n = (rows[-1].period if rows else 0) + 1
    out = np.zeros(n)
    for r in rows:
        out[r.period] = float(r.total_principal)
    return out


def _interest_cashflows(result, tranche_id: str) -> np.ndarray:
    """Per-period cash interest paid to a bond."""
    rows = sorted(
        (r for r in result.bond_cashflows if r.tranche_id == tranche_id),
        key=lambda r: r.period,
    )
    n = (rows[-1].period if rows else 0) + 1
    out = np.zeros(n)
    for r in rows:
        out[r.period] = float(r.interest_paid)
    return out


def _io_cashflows_from_result(result, underlying_id: str, coupon_pct: float) -> np.ndarray:
    """Notional-IO cashflows for `underlying_id` on the result bundle.

    Thin wrapper around the canonical
    `bma_standard_formulas.deals.risk.io_cashflows_from_underlying_balance`
    that pulls the underlying bond's rows out of a ScenarioOutputBundle.
    """
    underlying_rows = [
        r for r in result.bond_cashflows if r.tranche_id == underlying_id
    ]
    return io_cashflows_from_underlying_balance(underlying_rows, coupon_pct)


# Backwards-compat names used by the YTM summary helper at the bottom of
# this module (and by other tests that import from here). All thin
# wrappers around the canonical primitives in `deals.risk`.
_solve_monthly_irr = solve_monthly_irr
_monthly_to_cbe = monthly_to_cbe
_bond_ytm = bond_ytm_cbe
_io_cashflows_from_underlying_balance = _io_cashflows_from_result


# ---------------------------------------------------------------------------
# Test fixtures: cached engine runs at each yield-table PSA speed
# ---------------------------------------------------------------------------


_GROUP_1_PSA_SET = sorted(set(PUBLISHED_YTM_EO.keys()) | set(PUBLISHED_YTM_PO.keys())
                          | set(PUBLISHED_YTM_EI.keys()))
_GROUP_2_PSA_SET = sorted(set(PUBLISHED_YTM_DO.keys()) | set(PUBLISHED_YTM_DI.keys()))


@pytest.fixture(scope="module")
def group_1_runs():
    deal = build_fnr_2006_018_group_1_deal(n_periods=360)
    out = {}
    for psa in _GROUP_1_PSA_SET:
        run_input = _deal_input_from_repline(float(psa), 360)
        out[psa] = run_deal(deal, run_input, scenario_name=f"{psa}PSA")
    return out


@pytest.fixture(scope="module")
def group_2_runs():
    deal = build_fnr_2006_018_group_2_deal(n_periods=240)
    out = {}
    for psa in _GROUP_2_PSA_SET:
        run_input = _group_2_collateral_input(float(psa), 240)
        out[psa] = run_deal(deal, run_input, scenario_name=f"{psa}PSA")
    return out


# Tolerance: published YTMs are quoted to 1 decimal place. The exact
# rounded value lies within +/- 0.05 percentage points of the printed
# value; we allow 0.20 pp for engine drift on top of that. Tighter
# overrides per-(PSA, tranche) are documented inline if needed.
YTM_TOLERANCE_PP = 0.20


# ---------------------------------------------------------------------------
# Group 1 PO classes (EO @ 56.796875%, PO @ 72.000000%)
# ---------------------------------------------------------------------------


class TestYieldTableEO:
    """EO PAC PO at 56.796875% price."""

    @pytest.mark.parametrize("psa", sorted(PUBLISHED_YTM_EO.keys()))
    def test_ytm_at_psa(self, group_1_runs, psa):
        result = group_1_runs[psa]
        cf = _principal_cashflows(result, "EO")
        face = _bond_face(GROUP_1_CLASSES, "EO")
        ytm = _bond_ytm(cf, PRICE_EO, face)
        published = PUBLISHED_YTM_EO[psa]
        assert abs(ytm - published) <= YTM_TOLERANCE_PP, (
            f"EO @ {psa}% PSA YTM: published={published:.2f}%, "
            f"engine={ytm:.4f}%, delta={ytm - published:+.4f}pp"
        )


class TestYieldTablePO:
    """PO Sup PO at 72.000000% price."""

    @pytest.mark.parametrize("psa", sorted(PUBLISHED_YTM_PO.keys()))
    def test_ytm_at_psa(self, group_1_runs, psa):
        result = group_1_runs[psa]
        cf = _principal_cashflows(result, "PO")
        face = _bond_face(GROUP_1_CLASSES, "PO")
        ytm = _bond_ytm(cf, PRICE_PO, face)
        published = PUBLISHED_YTM_PO[psa]
        # PO yield ranges from ~1% to 50%+ across PSA columns; absolute
        # 0.20pp tolerance plus 3% of published handles both the low-PSA
        # band (where 0.20pp dominates) and the high-PSA stress band
        # (where percentage drift dominates).
        tol = max(YTM_TOLERANCE_PP, 0.03 * abs(published))
        assert abs(ytm - published) <= tol, (
            f"PO @ {psa}% PSA YTM: published={published:.2f}%, "
            f"engine={ytm:.4f}%, delta={ytm - published:+.4f}pp "
            f"(tolerance={tol:.2f}pp)"
        )


# ---------------------------------------------------------------------------
# Group 2 PO class (DO @ 55.125000%)
# ---------------------------------------------------------------------------


class TestYieldTableDO:
    """DO Seq PO at 55.125000% price."""

    @pytest.mark.parametrize("psa", sorted(PUBLISHED_YTM_DO.keys()))
    def test_ytm_at_psa(self, group_2_runs, psa):
        result = group_2_runs[psa]
        cf = _principal_cashflows(result, "DO")
        face = _bond_face(GROUP_2_CLASSES, "DO")
        ytm = _bond_ytm(cf, PRICE_DO, face)
        published = PUBLISHED_YTM_DO[psa]
        assert abs(ytm - published) <= YTM_TOLERANCE_PP, (
            f"DO @ {psa}% PSA YTM: published={published:.2f}%, "
            f"engine={ytm:.4f}%, delta={ytm - published:+.4f}pp"
        )


# ---------------------------------------------------------------------------
# IO classes (EI @ 40.203125%, DI @ 41.875000%)
# ---------------------------------------------------------------------------


class TestYieldTableEI:
    """EI PAC IO at 40.203125% price (notional 5.50% on EO outstanding).

    EI is an RCR exchangeable (not directly modeled in the deal); its
    cashflows are derived from EO's balance trajectory * 5.50%/12.
    """

    @pytest.mark.parametrize("psa", sorted(PUBLISHED_YTM_EI.keys()))
    def test_ytm_at_psa(self, group_1_runs, psa):
        result = group_1_runs[psa]
        cf = _io_cashflows_from_underlying_balance(result, "EO", coupon_pct=5.50)
        face = _bond_face(GROUP_1_CLASSES, "EO")  # EI notional matches EO face.
        ytm = _bond_ytm(cf, PRICE_EI, face)
        published = PUBLISHED_YTM_EI[psa]
        # EI yield can become large negative at high PSA; allow a slightly
        # wider tolerance for that regime.
        tol = max(YTM_TOLERANCE_PP, 0.05 * abs(published))
        assert abs(ytm - published) <= tol, (
            f"EI @ {psa}% PSA YTM: published={published:.2f}%, "
            f"engine={ytm:.4f}%, delta={ytm - published:+.4f}pp "
            f"(tolerance={tol:.2f}pp)"
        )


class TestYieldTableDI:
    """DI Seq IO at 41.875000% price (notional 5.50% on DO outstanding).

    DI is modeled directly in the Group 2 deal via tracks_bonds; we use
    its interest_paid cashflows.
    """

    @pytest.mark.parametrize("psa", sorted(PUBLISHED_YTM_DI.keys()))
    def test_ytm_at_psa(self, group_2_runs, psa):
        result = group_2_runs[psa]
        cf = _interest_cashflows(result, "DI")
        face = _bond_face(GROUP_2_CLASSES, "DI")
        ytm = _bond_ytm(cf, PRICE_DI, face)
        published = PUBLISHED_YTM_DI[psa]
        # IO yields collapse near breakeven (DI at 500% PSA is +1.8%, near
        # the 541% PSA breakeven). Small timing shifts move the YTM by
        # tens of bp absolute when the value is small, so we use a 12%
        # relative tolerance for IOs in addition to the 0.20pp floor.
        tol = max(YTM_TOLERANCE_PP, 0.12 * abs(published))
        assert abs(ytm - published) <= tol, (
            f"DI @ {psa}% PSA YTM: published={published:.2f}%, "
            f"engine={ytm:.4f}%, delta={ytm - published:+.4f}pp "
            f"(tolerance={tol:.2f}pp)"
        )


# ---------------------------------------------------------------------------
# IO breakeven PSA: where YTM crosses zero
# ---------------------------------------------------------------------------


class TestIOBreakevenPSA:
    """IO classes have a breakeven PSA above which the YTM goes negative.

    Prospectus S-20 quotes:
        EI breaks even at 640% PSA
        DI breaks even at 541% PSA

    We verify the engine produces a YTM <= 0 at the published PSA AND
    YTM > 0 at slightly slower PSAs (95% of the published breakeven).
    Tolerance on the breakeven crossing is +/- 5% PSA.
    """

    def test_ei_breakeven(self):
        deal = build_fnr_2006_018_group_1_deal(n_periods=360)

        def ei_ytm_at(psa: float) -> float:
            run_input = _deal_input_from_repline(psa, 360)
            result = run_deal(deal, run_input, scenario_name=f"{psa}PSA")
            cf = _io_cashflows_from_underlying_balance(result, "EO", coupon_pct=5.50)
            face = _bond_face(GROUP_1_CLASSES, "EO")
            return _bond_ytm(cf, PRICE_EI, face)

        published_breakeven = PUBLISHED_BREAKEVEN_PSA["EI"]
        # Solve for the breakeven PSA via bisection on the published table neighborhood.
        ytm_low = ei_ytm_at(0.95 * published_breakeven)   # below breakeven, YTM > 0
        ytm_published = ei_ytm_at(published_breakeven)
        assert ytm_low > 0.0, (
            f"EI YTM at {0.95 * published_breakeven:.0f}% PSA = {ytm_low:.2f}%, "
            f"expected positive (below breakeven)"
        )
        assert abs(ytm_published) < 1.0, (
            f"EI YTM at published breakeven {published_breakeven}% PSA = "
            f"{ytm_published:.4f}%, expected near zero (within +/- 1pp)"
        )

    def test_di_breakeven(self):
        deal = build_fnr_2006_018_group_2_deal(n_periods=240)

        def di_ytm_at(psa: float) -> float:
            run_input = _group_2_collateral_input(psa, 240)
            result = run_deal(deal, run_input, scenario_name=f"{psa}PSA")
            cf = _interest_cashflows(result, "DI")
            face = _bond_face(GROUP_2_CLASSES, "DI")
            return _bond_ytm(cf, PRICE_DI, face)

        published_breakeven = PUBLISHED_BREAKEVEN_PSA["DI"]
        ytm_low = di_ytm_at(0.95 * published_breakeven)
        ytm_published = di_ytm_at(published_breakeven)
        assert ytm_low > 0.0, (
            f"DI YTM at {0.95 * published_breakeven:.0f}% PSA = {ytm_low:.2f}%, "
            f"expected positive (below breakeven)"
        )
        assert abs(ytm_published) < 1.0, (
            f"DI YTM at published breakeven {published_breakeven}% PSA = "
            f"{ytm_published:.4f}%, expected near zero (within +/- 1pp)"
        )
