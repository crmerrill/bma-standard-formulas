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
    WaterfallTargetPrimitive,
)

class SolverCancelledError(RuntimeError):
    """Raised when a solve run is cooperatively cancelled by caller."""



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

    if metric_path.startswith("pac_tac_diagnostics["):
        tranche_id = metric_path.split("[")[1].split("]")[0]
        attr = metric_path.split(".")[-1]
        values: list[float] = []
        for row in getattr(scenario_result, "pac_tac_diagnostics", []):
            if getattr(row, "tranche_id", None) != tranche_id:
                continue
            values.append(float(getattr(row, attr, 0.0) or 0.0))
        if values:
            return max(values)

    if metric_path.startswith("structure_composition["):
        tranche_id = metric_path.split("[")[1].split("]")[0]
        attr = metric_path.split(".")[-1]
        values: list[float] = []
        for row in getattr(scenario_result, "structure_composition", []):
            parent = getattr(row, "parent_tranche_id", None)
            child = getattr(row, "child_tranche_id", None)
            if tranche_id not in {parent, child}:
                continue
            values.append(float(getattr(row, attr, 0.0) or 0.0))
        if values:
            return max(values)

    return 0.0


def _extract_primitive_metric(
    scenario_result,
    risk_results: list,
    primitive: WaterfallTargetPrimitive,
    params: dict[str, Any] | None = None,
) -> float:
    """Derive a domain-native metric from waterfall outputs."""
    params = params or {}
    tranche_id = str(params.get("tranche_id", "A"))

    if primitive == WaterfallTargetPrimitive.CUM_LOSS_MULTIPLE_GAP:
        target_multiple = float(params.get("target_multiple", 2.0))
        collateral = getattr(scenario_result, "collateral_summary", None)
        total_loss = float(getattr(collateral, "total_collateral_loss", 0.0) or 0.0) if collateral else 0.0
        original_balance = float(getattr(collateral, "starting_balance", 0.0) or 0.0) if collateral else 0.0
        loss_pct = (total_loss / original_balance) if original_balance > 0 else 0.0
        achieved_multiple = (1.0 / loss_pct) if loss_pct > 0 else 999.0
        return max(0.0, target_multiple - achieved_multiple)

    if primitive in {
        WaterfallTargetPrimitive.NO_SHORTFALL_INTEREST,
        WaterfallTargetPrimitive.NO_SHORTFALL_PRINCIPAL,
    }:
        attr = "interest_shortfall_pct" if primitive == WaterfallTargetPrimitive.NO_SHORTFALL_INTEREST else "principal_shortfall_pct"
        max_shortfall = 0.0
        for row in getattr(scenario_result, "bond_cashflows", []):
            if getattr(row, "tranche_id", None) != tranche_id:
                continue
            if primitive == WaterfallTargetPrimitive.NO_SHORTFALL_INTEREST:
                denom = float(getattr(row, "interest_due", 0.0) or 0.0)
                raw = float(getattr(row, "interest_shortfall", 0.0) or 0.0)
            else:
                denom = float(getattr(row, "total_principal", 0.0) or 0.0)
                raw = float(getattr(row, "writedown", 0.0) or 0.0)
            pct = raw / denom if denom > 0 else 0.0
            max_shortfall = max(max_shortfall, pct)
        for r in risk_results:
            if getattr(r, "tranche_id", None) == tranche_id:
                max_shortfall = max(max_shortfall, float(getattr(r, attr, 0.0) or 0.0))
        return max_shortfall

    if primitive == WaterfallTargetPrimitive.OC_IC_TRIGGER_RESILIENCE:
        breaches = 0
        for row in getattr(scenario_result, "trigger_state_history", []):
            trigger_name = str(getattr(row, "trigger_id", "")).lower()
            state = str(getattr(row, "state", "")).upper()
            if ("oc" in trigger_name or "ic" in trigger_name) and state in {"BREACHED", "TRIGGERED"}:
                breaches += 1
        return float(breaches)

    if primitive == WaterfallTargetPrimitive.STEPDOWN_ELIGIBILITY_SAFETY:
        unsafe_events = 0
        for row in getattr(scenario_result, "trigger_state_history", []):
            trigger_name = str(getattr(row, "trigger_id", "")).lower()
            state = str(getattr(row, "state", "")).upper()
            if ("step" in trigger_name or "pro_rata" in trigger_name or "prorata" in trigger_name) and state in {"BREACHED", "TRIGGERED"}:
                unsafe_events += 1
        return float(unsafe_events)

    if primitive == WaterfallTargetPrimitive.SUBORDINATION_FLOOR_GAP:
        floor_pct = float(params.get("floor_pct", 0.0))
        ce_pct = 0.0
        for ce in getattr(scenario_result, "credit_enhancement", []):
            if getattr(ce, "tranche_id", None) == tranche_id:
                ce_pct = float(getattr(ce, "subordination_pct", 0.0) or 0.0)
                break
        return max(0.0, floor_pct - ce_pct)

    if primitive == WaterfallTargetPrimitive.RESERVE_SUFFICIENCY_GAP:
        floor_amount = float(params.get("reserve_floor", 0.0))
        min_reserve = None
        for row in getattr(scenario_result, "deal_accounts", []):
            account_name = str(getattr(row, "account_id", "")).lower()
            if "reserve" not in account_name and "liquidity" not in account_name:
                continue
            end_balance = float(getattr(row, "end_balance", 0.0) or 0.0)
            min_reserve = end_balance if min_reserve is None else min(min_reserve, end_balance)
        if min_reserve is None:
            return float(floor_amount > 0.0)
        return max(0.0, floor_amount - min_reserve)

    if primitive == WaterfallTargetPrimitive.CE_TARGET_DELTA:
        target_ce = float(params.get("target_ce_pct", 0.0))
        ce_pct = 0.0
        for ce in getattr(scenario_result, "credit_enhancement", []):
            if getattr(ce, "tranche_id", None) == tranche_id:
                ce_pct = float(getattr(ce, "total_ce_pct", 0.0) or 0.0)
                break
        return abs(target_ce - ce_pct)

    if primitive in {
        WaterfallTargetPrimitive.PAC_SCHEDULE_MISS,
        WaterfallTargetPrimitive.TAC_SCHEDULE_MISS,
    }:
        max_miss = 0.0
        expected = "PAC" if primitive == WaterfallTargetPrimitive.PAC_SCHEDULE_MISS else "TAC"
        for row in getattr(scenario_result, "pac_tac_diagnostics", []):
            if getattr(row, "tranche_id", None) != tranche_id:
                continue
            row_schedule = getattr(getattr(row, "schedule_type", None), "value", None)
            if row_schedule != expected:
                continue
            max_miss = max(max_miss, abs(float(getattr(row, "schedule_variance", 0.0) or 0.0)))
        return max_miss

    if primitive == WaterfallTargetPrimitive.Z_ACCRUAL_RELEASE_GAP:
        max_gap = 0.0
        for row in getattr(scenario_result, "structure_composition", []):
            if getattr(row, "child_tranche_id", None) != tranche_id:
                continue
            max_gap = max(max_gap, float(getattr(row, "principal_conservation_error", 0.0) or 0.0))
            max_gap = max(max_gap, float(getattr(row, "coupon_identity_error", 0.0) or 0.0))
        return max_gap

    if primitive == WaterfallTargetPrimitive.SUPPORT_BURNDOWN_GAP:
        max_gap = 0.0
        floor = float(params.get("support_floor", 0.0))
        for row in getattr(scenario_result, "structure_composition", []):
            if getattr(row, "parent_tranche_id", None) != tranche_id:
                continue
            remaining_gap = float(getattr(row, "principal_conservation_error", 0.0) or 0.0)
            max_gap = max(max_gap, max(0.0, remaining_gap - floor))
        return max_gap

    return 0.0


