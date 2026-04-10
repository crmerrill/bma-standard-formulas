"""Iterative deal solver — mutate IR knobs, rerun waterfall, evaluate, converge.

The solver loop:
1. Takes a base DealDefinition + DealRunInput + SolverSpec
2. For each layer in SolverSpec.layers:
   a. Applies current knob values to a mutable copy of the IR
   b. Runs the waterfall
   c. Evaluates objectives and constraints from the outputs
   d. Updates knobs via bisection/gradient step
   e. Repeats until convergence or max iterations
3. Produces a SolverRunSummary with iteration logs and solved deal version
"""
import time
from typing import Any

from .runtime import run_deal
from .risk import compute_tranche_risk
from .schemas.common import SolverStatus
from .schemas.input import DealRunInput
from .schemas.ir import DealDefinition
from .schemas.output_solver import SolverIterationRow, SolverRunSummary
from .schemas.solver import (
    ConstraintComparison,
    ConstraintSpec,
    KnobBound,
    ObjectiveSpec,
    ObjectiveType,
    SolverLayerSpec,
    SolverSpec,
)


# ---------------------------------------------------------------------------
# Knob manipulation
# ---------------------------------------------------------------------------


def _get_knob_value(deal: DealDefinition, knob_path: str) -> float:
    """Read a knob value from the deal IR by dot-path."""
    if knob_path.startswith("deal_knobs."):
        key = knob_path.split(".", 1)[1]
        return float(deal.deal_knobs.get(key, 0.0))

    if knob_path.startswith("bonds["):
        bond_name = knob_path.split("[")[1].split("]")[0]
        attr = knob_path.split(".")[-1]
        for b in deal.bonds:
            if b.name == bond_name:
                return float(getattr(b, attr, 0.0) or 0.0)

    return 0.0


def _set_knob_value(deal: DealDefinition, knob_path: str, value: float) -> None:
    """Set a knob value on the deal IR by dot-path (mutates in place)."""
    if knob_path.startswith("deal_knobs."):
        key = knob_path.split(".", 1)[1]
        deal.deal_knobs[key] = value
        return

    if knob_path.startswith("bonds["):
        bond_name = knob_path.split("[")[1].split("]")[0]
        attr = knob_path.split(".")[-1]
        for b in deal.bonds:
            if b.name == bond_name:
                object.__setattr__(b, attr, value)
                return


def _apply_knobs_to_bond_sizes(deal: DealDefinition) -> None:
    """Sync deal_knobs to bond size_pct/coupon fields."""
    for bond in deal.bonds:
        pct_key = f"class_{bond.name.lower()}_pctbal"
        cpn_key = f"class_{bond.name.lower()}_coupon"
        if pct_key in deal.deal_knobs:
            object.__setattr__(bond, "size_pct", float(deal.deal_knobs[pct_key]))
        if cpn_key in deal.deal_knobs:
            object.__setattr__(bond, "coupon", float(deal.deal_knobs[cpn_key]))


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------


def _extract_metric(
    scenario_result,
    risk_results: list,
    metric_path: str,
) -> float:
    """Extract a metric value from scenario outputs by path."""
    if metric_path.startswith("tranche_risk_summary["):
        tranche_id = metric_path.split("[")[1].split("]")[0]
        attr = metric_path.split(".")[-1]
        for r in risk_results:
            if r.tranche_id == tranche_id:
                return float(getattr(r, attr, 0.0))

    if metric_path.startswith("credit_enhancement["):
        tranche_id = metric_path.split("[")[1].split("]")[0]
        attr = metric_path.split(".")[-1]
        for r in scenario_result.credit_enhancement:
            if r.tranche_id == tranche_id:
                return float(getattr(r, attr, 0.0))

    return 0.0


# ---------------------------------------------------------------------------
# Constraint evaluation
# ---------------------------------------------------------------------------


def _evaluate_constraint(constraint: ConstraintSpec, metric_val: float) -> float:
    """Return constraint violation (0 if satisfied, positive if violated)."""
    if constraint.comparison == ConstraintComparison.GE:
        return max(0.0, (constraint.value or 0.0) - metric_val)
    elif constraint.comparison == ConstraintComparison.LE:
        return max(0.0, metric_val - (constraint.value or 0.0))
    elif constraint.comparison == ConstraintComparison.EQ:
        return abs(metric_val - (constraint.value or 0.0))
    elif constraint.comparison == ConstraintComparison.BETWEEN:
        lower = constraint.lower or 0.0
        upper = constraint.upper or 0.0
        if metric_val < lower:
            return lower - metric_val
        if metric_val > upper:
            return metric_val - upper
        return 0.0
    return 0.0


# ---------------------------------------------------------------------------
# Solver core
# ---------------------------------------------------------------------------


