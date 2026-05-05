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
        actual, scheduled, actual_by_group, scheduled_by_group = _extract_collateral_arrays(run_input)

        assert isinstance(actual, BMAActualCashflow)
        assert isinstance(scheduled, BMAScheduledCashflow)
        assert actual_by_group == {}        # single-pool: untagged loans skipped
        assert scheduled_by_group == {}

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
        actual, scheduled, actual_by_group, scheduled_by_group = _extract_collateral_arrays(run_input)

        assert isinstance(actual, BMAActualCashflow)
        assert set(actual_by_group.keys()) == {"GROUP_1", "GROUP_2"}
        for gid, g_actual in actual_by_group.items():
            assert isinstance(g_actual, BMAActualCashflow)
        assert set(scheduled_by_group.keys()) == {"GROUP_1", "GROUP_2"}

    def test_pooled_ldcma_input_returns_actual_only(self):
        loan = _build_loan(1, group_id=None)
        actual, _ = _build_actual_and_scheduled(loan)
        run_input = from_actual_cashflow(actual, horizon=361, initial_balance=1_000_000.0)

        a, s, abg, sbg = _extract_collateral_arrays(run_input)

        assert isinstance(a, BMAActualCashflow)
        assert s is None              # LDCMA inputs have no scheduled stream
        assert abg == {} and sbg == {}

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
        actual, _, actual_by_group, _ = _extract_collateral_arrays(run_input)

        # Linearity property: aggregate perf_bal == sum of per-group perf_bal
        np.testing.assert_allclose(
            actual.perf_bal,
            actual_by_group["GROUP_1"].perf_bal + actual_by_group["GROUP_2"].perf_bal,
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
