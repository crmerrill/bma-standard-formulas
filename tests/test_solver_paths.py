from __future__ import annotations

from types import SimpleNamespace

import pytest

from bma_standard_formulas.deals.deal_library import passthrough_deal
from bma_standard_formulas.deals.solver import SolverCancelledError, solve_deal
from bma_standard_formulas.deals.schemas.input import CollateralCashflows, DealRunInput, PooledCollateralInput
from bma_standard_formulas.deals.schemas.solver import (
    KnobBound,
    ObjectiveSpec,
    ObjectiveType,
    ConstraintComparison,
    ConstraintSpec,
    SolverLayerSpec,
    SolverSpec,
    WaterfallTargetPrimitive,
)


def _tiny_run_input() -> DealRunInput:
    return DealRunInput.model_validate(
        {
            "collateral": {
                "mode": "POOLED",
                "collateral": {
                    "cfdate": [0],
                    "balance": [100.0],
                    "principal": [0.0],
                    "interest": [0.0],
                    "cashflow": [0.0],
                    "loss": [0.0],
                    "prepbal": [0.0],
                    "defbal": [0.0],
                    "recovery": [0.0],
                    "principal_sched": [0.0],
                    "principal_unsched": [0.0],
                    "cpr": [0.0],
                    "cdr": [0.0],
                    "sev": [0.0],
                    "dq": [0.0],
                    "surv_fac": [1.0],
                    "sched_coupon": [6.0],
                    "sched_netcoupon": [5.0],
                    "coupon": [6.0],
                    "effcoupon": [6.0],
                    "sched_balance": [100.0],
                    "discount_factor": [1.0],
                },
            }
        }
    )


def test_solver_returns_summary_and_knobs():
    deal = passthrough_deal()
    deal.deal_knobs["class_a_coupon"] = 6.0
    run_input = DealRunInput(
        collateral=PooledCollateralInput(
            collateral=CollateralCashflows(
                cfdate=[0, 1, 2],
                balance=[100.0, 90.0, 80.0],
                principal=[0.0, 10.0, 10.0],
                interest=[0.0, 1.0, 0.8],
                cashflow=[0.0, 11.0, 10.8],
                loss=[0.0, 0.0, 0.0],
                prepbal=[0.0, 0.0, 0.0],
                defbal=[0.0, 0.0, 0.0],
                recovery=[0.0, 0.0, 0.0],
                principal_sched=[0.0, 10.0, 10.0],
                principal_unsched=[0.0, 0.0, 0.0],
                cpr=[0.0, 0.0, 0.0],
                cdr=[0.0, 0.0, 0.0],
                sev=[0.0, 0.0, 0.0],
                dq=[0.0, 0.0, 0.0],
                surv_fac=[1.0, 1.0, 1.0],
                sched_coupon=[6.0, 6.0, 6.0],
                sched_netcoupon=[5.0, 5.0, 5.0],
                coupon=[6.0, 6.0, 6.0],
                effcoupon=[6.0, 6.0, 6.0],
                sched_balance=[100.0, 90.0, 80.0],
                discount_factor=[1.0, 1.0, 1.0],
            )
        ),
        original_collateral_balance=100.0,
    )
    spec = SolverSpec(
        solver_name="test_solver",
        layers=[
            SolverLayerSpec(
                layer_name="base",
                objectives=[
                    ObjectiveSpec(
                        name="target_A_yield",
                        metric_path="tranche_risk_summary[R].yield_pct",
                        objective_type=ObjectiveType.TARGET,
                        target_value=6.0,
                        weight=1.0,
                    )
                ],
                knobs=[
                    KnobBound(
                        knob_path="deal_knobs.class_a_coupon",
                        lower=3.0,
                        upper=10.0,
                        initial=6.0,
                    )
                ],
                max_iterations=2,
            )
        ],
    )
    _, summary = solve_deal(deal, run_input, spec, scenario_name="Base Case")
    assert summary.total_iterations >= 1
    assert "deal_knobs.class_a_coupon" in summary.solved_knobs
    assert len(summary.iteration_log) >= 1
    assert summary.selected_solution.get("scenario_name") == "Base Case"


