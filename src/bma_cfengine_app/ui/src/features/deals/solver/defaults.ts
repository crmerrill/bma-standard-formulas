import type {
  AdvancedJsonState,
  SensitivitySweepConfig,
  SolverSpecDraft,
  TelemetryState,
} from "./types";
import { builderToSolverSpec } from "./builderToSolverSpec";

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
  const canonical = builderToSolverSpec(draft);
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