def _objective_term(metric: float, obj: ObjectiveSpec) -> float:
    if obj.objective_type == ObjectiveType.TARGET:
        return obj.weight * abs(metric - (obj.target_value or 0.0))
    if obj.objective_type == ObjectiveType.MINIMIZE:
        return obj.weight * metric
    if obj.objective_type == ObjectiveType.MAXIMIZE:
        return -obj.weight * metric
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
    progress_callback: Any | None = None,
    should_cancel: Any | None = None,
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
            if callable(should_cancel) and should_cancel():
                raise SolverCancelledError("Solver cancelled by user request")
            total_iters += 1

            for path, val in knob_values.items():
                _set_knob_value(deal, path, val)
            _apply_knobs_to_bond_sizes(deal)

            scenario_result = run_deal(deal, run_input, scenario_name=scenario_name, collect_trace=False)
            risk_results = compute_tranche_risk(scenario_result)

            obj_value = 0.0
            for obj in layer.objectives:
                if obj.target_primitive:
                    metric = _extract_primitive_metric(
                        scenario_result,
                        risk_results,
                        obj.target_primitive,
                        obj.primitive_params,
                    )
                    metric_key = f"primitive:{obj.target_primitive.value}"
                else:
                    metric = _extract_metric(scenario_result, risk_results, obj.metric_path)
                    metric_key = obj.metric_path
                final_metrics[metric_key] = metric
                obj_value += _objective_term(metric, obj)

            violation_norm = 0.0
            for constraint in layer.constraints:
                if constraint.target_primitive:
                    metric = _extract_primitive_metric(
                        scenario_result,
                        risk_results,
                        constraint.target_primitive,
                        constraint.primitive_params,
                    )
                    metric_key = f"primitive:{constraint.target_primitive.value}"
                else:
                    metric = _extract_metric(scenario_result, risk_results, constraint.metric_path)
                    metric_key = constraint.metric_path
                final_metrics[metric_key] = metric
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
            if callable(progress_callback):
                progress_callback(
                    {
                        "stage": "optimizing",
                        "layer": layer.layer_name,
                        "iteration": iteration,
                        "objective_value": obj_value,
                        "constraint_violation_norm": violation_norm,
                        "feasible": feasible,
                    }
                )

            if obj_value < layer.convergence_tolerance and feasible:
                final_status = SolverStatus.CONVERGED
                final_obj = obj_value
                final_feasible = True
                break

            for knob in layer.knobs:
                if callable(should_cancel) and should_cancel():
                    raise SolverCancelledError("Solver cancelled by user request")
                path = knob.knob_path
                current = knob_values[path]

                delta = (knob.step_hint or (knob.upper - knob.lower) * 0.01)
                trial_up = min(current + delta, knob.upper)
                trial_down = max(current - delta, knob.lower)

                _set_knob_value(deal, path, trial_up)
                _apply_knobs_to_bond_sizes(deal)
                result_up = run_deal(deal, run_input, scenario_name=scenario_name, collect_trace=False)
                risk_up = compute_tranche_risk(result_up)
                obj_up = 0.0
                for obj in layer.objectives:
                    metric_up = (
                        _extract_primitive_metric(
                            result_up,
                            risk_up,
                            obj.target_primitive,
                            obj.primitive_params,
                        )
                        if obj.target_primitive
                        else _extract_metric(result_up, risk_up, obj.metric_path)
                    )
                    obj_up += _objective_term(metric_up, obj)

                _set_knob_value(deal, path, trial_down)
                _apply_knobs_to_bond_sizes(deal)
                result_down = run_deal(deal, run_input, scenario_name=scenario_name, collect_trace=False)
                risk_down = compute_tranche_risk(result_down)
                obj_down = 0.0
                for obj in layer.objectives:
                    metric_down = (
                        _extract_primitive_metric(
                            result_down,
                            risk_down,
                            obj.target_primitive,
                            obj.primitive_params,
                        )
                        if obj.target_primitive
                        else _extract_metric(result_down, risk_down, obj.metric_path)
                    )
                    obj_down += _objective_term(metric_down, obj)

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