def solve_deal(
    base_deal: DealDefinition,
    run_input: DealRunInput,
    solver_spec: SolverSpec,
    *,
    scenario_name: str = "Solver",
) -> tuple[DealDefinition, SolverRunSummary]:
    """Run the staged solver loop and return the solved deal + summary.

    Uses bisection-style parameter search per knob within each layer.
    """
    t_start = time.perf_counter()
    deal = base_deal.model_copy(deep=True)

    all_iterations: list[SolverIterationRow] = []
    total_iters = 0
    final_status = SolverStatus.RUNNING
    final_obj = 0.0
    final_feasible = False
    final_metrics: dict[str, float] = {}
    knob_values: dict[str, float] = {}

    for layer in solver_spec.layers:
        knob_values = {}
        for knob in layer.knobs:
            current = _get_knob_value(deal, knob.knob_path)
            knob_values[knob.knob_path] = knob.initial if knob.initial is not None else current

        for iteration in range(layer.max_iterations):
            total_iters += 1

            for path, val in knob_values.items():
                _set_knob_value(deal, path, val)
            _apply_knobs_to_bond_sizes(deal)

            scenario_result = run_deal(deal, run_input, scenario_name=scenario_name, collect_trace=False)
            risk_results = compute_tranche_risk(scenario_result)

            obj_value = 0.0
            for obj in layer.objectives:
                metric = _extract_metric(scenario_result, risk_results, obj.metric_path)
                final_metrics[obj.metric_path] = metric
                if obj.objective_type == ObjectiveType.TARGET:
                    obj_value += obj.weight * abs(metric - (obj.target_value or 0.0))
                elif obj.objective_type == ObjectiveType.MINIMIZE:
                    obj_value += obj.weight * metric
                elif obj.objective_type == ObjectiveType.MAXIMIZE:
                    obj_value -= obj.weight * metric

            violation_norm = 0.0
            for constraint in layer.constraints:
                metric = _extract_metric(scenario_result, risk_results, constraint.metric_path)
                final_metrics[constraint.metric_path] = metric
                violation_norm += _evaluate_constraint(constraint, metric) ** 2
            violation_norm = violation_norm ** 0.5

            feasible = violation_norm < layer.convergence_tolerance

            iter_row = SolverIterationRow(
                solver_job_id=solver_spec.solver_name,
                solver_layer=layer.layer_name,
                iteration=iteration,
                objective_value=obj_value,
                constraint_violation_norm=violation_norm,
                feasible_flag=feasible,
                step_size=0.0,
                convergence_metric=obj_value + violation_norm,
                status=SolverStatus.CONVERGED if (obj_value < layer.convergence_tolerance and feasible) else SolverStatus.RUNNING,
                mutated_knobs_json=dict(knob_values),
            )
            all_iterations.append(iter_row)

            if obj_value < layer.convergence_tolerance and feasible:
                final_status = SolverStatus.CONVERGED
                final_obj = obj_value
                final_feasible = True
                break

            for knob in layer.knobs:
                path = knob.knob_path
                current = knob_values[path]

                delta = (knob.step_hint or (knob.upper - knob.lower) * 0.01)
                trial_up = min(current + delta, knob.upper)
                trial_down = max(current - delta, knob.lower)

                _set_knob_value(deal, path, trial_up)
                _apply_knobs_to_bond_sizes(deal)
                result_up = run_deal(deal, run_input, scenario_name=scenario_name, collect_trace=False)
                risk_up = compute_tranche_risk(result_up)
                obj_up = sum(
                    o.weight * abs(
                        _extract_metric(result_up, risk_up, o.metric_path) - (o.target_value or 0.0)
                    )
                    for o in layer.objectives
                )

                _set_knob_value(deal, path, trial_down)
                _apply_knobs_to_bond_sizes(deal)
                result_down = run_deal(deal, run_input, scenario_name=scenario_name, collect_trace=False)
                risk_down = compute_tranche_risk(result_down)
                obj_down = sum(
                    o.weight * abs(
                        _extract_metric(result_down, risk_down, o.metric_path) - (o.target_value or 0.0)
                    )
                    for o in layer.objectives
                )

                if obj_up < obj_down:
                    knob_values[path] = trial_up
                else:
                    knob_values[path] = trial_down

        if final_status != SolverStatus.CONVERGED:
            if total_iters >= solver_spec.global_max_iterations:
                final_status = SolverStatus.FAILED
            else:
                final_status = SolverStatus.CONVERGED
                final_obj = obj_value
                final_feasible = feasible

    elapsed = round(time.perf_counter() - t_start, 3)

    summary = SolverRunSummary(
        solver_job_id=solver_spec.solver_name,
        solver_layers_run=[l.layer_name for l in solver_spec.layers],
        total_iterations=total_iters,
        final_status=final_status,
        final_objective_value=final_obj,
        final_feasible=final_feasible,
        elapsed_seconds=elapsed,
        solved_knobs={k: v for k, v in knob_values.items()},
        iteration_log=all_iterations,
        selected_solution={
            "scenario_name": scenario_name,
            "objective_value": final_obj,
            "feasible": final_feasible,
            "metrics": final_metrics,
            "knobs": {k: v for k, v in knob_values.items()},
        },
    )

    return deal, summary
