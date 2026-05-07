"""Tests for group-aware aggregation on PortfolioCashflow (Phase 0A).

Covers:
  1. The module-level helpers ``_aggregate_actual_by_group`` and
     ``_aggregate_scheduled_by_group``.
  2. The PortfolioCashflow methods ``aggregate_actual_by_group`` and
     ``aggregate_scheduled_by_group``.
  3. The flush() lifecycle interaction — per-group caches are populated
     before _pending is cleared so post-flush callers still get per-group
     results.

Why this matters:
  Per-loan cashflows carry a ``group_id`` field propagated from the source
  ``Loan.group_id``.  Multi-group RMBS deals (e.g., FNR 2006-018 with two
  collateral groups, each backing a different waterfall branch) need
  per-group cashflow streams.  The pre-Phase-0A pattern was to run the
  engine N+1 times — once for the aggregate, once per group with a filtered
  loan list.  Phase 0A makes this a single engine call followed by
  partition-and-aggregate over the resulting constituents, eliminating
  duplicate engine work.

  See ``docs/architecture/waterfall_ir_design.md`` proposal Phase 0
  (Round 3 IR rebuild) for the full architecture rationale.
"""
from __future__ import annotations

import numpy as np
import pytest

from bma_standard_formulas.engine.portfolio import (
    PortfolioCashflow,
    PortfolioMode,
    _aggregate_actual,
    _aggregate_actual_by_group,
    _aggregate_scheduled_by_group,
    _partition_by_group_id,
)
from bma_standard_formulas.engine.loan import (
    Loan,
    actual_cashflow_from_loan,
    scheduled_cashflow_from_loan,
)
from bma_standard_formulas.formulas import generate_smm_curve_from_psa
from datetime import date


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_loan(loan_id: int, group_id: str | None, balance: float = 1_000_000.0) -> Loan:
    """Construct a minimal fixed-rate Loan for testing.

    All loans share the same WAC, term, asof_date, and remaining_term so we
    can isolate the group-aggregation logic from per-loan amortization
    differences.  group_id is the only varying parameter.
    """
    return Loan(
        loan_id=loan_id,
        origination_date=date(2024, 1, 1),
        asof_date=date(2024, 1, 1),
        original_balance=balance,
        current_balance=balance,
        rate_margin=6.0,
        original_term=360,
        remaining_term=360,
        group_id=group_id,
    )


def _build_actual_cashflow(loan: Loan, psa_speed: float = 100.0):
    """Run the engine for a single loan and return its BMAActualCashflow."""
    sched = scheduled_cashflow_from_loan(loan)
    smm = generate_smm_curve_from_psa(psa_speed, loan.original_term)
    n = loan.original_term + 1
    actual = actual_cashflow_from_loan(
        loan=loan,
        scheduled_cf=sched,
        smm_curve=smm,
        mdr_curve=np.zeros(n),
        severity_curve=np.zeros(n),
    )
    return actual, sched


# ---------------------------------------------------------------------------
# 1. Module-level partitioning helper
# ---------------------------------------------------------------------------


class TestPartitionByGroupId:
    """The partition primitive routes constituents into named buckets."""

    def test_two_groups(self):
        l1, _ = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        l2, _ = _build_actual_cashflow(_build_loan(2, "GROUP_2"))
        l3, _ = _build_actual_cashflow(_build_loan(3, "GROUP_1"))
        buckets = _partition_by_group_id([l1, l2, l3])
        assert set(buckets.keys()) == {"GROUP_1", "GROUP_2"}
        assert len(buckets["GROUP_1"]) == 2
        assert len(buckets["GROUP_2"]) == 1

    def test_none_goes_to_ungrouped_bucket(self):
        l_tagged, _ = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        l_untagged, _ = _build_actual_cashflow(_build_loan(2, None))
        buckets = _partition_by_group_id([l_tagged, l_untagged])
        assert "_ungrouped" in buckets
        assert "GROUP_1" in buckets
        assert len(buckets["_ungrouped"]) == 1
        assert len(buckets["GROUP_1"]) == 1

    def test_empty_list_returns_empty_dict(self):
        assert _partition_by_group_id([]) == {}

    def test_numeric_group_id_stringified(self):
        """Numeric group_ids are coerced to str so dict keys are stable."""
        l1, _ = _build_actual_cashflow(_build_loan(1, group_id=1))
        l2, _ = _build_actual_cashflow(_build_loan(2, group_id=2))
        buckets = _partition_by_group_id([l1, l2])
        assert "1" in buckets and "2" in buckets


