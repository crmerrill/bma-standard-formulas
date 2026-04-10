import type {
  AdvancedJsonState,
  SensitivitySweepConfig,
  SolverSpecDraft,
  TelemetryState,
} from "./types";

export function getDefaultSolverSpecDraft(): SolverSpecDraft {
  return {
    solverName: "studio_solver",
    layerName: "base",
    checkpointEveryN: 4,
    globalMaxIterations: 60,
    description: "Studio automated solve",
    objectives: [
      {
        id: "obj_1",
        name: "target_A_yield",
        metricPath: "tranche_risk_summary[A].yield_pct",
        objectiveType: "TARGET",
        targetValue: 6.0,
        weight: 1.0,
      },
    ],
    constraints: [],
    knobs: [
      {
        id: "knob_1",
        knobPath: "deal_knobs.class_a_coupon",
        lower: 3.0,
        upper: 10.0,
        initial: 6.0,
        stepHint: 0.25,
      },
    ],
    maxIterations: 12,
    convergenceTolerance: 0.001,
    warmStartFromPrior: true,
    sourceMode: "runsetup_ref",
    sourceRunId: null,
    sourceScenarioName: null,
    scenarioSetText: "Base Case",
    nativeRunInputJson: "{}",
  };
}

export function solverSpecDraftToCanonicalJson(draft: SolverSpecDraft): string {
  const canonical = {
    solver_name: draft.solverName,
    layers: [
      {
        layer_name: draft.layerName,
        objectives: draft.objectives.map((o) => ({
          name: o.name,
          metric_path: o.metricPath,
          objective_type: o.objectiveType,
          target_value: o.targetValue ?? undefined,
          weight: o.weight,
        })),
        constraints: draft.constraints.map((c) => ({
          name: c.name,
          metric_path: c.metricPath,
          operator: c.operator,
          min_value: c.minValue ?? undefined,
          max_value: c.maxValue ?? undefined,
        })),
        knobs: draft.knobs.map((k) => ({
          knob_path: k.knobPath,
          lower: k.lower,
          upper: k.upper,
          initial: k.initial,
          step_hint: k.stepHint,
        })),
        max_iterations: draft.maxIterations,
        convergence_tolerance: draft.convergenceTolerance,
        warm_start_from_prior: draft.warmStartFromPrior,
      },
    ],
    checkpoint_every_n: draft.checkpointEveryN,
    global_max_iterations: draft.globalMaxIterations,
    description: draft.description,
  };
  return JSON.stringify(canonical, null, 2);
}

export function getDefaultAdvancedJsonState(
  draft: SolverSpecDraft = getDefaultSolverSpecDraft(),
): AdvancedJsonState {
  return {
    jsonText: solverSpecDraftToCanonicalJson(draft),
    parseError: null,
    lastSyncedAt: new Date().toISOString(),
  };
}

export function getDefaultTelemetryState(): TelemetryState {
  return {
    status: "idle",
    stage: "idle",
    iteration: 0,
    objectiveTrajectory: [],
    cancelToken: null,
    runId: null,
  };
}

export function getDefaultSensitivitySweepConfig(): SensitivitySweepConfig {
  return {
    enabled: false,
    mode: "ONE_D",
    primary: {
      knobPath: "deal_knobs.class_a_coupon",
      min: 4.0,
      max: 8.0,
      step: 0.25,
    },
    secondary: null,
    scenarioName: "Base Case",
  };
}
