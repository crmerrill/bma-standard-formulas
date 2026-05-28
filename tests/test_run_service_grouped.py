"""Tests for the Phase 0B orchestrator refactor.

Validates that ``_execute_single_scenario`` produces the same per-group
artifacts via a single engine call + per-group aggregation as the previous
N+1 invocation pattern would have produced.

Coverage:
  1. The helper ``_bma_actual_to_aggregate_dataframe`` produces a DataFrame
     with the same shape (pool + waterfall columns) as
     ``PortfolioCashflow.to_dataframe()``.
  2. ``_execute_single_scenario`` writes the expected aggregate and
     per-group artifacts to ``run_store`` for a multi-group run.
  3. The per-group artifacts are dollar-summable: the sum of per-group
     FLOW fields (act_am, vol_prepay, act_int, prin_loss) matches the
     whole-pool aggregate within rounding tolerance.
  4. Single-pool runs (no grouping) emit only the aggregate artifact.

Why this matters:

The pre-Phase-0B orchestrator ran the engine once per group on a filtered
subset of loans, duplicating the per-loan amortization / prepay / default
math the aggregate run had already performed. Phase 0A added per-group
aggregation methods to ``PortfolioCashflow``; Phase 0B uses those to
produce per-group artifacts from the single aggregate run. Tests below
pin the expected behavior so future refactors don't reintroduce the
duplicate-engine-call pattern.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import pytest

from bma_cfengine_app.api.models import (
    AssumptionSet,
    AssumptionsPayload,
    ConstantCurve,
    GroupingConfig,
)
from bma_cfengine_app.orchestrator import run_service
from bma_cfengine_app.orchestrator.run_service import (
    _bma_actual_to_aggregate_dataframe,
    _bma_scheduled_to_dataframe,
    _execute_single_scenario,
)
from bma_cfengine_app.storage import run_store
from bma_standard_formulas.engine import PortfolioCashflow
from bma_standard_formulas.engine.loan import Loan
from bma_standard_formulas.engine.portfolio import PortfolioMode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    """Redirect run_store to a tmp directory so tests are isolated."""
    app_home = tmp_path / "app_home"
    runs_dir = app_home / "runs"
    uploads_dir = app_home / "uploads"
    config_dir = app_home / "config"
    monkeypatch.setattr(run_store, "APP_HOME", app_home)
    monkeypatch.setattr(run_store, "_RUNS_DIR", runs_dir)
    monkeypatch.setattr(run_store, "_UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(run_store, "_CONFIG_DIR", config_dir)
    run_store.init_workspace()
    return app_home


def _make_loan(loan_id: int, group_id: str | None, balance: float = 1_000_000.0) -> Loan:
    """A minimal fixed-rate Loan for orchestrator testing."""
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


def _baseline_assumptions() -> AssumptionsPayload:
    """No prepay, no default, zero severity — keeps cashflows fully deterministic."""
    return AssumptionsPayload(
        portfolio_defaults=AssumptionSet(
            smm=ConstantCurve(value=0.0),
            mdr=ConstantCurve(value=0.0),
            severity=ConstantCurve(value=0.0),
        ),
    )


# ---------------------------------------------------------------------------
# 1. Helper: _bma_actual_to_aggregate_dataframe
# ---------------------------------------------------------------------------


class TestBMAActualToAggregateDataFrame:
    """The helper builds the same DataFrame shape as PortfolioCashflow.to_dataframe()."""

    def test_includes_pool_and_waterfall_columns(self, workspace):
        # Build a single BMAActualCashflow via the engine
        from bma_standard_formulas.engine.loan import actual_cashflow_from_loan, scheduled_cashflow_from_loan
        from bma_standard_formulas.formulas import generate_smm_curve_from_psa

        loan = _make_loan(1, "GROUP_1")
        sched = scheduled_cashflow_from_loan(loan)
        smm = generate_smm_curve_from_psa(0.0, loan.original_term)
        actual = actual_cashflow_from_loan(
            loan=loan,
            scheduled_cf=sched,
            smm_curve=smm,
            mdr_curve=np.zeros(loan.original_term + 1),
            severity_curve=np.zeros(loan.original_term + 1),
        )

        df = _bma_actual_to_aggregate_dataframe(actual, run_mode="actual")

        # Pool fields present
        for col in ("perf_bal", "act_am", "vol_prepay", "act_int", "prin_loss"):
            assert col in df.columns, f"missing pool column {col!r}"

        # Waterfall fields present (svc_paid, pt_principal, pt_interest, etc.)
        for col in ("svc_paid", "pt_principal", "pt_interest", "pt_cashflow"):
            assert col in df.columns, f"missing waterfall column {col!r}"

        # Period count should match the BMA cashflow length
        assert len(df) == len(actual.period)


# ---------------------------------------------------------------------------
# 2. _execute_single_scenario — multi-group integration
# ---------------------------------------------------------------------------


class TestExecuteSingleScenarioGrouped:
    """End-to-end: multi-group run produces aggregate + per-group artifacts."""

    def test_per_group_artifacts_emitted(self, workspace):
        run_id = "test_run_grouped"
        run_store.save_manifest(run_id, {"status": "running"})

        # Two groups, two loans each
        loans = [
            _make_loan(1, "GROUP_1", balance=1_000_000),
            _make_loan(2, "GROUP_1", balance=2_000_000),
            _make_loan(3, "GROUP_2", balance=500_000),
            _make_loan(4, "GROUP_2", balance=750_000),
        ]
        groups_by_id = {
            "GROUP_1": loans[:2],
            "GROUP_2": loans[2:],
        }
        group_id_map = {1: "GROUP_1", 2: "GROUP_1", 3: "GROUP_2", 4: "GROUP_2"}

        # Minimal grouping config — the keys list is informational; the
        # actual loan.group_id has already been set above.
        grouping = GroupingConfig(keys=["pool_id"])

        sections, group_names, group_artifacts = _execute_single_scenario(
            run_id=run_id,
            scenario_name="Base Case",
            loans=loans,
            groups_by_id=groups_by_id,
            group_id_map=group_id_map,
            assumptions=_baseline_assumptions(),
            run_mode="actual",
            rate_index=None,
            grouping=grouping,
        )

        assert "Base_Case_portfolio_actual" in sections
        assert set(group_names) == {"GROUP_1", "GROUP_2"}
        assert "GROUP_1" in group_artifacts
        assert "GROUP_2" in group_artifacts

        # Aggregate artifact saved
        agg_df = run_store.load_artifact(run_id, "Base_Case_portfolio_actual")
        assert "perf_bal" in agg_df.columns
        assert "pt_principal" in agg_df.columns

        # Per-group artifacts saved
        g1_df = run_store.load_artifact(run_id, group_artifacts["GROUP_1"])
        g2_df = run_store.load_artifact(run_id, group_artifacts["GROUP_2"])
        assert "perf_bal" in g1_df.columns
        assert "perf_bal" in g2_df.columns

    def test_per_group_flows_sum_to_aggregate(self, workspace):
        """Linearity: sum of per-group FLOW fields == aggregate FLOW field."""
        run_id = "test_run_grouped_sum"
        run_store.save_manifest(run_id, {"status": "running"})

        loans = [
            _make_loan(1, "GROUP_1", balance=1_500_000),
            _make_loan(2, "GROUP_2", balance=800_000),
        ]
        groups_by_id = {"GROUP_1": [loans[0]], "GROUP_2": [loans[1]]}
        group_id_map = {1: "GROUP_1", 2: "GROUP_2"}

        grouping = GroupingConfig(keys=["pool_id"])

        _, group_names, group_artifacts = _execute_single_scenario(
            run_id=run_id,
            scenario_name="Base Case",
            loans=loans,
            groups_by_id=groups_by_id,
            group_id_map=group_id_map,
            assumptions=_baseline_assumptions(),
            run_mode="actual",
            rate_index=None,
            grouping=grouping,
        )

        agg_df = run_store.load_artifact(run_id, "Base_Case_portfolio_actual")
        g1_df = run_store.load_artifact(run_id, group_artifacts["GROUP_1"])
        g2_df = run_store.load_artifact(run_id, group_artifacts["GROUP_2"])

        # Align lengths (trim to shortest if any padding differences)
        n = min(len(agg_df), len(g1_df), len(g2_df))

        # FLOW fields are linear under summation: agg = g1 + g2
        for field in ("act_am", "vol_prepay", "act_int", "prin_loss"):
            agg_arr = agg_df[field].to_numpy()[:n]
            summed = g1_df[field].to_numpy()[:n] + g2_df[field].to_numpy()[:n]
            np.testing.assert_allclose(
                agg_arr, summed, rtol=1e-9, atol=1e-6,
                err_msg=f"per-group sum != aggregate for FLOW field {field!r}",
            )

        # Pool stock (perf_bal) is also additive at the boundary
        np.testing.assert_allclose(
            agg_df["perf_bal"].to_numpy()[:n],
            g1_df["perf_bal"].to_numpy()[:n] + g2_df["perf_bal"].to_numpy()[:n],
            rtol=1e-9, atol=1e-6,
        )


# ---------------------------------------------------------------------------
# 3. Single-pool: no per-group artifacts emitted
# ---------------------------------------------------------------------------


class TestExecuteSingleScenarioUngrouped:
    """When grouping is None, only the aggregate artifact is emitted."""

    def test_no_per_group_artifacts(self, workspace):
        run_id = "test_run_ungrouped"
        run_store.save_manifest(run_id, {"status": "running"})

        loans = [
            _make_loan(1, None, balance=1_000_000),
            _make_loan(2, None, balance=750_000),
        ]

        sections, group_names, group_artifacts = _execute_single_scenario(
            run_id=run_id,
            scenario_name="Base Case",
            loans=loans,
            groups_by_id={},
            group_id_map=None,
            assumptions=_baseline_assumptions(),
            run_mode="actual",
            rate_index=None,
            grouping=None,
        )

        assert sections == ["Base_Case_portfolio_actual"]
        assert group_names == []
        assert group_artifacts == {}

        # Aggregate exists; no group artifacts present
        agg_df = run_store.load_artifact(run_id, "Base_Case_portfolio_actual")
        assert "perf_bal" in agg_df.columns


# ---------------------------------------------------------------------------
# 4. _bma_scheduled_to_dataframe smoke
# ---------------------------------------------------------------------------


class TestBMAScheduledToDataFrame:
    def test_scheduled_to_df_includes_array_fields_only(self, workspace):
        from bma_standard_formulas.engine.loan import scheduled_cashflow_from_loan

        loan = _make_loan(1, "GROUP_1")
        sched = scheduled_cashflow_from_loan(loan)
        df = _bma_scheduled_to_dataframe(sched)

        # Array fields included
        assert "beginning_balance" in df.columns
        assert "scheduled_payment" in df.columns
        assert len(df) == len(sched.period)

        # Non-array (scalar / metadata) fields excluded
        assert "loan_id" not in df.columns
        assert "original_balance" not in df.columns


# ---------------------------------------------------------------------------
# 5. RG7: Divergent per-group assumptions test (Phase 0B acceptance)
# ---------------------------------------------------------------------------


class TestDivergentGroupAssumptions:
    """RG7 acceptance test: when group 1 and group 2 have different per-group
    SMM assumptions, the per-group artifacts reflect different cashflow
    patterns and the aggregate is their sum.

    This proves that the single-call engine path correctly applies per-group
    curves (via group_overrides) rather than a single pooled assumption.
    """

    def test_divergent_smm_per_group_produces_different_cashflows(self, workspace):
        """Group 1 = 0 SMM (no prepay), Group 2 = high SMM (fast prepay).
        Per-group vol_prepay arrays must differ; aggregate must sum to their total.
        """
        from bma_cfengine_app.api.models import AssumptionSet, ConstantCurve

        run_id = "test_divergent_smm"
        run_store.save_manifest(run_id, {"status": "running"})

        loans = [
            _make_loan(1, "GROUP_1", balance=1_000_000),
            _make_loan(2, "GROUP_2", balance=1_000_000),
        ]
        groups_by_id = {"GROUP_1": [loans[0]], "GROUP_2": [loans[1]]}
        group_id_map = {1: "GROUP_1", 2: "GROUP_2"}
        grouping = GroupingConfig(keys=["pool_id"])

        # Group 1: no prepay; Group 2: high SMM (fast payoff).
        assumptions = AssumptionsPayload(
            portfolio_defaults=AssumptionSet(
                smm=ConstantCurve(value=0.0),
                mdr=ConstantCurve(value=0.0),
                severity=ConstantCurve(value=0.0),
            ),
            group_overrides={
                "GROUP_2": AssumptionSet(
                    smm=ConstantCurve(value=0.10),  # 10% monthly prepay
                    mdr=ConstantCurve(value=0.0),
                    severity=ConstantCurve(value=0.0),
                ),
            },
        )

        _, _, group_artifacts = _execute_single_scenario(
            run_id=run_id,
            scenario_name="Divergent",
            loans=loans,
            groups_by_id=groups_by_id,
            group_id_map=group_id_map,
            assumptions=assumptions,
            run_mode="actual",
            rate_index=None,
            grouping=grouping,
        )

        agg_df = run_store.load_artifact(run_id, "Divergent_portfolio_actual")
        g1_df = run_store.load_artifact(run_id, group_artifacts["GROUP_1"])
        g2_df = run_store.load_artifact(run_id, group_artifacts["GROUP_2"])

        n = min(len(agg_df), len(g1_df), len(g2_df))

        # GROUP_2 has high prepay; GROUP_1 has zero prepay.
        # At period 1, GROUP_2 vol_prepay must be > GROUP_1 vol_prepay.
        g1_vol_prepay = g1_df["vol_prepay"].to_numpy()[:n]
        g2_vol_prepay = g2_df["vol_prepay"].to_numpy()[:n]
        # With SMM=0.10, GROUP_2 should have substantial vol_prepay from period 1.
        assert g2_vol_prepay.sum() > g1_vol_prepay.sum(), (
            "GROUP_2 (high SMM) must have more prepayments than GROUP_1 (zero SMM)"
        )
        # GROUP_1 SMM=0: no voluntary prepayments at all.
        np.testing.assert_allclose(
            g1_vol_prepay, 0.0, atol=1e-4,
            err_msg="GROUP_1 (SMM=0) should have zero voluntary prepayments",
        )
        # GROUP_2 SMM=0.10: period-1 prepay should be ~10% of initial balance (1M).
        assert g2_vol_prepay[1] > 50_000.0, (
            f"GROUP_2 period-1 vol_prepay {g2_vol_prepay[1]:.0f} too small for SMM=0.10; "
            "check that group_overrides is being applied"
        )

        # Aggregate FLOW fields must equal sum of per-group fields.
        for field in ("act_am", "vol_prepay", "act_int", "prin_loss"):
            agg_arr = agg_df[field].to_numpy()[:n]
            summed = g1_df[field].to_numpy()[:n] + g2_df[field].to_numpy()[:n]
            np.testing.assert_allclose(
                agg_arr, summed, rtol=1e-9, atol=1e-3,
                err_msg=f"Aggregate {field!r} != sum of per-group {field!r}",
            )


class TestPairedArtifactWrittenByExecuteSingleScenario:
    """RG2-B1 acceptance: _execute_single_scenario must write the portfolio_paired
    artifact with true per-loan constituents accessible after the run.

    This tests the production code path, not the _write_paired_artifact helper
    directly, to prove the flush-order fix is wired correctly.
    """

    def test_paired_artifact_written_and_has_correct_loan_count(self, workspace):
        from bma_cfengine_app.orchestrator.run_service import _read_paired_artifact

        run_id = "test_paired_written"
        run_store.save_manifest(run_id, {"status": "running"})

        loans = [
            _make_loan(1, "GROUP_1", balance=500_000),
            _make_loan(2, "GROUP_1", balance=300_000),
            _make_loan(3, "GROUP_2", balance=200_000),
        ]
        groups_by_id = {"GROUP_1": loans[:2], "GROUP_2": loans[2:]}
        group_id_map = {1: "GROUP_1", 2: "GROUP_1", 3: "GROUP_2"}
        grouping = GroupingConfig(keys=["pool_id"])

        _execute_single_scenario(
            run_id=run_id,
            scenario_name="Base Case",
            loans=loans,
            groups_by_id=groups_by_id,
            group_id_map=group_id_map,
            assumptions=_baseline_assumptions(),
            run_mode="actual",
            rate_index=None,
            grouping=grouping,
        )

        constituents = _read_paired_artifact(run_id, "Base_Case_portfolio_paired")
        assert len(constituents) == 3, (
            f"Expected 3 per-loan constituents, got {len(constituents)}. "
            f"Check that _execute_single_scenario extracts before flush."
        )
        loan_ids = {int(c.loan_id) for c in constituents}
        assert loan_ids == {1, 2, 3}

    def test_paired_artifact_has_correct_group_ids(self, workspace):
        from bma_cfengine_app.orchestrator.run_service import _read_paired_artifact

        run_id = "test_paired_groups"
        run_store.save_manifest(run_id, {"status": "running"})

        loans = [
            _make_loan(10, "GROUP_1", balance=1_000_000),
            _make_loan(20, "GROUP_2", balance=500_000),
        ]
        groups_by_id = {"GROUP_1": [loans[0]], "GROUP_2": [loans[1]]}
        group_id_map = {10: "GROUP_1", 20: "GROUP_2"}
        grouping = GroupingConfig(keys=["pool_id"])

        _execute_single_scenario(
            run_id=run_id,
            scenario_name="Base Case",
            loans=loans,
            groups_by_id=groups_by_id,
            group_id_map=group_id_map,
            assumptions=_baseline_assumptions(),
            run_mode="actual",
            rate_index=None,
            grouping=grouping,
        )

        constituents = _read_paired_artifact(run_id, "Base_Case_portfolio_paired")
        assert len(constituents) == 2
        by_group = {str(c.group_id): c for c in constituents}
        assert "GROUP_1" in by_group, f"group_ids: {[str(c.group_id) for c in constituents]}"
        assert "GROUP_2" in by_group