# ---------------------------------------------------------------------------
# 2. Module-level aggregation helpers
# ---------------------------------------------------------------------------


class TestAggregateActualByGroup:
    """The actual-cashflow aggregator partitions then aggregates."""

    def test_two_groups_produces_two_aggregates(self):
        l1, _ = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        l2, _ = _build_actual_cashflow(_build_loan(2, "GROUP_2"))
        result = _aggregate_actual_by_group([l1, l2])
        assert set(result.keys()) == {"GROUP_1", "GROUP_2"}
        # Each group has only one constituent, so the aggregate is the
        # constituent itself (single-CF early return path).
        assert result["GROUP_1"] is l1
        assert result["GROUP_2"] is l2

    def test_per_group_sums_match_whole_portfolio_for_flow_fields(self):
        """Linearity check: sum of per-group flow arrays equals whole-portfolio.

        FLOW fields (perf_bal, act_int, act_am, vol_prepay, prin_loss, ...)
        are linear under summation.  Aggregating all constituents then
        comparing to the period-wise sum of per-group aggregates must agree
        within floating-point tolerance.
        """
        l1, _ = _build_actual_cashflow(_build_loan(1, "GROUP_1", balance=1_000_000))
        l2, _ = _build_actual_cashflow(_build_loan(2, "GROUP_1", balance=2_000_000))
        l3, _ = _build_actual_cashflow(_build_loan(3, "GROUP_2", balance=500_000))
        l4, _ = _build_actual_cashflow(_build_loan(4, "GROUP_2", balance=750_000))

        whole = _aggregate_actual([l1, l2, l3, l4])
        per_group = _aggregate_actual_by_group([l1, l2, l3, l4])

        assert set(per_group.keys()) == {"GROUP_1", "GROUP_2"}

        # Check flow-field identity for the major BMA flow fields
        for field_name in ("act_am", "vol_prepay", "act_int", "new_def", "prin_loss"):
            whole_arr = getattr(whole, field_name)
            summed = (
                getattr(per_group["GROUP_1"], field_name)
                + getattr(per_group["GROUP_2"], field_name)
            )
            np.testing.assert_allclose(whole_arr, summed, rtol=1e-10, atol=1e-6)

        # Stock fields (perf_bal) also additive at flow boundaries
        np.testing.assert_allclose(
            whole.perf_bal,
            per_group["GROUP_1"].perf_bal + per_group["GROUP_2"].perf_bal,
            rtol=1e-10, atol=1e-6,
        )

    def test_empty_list_returns_empty_dict(self):
        assert _aggregate_actual_by_group([]) == {}

    def test_mixed_grouped_and_ungrouped(self):
        l1, _ = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        l2, _ = _build_actual_cashflow(_build_loan(2, None))
        result = _aggregate_actual_by_group([l1, l2])
        assert set(result.keys()) == {"GROUP_1", "_ungrouped"}


class TestAggregateScheduledByGroup:
    """The scheduled-cashflow aggregator partitions then aggregates."""

    def test_per_group_sums_match_whole_portfolio(self):
        _, s1 = _build_actual_cashflow(_build_loan(1, "GROUP_1", balance=1_000_000))
        _, s2 = _build_actual_cashflow(_build_loan(2, "GROUP_2", balance=500_000))
        per_group = _aggregate_scheduled_by_group([s1, s2])
        assert set(per_group.keys()) == {"GROUP_1", "GROUP_2"}
        # Single-constituent groups return the constituent itself
        assert per_group["GROUP_1"] is s1
        assert per_group["GROUP_2"] is s2


# ---------------------------------------------------------------------------
# 3. PortfolioCashflow instance methods
# ---------------------------------------------------------------------------


