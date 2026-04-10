from __future__ import annotations

import pytest

from bma_standard_formulas.deals.deal_library import passthrough_deal
from bma_standard_formulas.deals.solver import SolverCancelledError, solve_deal
from bma_standard_formulas.deals.schemas.input import CollateralCashflows, DealRunInput, PooledCollateralInput
from bma_standard_formulas.deals.schemas.solver import (
    KnobBound,
    ObjectiveSpec,
    ObjectiveType,
    SolverLayerSpec,
    SolverSpec,
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
