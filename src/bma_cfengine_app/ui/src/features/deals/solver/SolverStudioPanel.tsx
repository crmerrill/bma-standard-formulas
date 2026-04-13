import React, { useMemo } from "react";
import { CircleStop, Play, Sigma } from "lucide-react";
import { toast } from "sonner";
import CollapsiblePanel from "../../../components/CollapsiblePanel";
import DataTable, { type DataTableColumn } from "../../../components/DataTable";
import FormSelect from "../../../components/FormSelect";
import MetricCard from "../../../components/MetricCard";
import type { RunListItem } from "../../../services/api";
import AdvancedJsonEditor from "./AdvancedJsonEditor";
import ConstraintBuilder from "./ConstraintBuilder";
import ExistingRunSelector from "./ExistingRunSelector";
import KnobCatalog from "./KnobCatalog";
import ObjectiveBuilder from "./ObjectiveBuilder";
import PresetLibrary from "./PresetLibrary";
import { builderToSolverSpec } from "./builderToSolverSpec";
import { solverSpecToBuilder } from "./solverSpecToBuilder";
import type {
  AdvancedJsonState,
  SensitivitySweepConfig,
  SolverSpecDraft,
  TelemetryState,
} from "./types";

interface Props {
  savedDealId: string | null;
  productFamily: "AGENCY" | "PRIME_JUMBO" | "NON_QM_QRM" | "CUSTOM";
  runBusy: boolean;
  solveBusy: boolean;
  availableRuns: RunListItem[];
  runsLoading: boolean;
  runsError: string | null;
  refreshRuns: () => void;
  solverSpecDraft: SolverSpecDraft;
  setSolverSpecDraft: React.Dispatch<React.SetStateAction<SolverSpecDraft>>;
  advancedJson: AdvancedJsonState;
  setAdvancedJson: React.Dispatch<React.SetStateAction<AdvancedJsonState>>;
  telemetryState: TelemetryState;
  setTelemetryState: React.Dispatch<React.SetStateAction<TelemetryState>>;
  sensitivitySweepConfig: SensitivitySweepConfig;
  setSensitivitySweepConfig: React.Dispatch<React.SetStateAction<SensitivitySweepConfig>>;
  onRunDeal: () => Promise<void>;
  onSolveDeal: () => Promise<void>;
  onCancelSolve: () => void;
  irJson: string;
  irErrors: string[];
}

