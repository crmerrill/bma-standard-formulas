import { getDefaultSolverSpecDraft } from "./defaults";
import type {
  ConstraintDraftRow,
  KnobDraftRow,
  ObjectiveDraftRow,
  SolverSpecDraft,
} from "./types";

function asNumber(value: unknown, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function asNullableNumber(value: unknown): number | null {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function solverSpecToBuilder(spec: Record<string, unknown>): SolverSpecDraft {
  const base = getDefaultSolverSpecDraft();
  const layers = Array.isArray(spec.layers) ? spec.layers : [];
  const layer = (layers[0] ?? {}) as Record<string, unknown>;
  const objectives = Array.isArray(layer.objectives) ? layer.objectives : [];
  const constraints = Array.isArray(layer.constraints) ? layer.constraints : [];
  const knobs = Array.isArray(layer.knobs) ? layer.knobs : [];

  const objectiveRows: ObjectiveDraftRow[] = objectives.map((objective, idx) => {
    const o = objective as Record<string, unknown>;
    const objectiveType =
      o.objective_type === "MINIMIZE" || o.objective_type === "MAXIMIZE" || o.objective_type === "TARGET"
        ? o.objective_type
        : "TARGET";
    return {
      id: `obj_${idx + 1}`,
      name: String(o.name ?? `objective_${idx + 1}`),
      metricPath: String(o.metric_path ?? ""),
      objectiveType,
      targetValue: asNullableNumber(o.target_value),
      weight: asNumber(o.weight, 1),
    };
  });

  const constraintRows: ConstraintDraftRow[] = constraints.map((constraint, idx) => {
    const c = constraint as Record<string, unknown>;
    const operator =
      c.comparison === "GE" || c.comparison === "LE" || c.comparison === "EQ" || c.comparison === "BETWEEN"
        ? c.comparison
        : "LE";
    const value = asNullableNumber(c.value);
    return {
      id: `constraint_${idx + 1}`,
      name: String(c.name ?? `constraint_${idx + 1}`),
      metricPath: String(c.metric_path ?? ""),
      operator,
      minValue: operator === "GE" ? value : asNullableNumber(c.lower),
      maxValue: operator === "BETWEEN" ? asNullableNumber(c.upper) : value,
    };
  });

  const knobRows: KnobDraftRow[] = knobs.map((knob, idx) => {
    const k = knob as Record<string, unknown>;
    return {
      id: `knob_${idx + 1}`,
      knobPath: String(k.knob_path ?? ""),
      lower: asNumber(k.lower, 0),
      upper: asNumber(k.upper, 0),
      initial: asNumber(k.initial, asNumber(k.lower, 0)),
      stepHint: asNumber(k.step_hint, 0.1),
    };
  });

  return {
    ...base,
    solverName: String(spec.solver_name ?? base.solverName),
    layerName: String(layer.layer_name ?? base.layerName),
    checkpointEveryN: asNumber(spec.checkpoint_every_n, base.checkpointEveryN),
    globalMaxIterations: asNumber(spec.global_max_iterations, base.globalMaxIterations),
    description: String(spec.description ?? base.description),
    objectives: objectiveRows.length ? objectiveRows : base.objectives,
    constraints: constraintRows,
    knobs: knobRows.length ? knobRows : base.knobs,
    maxIterations: asNumber(layer.max_iterations, base.maxIterations),
    convergenceTolerance: asNumber(layer.convergence_tolerance, base.convergenceTolerance),
    warmStartFromPrior:
      typeof layer.warm_start_from_prior === "boolean"
        ? layer.warm_start_from_prior
        : base.warmStartFromPrior,
  };
}