class TestPortfolioAggregateActualByGroup:
    """The PortfolioCashflow method exposes the helper with caching + lifecycle."""

    def test_returns_one_aggregate_per_group(self):
        l1, _ = _build_actual_cashflow(_build_loan(1, "GROUP_1", balance=1_000_000))
        l2, _ = _build_actual_cashflow(_build_loan(2, "GROUP_2", balance=500_000))
        portfolio = PortfolioCashflow([l1, l2], mode=PortfolioMode.ACTUAL_ONLY)
        result = portfolio.aggregate_actual_by_group()
        assert set(result.keys()) == {"GROUP_1", "GROUP_2"}

    def test_result_is_cached(self):
        """Second call returns the same dict object (cached in _committed)."""
        l1, _ = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        portfolio = PortfolioCashflow([l1], mode=PortfolioMode.ACTUAL_ONLY)
        first = portfolio.aggregate_actual_by_group()
        second = portfolio.aggregate_actual_by_group()
        assert first is second

    def test_empty_portfolio_returns_empty_dict(self):
        portfolio = PortfolioCashflow([], mode=PortfolioMode.ACTUAL_ONLY)
        assert portfolio.aggregate_actual_by_group() == {}

    def test_paired_mode_uses_actual_component(self):
        """In PAIRED mode the .actual component of each CashFlowPair is used."""
        from bma_standard_formulas.formulas.cashflows import CashFlowPair

        l1 = _build_loan(1, "GROUP_1")
        a1, s1 = _build_actual_cashflow(l1)
        pair = CashFlowPair(scheduled=s1, actual=a1)
        portfolio = PortfolioCashflow([pair], mode=PortfolioMode.PAIRED)
        result = portfolio.aggregate_actual_by_group()
        assert "GROUP_1" in result

    def test_aggregate_sum_equals_whole_pool(self):
        """Property: summing per-group aggregates over FLOW fields == pool aggregate."""
        loans_g1 = [_build_loan(i, "GROUP_1", balance=500_000) for i in (1, 2)]
        loans_g2 = [_build_loan(i, "GROUP_2", balance=750_000) for i in (3, 4)]
        cashflows = [_build_actual_cashflow(loan)[0] for loan in loans_g1 + loans_g2]
        portfolio = PortfolioCashflow(cashflows, mode=PortfolioMode.ACTUAL_ONLY)

        whole = portfolio.pool
        per_group = portfolio.aggregate_actual_by_group()

        for field_name in ("act_am", "vol_prepay", "act_int"):
            whole_arr = getattr(whole, field_name)
            summed = sum(getattr(g, field_name) for g in per_group.values())
            np.testing.assert_allclose(whole_arr, summed, rtol=1e-10, atol=1e-6)


class TestPortfolioAggregateScheduledByGroup:
    """SCHEDULED_ONLY and PAIRED modes expose per-group scheduled aggregates."""

    def test_scheduled_only_mode(self):
        _, s1 = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        _, s2 = _build_actual_cashflow(_build_loan(2, "GROUP_2"))
        portfolio = PortfolioCashflow([s1, s2], mode=PortfolioMode.SCHEDULED_ONLY)
        result = portfolio.aggregate_scheduled_by_group()
        assert set(result.keys()) == {"GROUP_1", "GROUP_2"}

    def test_paired_mode_uses_scheduled_component(self):
        from bma_standard_formulas.formulas.cashflows import CashFlowPair

        l1 = _build_loan(1, "GROUP_1")
        a1, s1 = _build_actual_cashflow(l1)
        pair = CashFlowPair(scheduled=s1, actual=a1)
        portfolio = PortfolioCashflow([pair], mode=PortfolioMode.PAIRED)
        result = portfolio.aggregate_scheduled_by_group()
        assert "GROUP_1" in result


# ---------------------------------------------------------------------------
# 4. Flush lifecycle
# ---------------------------------------------------------------------------


