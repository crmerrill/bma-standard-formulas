from __future__ import annotations

import pandas as pd

from bma_cfengine_app.orchestrator.deals.collateral_bridge import (
    build_from_deal_native,
    build_from_runsetup_ref,
)
from bma_cfengine_app.orchestrator.deals.deal_run_service import _persist_scenario_artifacts
from bma_cfengine_app.storage import run_store
from bma_standard_formulas.deals.schemas.output_bond import (
    BondCashflowRow,
    CreditEnhancementRow,
    TrancheRiskSummaryRow,
)
from bma_standard_formulas.deals.schemas.output_bundle import ScenarioOutputBundle
from bma_standard_formulas.deals.schemas.output_structuring import (
    PacTacDiagnosticsRow,
    StructureCompositionRow,
)
from bma_standard_formulas.deals.schemas.output_waterfall import TriggerStateRow, WaterfallTraceRow


def _use_tmp_workspace(monkeypatch, tmp_path):
    app_home = tmp_path / "app_home"
    runs_dir = app_home / "runs"
    uploads_dir = app_home / "uploads"
    config_dir = app_home / "config"
    monkeypatch.setattr(run_store, "APP_HOME", app_home)
    monkeypatch.setattr(run_store, "_RUNS_DIR", runs_dir)
    monkeypatch.setattr(run_store, "_UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(run_store, "_CONFIG_DIR", config_dir)
    run_store.init_workspace()


def test_bridge_builds_runsetup_ref_inputs(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    run_id = "run_seed"
    run_store.save_manifest(
        run_id,
        {"status": "completed", "scenario_names": ["Base Case"], "loan_count": 2},
    )
    portfolio_df = pd.DataFrame(
        {
            "perf_bal": [100.0, 90.0, 80.0],
            "act_am": [0.0, 10.0, 10.0],
            "vol_prepay": [0.0, 0.0, 0.0],
            "act_int": [0.0, 1.0, 0.8],
            "new_def": [0.0, 0.0, 0.0],
            "prin_recov": [0.0, 0.0, 0.0],
            "prin_loss": [0.0, 0.0, 0.0],
        }
    )
    run_store.save_artifact(run_id, "Base_Case_portfolio_actual", portfolio_df)

    built = build_from_runsetup_ref(run_id, scenario_names=["Base Case"])
    assert "Base Case" in built
    assert built["Base Case"].loan_count == 2
    # Phase 1g: bridge produces PairedCollateralInput (PAIRED mode) with
    # an ACTUAL_ONLY-mode PortfolioCashflow under the hood.
    assert built["Base Case"].collateral.mode == "PAIRED"
    portfolio = built["Base Case"].collateral.portfolio
    assert len(portfolio.actual_constituents()) == 1
    # Single-pool: the synthesized constituent is untagged.
    assert portfolio.actual_constituents()[0].group_id is None


def test_bridge_reads_per_group_artifacts_for_grouped_run(monkeypatch, tmp_path):
    """Phase 0C: when the source run has group_names, the bridge produces
    a GroupedCollateralInput by reading the per-group portfolio artifacts.

    Pre-Phase-0C the bridge silently fell back to the aggregate-only
    PooledCollateralInput regardless of grouping configuration, leaving
    multi-group deal runs unable to receive per-group cashflows from
    Run-Setup-driven portfolio runs.
    """
    _use_tmp_workspace(monkeypatch, tmp_path)
    run_id = "run_grouped"

    # Manifest mirrors what run_service writes for a grouped completed run:
    # group_names list + per-scenario per-group artifact keys live alongside
    # the aggregate artifact key under the same scenario prefix.
    run_store.save_manifest(
        run_id,
        {
            "status": "completed",
            "scenario_names": ["Base Case"],
            "loan_count": 4,
            "group_names": ["GROUP_1", "GROUP_2"],
            "group_artifacts": {
                "GROUP_1": "Base_Case_group_GROUP_1_actual",
                "GROUP_2": "Base_Case_group_GROUP_2_actual",
            },
        },
    )

    # Aggregate artifact (would be the fallback if per-group artifacts go missing)
    agg_df = pd.DataFrame(
        {
            "perf_bal": [300.0, 270.0, 240.0],
            "act_am": [0.0, 30.0, 30.0],
            "vol_prepay": [0.0, 0.0, 0.0],
            "act_int": [0.0, 3.0, 2.4],
            "new_def": [0.0, 0.0, 0.0],
            "prin_recov": [0.0, 0.0, 0.0],
            "prin_loss": [0.0, 0.0, 0.0],
        }
    )
    run_store.save_artifact(run_id, "Base_Case_portfolio_actual", agg_df)

    # Per-group artifacts — the bridge should pick THESE up under proposal
    # 0C, in preference to the aggregate.
    g1_df = pd.DataFrame(
        {
            "perf_bal": [200.0, 180.0, 160.0],
            "act_am": [0.0, 20.0, 20.0],
            "vol_prepay": [0.0, 0.0, 0.0],
            "act_int": [0.0, 2.0, 1.6],
            "new_def": [0.0, 0.0, 0.0],
            "prin_recov": [0.0, 0.0, 0.0],
            "prin_loss": [0.0, 0.0, 0.0],
        }
    )
    g2_df = pd.DataFrame(
        {
            "perf_bal": [100.0, 90.0, 80.0],
            "act_am": [0.0, 10.0, 10.0],
            "vol_prepay": [0.0, 0.0, 0.0],
            "act_int": [0.0, 1.0, 0.8],
            "new_def": [0.0, 0.0, 0.0],
            "prin_recov": [0.0, 0.0, 0.0],
            "prin_loss": [0.0, 0.0, 0.0],
        }
    )
    run_store.save_artifact(run_id, "Base_Case_group_GROUP_1_actual", g1_df)
    run_store.save_artifact(run_id, "Base_Case_group_GROUP_2_actual", g2_df)

    built = build_from_runsetup_ref(run_id, scenario_names=["Base Case"])

    assert "Base Case" in built
    deal_input = built["Base Case"]
    # Phase 1g: bridge produces PairedCollateralInput (PAIRED mode) with
    # one ACTUAL_ONLY constituent per group, tagged with its group_id.
    assert deal_input.collateral.mode == "PAIRED"
    portfolio = deal_input.collateral.portfolio
    constituents = portfolio.actual_constituents()
    assert len(constituents) == 2
    by_group = portfolio.actual_constituents_by_group()
    assert set(by_group.keys()) == {"GROUP_1", "GROUP_2"}

    # The per-group constituents should reflect the per-group artifacts,
    # not the aggregate (period-0 perf_bal is 200 / 100, not 300).
    g1_cfs = by_group["GROUP_1"]
    g2_cfs = by_group["GROUP_2"]
    assert g1_cfs[0].perf_bal[0] == 200.0
    assert g2_cfs[0].perf_bal[0] == 100.0

    # Original collateral balance is the sum of per-group initial balances.
    assert deal_input.original_collateral_balance == 300.0


def test_bridge_falls_back_to_aggregate_when_per_group_artifacts_missing(monkeypatch, tmp_path):
    """If a grouped run has missing per-group artifacts (e.g. workspace
    corruption), the bridge falls back to the aggregate-only path so the
    deal can still be wired up with a degraded representation."""
    _use_tmp_workspace(monkeypatch, tmp_path)
    run_id = "run_grouped_partial"
    run_store.save_manifest(
        run_id,
        {
            "status": "completed",
            "scenario_names": ["Base Case"],
            "loan_count": 4,
            "group_names": ["GROUP_1", "GROUP_2"],
        },
    )
    agg_df = pd.DataFrame(
        {
            "perf_bal": [300.0, 270.0],
            "act_am": [0.0, 30.0],
            "vol_prepay": [0.0, 0.0],
            "act_int": [0.0, 3.0],
            "new_def": [0.0, 0.0],
            "prin_recov": [0.0, 0.0],
            "prin_loss": [0.0, 0.0],
        }
    )
    run_store.save_artifact(run_id, "Base_Case_portfolio_actual", agg_df)
    # Per-group artifacts intentionally missing.

    built = build_from_runsetup_ref(run_id, scenario_names=["Base Case"])

    # Falls back to the single-pool path. Phase 1g: PAIRED-mode payload
    # with one untagged constituent (no per-group routing because the
    # per-group artifacts were missing).
    assert built["Base Case"].collateral.mode == "PAIRED"
    portfolio = built["Base Case"].collateral.portfolio
    assert len(portfolio.actual_constituents()) == 1
    assert portfolio.actual_constituents()[0].group_id is None


def test_bridge_builds_deal_native_inputs():
    payload = {
        "scenario_name": "Base Case",
        "run_input": {
            "collateral": {
                "mode": "POOLED",
                "collateral": {
                    "cfdate": [0, 1],
                    "balance": [100.0, 90.0],
                    "principal": [0.0, 10.0],
                    "interest": [0.0, 1.0],
                    "cashflow": [0.0, 11.0],
                    "loss": [0.0, 0.0],
                    "prepbal": [0.0, 0.0],
                    "defbal": [0.0, 0.0],
                    "recovery": [0.0, 0.0],
                    "principal_sched": [0.0, 10.0],
                    "principal_unsched": [0.0, 0.0],
                    "cpr": [0.0, 0.0],
                    "cdr": [0.0, 0.0],
                    "sev": [0.0, 0.0],
                    "dq": [0.0, 0.0],
                    "surv_fac": [1.0, 1.0],
                    "sched_coupon": [6.0, 6.0],
                    "sched_netcoupon": [5.0, 5.0],
                    "coupon": [6.0, 6.0],
                    "effcoupon": [6.0, 6.0],
                    "sched_balance": [100.0, 90.0],
                    "discount_factor": [1.0, 1.0],
                },
            },
            "loan_count": 1,
            "original_collateral_balance": 100.0,
        },
    }
    built = build_from_deal_native(payload)
    assert list(built.keys()) == ["Base Case"]
    assert built["Base Case"].original_collateral_balance == 100.0


def test_persist_scenario_artifacts_writes_extended_outputs(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    run_id = "run_structured"
    scenario = ScenarioOutputBundle(
        scenario_name="Base Case",
        bond_cashflows=[
            BondCashflowRow(
                scenario_name="Base Case",
                tranche_id="A",
                period=0,
                begin_balance=100.0,
                end_balance=100.0,
            ),
            BondCashflowRow(
                scenario_name="Base Case",
                tranche_id="A",
                period=1,
                begin_balance=100.0,
                total_principal=10.0,
                interest_due=1.0,
                interest_paid=1.0,
                cashflow_total=11.0,
                end_balance=90.0,
            ),
        ],
        waterfall_trace=[
            WaterfallTraceRow(
                scenario_name="Base Case",
                period=1,
                rule_id="r1",
                rule_order=1,
                rule_type="PAY_INTEREST",
                from_source="CASH",
                to_target="A",
                amount_requested=1.0,
                amount_paid=1.0,
            )
        ],
        trigger_state_history=[
            TriggerStateRow(
                scenario_name="Base Case",
                trigger_id="T1",
                period=1,
                metric_value=0.1,
                threshold_value=0.2,
                state="inactive",
            )
        ],
        tranche_risk_summary=[
            TrancheRiskSummaryRow(scenario_name="Base Case", tranche_id="A", wal_years=0.08)
        ],
        credit_enhancement=[
            CreditEnhancementRow(scenario_name="Base Case", tranche_id="A", total_ce_pct=10.0)
        ],
        pac_tac_diagnostics=[
            PacTacDiagnosticsRow(
                scenario_name="Base Case",
                tranche_id="A",
                schedule_type="PAC",
                period=1,
                scheduled_principal=10.0,
                actual_principal=9.0,
                schedule_variance=-1.0,
            )
        ],
        structure_composition=[
            StructureCompositionRow(
                scenario_name="Base Case",
                parent_tranche_id="B",
                child_tranche_id="Z",
                relation_type="ACCRETES_TO",
            )
        ],
    )
    keys = _persist_scenario_artifacts(run_id, "Base Case", scenario)
    assert "Base_Case_tranche_risk_summary" in keys
    assert "Base_Case_credit_enhancement" in keys
    assert "Base_Case_pac_tac_diagnostics" in keys
    assert "Base_Case_structure_composition" in keys
    assert "Base_Case_decrement_table" in keys
    assert "Base_Case_stress_matrix" in keys
