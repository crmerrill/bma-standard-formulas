import React, { useMemo } from "react";
import { CircleStop, Play, Sigma } from "lucide-react";
import { toast } from "sonner";
import CollapsiblePanel from "../../../components/CollapsiblePanel";
import DataTable, { type DataTableColumn } from "../../../components/DataTable";
import MetricCard from "../../../components/MetricCard";
import type { RunListItem } from "../../../services/api";
import ExistingRunSelector from "./ExistingRunSelector";
import type {
  AdvancedJsonState,
  SensitivitySweepConfig,
  SolverSpecDraft,
  TelemetryState,
} from "./types";

interface Props {
  savedDealId: string | null;
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
            <select
              value={solverSpecDraft.sourceMode}
              onChange={(e) =>
                setSolverSpecDraft((prev) => ({
                  ...prev,
                  sourceMode: e.target.value as "runsetup_ref" | "deal_native",
                }))
              }
              className="px-2 py-1 rounded border border-border bg-input-background text-foreground"
            >
              <option value="runsetup_ref">Run Setup ref</option>
              <option value="deal_native">Deal-native</option>
            </select>
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
                <select
                  value={solverSpecDraft.sourceScenarioName ?? ""}
                  onChange={(e) =>
                    setSolverSpecDraft((prev) => ({
                      ...prev,
                      sourceScenarioName: e.target.value || null,
                    }))
                  }
                  className="w-full px-2 py-1 rounded border border-border bg-input-background text-foreground"
                >
                  <option value="">Auto-select from scenario set</option>
                  {scenarioOptions.map((scenarioName) => (
                    <option key={scenarioName} value={scenarioName}>
                      {scenarioName}
                    </option>
                  ))}
                </select>
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

      <CollapsiblePanel title="Solver Builder (Phase A shell)" defaultOpen>
        <div className="p-3 space-y-2 text-xs">
          <p className="text-muted-foreground">
            Objective, constraint, knob, and preset builders are landing in Phase B. This shell
            already persists canonical advanced JSON and source selection state.
          </p>
          <label className="block space-y-1">
            <span className="text-muted-foreground">Advanced solver spec (JSON)</span>
            <textarea
              value={advancedJson.jsonText}
              onChange={(e) =>
                setAdvancedJson((prev) => ({
                  ...prev,
                  jsonText: e.target.value,
                  parseError: null,
                }))
              }
              rows={12}
              className="w-full px-2 py-1 rounded border border-border bg-input-background text-foreground"
            />
          </label>
          {advancedJson.parseError && (
            <div className="text-[11px] text-destructive">{advancedJson.parseError}</div>
          )}
          <button
            type="button"
            onClick={() => {
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
            className="px-2 py-1 rounded border border-border text-muted-foreground hover:text-foreground"
          >
            Validate JSON
          </button>
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
          <pre className="max-h-[240px] overflow-auto rounded border border-border px-2 py-1 text-[10px]">
            {irErrors.length > 0 ? irErrors.join("\n") : irJson || "// Build the waterfall to see IR"}
          </pre>
        </div>
      </CollapsiblePanel>
    </div>
  );
}