class TestFlushLifecycle:
    """flush() must populate per-group caches BEFORE _pending is cleared."""

    def test_flush_preserves_per_group_aggregates_when_grouped(self):
        l1, _ = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        l2, _ = _build_actual_cashflow(_build_loan(2, "GROUP_2"))
        portfolio = PortfolioCashflow([l1, l2], mode=PortfolioMode.ACTUAL_ONLY)
        portfolio.flush()
        # Post-flush: _pending is empty, but per-group cache should be populated
        assert len(portfolio._pending) == 0
        result = portfolio.aggregate_actual_by_group()
        assert set(result.keys()) == {"GROUP_1", "GROUP_2"}

    def test_flush_skips_per_group_when_no_grouped_constituents(self):
        """Pure single-pool portfolios skip the per-group partition cost.

        After flush(), aggregate_actual_by_group() returns {} for an
        all-ungrouped portfolio because (a) we don't pay the partition cost
        on flush, and (b) the constituents are gone so we can't compute it
        on demand.  This is the intended behavior — single-pool callers don't
        need per-group results.
        """
        l1, _ = _build_actual_cashflow(_build_loan(1, None))
        l2, _ = _build_actual_cashflow(_build_loan(2, None))
        portfolio = PortfolioCashflow([l1, l2], mode=PortfolioMode.ACTUAL_ONLY)
        portfolio.flush()
        assert portfolio._has_grouped_constituents() is False
        # After flush with no grouping, per-group dict is empty
        assert portfolio.aggregate_actual_by_group() == {}

    def test_paired_flush_populates_both_caches(self):
        from bma_standard_formulas.formulas.cashflows import CashFlowPair

        a1, s1 = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        a2, s2 = _build_actual_cashflow(_build_loan(2, "GROUP_2"))
        pair1 = CashFlowPair(scheduled=s1, actual=a1)
        pair2 = CashFlowPair(scheduled=s2, actual=a2)
        portfolio = PortfolioCashflow([pair1, pair2], mode=PortfolioMode.PAIRED)
        portfolio.flush()
        # Both per-group caches populated
        actual_result = portfolio.aggregate_actual_by_group()
        scheduled_result = portfolio.aggregate_scheduled_by_group()
        assert set(actual_result.keys()) == {"GROUP_1", "GROUP_2"}
        assert set(scheduled_result.keys()) == {"GROUP_1", "GROUP_2"}

    def test_has_grouped_constituents_detects_partial_tagging(self):
        """One tagged loan is enough to trigger the flag (and per-group flush)."""
        l_tagged, _ = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        l_untagged, _ = _build_actual_cashflow(_build_loan(2, None))
        portfolio = PortfolioCashflow(
            [l_untagged, l_tagged],
            mode=PortfolioMode.ACTUAL_ONLY,
        )
        assert portfolio._has_grouped_constituents() is True


# ---------------------------------------------------------------------------
# 5. Invalidation on mutation
# ---------------------------------------------------------------------------


class TestInvalidation:
    """The cached per-group result must be invalidated when the portfolio mutates."""

    def test_per_group_cache_cleared_on_addition(self):
        l1, _ = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        l2, _ = _build_actual_cashflow(_build_loan(2, "GROUP_2"))
        portfolio = PortfolioCashflow([l1], mode=PortfolioMode.ACTUAL_ONLY)
        result_a = portfolio.aggregate_actual_by_group()
        assert set(result_a.keys()) == {"GROUP_1"}

        # Mutate via in-place add
        portfolio += l2
        # Cache should be invalidated; new call returns updated dict
        result_b = portfolio.aggregate_actual_by_group()
        assert set(result_b.keys()) == {"GROUP_1", "GROUP_2"}
        assert result_a is not result_b


# ---------------------------------------------------------------------------
# 6. Phase 1d.1: Public per-loan constituent accessors
# ---------------------------------------------------------------------------
#
# ``actual_constituents`` / ``scheduled_constituents`` (and their _by_group
# variants) expose per-loan cashflow leaves so downstream consumers (deal
# runtime ExecutionContext, structuring tools, analytics) can reference
# individual loans rather than only the aggregated pool. They wrap the
# private ``_extract_*_constituents`` helpers and return new lists so caller
# mutation cannot corrupt internal state.
#
# The runtime uses these for the Phase 1d.3 ``loans`` expression accessor,
# which lets calculation expressions iterate per-loan attributes (e.g.,
# ``len([l for l in loans if l.perf_bal[i] > 0])``).


class TestActualConstituentsPublic:
    """Public ``actual_constituents`` accessor on PortfolioCashflow."""

    def test_returns_per_loan_actual_cashflows(self):
        l1, _ = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        l2, _ = _build_actual_cashflow(_build_loan(2, "GROUP_1"))
        l3, _ = _build_actual_cashflow(_build_loan(3, "GROUP_2"))
        portfolio = PortfolioCashflow([l1, l2, l3], mode=PortfolioMode.ACTUAL_ONLY)

        cfs = portfolio.actual_constituents()

        assert len(cfs) == 3
        assert [cf.loan_id for cf in cfs] == [1, 2, 3]

    def test_returns_new_list_not_view(self):
        """Caller mutation of the returned list must not affect the portfolio."""
        l1, _ = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        l2, _ = _build_actual_cashflow(_build_loan(2, "GROUP_2"))
        portfolio = PortfolioCashflow([l1, l2], mode=PortfolioMode.ACTUAL_ONLY)

        cfs = portfolio.actual_constituents()
        cfs.clear()

        # Internal _pending should still hold both constituents.
        assert len(portfolio._pending) == 2

    def test_returns_empty_after_flush(self):
        """flush() clears _pending, so constituent accessors return []."""
        l1, _ = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        portfolio = PortfolioCashflow([l1], mode=PortfolioMode.ACTUAL_ONLY)
        portfolio.flush()
        assert portfolio.actual_constituents() == []