def test_solver_emits_progress_and_supports_cancel():
    deal = passthrough_deal()
    deal.deal_knobs["class_a_coupon"] = 6.0
    run_input = DealRunInput(
        collateral=PooledCollateralInput(
            collateral=CollateralCashflows(
                cfdate=[0, 1, 2],
                balance=[100.0, 90.0, 80.0],
                principal=[0.0, 10.0, 10.0],
                interest=[0.0, 1.0, 0.8],
                cashflow=[0.0, 11.0, 10.8],
                loss=[0.0, 0.0, 0.0],
                prepbal=[0.0, 0.0, 0.0],
                defbal=[0.0, 0.0, 0.0],
                recovery=[0.0, 0.0, 0.0],
                principal_sched=[0.0, 10.0, 10.0],
                principal_unsched=[0.0, 0.0, 0.0],
                cpr=[0.0, 0.0, 0.0],
                cdr=[0.0, 0.0, 0.0],
                sev=[0.0, 0.0, 0.0],
                dq=[0.0, 0.0, 0.0],
                surv_fac=[1.0, 1.0, 1.0],
                sched_coupon=[6.0, 6.0, 6.0],
                sched_netcoupon=[5.0, 5.0, 5.0],
                coupon=[6.0, 6.0, 6.0],
                effcoupon=[6.0, 6.0, 6.0],
                sched_balance=[100.0, 90.0, 80.0],
                discount_factor=[1.0, 1.0, 1.0],
            )
        ),
        original_collateral_balance=100.0,
    )
    spec = SolverSpec(
        solver_name="test_solver_cancel",
        layers=[
            SolverLayerSpec(
                layer_name="base",
                objectives=[
                    ObjectiveSpec(
                        name="target_A_yield",
                        metric_path="tranche_risk_summary[R].yield_pct",
                        objective_type=ObjectiveType.TARGET,
                        target_value=6.0,
                        weight=1.0,
                    )
                ],
                knobs=[
                    KnobBound(
                        knob_path="deal_knobs.class_a_coupon",
                        lower=3.0,
                        upper=10.0,
                        initial=6.0,
                    )
                ],
                max_iterations=5,
            )
        ],
    )

    progress_events: list[dict] = []
    cancel_requested = {"value": False}

    def on_progress(payload: dict) -> None:
        progress_events.append(payload)
        if int(payload.get("iteration", 0)) >= 0:
            cancel_requested["value"] = True

    with pytest.raises(SolverCancelledError):
        solve_deal(
            deal,
            run_input,
            spec,
            scenario_name="Base Case",
            progress_callback=on_progress,
            should_cancel=lambda: cancel_requested["value"],
        )
    assert len(progress_events) >= 1


def test_solver_cum_loss_multiple_primitive(monkeypatch):
    import bma_standard_formulas.deals.solver as solver_mod

    deal = passthrough_deal()
    deal.deal_knobs["class_a_coupon"] = 6.0
    run_input = _tiny_run_input()

    fake_result = SimpleNamespace(
        collateral_summary=SimpleNamespace(total_collateral_loss=4.0, starting_balance=100.0),
        bond_cashflows=[],
        trigger_state_history=[],
        deal_accounts=[],
        credit_enhancement=[],
    )
    monkeypatch.setattr(solver_mod, "run_deal", lambda *args, **kwargs: fake_result)
    monkeypatch.setattr(solver_mod, "compute_tranche_risk", lambda *args, **kwargs: [])

    spec = SolverSpec(
        solver_name="test_cum_loss_primitive",
        layers=[
            SolverLayerSpec(
                layer_name="base",
                objectives=[
                    ObjectiveSpec(
                        name="cum_loss_multiple_gap_A",
                        metric_path="primitive:CUM_LOSS_MULTIPLE_GAP",
                        objective_type=ObjectiveType.MINIMIZE,
                        weight=1.0,
                        target_primitive=WaterfallTargetPrimitive.CUM_LOSS_MULTIPLE_GAP,
                        primitive_params={"tranche_id": "A", "target_multiple": 2.0},
                    )
                ],
                knobs=[KnobBound(knob_path="deal_knobs.class_a_coupon", lower=4.0, upper=8.0, initial=6.0)],
                max_iterations=1,
            )
        ],
    )
    _, summary = solve_deal(deal, run_input, spec, scenario_name="Base Case")
    assert summary.total_iterations >= 1
    assert "primitive:CUM_LOSS_MULTIPLE_GAP" in summary.selected_solution.get("metrics", {})


