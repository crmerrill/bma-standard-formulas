import type { SolverSpecDraft } from "./types";

function cleanString(value: string, fallback: string): string {
  const v = value.trim();
  return v || fallback;
}

export function builderToSolverSpec(draft: SolverSpecDraft): Record<string, unknown> {
  return {
    solver_name: cleanString(draft.solverName, "studio_solver"),
    layers: [
      {
        layer_name: cleanString(draft.layerName, "base"),
        objectives: draft.objectives.map((objective, idx) => ({
          name: cleanString(objective.name, `objective_${idx + 1}`),
          metric_path: cleanString(objective.metricPath, "tranche_risk_summary[A].yield_pct"),
          objective_type: objective.objectiveType,
          target_value: objective.objectiveType === "TARGET" ? objective.targetValue ?? 0 : null,
          weight: objective.weight,
          target_primitive: objective.targetPrimitive ?? null,
          primitive_params: objective.primitiveParams ?? {},
        })),
        constraints: draft.constraints.map((constraint, idx) => {
          const base = {
            name: cleanString(constraint.name, `constraint_${idx + 1}`),
            metric_path: cleanString(constraint.metricPath, "tranche_risk_summary[A].wal"),
            comparison: constraint.operator,
            tolerance: 1e-6,
            hard: true,
            target_primitive: constraint.targetPrimitive ?? null,
            primitive_params: constraint.primitiveParams ?? {},
          } as Record<string, unknown>;
          if (constraint.operator === "BETWEEN") {
            base.lower = constraint.minValue ?? 0;
            base.upper = constraint.maxValue ?? 0;
          } else if (constraint.operator === "GE") {
            base.value = constraint.minValue ?? 0;
          } else {
            base.value = constraint.maxValue ?? 0;
          }
          return base;
        }),
        knobs: draft.knobs.map((knob) => ({
          knob_path: cleanString(knob.knobPath, "deal_knobs.class_a_coupon"),
          lower: knob.lower,
          upper: knob.upper,
          initial: knob.initial,
          step_hint: knob.stepHint,
        })),
        max_iterations: draft.maxIterations,
        convergence_tolerance: draft.convergenceTolerance,
        warm_start_from_prior: draft.warmStartFromPrior,
      },
    ],
    checkpoint_every_n: draft.checkpointEveryN,
    global_max_iterations: draft.globalMaxIterations,
    description: draft.description ?? "",
  };
}
