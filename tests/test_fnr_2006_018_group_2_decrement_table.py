"""Decrement-table tie-out for FNR 2006-018 **Group 2** vs prospectus S-27.

Group 2 is a 4-class sequential cascade (BA -> BC -> BD -> DO) plus a
notional IO (DI) that strips interest off the DO balance. The pool is a
single MBS (240-month, WALA 24, 5.94% gross / 5.50% net pass-through).

Mirrors the structure of ``test_fnr_2006_018_decrement_table.py`` (which
covers Group 1) but uses Group 2's PSA columns: 0%, 100%, 206%, 300%,
400%, 500%. The 206% column is the DO/DI yield-table speed and is the
canonical pricing speed for the Group 2 PO/IO pair.

For each (PSA, tranche) pair:

  - **Per-period factors** at every annual February distribution date
    match the published integer-percent factor within tolerance.

  - **Per-bond WAL** matches published within tolerance.

The pool flows through the canonical ``from_actual_cashflow`` adapter
(same path as production), with ``Loan.wala_override`` set to the
published WALA (24) so the SMM curve seasons correctly.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from bma_standard_formulas.deals.adapters import from_actual_cashflow
from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.input import DealRunInput
from bma_standard_formulas.engine.loan import (
    Loan,
    actual_cashflow_from_loan,
    scheduled_cashflow_from_loan,
)
from bma_standard_formulas.formulas import generate_smm_curve_from_psa

from tests.fixtures.fnr_2006_018 import (
    DECREMENT_TABLE_PERIODS,
    GROUP_2_CLASSES,
    GROUP_2_POOL_ASSUMPTIONS,
    GROUP_2_REPLINE,
    GROUP_2_ZERO_PSA_PRICING_OVERRIDE,
    PUBLISHED_FACTORS_GROUP_2_BY_PSA,
    PUBLISHED_WAL_GROUP_2,
    PUBLISHED_WAL_PSA_COLUMNS_GROUP_2,
)
from tests.fixtures.fnr_2006_018.deal_definition import (
    build_fnr_2006_018_group_2_deal,
)


N_PERIODS = 240
GROUP_2_FACE = float(GROUP_2_POOL_ASSUMPTIONS["aggregate_upb_dollars"])

# Tranche evaluation order follows the rule priority: BA pays first, BD
# last among the cash-paying sequentials, DO is the PO catch-all, DI is
# the notional IO.
GROUP_2_TRANCHE_ORDER = ["BA", "BC", "BD", "DO", "DI"]


_ASOF_DATE = date(2006, 2, 1)


# ---------------------------------------------------------------------------
# Collateral pipeline: Loan -> BMA cashflow engine -> canonical adapter
# ---------------------------------------------------------------------------


def _build_group_2_loan(psa_speed: float) -> Loan:
    """Build the single Group 2 sub-repline Loan.

    Mirrors the FNR 2006-018 Pricing Assumption: Group 2 MBS is a single
    20-year repline at $128.6MM, 5.94% gross / 5.50% net, original 240
    months, remaining 214 months, WALA 24. At 0% PSA the prospectus
    overrides to 240/240/8.00%.
    """
    if psa_speed <= 0.0:
        wac_pct = float(GROUP_2_ZERO_PSA_PRICING_OVERRIDE["weighted_average_coupon_pct"])
        original_term = int(GROUP_2_ZERO_PSA_PRICING_OVERRIDE["original_term_months"])
        remaining_term = int(GROUP_2_ZERO_PSA_PRICING_OVERRIDE["weighted_average_remaining_term_months"])
        balance = float(GROUP_2_REPLINE["current_balance"])
        origination = _ASOF_DATE
        wala_override: int | None = None
    else:
        wac_pct = float(GROUP_2_REPLINE["wac_pct"])
        original_term = int(GROUP_2_REPLINE["original_term_months"])
        remaining_term = int(GROUP_2_REPLINE["remaining_term_months"])
        balance = float(GROUP_2_REPLINE["current_balance"])
        wala_override = int(GROUP_2_REPLINE["wala_months"])
        # Origination back-dated by WALA months for date-field consistency.
        years_back = wala_override // 12
        months_back = wala_override % 12
        orig_year = _ASOF_DATE.year - years_back
        orig_month = _ASOF_DATE.month - months_back
        if orig_month <= 0:
            orig_month += 12
            orig_year -= 1
        origination = date(orig_year, orig_month, 1)
    net_pct = float(GROUP_2_POOL_ASSUMPTIONS["mbs_pass_through_rate_pct"])
    servicing_pct = max(0.0, wac_pct - net_pct)
    return Loan(
        loan_id=2018002,
        origination_date=origination,
        asof_date=_ASOF_DATE,
        original_balance=float(GROUP_2_REPLINE["original_balance"]),
        current_balance=balance,
        rate_margin=wac_pct,
        servicing_fee=servicing_pct,
        original_term=original_term,
        remaining_term=remaining_term,
        wala_override=wala_override,
    )


def _group_2_collateral_input(psa_speed: float, n_periods: int) -> DealRunInput:
    """Build a Group 2 DealRunInput by routing the Loan through BMA actual
    cashflow + the canonical ``from_actual_cashflow`` adapter.
    """
    loan = _build_group_2_loan(psa_speed)
    sched = scheduled_cashflow_from_loan(loan)
    smm = generate_smm_curve_from_psa(float(psa_speed), loan.original_term)
    n = loan.original_term + 1
    actual = actual_cashflow_from_loan(
        loan=loan,
        scheduled_cf=sched,
        smm_curve=smm,
        mdr_curve=np.zeros(n),
        severity_curve=np.zeros(n),
    )
    return from_actual_cashflow(
        actual,
        horizon=n_periods + 1,
        loan_count=int(GROUP_2_FACE / 200_000.0),
        initial_balance=GROUP_2_FACE,
        # FNR Group 2: net of MBS-layer servicing wedge (see adapter docs).
        net_of_servicing=True,
    )


# ---------------------------------------------------------------------------
# Test plumbing
# ---------------------------------------------------------------------------


def _bond_face(tranche_id: str) -> float:
    spec = next((c for c in GROUP_2_CLASSES if c["name"] == tranche_id), None)
    return float(spec["size"]) if spec else 0.0


def _balance_at(result, tranche_id: str, period: int) -> float:
    rows = [r for r in result.bond_cashflows if r.tranche_id == tranche_id]
    if period == 0:
        first = next((r for r in rows if r.period == 1), None)
        return float(first.begin_balance) if first is not None else 0.0
    row = next((r for r in rows if r.period == period), None)
    return float(row.end_balance) if row is not None else 0.0


def _factor_at(result, tranche_id: str, period: int) -> float:
    face = _bond_face(tranche_id)
    if face <= 0.0:
        return 0.0
    return _balance_at(result, tranche_id, period) / face * 100.0


def _wal_years(result, tranche_id: str) -> float:
    rows = sorted(
        (r for r in result.bond_cashflows if r.tranche_id == tranche_id and r.period > 0),
        key=lambda r: r.period,
    )
    pairs = [(r.period, r.total_principal) for r in rows]
    total = sum(p for _, p in pairs)
    if total <= 0.0:
        return 0.0
    return sum(t * p for t, p in pairs) / total / 12.0


def _wal_years_io(result, tranche_id: str) -> float:
    """WAL of an IO computed by interest payments.

    For a notional IO (no principal), WAL is interest-cashflow-weighted
    average period. The prospectus convention for IOs is the same WAL
    formula but on principal -- since IOs have no principal, the
    industry convention is to use the underlying notional's principal
    cashflow timing. For DI tracking DO, this equals DO's principal WAL.
    """
    return _wal_years(result, "DO") if tranche_id == "DI" else _wal_years(result, tranche_id)


# Per-(PSA, tranche) factor tolerance overrides. Same pattern as Group 1
# decrement-table test: each entry has a documented precision source.
FACTOR_TOLERANCE_PP_DEFAULT = 2.5
FACTOR_TOLERANCE_OVERRIDES_PP_GROUP_2: dict[tuple[int, str], float] = {
    # Empty for now -- if any (PSA, tranche) needs widening we add an
    # entry with a clear comment explaining the precision source.
}


def _factor_tolerance(psa: int, tranche: str) -> float:
    return FACTOR_TOLERANCE_OVERRIDES_PP_GROUP_2.get(
        (psa, tranche), FACTOR_TOLERANCE_PP_DEFAULT
    )


# WAL tolerances per PSA column. Tight uniform 0.10 years given how clean
# the Group 2 sequential cascade is (no PAC schedules, no Z bond, no
# face-weighted splits). All 6 published Group 2 PSA columns are covered.
WAL_TOLERANCES_BY_PSA: dict[int, dict[str, float]] = {
    psa: {tr: 0.10 for tr in GROUP_2_TRANCHE_ORDER}
    for psa in PUBLISHED_WAL_PSA_COLUMNS_GROUP_2
}


@pytest.fixture(scope="module")
def deal_definition():
    return build_fnr_2006_018_group_2_deal(n_periods=N_PERIODS)


@pytest.fixture(scope="module")
def runs_by_psa(deal_definition):
    """Compute one engine result per published Group 2 PSA column."""
    out = {}
    for psa in PUBLISHED_WAL_PSA_COLUMNS_GROUP_2:
        run_input = _group_2_collateral_input(float(psa), N_PERIODS)
        out[psa] = run_deal(deal_definition, run_input, scenario_name=f"{psa}PSA")
    return out


def _factor_test_params() -> list[tuple[int, str]]:
    return [
        (psa, tranche)
        for psa in PUBLISHED_FACTORS_GROUP_2_BY_PSA.keys()
        for tranche in GROUP_2_TRANCHE_ORDER
    ]


def _wal_test_params() -> list[tuple[int, str]]:
    return [
        (psa, tranche)
        for psa in PUBLISHED_WAL_PSA_COLUMNS_GROUP_2
        for tranche in GROUP_2_TRANCHE_ORDER
    ]


# ---------------------------------------------------------------------------
# Parametrized factor + WAL tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("psa,tranche", _factor_test_params())
def test_factor_at_each_check_period(runs_by_psa, psa: int, tranche: str):
    result = runs_by_psa[psa]
    factor_table = PUBLISHED_FACTORS_GROUP_2_BY_PSA[psa]
    published = factor_table.get(tranche)
    assert published is not None, f"missing published {psa}% PSA row for {tranche}"
    assert len(published) == len(DECREMENT_TABLE_PERIODS), (
        f"{tranche} @ {psa}% PSA: published row length {len(published)} != "
        f"snapshot count {len(DECREMENT_TABLE_PERIODS)}"
    )
    tol = _factor_tolerance(psa, tranche)
    deltas: list[tuple[int, float, float]] = []
    for period, pub_pct in zip(DECREMENT_TABLE_PERIODS, published):
        eng_pct = _factor_at(result, tranche, period)
        if abs(eng_pct - pub_pct) > tol:
            deltas.append((period, float(pub_pct), eng_pct))
    assert not deltas, (
        f"{tranche} @ {psa}% PSA factor mismatches > {tol}pp:\n"
        + "\n".join(
            f"  period {p:>3} (Feb {2006 + p // 12}): "
            f"published={pub:.0f}%, engine={eng:.2f}% (delta={eng - pub:+.2f}pp)"
            for p, pub, eng in deltas
        )
    )


@pytest.mark.parametrize("psa,tranche", _wal_test_params())
def test_wal_within_tolerance(runs_by_psa, psa: int, tranche: str):
    result = runs_by_psa[psa]
    col = PUBLISHED_WAL_PSA_COLUMNS_GROUP_2.index(psa)
    published = float(PUBLISHED_WAL_GROUP_2[tranche][col])
    if tranche == "DI":
        engine = _wal_years_io(result, tranche)
    else:
        engine = _wal_years(result, tranche)
    tolerance = WAL_TOLERANCES_BY_PSA.get(psa, {}).get(tranche, 0.50)
    assert abs(engine - published) <= tolerance, (
        f"{tranche} @ {psa}% PSA WAL: published={published:.2f}y, "
        f"engine={engine:.2f}y, delta={engine - published:+.2f}y "
        f"(tolerance={tolerance:.2f}y)"
    )
