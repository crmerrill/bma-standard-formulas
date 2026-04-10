/**
 * DealEditor — composition root for Structuring + Solver Studio.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Code2, GripVertical, LayoutDashboard, Save, Settings2, Sigma } from "lucide-react";
import { toast } from "sonner";
import BlocklyCanvas from "./BlocklyCanvas";
import PropertyPanel from "./PropertyPanel";
import { generateDealIR } from "./irGenerator";
import { applyDynamicColors } from "./blockColors";
import { MONO } from "../../lib/format";
import * as api from "../../services/api";
import TabBar from "../../components/TabBar";
import SolverStudioPanel from "./solver/SolverStudioPanel";
import {
  getDefaultAdvancedJsonState,
  getDefaultSensitivitySweepConfig,
  getDefaultSolverSpecDraft,
  getDefaultTelemetryState,
  solverSpecDraftToCanonicalJson,
} from "./solver/defaults";
import type {
  AdvancedJsonState,
  SensitivitySweepConfig,
  SolverSpecDraft,
  TelemetryState,
} from "./solver/types";

const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 640;
const PROPERTIES_PCT_MIN = 22;
const PROPERTIES_PCT_MAX = 82;

type StudioTab = "design" | "solver" | "ir";

function parseScenarioSet(text: string): string[] {
  const names = text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return names.length ? names : ["Base Case"];
}

interface DealEditorProps {
  initialSourceRunId?: string | null;
}

export default function DealEditor({ initialSourceRunId = null }: DealEditorProps) {
  const [studioTab, setStudioTab] = useState<StudioTab>("design");
  const [irJson, setIrJson] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [workspace, setWorkspace] = useState<any>(null);
  const [showDesignIr, setShowDesignIr] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(288);
  const [propertiesPct, setPropertiesPct] = useState(58);
  const [dealName, setDealName] = useState("Deal");
  const [savedDealId, setSavedDealId] = useState<string | null>(null);
  const [saveBusy, setSaveBusy] = useState(false);
  const [runBusy, setRunBusy] = useState(false);
  const [solveBusy, setSolveBusy] = useState(false);
  const [availableRuns, setAvailableRuns] = useState<api.RunListItem[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);

  const [solverSpecDraft, setSolverSpecDraft] = useState<SolverSpecDraft>(() => getDefaultSolverSpecDraft());
  const [advancedJson, setAdvancedJson] = useState<AdvancedJsonState>(() =>
    getDefaultAdvancedJsonState(),
  );
  const [telemetryState, setTelemetryState] = useState<TelemetryState>(() =>
    getDefaultTelemetryState(),
  );
  const [sensitivitySweepConfig, setSensitivitySweepConfig] = useState<SensitivitySweepConfig>(() =>
    getDefaultSensitivitySweepConfig(),
  );

  const rightColRef = useRef<HTMLDivElement>(null);
  const colDragRef = useRef<{ startX: number; startW: number } | null>(null);
  const rowDragRef = useRef<{ startY: number; startPct: number; height: number } | null>(null);
  const progressPollRef = useRef<number | null>(null);
  const scenarioNames = useMemo(
    () => parseScenarioSet(solverSpecDraft.scenarioSetText),
    [solverSpecDraft.scenarioSetText],
  );

  const refreshRuns = useCallback(async () => {
    setRunsLoading(true);
    setRunsError(null);
    try {
      const runs = await api.listRuns();
      const sorted = [...runs].sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
      setAvailableRuns(sorted);
      setSolverSpecDraft((prev) => {
        if (prev.sourceRunId) return prev;
        const defaultRun = sorted.find((r) => r.status === "completed");
        return {
          ...prev,
          sourceRunId: defaultRun?.run_id ?? null,
          sourceScenarioName: defaultRun?.scenario_names?.[0] ?? null,
        };
      });
    } catch (error) {
      setRunsError(error instanceof Error ? error.message : String(error));
    } finally {
      setRunsLoading(false);
    }
  }, []);

  const handleWorkspaceChange = useCallback((ws: any) => {
    setWorkspace(ws);
    applyDynamicColors(ws);
    try {
      const ir = generateDealIR(ws);
      setIrJson(JSON.stringify(ir, null, 2));
      setErrors([]);
      if (ir?.deal_name && typeof ir.deal_name === "string") {
        setDealName((prev) => (prev === "Deal" ? ir.deal_name : prev));
      }
    } catch (e: any) {
      setErrors([e.message || "Error generating IR"]);
    }
  }, []);

  const handleSaveDeal = useCallback(async () => {
    if (errors.length > 0 || !irJson.trim()) {
      toast.error("Fix workspace errors or add pay rules before saving.");
      return;
    }
    let ir: Record<string, unknown>;
    let solverSpec: Record<string, unknown>;
    try {
      ir = JSON.parse(irJson) as Record<string, unknown>;
      solverSpec = JSON.parse(advancedJson.jsonText || "{}");
      setAdvancedJson((prev) => ({
        ...prev,
        parseError: null,
        lastSyncedAt: new Date().toISOString(),
      }));
    } catch (error) {
      const parseError = error instanceof Error ? error.message : String(error);
      setAdvancedJson((prev) => ({ ...prev, parseError }));
      toast.error("Solver spec JSON is invalid.");
      return;
    }
    ir.deal_name = dealName.trim() || "Deal";
    ir.solver_presets = {
      source_mode: solverSpecDraft.sourceMode,
      runsetup_ref_run_id: solverSpecDraft.sourceRunId,
      scenario_set: scenarioNames,
      source_scenario_name: solverSpecDraft.sourceScenarioName,
      sensitivity_sweep: sensitivitySweepConfig,
      solver_spec: solverSpec,
    };
    setSaveBusy(true);
    try {
      const res = await api.saveStudioDeal({
        deal_id: savedDealId,
        deal_name: dealName.trim() || "Deal",
        ir,
      });
      setSavedDealId(res.deal_id);
      toast.success(`Saved ${res.deal_name} as ${res.deal_id} (v${res.version})`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaveBusy(false);
    }
  }, [
    errors.length,
    irJson,
    advancedJson.jsonText,
    dealName,
    savedDealId,
    solverSpecDraft.sourceMode,
    solverSpecDraft.sourceRunId,
    solverSpecDraft.sourceScenarioName,
    scenarioNames,
    sensitivitySweepConfig,
  ]);

  const handleRunDeal = useCallback(async () => {
    if (!savedDealId) {
      toast.error("Save the deal first before running.");
      return;
    }
    setRunBusy(true);
    try {
      const source =
        solverSpecDraft.sourceMode === "runsetup_ref"
          ? {
              source_mode: "runsetup_ref" as const,
              run_id: solverSpecDraft.sourceRunId ?? "",
              scenario_names: scenarioNames,
            }
          : {
              source_mode: "deal_native" as const,
              scenario_name: solverSpecDraft.sourceScenarioName ?? scenarioNames[0] ?? "Base Case",
              run_input: JSON.parse(solverSpecDraft.nativeRunInputJson || "{}"),
            };
      if (solverSpecDraft.sourceMode === "runsetup_ref" && !solverSpecDraft.sourceRunId) {
        throw new Error("Run Setup ref mode requires selecting a base CF run.");
      }
      const res = await api.runDeal(savedDealId, {
        source,
        scenario_names: scenarioNames,
      });
      toast.success(`Deal run created: ${res.run_id ?? savedDealId}`);
      refreshRuns();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setRunBusy(false);
    }
  }, [
    savedDealId,
    solverSpecDraft.sourceMode,
    solverSpecDraft.sourceRunId,
    solverSpecDraft.sourceScenarioName,
    solverSpecDraft.nativeRunInputJson,
    scenarioNames,
    refreshRuns,
  ]);

  const handleSolveDeal = useCallback(async () => {
    if (!savedDealId) {
      toast.error("Save the deal first before solving.");
      return;
    }
    setSolveBusy(true);
    if (progressPollRef.current != null) {
      window.clearInterval(progressPollRef.current);
      progressPollRef.current = null;
    }
    setTelemetryState({
      status: "running",
      stage: "Submitting solve request",
      iteration: 0,
      objectiveTrajectory: [],
      cancelToken: savedDealId,
      runId: null,
    });
    try {
      const source =
        solverSpecDraft.sourceMode === "runsetup_ref"
          ? {
              source_mode: "runsetup_ref" as const,
              run_id: solverSpecDraft.sourceRunId ?? "",
              scenario_names: scenarioNames,
            }
          : {
              source_mode: "deal_native" as const,
              scenario_name: solverSpecDraft.sourceScenarioName ?? scenarioNames[0] ?? "Base Case",
              run_input: JSON.parse(solverSpecDraft.nativeRunInputJson || "{}"),
            };
      if (solverSpecDraft.sourceMode === "runsetup_ref" && !solverSpecDraft.sourceRunId) {
        throw new Error("Run Setup ref mode requires selecting a base CF run.");
      }
      const solverSpec = JSON.parse(advancedJson.jsonText || "{}");
      const scenarioName = solverSpecDraft.sourceScenarioName ?? scenarioNames[0] ?? "Base Case";
      const res = await api.solveDeal(savedDealId, {
        source,
        scenario_name: scenarioName,
        solver_spec: solverSpec,
      });
      const runId = res.run_id ?? null;
      setTelemetryState((prev) => ({
        ...prev,
        status: "running",
        stage: "Solver running",
        runId,
      }));
      if (runId) {
        progressPollRef.current = window.setInterval(async () => {
          try {
            const progress = await api.getDealSolverProgress(savedDealId, runId);
            setTelemetryState((prev) => ({
              ...prev,
              status: (progress.status as TelemetryState["status"]) ?? prev.status,
              stage: progress.stage ?? prev.stage,
              iteration: progress.iteration ?? prev.iteration,
              runId,
            }));
            if (
              progress.status === "completed"
              || progress.status === "failed"
              || progress.status === "cancelled"
            ) {
              if (progressPollRef.current != null) {
                window.clearInterval(progressPollRef.current);
                progressPollRef.current = null;
              }
              setSolveBusy(false);
              refreshRuns();
              toast.success(`Solver run ${progress.status}: ${runId}`);
            }
          } catch (error) {
            if (progressPollRef.current != null) {
              window.clearInterval(progressPollRef.current);
              progressPollRef.current = null;
            }
            setSolveBusy(false);
            setTelemetryState((prev) => ({
              ...prev,
              status: "failed",
              stage: error instanceof Error ? error.message : String(error),
            }));
          }
        }, 1000);
      } else {
        setSolveBusy(false);
      }
      toast.success(`Solver run started: ${runId ?? savedDealId}`);
    } catch (e: unknown) {
      setTelemetryState((prev) => ({
        ...prev,
        status: "failed",
        stage: "Solve failed",
      }));
      setSolveBusy(false);
      toast.error(e instanceof Error ? e.message : String(e));
    }
  }, [
    savedDealId,
    solverSpecDraft.sourceMode,
    solverSpecDraft.sourceRunId,
    solverSpecDraft.sourceScenarioName,
    solverSpecDraft.nativeRunInputJson,
    scenarioNames,
    advancedJson.jsonText,
    refreshRuns,
  ]);

  const handleCancelSolve = useCallback(async () => {
    if (!savedDealId || !telemetryState.runId) return;
    try {
      await api.cancelDealSolverRun(savedDealId, telemetryState.runId);
      setTelemetryState((prev) => ({
        ...prev,
        status: "cancelled",
        stage: "Cancellation requested",
      }));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
  }, [savedDealId, telemetryState.runId]);

  useEffect(() => {
    setAdvancedJson((prev) => {
      if (prev.lastSyncedAt) return prev;
      return { ...prev, jsonText: solverSpecDraftToCanonicalJson(solverSpecDraft) };
    });
  }, [solverSpecDraft]);

  useEffect(() => {
    refreshRuns();
  }, [refreshRuns]);

  useEffect(() => {
    if (!initialSourceRunId) return;
    setSolverSpecDraft((prev) => ({
      ...prev,
      sourceMode: "runsetup_ref",
      sourceRunId: prev.sourceRunId ?? initialSourceRunId,
    }));
  }, [initialSourceRunId]);

  useEffect(() => {
    const onColMove = (e: MouseEvent) => {
      const d = colDragRef.current;
      if (!d) return;
      const dx = e.clientX - d.startX;
      setSidebarWidth(Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, d.startW - dx)));
    };
    const onColUp = () => {
      colDragRef.current = null;
      document.body.style.removeProperty("cursor");
      document.body.style.removeProperty("user-select");
    };
    const onRowMove = (e: MouseEvent) => {
      const d = rowDragRef.current;
      if (!d || d.height <= 0) return;
      const dy = e.clientY - d.startY;
      const deltaPct = (dy / d.height) * 100;
      const next = d.startPct + deltaPct;
      setPropertiesPct(Math.min(PROPERTIES_PCT_MAX, Math.max(PROPERTIES_PCT_MIN, next)));
    };
    const onRowUp = () => {
      rowDragRef.current = null;
      document.body.style.removeProperty("cursor");
      document.body.style.removeProperty("user-select");
    };

    window.addEventListener("mousemove", onColMove);
    window.addEventListener("mouseup", onColUp);
    window.addEventListener("mousemove", onRowMove);
    window.addEventListener("mouseup", onRowUp);
    return () => {
      window.removeEventListener("mousemove", onColMove);
      window.removeEventListener("mouseup", onColUp);
      window.removeEventListener("mousemove", onRowMove);
      window.removeEventListener("mouseup", onRowUp);
    };
  }, []);

  useEffect(() => {
    return () => {
      if (progressPollRef.current != null) {
        window.clearInterval(progressPollRef.current);
      }
    };
  }, []);

  const onColumnResizeStart = (e: React.MouseEvent) => {
    e.preventDefault();
    colDragRef.current = { startX: e.clientX, startW: sidebarWidth };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  const onRowResizeStart = (e: React.MouseEvent) => {
    e.preventDefault();
    const h = rightColRef.current?.getBoundingClientRect().height ?? 0;
    rowDragRef.current = { startY: e.clientY, startPct: propertiesPct, height: h };
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="flex shrink-0 flex-wrap items-center gap-2 px-1">
        <input
          type="text"
          value={dealName}
          onChange={(e) => setDealName(e.target.value)}
          placeholder="Deal name"
          className="min-w-[8rem] max-w-[16rem] flex-1 px-2 py-1 rounded border border-border bg-input-background text-xs text-foreground"
          style={MONO}
          aria-label="Deal name"
        />
        <button
          type="button"
          onClick={handleSaveDeal}
          disabled={saveBusy || errors.length > 0 || !irJson.trim()}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded border border-primary/30 bg-primary/10 text-primary text-xs font-medium hover:bg-primary/20 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Save className="w-3.5 h-3.5" />
          {saveBusy ? "Saving..." : "Save deal"}
        </button>
        {savedDealId && (
          <span className="text-[10px] text-muted-foreground" style={MONO}>
            {savedDealId}
          </span>
        )}
      </div>

      <TabBar
        tabs={[
          { id: "design", label: "Design", icon: LayoutDashboard },
          { id: "solver", label: "Solver", icon: Sigma },
          { id: "ir", label: "IR", icon: Code2 },
        ]}
        active={studioTab}
        onSelect={(id) => setStudioTab(id as StudioTab)}
      />

      {studioTab === "solver" && (
        <SolverStudioPanel
          savedDealId={savedDealId}
          runBusy={runBusy}
          solveBusy={solveBusy}
          availableRuns={availableRuns}
          runsLoading={runsLoading}
          runsError={runsError}
          refreshRuns={refreshRuns}
          solverSpecDraft={solverSpecDraft}
          setSolverSpecDraft={setSolverSpecDraft}
          advancedJson={advancedJson}
          setAdvancedJson={setAdvancedJson}
          telemetryState={telemetryState}
          setTelemetryState={setTelemetryState}
          sensitivitySweepConfig={sensitivitySweepConfig}
          setSensitivitySweepConfig={setSensitivitySweepConfig}
          onRunDeal={handleRunDeal}
          onSolveDeal={handleSolveDeal}
          onCancelSolve={handleCancelSolve}
          irJson={irJson}
          irErrors={errors}
        />
      )}

      {studioTab === "ir" && (
        <div className="flex-1 min-h-0 px-1">
          <pre
            className="h-full min-h-[200px] overflow-auto rounded-md border border-border bg-[#0d1220] px-3 py-2 text-[11px] leading-relaxed text-secondary-foreground"
            style={MONO}
          >
            {errors.length > 0
              ? errors.map((e, i) => (
                  <div key={i} className="text-destructive">
                    {e}
                  </div>
                ))
              : irJson || "// Build the waterfall to see IR"}
          </pre>
        </div>
      )}

      {studioTab === "design" && (
        <div className="flex min-h-0 flex-1 gap-0">
          <BlocklyCanvas onChange={handleWorkspaceChange} />
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize sidebar"
            onMouseDown={onColumnResizeStart}
            className="group relative w-2 shrink-0 cursor-col-resize flex items-center justify-center hover:bg-primary/15"
          >
            <div className="absolute inset-y-2 w-px bg-border group-hover:bg-primary/50" />
            <GripVertical className="w-3 h-3 text-muted-foreground/60 group-hover:text-muted-foreground relative z-[1]" />
          </div>
          <div
            ref={rightColRef}
            style={{ width: sidebarWidth }}
            className="flex h-full min-h-0 min-w-0 shrink-0 flex-col"
          >
            <div
              className={
                showDesignIr
                  ? "flex flex-col min-h-0 overflow-hidden rounded-md border border-border bg-[#0d1220]"
                  : "flex flex-1 flex-col min-h-0 overflow-hidden rounded-md border border-border bg-[#0d1220]"
              }
              style={showDesignIr ? { height: `${propertiesPct}%`, minHeight: 120 } : undefined}
            >
              <div className="shrink-0 flex items-center gap-1.5 px-3 pt-3 pb-2 border-b border-border/60">
                <Settings2 className="w-3.5 h-3.5 text-muted-foreground" />
                <span className="text-xs font-medium text-foreground">Properties</span>
              </div>
              <div className="flex-1 min-h-0 overflow-auto p-3 pt-2">
                <PropertyPanel workspace={workspace} />
              </div>
            </div>

            {showDesignIr && (
              <div
                role="separator"
                aria-orientation="horizontal"
                aria-label="Resize Properties and Deal IR"
                onMouseDown={onRowResizeStart}
                className="group relative h-2 shrink-0 cursor-row-resize flex items-center justify-center hover:bg-primary/15"
              >
                <div className="absolute inset-x-2 h-px bg-border group-hover:bg-primary/50" />
                <GripVertical className="w-3 h-3 text-muted-foreground/60 group-hover:text-muted-foreground rotate-90 relative z-[1]" />
              </div>
            )}

            <div
              className={
                showDesignIr
                  ? "flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border border-border bg-[#0d1220]"
                  : "shrink-0 rounded-md border border-border bg-[#0d1220]"
              }
            >
              <button
                type="button"
                onClick={() => setShowDesignIr(!showDesignIr)}
                className="w-full flex items-center gap-1.5 px-3 py-2 text-xs text-muted-foreground hover:text-foreground transition-colors shrink-0"
              >
                {showDesignIr ? (
                  <ChevronDown className="w-3 h-3" />
                ) : (
                  <ChevronRight className="w-3 h-3" />
                )}
                <Code2 className="w-3 h-3" />
                <span>Deal IR</span>
                {errors.length > 0 && (
                  <span className="ml-auto text-destructive text-[10px]">error</span>
                )}
              </button>
              {showDesignIr && (
                <pre
                  className="flex-1 min-h-[120px] overflow-auto px-3 pb-2 text-[10px] leading-relaxed text-secondary-foreground border-t border-border"
                  style={MONO}
                >
                  {errors.length > 0
                    ? errors.map((e, i) => (
                        <div key={i} className="text-destructive">
                          {e}
                        </div>
                      ))
                    : irJson || "// Build the waterfall to see IR"}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
