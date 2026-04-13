export type RiskSourceMode = "new_risk" | "existing_run";
export type ProductFamily = "AGENCY" | "PRIME_JUMBO" | "NON_QM_QRM" | "CUSTOM";

export interface RiskParameterSet {
  cpr: number;
  cdr: number;
  severity: number;
  horizonMonths: number;
}

export interface RateScenarioControls {
  scenarioName: string;
  spreadShockBps: number;
  yieldShockBps: number;
}

export interface ExecutionOptions {
  runMode: "cashflow" | "solver";
  artifactScope: "standard" | "full";
  compareBaselineRunId: string | null;
}

export interface RiskValidationState {
  isValid: boolean;
  messages: string[];
}

export interface CollateralRiskSettings {
  productFamily: ProductFamily;
  tapeId: string;
  tapeMappingId: string;
  poolId: string;
  poolName: string;
  poolVersion: number | null;
  riskSourceMode: RiskSourceMode;
  existingRiskRunId: string | null;
  newRiskParams: RiskParameterSet;
  rateScenario: RateScenarioControls;
  execution: ExecutionOptions;
  validation: RiskValidationState;
}

export function getDefaultCollateralRiskSettings(): CollateralRiskSettings {
  return {
    productFamily: "AGENCY",
    tapeId: "",
    tapeMappingId: "",
    poolId: "",
    poolName: "",
    poolVersion: null,
    riskSourceMode: "existing_run",
    existingRiskRunId: null,
    newRiskParams: { cpr: 6, cdr: 2, severity: 35, horizonMonths: 360 },
    rateScenario: { scenarioName: "Base", spreadShockBps: 0, yieldShockBps: 0 },
    execution: { runMode: "cashflow", artifactScope: "standard", compareBaselineRunId: null },
    validation: { isValid: false, messages: ["Pool/tape selection is required."] },
  };
}

export function applyProductFamilyPreset(
  settings: CollateralRiskSettings,
  productFamily: ProductFamily,
): CollateralRiskSettings {
  const nextBase: CollateralRiskSettings = {
    ...settings,
    productFamily,
  };
  if (productFamily === "CUSTOM") {
    return nextBase;
  }
  if (productFamily === "AGENCY") {
    return {
      ...nextBase,
      newRiskParams: {
        ...nextBase.newRiskParams,
        cpr: 12,
        cdr: 0.5,
        severity: 18,
        horizonMonths: 360,
      },
      rateScenario: {
        ...nextBase.rateScenario,
        scenarioName: nextBase.rateScenario.scenarioName || "Agency Base",
      },
      execution: {
        ...nextBase.execution,
        artifactScope: "standard",
      },
    };
  }
  if (productFamily === "NON_QM_QRM") {
    return {
      ...nextBase,
      newRiskParams: {
        ...nextBase.newRiskParams,
        cpr: 6,
        cdr: 4,
        severity: 42,
        horizonMonths: 360,
      },
      rateScenario: {
        ...nextBase.rateScenario,
        scenarioName: nextBase.rateScenario.scenarioName || "Credit Stress",
      },
      execution: {
        ...nextBase.execution,
        artifactScope: "full",
      },
    };
  }
  return {
    ...nextBase,
    newRiskParams: {
      ...nextBase.newRiskParams,
      cpr: 9,
      cdr: 1,
      severity: 25,
      horizonMonths: 360,
    },
    rateScenario: {
      ...nextBase.rateScenario,
      scenarioName: nextBase.rateScenario.scenarioName || "Base",
    },
    execution: {
      ...nextBase.execution,
      artifactScope: "standard",
    },
  };
}

export function validateCollateralRiskSettings(
  settings: CollateralRiskSettings,
): RiskValidationState {
  const hasTape = !!settings.tapeId.trim();
  const messages: string[] = [];
  if (!hasTape) {
    messages.push("Select a tape.");
  }
  if (hasTape && !settings.tapeMappingId.trim()) {
    messages.push("No saved mapping found for the selected tape. Open Tape View to map and save one.");
  }
  if (settings.riskSourceMode === "existing_run" && !settings.existingRiskRunId) {
    messages.push("Choose an existing risk run or switch to new risk.");
  }
  if (settings.newRiskParams.horizonMonths <= 0) {
    messages.push("Horizon must be greater than 0 months.");
  }
  return { isValid: messages.length === 0, messages };
}
