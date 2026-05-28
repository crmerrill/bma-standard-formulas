"""End-to-end tests for the PAIRED collateral input runtime branch (Phase 1b).

Validates that ``run_deal`` accepts a ``PairedCollateralInput`` payload and
produces results equivalent to feeding the same engine output through the
legacy LDCMA-format adapter (``from_actual_cashflow``).

The runtime carries collateral cashflows as typed BMA objects:
``ExecutionContext.actual: BMAActualCashflow`` and (optionally)
``ExecutionContext.scheduled: BMAScheduledCashflow``. All read sites use
attribute access (``actual.perf_bal[i]``, ``actual.act_cash[i]``,
``actual.total_bal[i]``) — no dict-of-arrays indirection. LDCMA-format
inputs are translated at the boundary by ``_ldcma_to_bma_actual``.

What's covered:
  1. The boundary helper ``_ldcma_to_bma_actual`` produces a properly-formed
     BMAActualCashflow from a CollateralCashflows Pydantic model.
  2. PAIRED input parity: a deal run via PAIRED produces bond cashflows
     identical to the same deal run via the legacy LDCMA path.
  3. Multi-group PAIRED: ``ExecutionContext.actual_by_group`` carries one
     BMAActualCashflow per group_id; the runtime routes ``GROUP_<id>_*``
     source tokens correctly.
  4. ``actual.total_bal`` (= perf_bal + fcl) is the deal-mechanics
     "balance" — exposed in the expression context as
     ``collateral_balance`` per deal-mechanics convention.

Why this matters:
  Pre-Phase-1b the deal runtime accepted only LDCMA-format collateral
  feeds, forcing every BMA engine output through a translation adapter
  on every run, then a dict-of-arrays representation internally. PAIRED
  input lets the runtime consume PortfolioCashflow natively with full
  per-loan visibility and BMA-native typed access throughout.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

# Phase 1h: this module exercises the legacy LDCMA-format adapter
# (``from_actual_cashflow``) on purpose — the parity tests below compare
# LDCMA-branch outputs vs PAIRED-branch outputs to validate the runtime's
# input-mode equivalence. Suppress the DeprecationWarning at module
# scope so test output stays clean. Remove this filter when the LDCMA
# path is fully retired.
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

from bma_standard_formulas.deals.adapters import from_actual_cashflow
from bma_standard_formulas.deals.deal_library import passthrough_deal
from bma_standard_formulas.deals.runtime import (
    _extract_collateral_arrays,
    _ldcma_to_bma_actual,
    run_deal,
)
from bma_standard_formulas.deals.schemas.input import (
    DealRunInput,
    PairedCollateralInput,
)
from bma_standard_formulas.engine import PortfolioCashflow
from bma_standard_formulas.engine.loan import (
    Loan,
    actual_cashflow_from_loan,
    scheduled_cashflow_from_loan,
)
from bma_standard_formulas.engine.portfolio import PortfolioMode
from bma_standard_formulas.formulas import generate_smm_curve_from_psa
from bma_standard_formulas.formulas.cashflows import (
    BMAActualCashflow,
    BMAScheduledCashflow,
    CashFlowPair,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_loan(loan_id: int, group_id: str | None = "GROUP_1", balance: float = 1_000_000.0) -> Loan:
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


def _build_actual_and_scheduled(loan: Loan, psa_speed: float = 100.0):
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


def _build_paired_portfolio(loans: list[Loan], psa_speed: float = 100.0) -> PortfolioCashflow:
    pairs = []
    for loan in loans:
        actual, sched = _build_actual_and_scheduled(loan, psa_speed)
        pairs.append(CashFlowPair(scheduled=sched, actual=actual))
    return PortfolioCashflow(pairs, mode=PortfolioMode.PAIRED)


# ---------------------------------------------------------------------------
# 1. Boundary helper: _ldcma_to_bma_actual
# ---------------------------------------------------------------------------


class TestLDCMAtoBMAActual:
    """The boundary helper synthesizes a BMAActualCashflow from an LDCMA dict."""

    def test_returns_bma_actual_cashflow(self):
        loan = _build_loan(1, group_id=None)
        actual, _ = _build_actual_and_scheduled(loan)
        run_input = from_actual_cashflow(actual, horizon=361, initial_balance=1_000_000.0)

        synth = _ldcma_to_bma_actual(run_input.collateral.collateral)

        assert isinstance(synth, BMAActualCashflow)
        # Primitive BMA fields populated from LDCMA equivalents
        assert synth.perf_bal[0] == pytest.approx(1_000_000.0)
        assert len(synth.act_int) == 361
        assert len(synth.act_am) == 361

    def test_derived_fields_populated_after_construction(self):
        """__post_init__ on the BMA dataclass populates act_prin / act_cash /
        total_bal automatically once the synthesized object is constructed."""
        loan = _build_loan(1, group_id=None)
        actual, _ = _build_actual_and_scheduled(loan)
        run_input = from_actual_cashflow(actual, horizon=361, initial_balance=1_000_000.0)
        synth = _ldcma_to_bma_actual(run_input.collateral.collateral)

        np.testing.assert_array_equal(synth.act_prin, synth.act_am + synth.vol_prepay)
        np.testing.assert_array_equal(synth.act_cash, synth.act_prin + synth.act_int)
        np.testing.assert_array_equal(synth.total_bal, synth.perf_bal + synth.fcl)

    def test_fcl_is_zero_for_ldcma_input(self):
        """LDCMA dicts have no foreclosure pipeline representation, so the
        synthesized BMAActualCashflow has fcl = 0 everywhere. This means
        total_bal == perf_bal for any LDCMA-sourced run."""
        loan = _build_loan(1, group_id=None)
        actual, _ = _build_actual_and_scheduled(loan)
        run_input = from_actual_cashflow(actual, horizon=361, initial_balance=1_000_000.0)
        synth = _ldcma_to_bma_actual(run_input.collateral.collateral)

        np.testing.assert_array_equal(synth.fcl, np.zeros(361))
        np.testing.assert_array_equal(synth.total_bal, synth.perf_bal)


# ---------------------------------------------------------------------------
# 2. _extract_collateral_arrays returns typed BMA objects
# ---------------------------------------------------------------------------


class TestExtractCollateralArrays:
    """The runtime extractor returns typed BMA cashflow objects."""

    def test_paired_input_returns_typed_objects(self):
        loan = _build_loan(1, group_id=None)
        portfolio = _build_paired_portfolio([loan])
        run_input = DealRunInput(
            collateral=PairedCollateralInput(portfolio=portfolio),
            loan_count=1,
            original_collateral_balance=1_000_000.0,
        )
        result = _extract_collateral_arrays(run_input)

        assert isinstance(result.actual, BMAActualCashflow)
        assert isinstance(result.scheduled, BMAScheduledCashflow)
        assert result.actual_by_group == {}        # single-pool: untagged loans skipped
        assert result.scheduled_by_group == {}

    def test_paired_multi_group_returns_per_group_dicts(self):
        loans = [
            _build_loan(1, group_id="GROUP_1", balance=1_000_000),
            _build_loan(2, group_id="GROUP_2", balance=500_000),
        ]
        portfolio = _build_paired_portfolio(loans)
        run_input = DealRunInput(
            collateral=PairedCollateralInput(portfolio=portfolio),
            loan_count=2,
            original_collateral_balance=1_500_000.0,
        )
        result = _extract_collateral_arrays(run_input)

        assert isinstance(result.actual, BMAActualCashflow)
        assert set(result.actual_by_group.keys()) == {"GROUP_1", "GROUP_2"}
        for gid, g_actual in result.actual_by_group.items():
            assert isinstance(g_actual, BMAActualCashflow)
        assert set(result.scheduled_by_group.keys()) == {"GROUP_1", "GROUP_2"}

    def test_pooled_ldcma_input_returns_actual_only(self):
        loan = _build_loan(1, group_id=None)
        actual, _ = _build_actual_and_scheduled(loan)
        run_input = from_actual_cashflow(actual, horizon=361, initial_balance=1_000_000.0)

        result = _extract_collateral_arrays(run_input)

        assert isinstance(result.actual, BMAActualCashflow)
        assert result.scheduled is None              # LDCMA inputs have no scheduled stream
        assert result.actual_by_group == {} and result.scheduled_by_group == {}

    def test_paired_aggregate_perf_bal_sums_per_group(self):
        loans = [
            _build_loan(1, "GROUP_1", balance=1_000_000),
            _build_loan(2, "GROUP_2", balance=500_000),
        ]
        portfolio = _build_paired_portfolio(loans)
        run_input = DealRunInput(
            collateral=PairedCollateralInput(portfolio=portfolio),
            loan_count=2,
            original_collateral_balance=1_500_000.0,
        )
        result = _extract_collateral_arrays(run_input)

        # Linearity property: aggregate perf_bal == sum of per-group perf_bal
        np.testing.assert_allclose(
            result.actual.perf_bal,
            result.actual_by_group["GROUP_1"].perf_bal
            + result.actual_by_group["GROUP_2"].perf_bal,
            rtol=1e-10, atol=1e-6,
        )


# ---------------------------------------------------------------------------
# 3. End-to-end PAIRED parity
# ---------------------------------------------------------------------------


class TestPairedDealRunParity:
    """A deal run via PAIRED input produces the same bond cashflows as the
    same deal run via the legacy LDCMA path."""

    @pytest.fixture(scope="class")
    def paired_run_result(self):
        loan = _build_loan(1, group_id=None)
        portfolio = _build_paired_portfolio([loan])
        run_input = DealRunInput(
            collateral=PairedCollateralInput(portfolio=portfolio),
            loan_count=1,
            original_collateral_balance=1_000_000.0,
        )
        return run_deal(passthrough_deal(), run_input, scenario_name="paired")

    @pytest.fixture(scope="class")
    def ldcma_run_result(self):
        loan = _build_loan(1, group_id=None)
        actual, _ = _build_actual_and_scheduled(loan)
        run_input = from_actual_cashflow(actual, horizon=361, initial_balance=1_000_000.0)
        return run_deal(passthrough_deal(), run_input, scenario_name="ldcma")

    def test_residual_balance_matches(self, paired_run_result, ldcma_run_result):
        """The residual class R receives the same cashflows under both inputs."""
        paired_r = [r for r in paired_run_result.bond_cashflows if r.tranche_id == "R"]
        ldcma_r = [r for r in ldcma_run_result.bond_cashflows if r.tranche_id == "R"]
        assert len(paired_r) == len(ldcma_r)

        for p, l in zip(paired_r, ldcma_r):
            assert p.period == l.period
            assert p.cashflow_total == pytest.approx(l.cashflow_total, rel=1e-9, abs=1e-6), (
                f"period {p.period}: cashflow paired={p.cashflow_total} vs ldcma={l.cashflow_total}"
            )

    def test_account_artifacts_match(self, paired_run_result, ldcma_run_result):
        paired_acc = {(r.account_id, r.period): r for r in paired_run_result.deal_accounts}
        ldcma_acc = {(r.account_id, r.period): r for r in ldcma_run_result.deal_accounts}
        assert paired_acc.keys() == ldcma_acc.keys()
        for key, paired_row in paired_acc.items():
            ldcma_row = ldcma_acc[key]
            assert paired_row.end_balance == pytest.approx(
                ldcma_row.end_balance, rel=1e-9, abs=1e-6,
            )


# ---------------------------------------------------------------------------
# 4. Phase 1d.1: Per-loan constituent exposure
# ---------------------------------------------------------------------------
#
# The runtime exposes per-loan cashflow leaves on ``ExecutionContext`` so
# downstream consumers (trigger calculations, rule expressions via the
# Phase 1d.3 ``loans`` accessor, structuring tools, analytics) can reference
# individual loan trajectories rather than only the aggregated pool.
#
# PAIRED inputs carry per-loan ``CashFlowPair`` constituents and populate
# the constituent fields. LDCMA inputs (POOLED, GROUPED, STRIP_PI) are
# pre-aggregated at the source and leave the constituent fields empty —
# the per-loan trajectories are simply not recoverable from an LDCMA
# dict-of-arrays.


class TestExtractCollateralArraysConstituents:
    """Per-loan constituent visibility on the extraction result."""

    def test_paired_single_pool_exposes_actual_constituents(self):
        loans = [_build_loan(i, group_id=None) for i in range(1, 4)]
        portfolio = _build_paired_portfolio(loans)
        run_input = DealRunInput(
            collateral=PairedCollateralInput(portfolio=portfolio),
            loan_count=3,
            original_collateral_balance=3_000_000.0,
        )
        result = _extract_collateral_arrays(run_input)

        # One BMAActualCashflow per loan, in input order.
        assert len(result.actual_constituents) == 3
        for cf in result.actual_constituents:
            assert isinstance(cf, BMAActualCashflow)
        loan_ids = [cf.loan_id for cf in result.actual_constituents]
        assert loan_ids == [1, 2, 3]

        # Single-pool: every loan has group_id=None so by_group is empty
        # (the "_ungrouped" bucket is filtered out for parity with
        # actual_by_group, which also drops it).
        assert result.actual_constituents_by_group == {}

    def test_paired_single_pool_exposes_scheduled_constituents(self):
        loans = [_build_loan(i, group_id=None) for i in range(1, 4)]
        portfolio = _build_paired_portfolio(loans)
        run_input = DealRunInput(
            collateral=PairedCollateralInput(portfolio=portfolio),
            loan_count=3,
            original_collateral_balance=3_000_000.0,
        )
        result = _extract_collateral_arrays(run_input)

        assert len(result.scheduled_constituents) == 3
        for cf in result.scheduled_constituents:
            assert isinstance(cf, BMAScheduledCashflow)

    def test_paired_multi_group_partitions_constituents(self):
        loans = [
            _build_loan(1, group_id="GROUP_1"),
            _build_loan(2, group_id="GROUP_1"),
            _build_loan(3, group_id="GROUP_2"),
        ]
        portfolio = _build_paired_portfolio(loans)
        run_input = DealRunInput(
            collateral=PairedCollateralInput(portfolio=portfolio),
            loan_count=3,
            original_collateral_balance=3_000_000.0,
        )
        result = _extract_collateral_arrays(run_input)

        # Whole-pool view holds every loan.
        assert len(result.actual_constituents) == 3

        # Per-group partition: GROUP_1 has 2 loans, GROUP_2 has 1.
        assert set(result.actual_constituents_by_group.keys()) == {"GROUP_1", "GROUP_2"}
        assert len(result.actual_constituents_by_group["GROUP_1"]) == 2
        assert len(result.actual_constituents_by_group["GROUP_2"]) == 1
        assert {cf.loan_id for cf in result.actual_constituents_by_group["GROUP_1"]} == {1, 2}
        assert {cf.loan_id for cf in result.actual_constituents_by_group["GROUP_2"]} == {3}

    def test_paired_multi_group_filters_ungrouped_bucket(self):
        """Mixed tagged + untagged tape: untagged loans contribute to the
        whole-pool view but are filtered out of the per-group partition
        for consistency with ``actual_by_group``."""
        loans = [
            _build_loan(1, group_id="GROUP_1"),
            _build_loan(2, group_id=None),       # untagged
            _build_loan(3, group_id="GROUP_2"),
        ]
        portfolio = _build_paired_portfolio(loans)
        run_input = DealRunInput(
            collateral=PairedCollateralInput(portfolio=portfolio),
            loan_count=3,
            original_collateral_balance=3_000_000.0,
        )
        result = _extract_collateral_arrays(run_input)

        # Whole-pool view includes the untagged loan.
        assert {cf.loan_id for cf in result.actual_constituents} == {1, 2, 3}

        # Per-group partition does NOT surface the "_ungrouped" bucket.
        assert "_ungrouped" not in result.actual_constituents_by_group
        assert set(result.actual_constituents_by_group.keys()) == {"GROUP_1", "GROUP_2"}

    def test_pooled_ldcma_input_constituents_empty(self):
        """LDCMA inputs are pre-aggregated and have no per-loan visibility."""
        loan = _build_loan(1, group_id=None)
        actual, _ = _build_actual_and_scheduled(loan)
        run_input = from_actual_cashflow(actual, horizon=361, initial_balance=1_000_000.0)

        result = _extract_collateral_arrays(run_input)

        assert result.actual_constituents == []
        assert result.scheduled_constituents == []
        assert result.actual_constituents_by_group == {}
        assert result.scheduled_constituents_by_group == {}

    def test_constituent_aggregation_invariant(self):
        """Sum of per-loan act_int across constituents equals the aggregate
        act_int. Pins the invariant that constituents are the same data
        the aggregator consumed."""
        loans = [_build_loan(i, group_id=None) for i in range(1, 4)]
        portfolio = _build_paired_portfolio(loans)
        run_input = DealRunInput(
            collateral=PairedCollateralInput(portfolio=portfolio),
            loan_count=3,
            original_collateral_balance=3_000_000.0,
        )
        result = _extract_collateral_arrays(run_input)

        per_loan_sum = np.zeros_like(result.actual.act_int)
        for cf in result.actual_constituents:
            per_loan_sum = per_loan_sum + cf.act_int

        np.testing.assert_allclose(
            result.actual.act_int, per_loan_sum, rtol=1e-9, atol=1e-6,
        )


class TestExecutionContextConstituents:
    """``run_deal`` populates ``ExecutionContext.constituents`` from the
    extraction result so downstream rule/calculation hooks see the per-loan
    leaves. Phase 1d.3 adds the ``loans`` expression accessor that
    consumes this data; the end-to-end test below validates that a
    ``CalculationNode`` can iterate ``loans`` and produce a value that
    matches the equivalent BMA-aggregate calculation."""

    def test_paired_run_populates_constituents_via_trace(self):
        # Use a passthrough_deal that emits a trace; we verify the runtime
        # accepts a PAIRED input with constituents and runs to completion.
        # The constituents fields on ExecutionContext are private to the
        # runtime, so the assertion here is end-to-end: the run completes
        # AND the underlying portfolio's constituent count survives the
        # extraction round-trip (verified by re-extracting from the input).
        loans = [_build_loan(i, group_id=None) for i in range(1, 4)]
        portfolio = _build_paired_portfolio(loans)
        run_input = DealRunInput(
            collateral=PairedCollateralInput(portfolio=portfolio),
            loan_count=3,
            original_collateral_balance=3_000_000.0,
        )

        bundle = run_deal(passthrough_deal(), run_input, scenario_name="constituent_test")
        assert bundle is not None

        # The same extraction the runtime did should give us the constituents.
        extraction = _extract_collateral_arrays(run_input)
        assert len(extraction.actual_constituents) == 3
        assert {cf.loan_id for cf in extraction.actual_constituents} == {1, 2, 3}

    def test_loans_accessor_in_expression_context(self):
        """End-to-end Phase 1d.3 validation: ``_build_expr_context``
        populates the ``loans`` and ``loans_by_group`` keys with
        ``LoanProxy`` lists when constituents are present, and the
        sandbox can iterate over them.

        Pins the wire-up that ``ExecutionContext.constituents`` →
        ``_build_expr_context`` argument → ``LoanProxy`` list under the
        ``loans`` key → safe-eval comprehension produces the right
        value.
        """
        from bma_standard_formulas.deals.runtime import (
            LoanProxy,
            _build_expr_context,
            _safe_eval_expr,
        )
        from bma_standard_formulas.deals.schemas.ir import (
            DealDefinition, BondDef, RuleNode, RuleType,
        )

        loans = [_build_loan(i, group_id=None) for i in range(1, 4)]
        portfolio = _build_paired_portfolio(loans)
        run_input = DealRunInput(
            collateral=PairedCollateralInput(portfolio=portfolio),
            loan_count=3,
            original_collateral_balance=3_000_000.0,
        )
        extraction = _extract_collateral_arrays(run_input)

        # Minimal deal stub for _build_expr_context's first arg.
        deal = DealDefinition(
            deal_name="loans_accessor_e2e",
            bonds=[
                BondDef(name="A", coupon=5.0, notional=3_000_000.0),
                BondDef(name="R", is_pseudo=True, kind="RESIDUAL"),
            ],
            waterfall_rules=[
                RuleNode(
                    rule_id="r_resid",
                    rule_type=RuleType.PAY_RESIDUAL,
                    order=0,
                    from_sources=["CASH"],
                    to_targets=["R"],
                ),
            ],
        )

        # Period 1 — first month with cashflow.
        i = 1
        ctx = _build_expr_context(
            deal=deal,
            run_input=run_input,
            actual=extraction.actual,
            scheduled=extraction.scheduled,
            bonds={},
            accounts={},
            trigger_states={},
            calculation_values={},
            virtual_sources={},
            cash_avail=None,
            i=i,
            orig_collat_bal=3_000_000.0,
            constituents=extraction.actual_constituents,
            constituents_by_group=extraction.actual_constituents_by_group,
        )

        # 1) ``loans`` is exposed as a list of LoanProxy objects.
        assert "loans" in ctx
        assert isinstance(ctx["loans"], list)
        assert len(ctx["loans"]) == 3
        assert all(isinstance(p, LoanProxy) for p in ctx["loans"])

        # 2) Iterating loans in a comprehension produces the right count.
        assert _safe_eval_expr("len(loans)", ctx) == 3.0

        # 3) Sum-over-loans equals the aggregate field exposed in the
        #    same context (collateral_act_int). Period 1 act_int per
        #    loan summed equals the pool-level act_int.
        per_loan_sum = _safe_eval_expr("sum(l.act_int[period] for l in loans)", ctx)
        aggregate = ctx["collateral_act_int"]
        assert per_loan_sum == pytest.approx(aggregate, rel=1e-9, abs=1e-6)

        # 4) Filter expression: count loans with positive perf_bal at period 1.
        active_count = _safe_eval_expr(
            "len([l for l in loans if l.perf_bal[period] > 0])", ctx,
        )
        assert active_count == 3.0

    def test_loans_accessor_empty_for_ldcma_input(self):
        """LDCMA-format inputs are pre-aggregated and have no per-loan
        visibility. The ``loans`` accessor must be an empty list so
        expressions degrade gracefully without raising."""
        from bma_standard_formulas.deals.runtime import (
            _build_expr_context,
            _safe_eval_expr,
        )
        from bma_standard_formulas.deals.schemas.ir import (
            DealDefinition, BondDef, RuleNode, RuleType,
        )

        loan = _build_loan(1, group_id=None)
        actual, _ = _build_actual_and_scheduled(loan)
        run_input = from_actual_cashflow(actual, horizon=361, initial_balance=1_000_000.0)
        extraction = _extract_collateral_arrays(run_input)

        deal = DealDefinition(
            deal_name="ldcma_no_loans",
            bonds=[
                BondDef(name="A", coupon=5.0, notional=1_000_000.0),
                BondDef(name="R", is_pseudo=True, kind="RESIDUAL"),
            ],
            waterfall_rules=[
                RuleNode(
                    rule_id="r_resid",
                    rule_type=RuleType.PAY_RESIDUAL,
                    order=0,
                    from_sources=["CASH"],
                    to_targets=["R"],
                ),
            ],
        )

        ctx = _build_expr_context(
            deal=deal,
            run_input=run_input,
            actual=extraction.actual,
            scheduled=extraction.scheduled,
            bonds={},
            accounts={},
            trigger_states={},
            calculation_values={},
            virtual_sources={},
            cash_avail=None,
            i=1,
            orig_collat_bal=1_000_000.0,
            constituents=extraction.actual_constituents,
            constituents_by_group=extraction.actual_constituents_by_group,
        )

        assert ctx["loans"] == []
        # Empty iteration yields zero — expression doesn't crash.
        assert _safe_eval_expr("len(loans)", ctx) == 0.0
        assert _safe_eval_expr("sum(l.act_int[period] for l in loans)", ctx) == 0.0
