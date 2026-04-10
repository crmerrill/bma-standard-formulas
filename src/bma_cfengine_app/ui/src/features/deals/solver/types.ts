export interface ObjectiveDraftRow {
  id: string;
  name: string;
  metricPath: string;
  objectiveType: "TARGET" | "MINIMIZE" | "MAXIMIZE";
  targetValue: number | null;
  weight: number;
}

export interface ConstraintDraftRow {
  id: string;
  name: string;
  metricPath: string;
  operator: "GE" | "LE" | "EQ" | "BETWEEN";
  minValue: number | null;
  maxValue: number | null;
}

export interface KnobDraftRow {
  id: string;
  knobPath: string;
  lower: number;
  upper: number;
  initial: number;
  stepHint: number;
}

export interface SolverSpecDraft {
  solverName: string;
  layerName: string;
  checkpointEveryN: number;
  globalMaxIterations: number;
  description: string;
  objectives: ObjectiveDraftRow[];
  constraints: ConstraintDraftRow[];
  knobs: KnobDraftRow[];
  maxIterations: number;
  convergenceTolerance: number;
  warmStartFromPrior: boolean;
  sourceMode: "runsetup_ref" | "deal_native";
  sourceRunId: string | null;
  sourceScenarioName: string | null;
  scenarioSetText: string;
  nativeRunInputJson: string;
}

export interface AdvancedJsonState {
  jsonText: string;
  parseError: string | null;
  lastSyncedAt: string | null;
}

export interface TelemetryPoint {
  iteration: number;
  objectiveValue: number;
}

export interface TelemetryState {
  status: "idle" | "running" | "completed" | "failed" | "cancelled";
  stage: string;
  iteration: number;
  objectiveTrajectory: TelemetryPoint[];
  cancelToken: string | null;
  runId: string | null;
}

export interface SensitivityAxisConfig {
  knobPath: string;
  min: number;
  max: number;
  step: number;
}

export interface SensitivitySweepConfig {
  enabled: boolean;
  mode: "ONE_D" | "TWO_D";
  primary: SensitivityAxisConfig;
  secondary: SensitivityAxisConfig | null;
  scenarioName: string;
}
