"""End-to-end tests for the PAIRED collateral input runtime branch (Phase 1b).

Validates that ``run_deal`` accepts a ``PairedCollateralInput`` payload and
produces results equivalent to feeding the same engine output through the
legacy LDCMA-format adapter (``from_actual_cashflow``).

The runtime now uses BMA-native field names internally (``perf_bal``,
``act_int``, ``act_am``, ``vol_prepay``, ``prin_loss``, ``prin_recov``,
``new_def``, plus combined ``act_prin`` and ``act_cash``), with LDCMA
aliases (``balance``, ``interest``, ``principal``, ``cashflow``, ``loss``,
...) populated as views onto the BMA-native arrays for backward
compatibility with existing fixtures and IR expressions.

What's covered:
  1. PAIRED input parity: a deal run via PAIRED produces bond cashflows
     identical to the same deal run via the legacy LDCMA path.
  2. Multi-group PAIRED: the runtime extracts per-group BMA-native arrays
     via ``portfolio.aggregate_actual_by_group()`` and
     ``aggregate_scheduled_by_group()`` (Phase 0A) so ``GROUP_<id>_*``
     source tokens route correctly.
  3. Internal BMA-native naming: the collateral dict carries both the
     BMA-native canonical keys and the LDCMA aliases.

Why this matters:
  Pre-Phase-1b the deal runtime accepted only LDCMA-format collateral
  feeds, forcing every BMA engine output through a translation adapter
  on every run. PAIRED input lets the runtime consume PortfolioCashflow
  natively with full per-loan visibility (the ``portfolio.constituents``
  list is preserved through the runtime context for Phase 1d).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from bma_standard_formulas.deals.adapters import from_actual_cashflow
from bma_standard_formulas.deals.deal_library import passthrough_deal
from bma_standard_formulas.deals.runtime import (
    _bma_actual_to_dict,
    _ldcma_cashflow_to_bma_native,
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
from bma_standard_formulas.formulas.cashflows import CashFlowPair


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
# 1. BMA-native dict shape
# ---------------------------------------------------------------------------


class TestBMAActualToDict:
    """The BMA-native dict carries both canonical names and LDCMA aliases."""

    def test_canonical_bma_keys_present(self):
        loan = _build_loan(1)
        actual, _ = _build_actual_and_scheduled(loan)
        out = _bma_actual_to_dict(actual)

        # Canonical BMA-native FLOW + STOCK + RATIO fields
        for key in (
            "perf_bal", "act_int", "act_am", "vol_prepay",
            "prin_loss", "prin_recov", "new_def",
            "mdr", "smm", "gross_rate", "net_rate", "age",
        ):
            assert key in out, f"missing canonical BMA key {key!r}"

    def test_combined_streams_are_correct_sums(self):
        loan = _build_loan(1)
        actual, _ = _build_actual_and_scheduled(loan)
        out = _bma_actual_to_dict(actual)

        # act_prin = act_am + vol_prepay
        np.testing.assert_allclose(
            out["act_prin"], out["act_am"] + out["vol_prepay"],
            rtol=0, atol=1e-9,
        )
        # act_cash = act_prin + act_int
        np.testing.assert_allclose(
            out["act_cash"], out["act_prin"] + out["act_int"],
            rtol=0, atol=1e-9,
        )

    def test_ldcma_aliases_match_canonical(self):
        loan = _build_loan(1)
        actual, _ = _build_actual_and_scheduled(loan)
        out = _bma_actual_to_dict(actual)

        # Aliases point at the same arrays as the BMA canonical names
        assert out["balance"] is out["perf_bal"] or np.array_equal(out["balance"], out["perf_bal"])
        assert out["interest"] is out["act_int"] or np.array_equal(out["interest"], out["act_int"])
        assert out["loss"] is out["prin_loss"] or np.array_equal(out["loss"], out["prin_loss"])
        np.testing.assert_array_equal(out["principal"], out["act_prin"])
        np.testing.assert_array_equal(out["cashflow"], out["act_cash"])

    def test_cpr_cdr_derived_from_smm_mdr(self):
        loan = _build_loan(1)
        actual, _ = _build_actual_and_scheduled(loan, psa_speed=100.0)
        out = _bma_actual_to_dict(actual)

        # cpr = 1 - (1 - smm)**12
        expected_cpr = 1.0 - np.power(np.maximum(1.0 - out["smm"], 0.0), 12)
        np.testing.assert_allclose(out["cpr"], expected_cpr, rtol=1e-12)


# ---------------------------------------------------------------------------
# 2. LDCMA -> BMA-native translation
# ---------------------------------------------------------------------------


class TestLDCMAtoBMANative:
    """LDCMA-format inputs translate to the same BMA-native dict shape."""

    def test_ldcma_dict_produces_bma_native_keys(self):
        # Build an LDCMA-format DealRunInput via the legacy adapter, then
        # translate the inner CollateralCashflows back to BMA-native.
        loan = _build_loan(1)
        actual, _ = _build_actual_and_scheduled(loan)
        run_input = from_actual_cashflow(actual, horizon=361, initial_balance=1_000_000.0)
        out = _ldcma_cashflow_to_bma_native(run_input.collateral.collateral)

        for key in (
            "perf_bal", "act_int", "act_am", "vol_prepay",
            "prin_loss", "prin_recov", "new_def",
            "act_prin", "act_cash",
            # aliases populated alongside
            "balance", "interest", "principal", "cashflow", "loss",
        ):
            assert key in out, f"missing BMA-native key {key!r} after LDCMA translation"


# ---------------------------------------------------------------------------
# 3. End-to-end PAIRED parity
# ---------------------------------------------------------------------------


class TestPairedDealRunParity:
    """Running a deal via PAIRED input produces the same bond cashflows
    as running it via the legacy LDCMA path."""

    @pytest.fixture(scope="class")
    def paired_run_result(self):
        loan = _build_loan(1, group_id=None)  # passthrough_deal has no groups
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

        # Compare key flow fields period-by-period
        for p, l in zip(paired_r, ldcma_r):
            assert p.period == l.period
            assert p.cashflow_total == pytest.approx(l.cashflow_total, rel=1e-9, abs=1e-6), (
                f"period {p.period}: cashflow paired={p.cashflow_total} vs ldcma={l.cashflow_total}"
            )

    def test_account_artifacts_match(self, paired_run_result, ldcma_run_result):
        """Account balances should also match between PAIRED and LDCMA paths."""
        paired_acc = {(r.account_id, r.period): r for r in paired_run_result.deal_accounts}
        ldcma_acc = {(r.account_id, r.period): r for r in ldcma_run_result.deal_accounts}
        assert paired_acc.keys() == ldcma_acc.keys()
        for key, paired_row in paired_acc.items():
            ldcma_row = ldcma_acc[key]
            assert paired_row.end_balance == pytest.approx(
                ldcma_row.end_balance, rel=1e-9, abs=1e-6,
            )


# ---------------------------------------------------------------------------
# 4. Multi-group PAIRED: per-group routing via aggregate_actual_by_group()
# ---------------------------------------------------------------------------


class TestPairedMultiGroup:
    """Multi-group PAIRED inputs: per-group BMA-native arrays in collateral_by_group."""

    def test_per_group_arrays_available_in_runtime(self):
        from bma_standard_formulas.deals.runtime import _extract_collateral_arrays

        loans_g1 = [_build_loan(1, "GROUP_1", balance=1_000_000)]
        loans_g2 = [_build_loan(2, "GROUP_2", balance=500_000)]
        portfolio = _build_paired_portfolio(loans_g1 + loans_g2)
        run_input = DealRunInput(
            collateral=PairedCollateralInput(portfolio=portfolio),
            loan_count=2,
            original_collateral_balance=1_500_000.0,
        )
        agg, per_group = _extract_collateral_arrays(run_input)

        # Aggregate carries BMA-native keys + LDCMA aliases
        assert "perf_bal" in agg
        assert "act_int" in agg
        assert "balance" in agg

        # Per-group dict has both groups
        assert set(per_group.keys()) == {"GROUP_1", "GROUP_2"}

        # Per-group arrays have BMA-native keys
        for gid, g in per_group.items():
            assert "perf_bal" in g
            assert "act_int" in g
            assert "act_am" in g
            assert "vol_prepay" in g
            assert "prin_loss" in g

        # Linearity: aggregate perf_bal = sum of per-group perf_bal at every period
        np.testing.assert_allclose(
            agg["perf_bal"],
            per_group["GROUP_1"]["perf_bal"] + per_group["GROUP_2"]["perf_bal"],
            rtol=1e-10, atol=1e-6,
        )

    def test_paired_input_includes_scheduled_fields(self):
        from bma_standard_formulas.deals.runtime import _extract_collateral_arrays

        loan = _build_loan(1)
        portfolio = _build_paired_portfolio([loan])
        run_input = DealRunInput(
            collateral=PairedCollateralInput(portfolio=portfolio),
            loan_count=1,
            original_collateral_balance=1_000_000.0,
        )
        agg, _ = _extract_collateral_arrays(run_input)

        # Scheduled-derived fields populated in PAIRED mode
        assert "survival_factor" in agg
        assert "pool_factor" in agg
        assert "amortized_balance_fraction" in agg
        assert "payment_factor" in agg
        assert "sched_gross_rate" in agg
