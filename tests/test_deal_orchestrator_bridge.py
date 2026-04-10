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
    assert built["Base Case"].collateral.mode == "POOLED"


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
    )
    keys = _persist_scenario_artifacts(run_id, "Base Case", scenario)
    assert "Base_Case_tranche_risk_summary" in keys
    assert "Base_Case_credit_enhancement" in keys
    assert "Base_Case_decrement_table" in keys
