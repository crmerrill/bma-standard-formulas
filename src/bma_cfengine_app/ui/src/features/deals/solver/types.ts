export interface ObjectiveDraftRow {
  id: string;
  name: string;
  metricPath: string;
  objectiveType: "TARGET" | "MINIMIZE" | "MAXIMIZE";
  targetValue: number | null;
  weight: number;
  targetPrimitive:
    | "CUM_LOSS_MULTIPLE_GAP"
    | "NO_SHORTFALL_INTEREST"
    | "NO_SHORTFALL_PRINCIPAL"
    | "OC_IC_TRIGGER_RESILIENCE"
    | "STEPDOWN_ELIGIBILITY_SAFETY"
    | "SUBORDINATION_FLOOR_GAP"
    | "RESERVE_SUFFICIENCY_GAP"
    | "CE_TARGET_DELTA"
    | "PAC_SCHEDULE_MISS"
    | "TAC_SCHEDULE_MISS"
    | "Z_ACCRUAL_RELEASE_GAP"
    | "SUPPORT_BURNDOWN_GAP"
    | null;
  primitiveParams: Record<string, number | string | boolean | null>;
}

export interface ConstraintDraftRow {
  id: string;
  name: string;
  metricPath: string;
  operator: "GE" | "LE" | "EQ" | "BETWEEN";
  minValue: number | null;
  maxValue: number | null;
  targetPrimitive:
    | "CUM_LOSS_MULTIPLE_GAP"
    | "NO_SHORTFALL_INTEREST"
    | "NO_SHORTFALL_PRINCIPAL"
    | "OC_IC_TRIGGER_RESILIENCE"
    | "STEPDOWN_ELIGIBILITY_SAFETY"
    | "SUBORDINATION_FLOOR_GAP"
    | "RESERVE_SUFFICIENCY_GAP"
    | "CE_TARGET_DELTA"
    | "PAC_SCHEDULE_MISS"
    | "TAC_SCHEDULE_MISS"
    | "Z_ACCRUAL_RELEASE_GAP"
    | "SUPPORT_BURNDOWN_GAP"
    | null;
  primitiveParams: Record<string, number | string | boolean | null>;
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
