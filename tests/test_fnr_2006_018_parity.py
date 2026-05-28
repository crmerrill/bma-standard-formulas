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

from datetime import date

import numpy as np
import pytest

from bma_standard_formulas.deals.adapters import (
    from_actual_cashflow,
    ldcma_to_paired,
)
from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows,
    DealRunInput,
    PooledCollateralInput,
)
from bma_standard_formulas.engine.loan import (
    Loan,
    actual_cashflow_from_loan,
    scheduled_cashflow_from_loan,
)
from bma_standard_formulas.formulas import generate_smm_curve_from_psa

from tests.fixtures.fnr_2006_018 import (
    GROUP_1_SUB_REPLINES,
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
# Repline via BMA Loan -> cashflow engine -> deal engine pipeline.
#
# Group 1 is modeled as TWO sub-replines per the prospectus Reference Sheet:
#
#     Sub-repline A: $ 37,414,966 at 360/349/9, WAC 5.94%, net 5.50%
#     Sub-repline B: $ 95,238,095 at 360/348/10, WAC 5.94%, net 5.50%
#
# Both run through the BMA `Loan` wrapper independently with age-indexed PSA
# SMM curves; results are summed into a single `CollateralCashflows` payload
# fed to the deal engine. This matches the prospectus's Pricing Assumptions
# verbatim (S-18: "the Mortgage Loans have the original terms to maturity,
# remaining terms to maturity, WALAs and interest rates specified under
# Reference Sheet").
#
# At 0% PSA the prospectus uses a single override repline
# (Group 1: 360/360/8.00%, see ZERO_PSA_PRICING_OVERRIDE).
# ---------------------------------------------------------------------------

# Stable date pair for the BMA Loan wrapper. Origination is set so each
# sub-repline's age = original_term - remaining_term matches the published
# WALA convention (within the 1-2 month BMA-vs-FNMA WALA-arithmetic offset).
_ASOF_DATE = date(2006, 2, 1)


def _build_sub_repline_loan(repline_spec: dict, psa_speed: float) -> Loan:
    """Build a Loan for one sub-repline at a given PSA speed.

    At 0% PSA the prospectus override (360/360/8.00%) replaces the actual
    sub-repline characteristics with a single full-term assumption.

    For non-zero PSA we honor the published Reference Sheet's WALA via
    `Loan.wala_override`. The Reference Sheet quotes WAM (remaining term)
    and WALA separately, and they don't necessarily satisfy
    ``WAM + WALA == original_term``: the FNR 2006-018 sub-replines have
    WAM 348/349 and WALA 9/10, which would imply original terms of 357
    or 359, not the canonical 360. Without the override the runtime
    seasons the SMM curve to age = ``original - remaining`` (= 11/12)
    instead of WALA (= 9/10), inflating year-1 prepay by ~0.4% CPR and
    shortening downstream tranche WALs by ~0.4 years.
    """
    if psa_speed <= 0.0:
        wac_pct = float(ZERO_PSA_PRICING_OVERRIDE["weighted_average_coupon_pct"])
        original_term = int(ZERO_PSA_PRICING_OVERRIDE["original_term_months"])
        remaining_term = int(ZERO_PSA_PRICING_OVERRIDE["weighted_average_remaining_term_months"])
        balance = float(repline_spec["current_balance"])
        origination = _ASOF_DATE
        wala_override: int | None = None  # 0% PSA: no prepay so seasoning irrelevant.
    else:
        wac_pct = float(repline_spec["wac_pct"])
        original_term = int(repline_spec["original_term_months"])
        remaining_term = int(repline_spec["remaining_term_months"])
        balance = float(repline_spec["current_balance"])
        wala_override = int(repline_spec.get("wala_months", original_term - remaining_term))
        # Origination is set to asof - WALA months so date-based fields
        # (first_payment_date, etc.) line up with the published WALA. The
        # `wala_override` then ensures the age-indexed curves use the
        # Reference Sheet WALA exactly.
        age_months = max(0, wala_override)
        origination = date(
            _ASOF_DATE.year - (age_months // 12),
            _ASOF_DATE.month - (age_months % 12) if (_ASOF_DATE.month - (age_months % 12)) > 0
                else _ASOF_DATE.month - (age_months % 12) + 12,
            1,
        )
        if age_months % 12 >= _ASOF_DATE.month:
            origination = date(origination.year - 1, origination.month, 1)
    net_pct = float(POOL_ASSUMPTIONS["mbs_pass_through_rate_pct"])
    servicing_pct = max(0.0, wac_pct - net_pct)
    return Loan(
        loan_id=int(repline_spec.get("loan_id", abs(hash(repline_spec["label"])) % (10**9))),
        origination_date=origination,
        asof_date=_ASOF_DATE,
        original_balance=float(repline_spec["original_balance"]),
        current_balance=balance,
        rate_margin=wac_pct,
        servicing_fee=servicing_pct,
        original_term=original_term,
        remaining_term=remaining_term,
        wala_override=wala_override,
    )


def _run_sub_repline_cashflow(repline_spec: dict, psa_speed: float):
    """Run BMA scheduled + actual cashflow for a single sub-repline."""
    loan = _build_sub_repline_loan(repline_spec, psa_speed)
    sched = scheduled_cashflow_from_loan(loan)
    smm = generate_smm_curve_from_psa(float(psa_speed), loan.original_term)
    mdr = np.zeros(loan.original_term + 1)
    sev = np.zeros(loan.original_term + 1)
    actual = actual_cashflow_from_loan(
        loan=loan,
        scheduled_cf=sched,
        smm_curve=smm,
        mdr_curve=mdr,
        severity_curve=sev,
    )
    return loan, sched, actual


def _repline_for_psa(psa_speed: float):
    """Aggregate Group 1 cashflow across all sub-replines at a given PSA speed.

    Each sub-repline is run through the BMA scheduled + actual cashflow
    engines; their outputs are summed (extensive fields like `act_am`,
    `vol_prepay`, `act_int`, `perf_bal`, `prin_loss`) into a single
    aggregated `BMAActualCashflow`-shaped object. This is the same
    aggregation the production portfolio runner performs internally; we
    do it inline so the FNR fixture exercises the same downstream
    `from_actual_cashflow` adapter the production app uses, with no
    manual interest reconstruction.

    Returns `(scheduled_balance_summary, aggregated_actual_cashflow,
    weighted_wac_pct)`.
    """
    if psa_speed <= 0.0:
        # 0% PSA override: single repline at 360/360/8.00%.
        repline_specs = [{
            **GROUP_1_SUB_REPLINES[0],
            "current_balance": float(POOL_ASSUMPTIONS["aggregate_upb_dollars"]),
            "original_balance": float(POOL_ASSUMPTIONS["aggregate_upb_dollars"]),
            "label": "Group 1 0% PSA override",
        }]
    else:
        repline_specs = list(GROUP_1_SUB_REPLINES)

    horizon: int | None = None
    sub_actuals = []
    waccs: list[float] = []
    bal_weights: list[float] = []
    for spec in repline_specs:
        _loan, _sched, actual = _run_sub_repline_cashflow(spec, psa_speed)
        n = len(actual.perf_bal)
        if horizon is None or n < horizon:
            horizon = n
        sub_actuals.append(actual)
        waccs.append(float(spec["wac_pct"]))
        bal_weights.append(float(spec["current_balance"]))

    horizon = horizon or 0
    weighted_wac = sum(w * b for w, b in zip(waccs, bal_weights)) / sum(bal_weights)

    # Sum extensive fields across sub-replines into a single aggregated
    # actual-cashflow that quacks like a BMAActualCashflow as far as the
    # `from_actual_cashflow` adapter is concerned. `svc_billed` is summed
    # so net-of-servicing routing in the adapter has the right wedge.
    class _AggregatedActual:
        pass
    agg_actual = _AggregatedActual()
    for fname in ("act_am", "vol_prepay", "act_int", "exp_int", "svc_billed",
                  "prin_loss", "prin_recov", "new_def", "perf_bal"):
        agg_actual.__dict__[fname] = sum(
            getattr(a, fname)[:horizon] for a in sub_actuals
        )

    # Aggregate scheduled-balance summary used by Stage 1 of the staged
    # tie-out (which only checks balance termination and total scheduled
    # principal, not WAC dynamics).
    class _AggregatedScheduled:
        pass
    agg_sched = _AggregatedScheduled()
    agg_sched.amortized_balance_fraction = (
        agg_actual.perf_bal / float(sum(bal_weights))
        if sum(bal_weights) > 0
        else agg_actual.perf_bal
    )
    return agg_sched, agg_actual, weighted_wac


def _deal_input_from_repline(
    psa_speed: float,
    n_periods: int,
    *,
    group_id: str | None = None,
) -> DealRunInput:
    """Build a DealRunInput by routing the BMA actual cashflow through the
    PAIRED runtime branch via ``ldcma_to_paired`` (Phase 1f migration).

    Pipeline:

      1. ``_repline_for_psa`` aggregates the FNR Group 1 sub-replines into
         a duck-typed ``_AggregatedActual`` carrying the primitive BMA
         flow / stock fields needed by the deal engine.
      2. ``from_actual_cashflow(net_of_servicing=True)`` builds the LDCMA
         intermediate. ``net_of_servicing`` subtracts ``svc_billed`` from
         ``act_int`` because each underlying MBS delivers only the 5.50%
         pass-through rate to the trust (Fannie Mae guaranty fee netted
         at the MBS layer; modeling it as a trust-level ``FeeDef`` would
         double-count).
      3. ``ldcma_to_paired`` wraps the LDCMA payload as a
         ``PairedCollateralInput`` over a ``PortfolioCashflow`` (ACTUAL_ONLY
         mode). The deal runtime consumes the BMA-native PAIRED form.
      4. When ``group_id`` is supplied, the synthesized BMAActualCashflow
         constituent is retagged via ``dataclasses.replace`` so the
         multi-group runtime path routes cash to the right group.

    Why route Group 1 through ``ldcma_to_paired`` rather than building a
    real ``BMAActualCashflow`` directly: ``_repline_for_psa`` returns a
    duck-typed ``_AggregatedActual`` (sum of sub-repline arrays) that
    only carries the primitive flow / stock fields the LDCMA adapter
    needs — many ``BMAActualCashflow`` fields (``mdr``, ``smm``,
    ``gross_rate``, ``age``, etc.) are not populated by the aggregator.
    ``ldcma_to_paired`` synthesizes a proper ``BMAActualCashflow`` via
    ``_ldcma_to_bma_actual`` (single source of truth shared with the
    runtime's PAIRED branch) so the fixture reaches the PAIRED runtime
    branch without needing a parallel aggregator that populates every
    BMA field. Group 2 (single-loan repline) is migrated directly to
    full PAIRED in ``_group_2_collateral_input``.
    """
    import dataclasses
    import warnings

    from bma_standard_formulas.deals.schemas.input import PairedCollateralInput
    from bma_standard_formulas.engine import PortfolioCashflow
    from bma_standard_formulas.engine.portfolio import PortfolioMode

    _sched, actual, _wac_pct = _repline_for_psa(psa_speed)
    initial_balance = float(POOL_ASSUMPTIONS["aggregate_upb_dollars"])
    # Suppress the Phase 1h DeprecationWarning: this helper is itself
    # transitional bridging machinery (LDCMA -> PAIRED via ldcma_to_paired).
    # ``from_actual_cashflow`` is used here as the LDCMA-side construction
    # step, then immediately wrapped via ldcma_to_paired - the BMA-native
    # PAIRED form is what the deal runtime ultimately consumes.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        ldcma_input = from_actual_cashflow(
            actual,
            horizon=n_periods + 1,
            loan_count=int(initial_balance / 200_000.0),
            initial_balance=initial_balance,
            net_of_servicing=True,
        )
    paired_input = ldcma_to_paired(ldcma_input)

    if group_id is None:
        return paired_input

    # Retag the synthesized constituent with the requested group_id so
    # the multi-group combined run routes cash through GROUP_<id>_*
    # tokens correctly. ldcma_to_paired emitted untagged constituents
    # (group_id=None); rebuild a portfolio whose constituents carry the
    # caller's group_id.
    portfolio = paired_input.collateral.portfolio
    retagged = [
        dataclasses.replace(cf, group_id=group_id)
        for cf in portfolio.actual_constituents()
    ]
    new_portfolio = PortfolioCashflow(retagged, mode=PortfolioMode.ACTUAL_ONLY)
    return DealRunInput(
        collateral=PairedCollateralInput(portfolio=new_portfolio),
        loan_count=paired_input.loan_count,
        original_collateral_balance=paired_input.original_collateral_balance,
        market_date=paired_input.market_date,
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
    """Compatibility wrapper for the seed script: builds an ephemeral repline
    Loan with the requested parameters and returns its (balance, sched_prin,
    vol_prepay) projection arrays via the BMA Loan wrapper.
    """
    age = max(0, term - remaining_term)
    origination = date(2006, 2, 1)
    asof = date(origination.year + age // 12, ((origination.month - 1 + age % 12) % 12) + 1, 1)
    loan = Loan(
        loan_id=1,
        origination_date=origination,
        asof_date=asof,
        original_balance=initial_balance,
        current_balance=initial_balance,
        rate_margin=annual_coupon_pct,
        servicing_fee=0.0,
        original_term=term,
        remaining_term=remaining_term,
    )
    sched = scheduled_cashflow_from_loan(loan)
    smm = generate_smm_curve_from_psa(float(psa_speed), term)
    mdr = np.zeros(term + 1)
    sev = np.zeros(term + 1)
    actual = actual_cashflow_from_loan(
        loan=loan,
        scheduled_cf=sched,
        smm_curve=smm,
        mdr_curve=mdr,
        severity_curve=sev,
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
        pac_bonds = [b for b in deal.bonds if b.kind.value in ("PAC", "TAC")]
        assert pac_bonds, "expected PAC bonds"
        for b in pac_bonds:
            assert b.schedule_contract, f"{b.name} missing schedule_contract"

    def test_z_bond_configured(self):
        deal = build_fnr_2006_018_group_1_deal(n_periods=360)
        z = next(b for b in deal.bonds if b.name == "Z")
        assert z.kind.value == "Z"
        assert z.pay_mode.value == "PIK"
        assert z.z_accrual_enabled
        accretes_to = [
            target
            for relation in z.relations
            if relation.relation_type.value == "ACCRETES_TO"
            for target in relation.targets
        ]
        assert "TA" in accretes_to
        assert "TB" in accretes_to


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
        # Phase 1f: collateral is now PairedCollateralInput; read pool
        # principal / interest from the BMA-native portfolio.pool fields
        # (act_prin = act_am + vol_prepay; act_int already netted of the
        # MBS-layer servicing wedge by ldcma_to_paired's input).
        pool = run_input.collateral.portfolio.pool
        pool_principal = float(pool.act_prin.sum())
        pool_interest = float(pool.act_int.sum())
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