def test_solver_no_shortfall_constraint_under_stress(monkeypatch):
    import bma_standard_formulas.deals.solver as solver_mod

    deal = passthrough_deal()
    deal.deal_knobs["class_a_coupon"] = 6.0
    run_input = _tiny_run_input()

    fake_bond_row = SimpleNamespace(
        tranche_id="A",
        interest_due=10.0,
        interest_shortfall=0.0,
        total_principal=10.0,
        writedown=0.0,
    )
    fake_result = SimpleNamespace(
        collateral_summary=SimpleNamespace(total_collateral_loss=8.0, starting_balance=100.0),
        bond_cashflows=[fake_bond_row],
        trigger_state_history=[],
        deal_accounts=[],
        credit_enhancement=[],
    )
    monkeypatch.setattr(solver_mod, "run_deal", lambda *args, **kwargs: fake_result)
    monkeypatch.setattr(solver_mod, "compute_tranche_risk", lambda *args, **kwargs: [])

    spec = SolverSpec(
        solver_name="test_shortfall_constraint",
        layers=[
            SolverLayerSpec(
                layer_name="stress_guard",
                objectives=[
                    ObjectiveSpec(
                        name="cum_loss_multiple_gap_A",
                        metric_path="primitive:CUM_LOSS_MULTIPLE_GAP",
                        objective_type=ObjectiveType.MINIMIZE,
                        weight=1.0,
                        target_primitive=WaterfallTargetPrimitive.CUM_LOSS_MULTIPLE_GAP,
                        primitive_params={"tranche_id": "A", "target_multiple": 2.0},
                    )
                ],
                constraints=[
                    ConstraintSpec(
                        name="A_no_interest_shortfall",
                        metric_path="primitive:NO_SHORTFALL_INTEREST",
                        comparison=ConstraintComparison.LE,
                        value=0.0,
                        target_primitive=WaterfallTargetPrimitive.NO_SHORTFALL_INTEREST,
                        primitive_params={"tranche_id": "A"},
                    )
                ],
                knobs=[
                    KnobBound(
                        knob_path="deal_knobs.class_a_coupon",
                        lower=4.0,
                        upper=8.0,
                        initial=6.0,
                    )
                ],
                max_iterations=1,
            )
        ],
    )
    _, summary = solve_deal(deal, run_input, spec, scenario_name="Stress")
    assert summary.final_feasible is True


def test_solver_pac_tac_and_z_primitives(monkeypatch):
    import bma_standard_formulas.deals.solver as solver_mod

    deal = passthrough_deal()
    run_input = _tiny_run_input()
    fake_diag_row = SimpleNamespace(tranche_id="A", schedule_type=SimpleNamespace(value="PAC"), schedule_variance=12.0)
    fake_struct_row = SimpleNamespace(
        parent_tranche_id="B",
        child_tranche_id="Z",
        principal_conservation_error=0.0,
        coupon_identity_error=0.0,
    )
    fake_result = SimpleNamespace(
        collateral_summary=SimpleNamespace(total_collateral_loss=0.0, starting_balance=100.0),
        bond_cashflows=[],
        trigger_state_history=[],
        deal_accounts=[],
        credit_enhancement=[],
        pac_tac_diagnostics=[fake_diag_row],
        structure_composition=[fake_struct_row],
    )
    monkeypatch.setattr(solver_mod, "run_deal", lambda *args, **kwargs: fake_result)
    monkeypatch.setattr(solver_mod, "compute_tranche_risk", lambda *args, **kwargs: [])

    spec = SolverSpec(
        solver_name="pac_tac_z_primitive_test",
        layers=[
            SolverLayerSpec(
                layer_name="base",
                objectives=[
                    ObjectiveSpec(
                        name="pac_miss",
                        metric_path="primitive:PAC_SCHEDULE_MISS",
                        objective_type=ObjectiveType.MINIMIZE,
                        target_primitive=WaterfallTargetPrimitive.PAC_SCHEDULE_MISS,
                        primitive_params={"tranche_id": "A"},
                    )
                ],
                constraints=[
                    ConstraintSpec(
                        name="z_release_ok",
                        metric_path="primitive:Z_ACCRUAL_RELEASE_GAP",
                        comparison=ConstraintComparison.LE,
                        value=0.0,
                        target_primitive=WaterfallTargetPrimitive.Z_ACCRUAL_RELEASE_GAP,
                        primitive_params={"tranche_id": "Z"},
                    )
                ],
                knobs=[KnobBound(knob_path="deal_knobs.class_a_coupon", lower=4.0, upper=8.0, initial=6.0)],
                max_iterations=1,
            )
        ],
    )
    _, summary = solve_deal(deal, run_input, spec)
    metrics = summary.selected_solution.get("metrics", {})
    assert "primitive:PAC_SCHEDULE_MISS" in metrics
    assert "primitive:Z_ACCRUAL_RELEASE_GAP" in metrics