export default function SolverStudioPanel({
  savedDealId,
  productFamily,
  runBusy,
  solveBusy,
  availableRuns,
  runsLoading,
  runsError,
  refreshRuns,
  solverSpecDraft,
  setSolverSpecDraft,
  advancedJson,
  setAdvancedJson,
  telemetryState,
  setTelemetryState,
  sensitivitySweepConfig,
  setSensitivitySweepConfig,
  onRunDeal,
  onSolveDeal,
  onCancelSolve,
  irJson,
  irErrors,
}: Props) {
  const selectedRun = useMemo(
    () => availableRuns.find((r) => r.run_id === solverSpecDraft.sourceRunId) ?? null,
    [availableRuns, solverSpecDraft.sourceRunId],
  );

  const scenarioOptions = selectedRun?.scenario_names?.length
    ? selectedRun.scenario_names
    : ["Base Case"];

  const runRows = useMemo(
    () =>
      availableRuns.slice(0, 10).map((run) => ({
        run_id: run.run_id,
        deal: run.deal_name ?? "Portfolio run",
        status: run.status,
        run_kind: run.run_kind ?? "run",
        created_at: run.created_at,
      })),
    [availableRuns],
  );

  const builderValidationErrors = useMemo(() => {
    const errors: string[] = [];
    const familyPrimitiveGuardrails: Record<string, Set<string>> = {
      AGENCY: new Set([
        "PAC_SCHEDULE_MISS",
        "TAC_SCHEDULE_MISS",
        "Z_ACCRUAL_RELEASE_GAP",
        "SUPPORT_BURNDOWN_GAP",
      ]),
      PRIME_JUMBO: new Set([
        "CUM_LOSS_MULTIPLE_GAP",
        "NO_SHORTFALL_INTEREST",
        "NO_SHORTFALL_PRINCIPAL",
        "OC_IC_TRIGGER_RESILIENCE",
        "CE_TARGET_DELTA",
      ]),
      NON_QM_QRM: new Set([
        "CUM_LOSS_MULTIPLE_GAP",
        "NO_SHORTFALL_INTEREST",
        "NO_SHORTFALL_PRINCIPAL",
        "STEPDOWN_ELIGIBILITY_SAFETY",
        "SUBORDINATION_FLOOR_GAP",
        "RESERVE_SUFFICIENCY_GAP",
        "CE_TARGET_DELTA",
      ]),
    };
    const allowedPrimitives = familyPrimitiveGuardrails[productFamily] ?? null;
    if (!solverSpecDraft.objectives.length) errors.push("Add at least one objective.");
    if (!solverSpecDraft.knobs.length) errors.push("Add at least one knob.");
    solverSpecDraft.objectives.forEach((objective, idx) => {
      if (!objective.name.trim()) errors.push(`Objective ${idx + 1} requires a name.`);
      if (!objective.metricPath.trim()) errors.push(`Objective ${idx + 1} requires a metric path.`);
      if (objective.objectiveType === "TARGET" && objective.targetValue == null) {
        errors.push(`Objective ${idx + 1} target value is required for TARGET.`);
      }
      if (
        allowedPrimitives
        && objective.targetPrimitive
        && !allowedPrimitives.has(objective.targetPrimitive)
      ) {
        errors.push(
          `Objective ${idx + 1} primitive ${objective.targetPrimitive} is outside ${productFamily} guardrails.`,
        );
      }
    });
    solverSpecDraft.constraints.forEach((constraint, idx) => {
      if (!constraint.name.trim()) errors.push(`Constraint ${idx + 1} requires a name.`);
      if (!constraint.metricPath.trim()) errors.push(`Constraint ${idx + 1} requires a metric path.`);
      if (constraint.operator === "BETWEEN") {
        if (constraint.minValue == null || constraint.maxValue == null) {
          errors.push(`Constraint ${idx + 1} requires min and max for BETWEEN.`);
        }
      } else if (constraint.operator === "GE") {
        if (constraint.minValue == null) errors.push(`Constraint ${idx + 1} requires value for GE.`);
      } else if (constraint.maxValue == null) {
        errors.push(`Constraint ${idx + 1} requires value for ${constraint.operator}.`);
      }
      if (
        allowedPrimitives
        && constraint.targetPrimitive
        && !allowedPrimitives.has(constraint.targetPrimitive)
      ) {
        errors.push(
          `Constraint ${idx + 1} primitive ${constraint.targetPrimitive} is outside ${productFamily} guardrails.`,
        );
      }
    });
    if (
      allowedPrimitives
      && !solverSpecDraft.objectives.some((row) => !!row.targetPrimitive)
      && !solverSpecDraft.constraints.some((row) => !!row.targetPrimitive)
      && productFamily !== "CUSTOM"
    ) {
      errors.push(`Use at least one waterfall primitive for ${productFamily} template workflows.`);
    }
    return errors;
  }, [solverSpecDraft, productFamily]);

  function syncBuilderToJson() {
    const solverSpec = builderToSolverSpec(solverSpecDraft);
    setAdvancedJson((prev) => ({
      ...prev,
      jsonText: JSON.stringify(solverSpec, null, 2),
      parseError: null,
      lastSyncedAt: new Date().toISOString(),
    }));
  }

  function applyJsonToBuilder() {
    try {
      const parsed = JSON.parse(advancedJson.jsonText || "{}") as Record<string, unknown>;
      const next = solverSpecToBuilder(parsed);
      setSolverSpecDraft((prev) => ({
        ...prev,
        ...next,
        sourceMode: prev.sourceMode,
        sourceRunId: prev.sourceRunId,
        sourceScenarioName: prev.sourceScenarioName,
        scenarioSetText: prev.scenarioSetText,
        nativeRunInputJson: prev.nativeRunInputJson,
      }));
      setAdvancedJson((prev) => ({
        ...prev,
        parseError: null,
        lastSyncedAt: new Date().toISOString(),
      }));
      toast.success("Applied JSON to visual builder.");
    } catch (error) {
      setAdvancedJson((prev) => ({
        ...prev,
        parseError: error instanceof Error ? error.message : String(error),
      }));
    }
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard icon={Sigma} label="Deal" value={savedDealId ?? "Unsaved"} />
        <MetricCard icon={Play} label="Source mode" value={solverSpecDraft.sourceMode} />
        <MetricCard icon={CircleStop} label="Telemetry" value={telemetryState.status} />
        <MetricCard icon={Sigma} label="Sweep mode" value={sensitivitySweepConfig.mode} />
      </div>

      <CollapsiblePanel title="Execution Source" defaultOpen>
        <div className="p-3 space-y-3 text-xs">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">Collateral/Assumptions Source</span>
            <FormSelect
              value={solverSpecDraft.sourceMode}
              onChange={(e) =>
                setSolverSpecDraft((prev) => ({
                  ...prev,
                  sourceMode: e.target.value as "runsetup_ref" | "deal_native",
                }))
              }
              className="w-auto"
            >
              <option value="runsetup_ref">Run Setup ref</option>
              <option value="deal_native">Deal-native</option>
            </FormSelect>
          </div>

          <label className="block space-y-1">
            <span className="text-muted-foreground">Scenario set (comma-separated)</span>
            <input
              value={solverSpecDraft.scenarioSetText}
              onChange={(e) =>
                setSolverSpecDraft((prev) => ({ ...prev, scenarioSetText: e.target.value }))
              }
              className="w-full px-2 py-1 rounded border border-border bg-input-background text-foreground"
            />
          </label>

          {solverSpecDraft.sourceMode === "runsetup_ref" ? (
            <div className="space-y-2">
              <ExistingRunSelector
                runs={availableRuns}
                loading={runsLoading}
                error={runsError}
                value={solverSpecDraft.sourceRunId}
                onChange={(next) =>
                  setSolverSpecDraft((prev) => ({
                    ...prev,
                    sourceRunId: next,
                    sourceScenarioName: null,
                  }))
                }
                onRetry={refreshRuns}
              />

              <label className="block space-y-1">
                <span className="text-muted-foreground">Scenario</span>
                <FormSelect
                  value={solverSpecDraft.sourceScenarioName ?? ""}
                  onChange={(e) =>
                    setSolverSpecDraft((prev) => ({
                      ...prev,
                      sourceScenarioName: e.target.value || null,
                    }))
                  }
                >
                  <option value="">Auto-select from scenario set</option>
                  {scenarioOptions.map((scenarioName) => (
                    <option key={scenarioName} value={scenarioName}>
                      {scenarioName}
                    </option>
                  ))}
                </FormSelect>
              </label>
            </div>
          ) : (
            <label className="block space-y-1">
              <span className="text-muted-foreground">deal_native run_input (JSON)</span>
              <textarea
                value={solverSpecDraft.nativeRunInputJson}
                onChange={(e) =>
                  setSolverSpecDraft((prev) => ({ ...prev, nativeRunInputJson: e.target.value }))
                }
                rows={7}
                className="w-full px-2 py-1 rounded border border-border bg-input-background text-foreground"
              />
            </label>
          )}

          <button
            type="button"
            onClick={onRunDeal}
            disabled={!savedDealId || runBusy}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded border border-primary/30 bg-primary/10 text-primary text-xs font-medium hover:bg-primary/20 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Play className="w-3.5 h-3.5" />
            {runBusy ? "Running..." : "Run deal"}
          </button>
        </div>
      </CollapsiblePanel>

      <CollapsiblePanel title="Preset Library" defaultOpen>
        <div className="p-3 text-xs">
          <PresetLibrary
            draft={solverSpecDraft}
            productFamily={productFamily}
            onApplyPreset={(next) => {
              setSolverSpecDraft(next);
              setAdvancedJson((prev) => ({ ...prev, lastSyncedAt: null }));
            }}
          />
        </div>
      </CollapsiblePanel>

      <CollapsiblePanel title="Objective Builder" defaultOpen>
        <div className="p-3 text-xs">
          <ObjectiveBuilder
            rows={solverSpecDraft.objectives}
            onChange={(rows) => {
              setSolverSpecDraft((prev) => ({ ...prev, objectives: rows }));
              setAdvancedJson((prev) => ({ ...prev, lastSyncedAt: null }));
            }}
          />
        </div>
      </CollapsiblePanel>

      <CollapsiblePanel title="Constraint Builder" defaultOpen>
        <div className="p-3 text-xs">
          <ConstraintBuilder
            rows={solverSpecDraft.constraints}
            onChange={(rows) => {
              setSolverSpecDraft((prev) => ({ ...prev, constraints: rows }));
              setAdvancedJson((prev) => ({ ...prev, lastSyncedAt: null }));
            }}
          />
        </div>
      </CollapsiblePanel>

      <CollapsiblePanel title="Knob Catalog + Bounds" defaultOpen>
        <div className="p-3 text-xs">
          <KnobCatalog
            rows={solverSpecDraft.knobs}
            onChange={(rows) => {
              setSolverSpecDraft((prev) => ({ ...prev, knobs: rows }));
              setAdvancedJson((prev) => ({ ...prev, lastSyncedAt: null }));
            }}
          />
        </div>
      </CollapsiblePanel>

      <CollapsiblePanel title="Advanced JSON Editor" defaultOpen>
        <div className="p-3 space-y-2 text-xs">
          <AdvancedJsonEditor
            state={advancedJson}
            onChange={setAdvancedJson}
            onValidate={() => {
              try {
                JSON.parse(advancedJson.jsonText || "{}");
                setAdvancedJson((prev) => ({
                  ...prev,
                  parseError: null,
                  lastSyncedAt: new Date().toISOString(),
                }));
                toast.success("Advanced JSON is valid.");
              } catch (error) {
                setAdvancedJson((prev) => ({
                  ...prev,
                  parseError: error instanceof Error ? error.message : String(error),
                }));
              }
            }}
            onSyncFromBuilder={syncBuilderToJson}
            onApplyToBuilder={applyJsonToBuilder}
          />
          {builderValidationErrors.length > 0 && (
            <div className="rounded border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
              {builderValidationErrors.map((error) => (
                <div key={error}>{error}</div>
              ))}
            </div>
          )}
        </div>
      </CollapsiblePanel>

      <CollapsiblePanel title="Execution + Telemetry" defaultOpen>
        <div className="p-3 flex flex-wrap items-center gap-2 text-xs">
          <button
            type="button"
            onClick={onSolveDeal}
            disabled={!savedDealId || solveBusy}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded border border-primary/30 bg-primary/10 text-primary text-xs font-medium hover:bg-primary/20 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Sigma className="w-3.5 h-3.5" />
            {solveBusy ? "Solving..." : "Solve deal"}
          </button>
          <button
            type="button"
            onClick={() => {
              setTelemetryState((prev) => ({ ...prev, status: "cancelled" }));
              onCancelSolve();
            }}
            disabled={!solveBusy}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded border border-destructive/40 bg-destructive/10 text-destructive text-xs font-medium hover:bg-destructive/20 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <CircleStop className="w-3.5 h-3.5" />
            Cancel
          </button>
          <span className="text-muted-foreground">
            Status: {telemetryState.status} | Stage: {telemetryState.stage} | Iteration:{" "}
            {telemetryState.iteration}
          </span>
        </div>
      </CollapsiblePanel>

      <CollapsiblePanel title="Sensitivity Sweep (state scaffold)" defaultOpen>
        <div className="p-3 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
          <label className="inline-flex items-center gap-2">
            <input
              type="checkbox"
              checked={sensitivitySweepConfig.enabled}
              onChange={(e) =>
                setSensitivitySweepConfig((prev) => ({ ...prev, enabled: e.target.checked }))
              }
            />
            Enable sweep
          </label>
          <label className="block space-y-1">
            <span className="text-muted-foreground">Scenario</span>
            <input
              value={sensitivitySweepConfig.scenarioName}
              onChange={(e) =>
                setSensitivitySweepConfig((prev) => ({ ...prev, scenarioName: e.target.value }))
              }
              className="w-full px-2 py-1 rounded border border-border bg-input-background text-foreground"
            />
          </label>
        </div>
      </CollapsiblePanel>

      <CollapsiblePanel title="Recent source runs" defaultOpen={false}>
        <div className="p-3">
          <DataTable
            tableId="solver_studio_run_sources"
            columns={[
              { id: "run_id", header: "Run", accessorFn: (r) => String(r.run_id).slice(0, 12) },
              { id: "deal", header: "Deal / Run", accessorKey: "deal", mono: false },
              { id: "status", header: "Status", accessorKey: "status", mono: false },
              { id: "kind", header: "Kind", accessorKey: "run_kind", mono: false },
              { id: "created", header: "Created", accessorKey: "created_at", mono: false },
            ] as DataTableColumn<(typeof runRows)[number]>[]}
            data={runRows}
            emptyMessage="No runs available."
            maxHeight={260}
          />
        </div>
      </CollapsiblePanel>

      <CollapsiblePanel title="Deal IR drawer" defaultOpen={false}>
        <div className="p-3">
          <pre className="max-h-[240px] overflow-auto rounded border border-border px-2 py-1 text-xs">
            {irErrors.length > 0 ? irErrors.join("\n") : irJson || "// Build the waterfall to see IR"}
          </pre>
        </div>
      </CollapsiblePanel>
    </div>
  );
}