class TestScheduledConstituentsPublic:
    """Public ``scheduled_constituents`` accessor on PortfolioCashflow."""

    def test_returns_per_loan_scheduled_cashflows(self):
        _, s1 = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        _, s2 = _build_actual_cashflow(_build_loan(2, "GROUP_2"))
        portfolio = PortfolioCashflow([s1, s2], mode=PortfolioMode.SCHEDULED_ONLY)

        cfs = portfolio.scheduled_constituents()

        assert len(cfs) == 2
        assert [cf.loan_id for cf in cfs] == [1, 2]


class TestActualConstituentsByGroupPublic:
    """Public partition accessor returns per-group lists of per-loan cashflows."""

    def test_partitions_by_group_id(self):
        l1, _ = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        l2, _ = _build_actual_cashflow(_build_loan(2, "GROUP_1"))
        l3, _ = _build_actual_cashflow(_build_loan(3, "GROUP_2"))
        portfolio = PortfolioCashflow([l1, l2, l3], mode=PortfolioMode.ACTUAL_ONLY)

        partitioned = portfolio.actual_constituents_by_group()

        assert set(partitioned.keys()) == {"GROUP_1", "GROUP_2"}
        assert {cf.loan_id for cf in partitioned["GROUP_1"]} == {1, 2}
        assert {cf.loan_id for cf in partitioned["GROUP_2"]} == {3}

    def test_untagged_loans_go_to_ungrouped_bucket(self):
        l_tagged, _ = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        l_untagged, _ = _build_actual_cashflow(_build_loan(2, None))
        portfolio = PortfolioCashflow(
            [l_tagged, l_untagged], mode=PortfolioMode.ACTUAL_ONLY,
        )

        partitioned = portfolio.actual_constituents_by_group()

        assert set(partitioned.keys()) == {"GROUP_1", "_ungrouped"}
        assert partitioned["GROUP_1"][0].loan_id == 1
        assert partitioned["_ungrouped"][0].loan_id == 2

    def test_returns_per_loan_objects_not_aggregates(self):
        """Distinguishes from ``aggregate_actual_by_group`` which returns
        per-group BMAActualCashflow aggregates. The partition accessor
        returns the original per-loan leaves; aggregation has not run."""
        l1, _ = _build_actual_cashflow(_build_loan(1, "GROUP_1", balance=1_000_000))
        l2, _ = _build_actual_cashflow(_build_loan(2, "GROUP_1", balance=500_000))
        portfolio = PortfolioCashflow([l1, l2], mode=PortfolioMode.ACTUAL_ONLY)

        partitioned = portfolio.actual_constituents_by_group()
        aggregated = portfolio.aggregate_actual_by_group()

        # Partitioned: list of two per-loan cashflows, each with its own balance
        assert len(partitioned["GROUP_1"]) == 2
        per_loan_balances = sorted(cf.original_balance for cf in partitioned["GROUP_1"])
        assert per_loan_balances == [500_000.0, 1_000_000.0]

        # Aggregated: single combined cashflow
        agg = aggregated["GROUP_1"]
        # Sum-of-act_int across per-loan cashflows equals the aggregated act_int
        np.testing.assert_allclose(
            agg.act_int,
            partitioned["GROUP_1"][0].act_int + partitioned["GROUP_1"][1].act_int,
            rtol=1e-9, atol=1e-6,
        )


class TestScheduledConstituentsByGroupPublic:
    """Mirror of TestActualConstituentsByGroupPublic for scheduled cashflows."""

    def test_partitions_by_group_id(self):
        _, s1 = _build_actual_cashflow(_build_loan(1, "GROUP_1"))
        _, s2 = _build_actual_cashflow(_build_loan(2, "GROUP_2"))
        portfolio = PortfolioCashflow([s1, s2], mode=PortfolioMode.SCHEDULED_ONLY)

        partitioned = portfolio.scheduled_constituents_by_group()

        assert set(partitioned.keys()) == {"GROUP_1", "GROUP_2"}
        assert partitioned["GROUP_1"][0].loan_id == 1
        assert partitioned["GROUP_2"][0].loan_id == 2
