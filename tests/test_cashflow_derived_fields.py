"""Tests for the derived FLOW/STOCK fields on BMAActualCashflow and BMAScheduledCashflow.

Validates the four derived fields added to the cashflow dataclasses so that
deal runtime, analytics, and reporting can reference combined / total
quantities directly without recomputing per period:

  BMAActualCashflow:
    act_prin   = act_am + vol_prepay              (FLOW)
    act_cash   = act_prin + act_int               (FLOW)
    total_bal  = perf_bal + fcl                   (STOCK)

  BMAScheduledCashflow:
    sched_cash = principal_paid + interest_paid   (FLOW)

What this covers:

  1. Construction: __post_init__ populates the derived fields from the
     primitives at construction time, on every code path that builds a
     cashflow (engine runners, aggregators, parquet round-trip).
  2. Immutability: derived arrays are frozen alongside the primitives;
     attempts to mutate them raise ValueError just like the primitives.
  3. Aggregation linearity: aggregating multiple cashflows produces an
     aggregate whose derived fields equal the sum of the constituents'
     derived fields (within floating-point tolerance).
  4. Aggregator efficiency: the FLOW accumulator skips derived fields
     so we don't pay for redundant per-constituent summation that would
     produce a value the new instance's __post_init__ overwrites anyway.
  5. Parquet persistence round-trip: derived fields are NOT written to
     disk; on read, the constructed instance regenerates them.

Why these matter for proposal R / Phase 1b:

  The deal runtime can now reference ``actual.act_prin``, ``actual.act_cash``,
  and ``actual.total_bal`` directly without going through a dict. The
  ``total_bal`` field is the deal-mechanics "pool balance" used for credit
  enhancement, pool factor, reserve floors, step-down checks, and pro-rata
  share weights — INCLUDES loans in the foreclosure pipeline that have
  defaulted but not yet liquidated. ``perf_bal`` is the narrower
  performing-only view; both remain accessible.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from bma_standard_formulas.engine.loan import (
    Loan,
    actual_cashflow_from_loan,
    scheduled_cashflow_from_loan,
)
from bma_standard_formulas.engine.portfolio import (
    PortfolioCashflow,
    PortfolioMode,
    _aggregate_actual,
    _aggregate_scheduled,
)
from bma_standard_formulas.formulas import generate_smm_curve_from_psa
from bma_standard_formulas.formulas.cashflows import (
    BMAActualCashflow,
    BMAScheduledCashflow,
    FieldKind,
    fields_by_kind,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_loan(loan_id: int = 1, balance: float = 1_000_000.0) -> Loan:
    return Loan(
        loan_id=loan_id,
        origination_date=date(2024, 1, 1),
        asof_date=date(2024, 1, 1),
        original_balance=balance,
        current_balance=balance,
        rate_margin=6.0,
        original_term=360,
        remaining_term=360,
    )


def _build_actual_and_scheduled(
    loan: Loan,
    psa_speed: float = 100.0,
    cdr_speed: float = 0.0,
    severity: float = 0.0,
):
    """Build paired scheduled + actual cashflows.

    Optionally with non-zero default rate so we can exercise the
    foreclosure pipeline (fcl) — important for testing total_bal in the
    presence of defaults.
    """
    sched = scheduled_cashflow_from_loan(loan)
    n = loan.original_term + 1
    smm = generate_smm_curve_from_psa(psa_speed, loan.original_term)
    # CDR vector: convert annual to monthly MDR
    mdr_vec = np.full(n, 1.0 - (1.0 - cdr_speed) ** (1.0 / 12.0))
    sev_vec = np.full(n, severity)
    actual = actual_cashflow_from_loan(
        loan=loan,
        scheduled_cf=sched,
        smm_curve=smm,
        mdr_curve=mdr_vec,
        severity_curve=sev_vec,
    )
    return actual, sched


# ---------------------------------------------------------------------------
# 1. Construction populates derived fields
# ---------------------------------------------------------------------------


class TestDerivedFieldConstruction:
    """__post_init__ derives the four shortcut fields from primitives."""

    def test_act_prin_equals_act_am_plus_vol_prepay(self):
        actual, _ = _build_actual_and_scheduled(_build_loan())
        np.testing.assert_array_equal(actual.act_prin, actual.act_am + actual.vol_prepay)

    def test_act_cash_equals_act_prin_plus_act_int(self):
        actual, _ = _build_actual_and_scheduled(_build_loan())
        np.testing.assert_array_equal(actual.act_cash, actual.act_prin + actual.act_int)
        # Also verifies transitivity from primitives
        np.testing.assert_array_equal(
            actual.act_cash,
            actual.act_am + actual.vol_prepay + actual.act_int,
        )

    def test_total_bal_equals_perf_bal_plus_fcl_zero_default_case(self):
        """With no defaults, total_bal == perf_bal (fcl is zero everywhere)."""
        actual, _ = _build_actual_and_scheduled(_build_loan())
        np.testing.assert_array_equal(actual.total_bal, actual.perf_bal + actual.fcl)
        # FCL should be zero in a no-default scenario, so total_bal == perf_bal
        np.testing.assert_array_equal(actual.fcl, np.zeros_like(actual.fcl))
        np.testing.assert_array_equal(actual.total_bal, actual.perf_bal)

    def test_total_bal_includes_fcl_when_loans_default(self):
        """With defaults active, total_bal > perf_bal during the FCL pipeline.

        The defaulted balance moves from perf_bal to fcl at the point of
        default. total_bal tracks the sum. This is the "pool balance"
        semantic that bond CE % and pool factor calculations require.
        """
        actual, _ = _build_actual_and_scheduled(
            _build_loan(),
            psa_speed=0.0,           # no prepays so fcl movement is the main story
            cdr_speed=0.05,          # 5% CDR -> non-trivial new_def each period
            severity=0.50,
        )
        # FCL has positive periods somewhere (not always zero)
        assert (actual.fcl > 0).any(), "expected fcl to be non-zero in defaulting scenario"
        # total_bal == perf_bal + fcl by construction
        np.testing.assert_array_equal(actual.total_bal, actual.perf_bal + actual.fcl)
        # During FCL pipeline, total_bal > perf_bal
        assert (actual.total_bal[actual.fcl > 0] > actual.perf_bal[actual.fcl > 0]).all()

    def test_sched_cash_equals_principal_paid_plus_interest_paid(self):
        _, sched = _build_actual_and_scheduled(_build_loan())
        np.testing.assert_array_equal(
            sched.sched_cash,
            sched.principal_paid + sched.interest_paid,
        )


# ---------------------------------------------------------------------------
# 2. Immutability — derived arrays frozen alongside primitives
# ---------------------------------------------------------------------------


class TestDerivedFieldImmutability:
    """Derived arrays must be frozen by _freeze_arrays just like primitives."""

    def test_actual_act_prin_is_read_only(self):
        actual, _ = _build_actual_and_scheduled(_build_loan())
        with pytest.raises(ValueError):
            actual.act_prin[5] = 999.0

    def test_actual_act_cash_is_read_only(self):
        actual, _ = _build_actual_and_scheduled(_build_loan())
        with pytest.raises(ValueError):
            actual.act_cash[5] = 999.0

    def test_actual_total_bal_is_read_only(self):
        actual, _ = _build_actual_and_scheduled(_build_loan())
        with pytest.raises(ValueError):
            actual.total_bal[5] = 999.0

    def test_scheduled_sched_cash_is_read_only(self):
        _, sched = _build_actual_and_scheduled(_build_loan())
        with pytest.raises(ValueError):
            sched.sched_cash[5] = 999.0


# ---------------------------------------------------------------------------
# 3. Aggregator linearity
# ---------------------------------------------------------------------------


class TestAggregatorLinearity:
    """Aggregating multiple cashflows produces correct derived fields.

    Since act_prin / act_cash / total_bal / sched_cash are linear in their
    primitive components, summing constituents' primitives in the aggregator
    and re-deriving in __post_init__ gives the same result as summing
    derived fields directly. This test pins the linearity property.
    """

    def test_actual_aggregate_act_prin_equals_sum_of_constituents(self):
        a1, _ = _build_actual_and_scheduled(_build_loan(loan_id=1, balance=1_000_000))
        a2, _ = _build_actual_and_scheduled(_build_loan(loan_id=2, balance=2_000_000))
        agg = _aggregate_actual([a1, a2])

        np.testing.assert_allclose(
            agg.act_prin,
            a1.act_prin + a2.act_prin,
            rtol=1e-12, atol=1e-9,
        )

    def test_actual_aggregate_act_cash_equals_sum_of_constituents(self):
        a1, _ = _build_actual_and_scheduled(_build_loan(loan_id=1, balance=1_000_000))
        a2, _ = _build_actual_and_scheduled(_build_loan(loan_id=2, balance=2_000_000))
        agg = _aggregate_actual([a1, a2])

        np.testing.assert_allclose(
            agg.act_cash,
            a1.act_cash + a2.act_cash,
            rtol=1e-12, atol=1e-9,
        )

    def test_actual_aggregate_total_bal_equals_sum_of_constituents(self):
        """total_bal linearity holds even when fcl is non-zero.

        Note: aggregator reconstructs perf_bal and fcl from cumsum of the
        summed flows, which introduces small numerical drift compared to
        the direct constituent-sum (~4e-9 absolute on $3M balances). The
        tolerance here matches the engine's internal balance-identity
        tolerance (atol=1e-5) — see _aggregate_scheduled's balance check.
        """
        a1, _ = _build_actual_and_scheduled(
            _build_loan(loan_id=1, balance=1_000_000),
            cdr_speed=0.03, severity=0.40,
        )
        a2, _ = _build_actual_and_scheduled(
            _build_loan(loan_id=2, balance=2_000_000),
            cdr_speed=0.03, severity=0.40,
        )
        agg = _aggregate_actual([a1, a2])

        np.testing.assert_allclose(
            agg.total_bal,
            a1.total_bal + a2.total_bal,
            rtol=1e-9, atol=1e-5,
        )

    def test_scheduled_aggregate_sched_cash_equals_sum_of_constituents(self):
        _, s1 = _build_actual_and_scheduled(_build_loan(loan_id=1, balance=1_000_000))
        _, s2 = _build_actual_and_scheduled(_build_loan(loan_id=2, balance=2_000_000))
        agg = _aggregate_scheduled([s1, s2])

        np.testing.assert_allclose(
            agg.sched_cash,
            s1.sched_cash + s2.sched_cash,
            rtol=1e-12, atol=1e-9,
        )


# ---------------------------------------------------------------------------
# 4. Aggregator efficiency — derived fields are skipped during accumulation
# ---------------------------------------------------------------------------


class TestAggregatorSkipsDerivedFields:
    """The FLOW accumulator must not include derived fields.

    If derived fields were summed across constituents, the aggregator would
    do redundant work (the new instance's __post_init__ would overwrite the
    summed values anyway). The metadata "derived": True flag tells the
    aggregator's filter to skip these fields.
    """

    def test_actual_flow_fields_excluded_from_accumulator(self):
        """The set of FLOW field names used by _aggregate_actual must NOT
        include act_prin or act_cash."""
        flow_field_names = {
            f.name for f in fields_by_kind(BMAActualCashflow, FieldKind.FLOW)
            if not f.metadata.get("derived")
        }
        # Primitive FLOW fields included
        assert "act_am" in flow_field_names
        assert "vol_prepay" in flow_field_names
        assert "act_int" in flow_field_names
        # Derived FLOW fields excluded
        assert "act_prin" not in flow_field_names
        assert "act_cash" not in flow_field_names

    def test_scheduled_flow_fields_excluded_from_accumulator(self):
        flow_field_names = {
            f.name for f in fields_by_kind(BMAScheduledCashflow, FieldKind.FLOW)
            if not f.metadata.get("derived")
        }
        assert "principal_paid" in flow_field_names
        assert "interest_paid" in flow_field_names
        # Derived field excluded
        assert "sched_cash" not in flow_field_names


# ---------------------------------------------------------------------------
# 5. Parquet round-trip: derived fields recomputed on read
# ---------------------------------------------------------------------------


class TestParquetRoundTrip:
    """Derived fields are not stored in Parquet; they regenerate on read."""

    def test_actual_round_trip_regenerates_derived(self, tmp_path):
        from bma_standard_formulas.engine.cashflow_persistence import (
            read_cashflows,
            write_cashflow,
        )

        actual, _ = _build_actual_and_scheduled(_build_loan())
        path = tmp_path / "cf.parquet"
        write_cashflow(actual, path=path)

        roundtripped = read_cashflows(path=path)[0]
        # All derived fields equal the originals
        np.testing.assert_array_equal(roundtripped.act_prin, actual.act_prin)
        np.testing.assert_array_equal(roundtripped.act_cash, actual.act_cash)
        np.testing.assert_array_equal(roundtripped.total_bal, actual.total_bal)

    def test_scheduled_round_trip_regenerates_derived(self, tmp_path):
        from bma_standard_formulas.engine.cashflow_persistence import (
            read_cashflows,
            write_cashflow,
        )

        _, sched = _build_actual_and_scheduled(_build_loan())
        path = tmp_path / "cf.parquet"
        write_cashflow(sched, path=path)

        roundtripped = read_cashflows(path=path)[0]
        np.testing.assert_array_equal(roundtripped.sched_cash, sched.sched_cash)


# ---------------------------------------------------------------------------
# 6. PortfolioCashflow exposes derived fields on aggregate (.pool / .scheduled)
# ---------------------------------------------------------------------------


class TestPortfolioPoolDerived:
    """When PortfolioCashflow aggregates constituents, the .pool and
    .scheduled properties expose derived fields directly."""

    def test_pool_act_prin_matches_sum_of_constituents(self):
        a1, _ = _build_actual_and_scheduled(_build_loan(loan_id=1, balance=1_000_000))
        a2, _ = _build_actual_and_scheduled(_build_loan(loan_id=2, balance=2_000_000))
        portfolio = PortfolioCashflow([a1, a2], mode=PortfolioMode.ACTUAL_ONLY)

        np.testing.assert_allclose(
            portfolio.pool.act_prin,
            a1.act_prin + a2.act_prin,
            rtol=1e-12, atol=1e-9,
        )

    def test_pool_total_bal_matches_sum_of_constituents(self):
        a1, _ = _build_actual_and_scheduled(_build_loan(loan_id=1, balance=1_000_000))
        a2, _ = _build_actual_and_scheduled(_build_loan(loan_id=2, balance=2_000_000))
        portfolio = PortfolioCashflow([a1, a2], mode=PortfolioMode.ACTUAL_ONLY)

        np.testing.assert_allclose(
            portfolio.pool.total_bal,
            a1.total_bal + a2.total_bal,
            rtol=1e-12, atol=1e-9,
        )

    def test_scheduled_sched_cash_matches_sum_of_constituents(self):
        _, s1 = _build_actual_and_scheduled(_build_loan(loan_id=1, balance=1_000_000))
        _, s2 = _build_actual_and_scheduled(_build_loan(loan_id=2, balance=2_000_000))
        portfolio = PortfolioCashflow([s1, s2], mode=PortfolioMode.SCHEDULED_ONLY)

        np.testing.assert_allclose(
            portfolio.scheduled.sched_cash,
            s1.sched_cash + s2.sched_cash,
            rtol=1e-12, atol=1e-9,
        )
