/**
 * DealEditor — composition root for Structuring + Solver Studio.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Code2,
  GripVertical,
  LayoutDashboard,
  Save,
  Settings2,
  Sigma,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import BlocklyCanvas from "./BlocklyCanvas";
import PropertyPanel from "./PropertyPanel";
import { generateDealIR } from "./irGenerator";
import { applyDynamicColors } from "./blockColors";
import { fmtNamedId, MONO } from "../../lib/format";
import * as api from "../../services/api";
import FormSelect from "../../components/FormSelect";
import TabBar from "../../components/TabBar";
import SolverStudioPanel from "./solver/SolverStudioPanel";
import SolverTemplateCards from "./solver/templates/SolverTemplateCards";
import { synthesizeWorkspaceState } from "./irToBlocklyState";
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
import type { CollateralRiskSettings } from "./shared/riskSettings";
import { getDefaultCollateralRiskSettings, validateCollateralRiskSettings } from "./shared/riskSettings";
import {
  computePsaScheduleStale,
  mergeScheduleOverlay,
  type ScheduleOverlay,
} from "./scheduleOverlayMerge";

const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 640;

type StudioTab = "design" | "solver" | "ir";
const STUDIO_DRAFT_STORAGE_KEY = "bma_structuring_studio_draft_v1";

interface StudioDraftState {
  studioTab: StudioTab;
  dealName: string;
  savedDealId: string | null;
  irJson: string;
  solverSpecDraft: SolverSpecDraft;
  advancedJson: AdvancedJsonState;
  sensitivitySweepConfig: SensitivitySweepConfig;
  collateralRiskSettings: CollateralRiskSettings;
  workspaceState: unknown | null;
}

function parseScenarioSet(text: string): string[] {
  const names = text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return names.length ? names : ["Base Case"];
}

function toCollateralRiskSettings(value: unknown): CollateralRiskSettings {
  const fallback = getDefaultCollateralRiskSettings();
  if (!value || typeof value !== "object") return fallback;
  const source = value as Record<string, unknown>;
  const merged: CollateralRiskSettings = {
    ...fallback,
    ...source,
    newRiskParams: {
      ...fallback.newRiskParams,
      ...((source.newRiskParams as Record<string, unknown> | undefined) ?? {}),
    },
    rateScenario: {
      ...fallback.rateScenario,
      ...((source.rateScenario as Record<string, unknown> | undefined) ?? {}),
    },
    execution: {
      ...fallback.execution,
      ...((source.execution as Record<string, unknown> | undefined) ?? {}),
    },
    validation: {
      ...fallback.validation,
      ...((source.validation as Record<string, unknown> | undefined) ?? {}),
    },
  };
  merged.validation = validateCollateralRiskSettings(merged);
  return merged;
}

interface DealEditorProps {
  initialSourceRunId?: string | null;
  collateralRiskSettings: CollateralRiskSettings;
  onCollateralRiskSettingsChange: (next: CollateralRiskSettings) => void;
  onOpenTape?: (uploadId: string, mappingId: string) => Promise<void> | void;
  onDirtyStateChange?: (dirty: boolean) => void;
}

export default function DealEditor({
  initialSourceRunId = null,
  collateralRiskSettings,
  onCollateralRiskSettingsChange,
  onOpenTape,
  onDirtyStateChange,
}: DealEditorProps) {
  const [studioTab, setStudioTab] = useState<StudioTab>("design");
  const [irJson, setIrJson] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [workspace, setWorkspace] = useState<any>(null);
  const [sidebarWidth, setSidebarWidth] = useState(288);
  const [dealName, setDealName] = useState("Deal");
  const [savedDealId, setSavedDealId] = useState<string | null>(null);
  const [saveBusy, setSaveBusy] = useState(false);
  const [runBusy, setRunBusy] = useState(false);
  const [solveBusy, setSolveBusy] = useState(false);
  // Live carry tie-out status, lifted up from PropertyPanel. Drives
  // the warn/block gate on Run/Solve actions per Phase 5 of the
  // engine_completeness_and_carry_tieout plan.
  const [carryStatus, setCarryStatus] = useState<{
    status: "OK" | "WARN" | "BLOCK" | null;
    reason: string;
  }>({ status: null, reason: "" });
  const [carryBlockOverridden, setCarryBlockOverridden] = useState(false);
  const handleCarryStatusChange = useCallback(
    (status: "OK" | "WARN" | "BLOCK" | null, reason: string) => {
      setCarryStatus({ status, reason });
      // Reset override whenever status improves so a freshly-OK deal
      // doesn't carry a stale acknowledgement forward.
      if (status !== "BLOCK") {
        setCarryBlockOverridden(false);
      }
    },
    [],
  );
  const [availableRuns, setAvailableRuns] = useState<api.RunListItem[]>([]);
  const [uploadLibrary, setUploadLibrary] = useState<api.UploadLibraryItem[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [studioDeals, setStudioDeals] = useState<api.StudioDealSummary[]>([]);
  const [poolSnapshots, setPoolSnapshots] = useState<api.PoolSnapshotSummary[]>([]);
  const [selectedStudioDealId, setSelectedStudioDealId] = useState<string>("");
  const [selectedStudioVersion, setSelectedStudioVersion] = useState<string>("");
  const [activeDealVersion, setActiveDealVersion] = useState<number | null>(null);
  const [pendingWorkspaceState, setPendingWorkspaceState] = useState<unknown | null>(null);
  const [lastSavedFingerprint, setLastSavedFingerprint] = useState<string>("");
  const [pendingCleanMark, setPendingCleanMark] = useState(false);
  const [verificationState, setVerificationState] = useState<api.StructuringVerificationResult | null>(null);
  /** Phase 1i: server-derived PAC/TAC PSA schedules merged into Blockly IR. */
  const [scheduleOverlay, setScheduleOverlay] = useState<ScheduleOverlay | null>(null);
  const scheduleOverlayRef = useRef<ScheduleOverlay | null>(null);
  scheduleOverlayRef.current = scheduleOverlay;
  const [poolDerivationCtx, setPoolDerivationCtx] = useState<api.DerivePsaSchedulesPoolBody | null>(null);
  const [scheduleDeriveBusy, setScheduleDeriveBusy] = useState(false);

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
  const designSplitRef = useRef<HTMLDivElement>(null);
  const colDragRef = useRef<{ startX: number; startW: number } | null>(null);
  const progressPollRef = useRef<number | null>(null);
  const userResizedSidebarRef = useRef(false);
  const scenarioNames = useMemo(
    () => parseScenarioSet(solverSpecDraft.scenarioSetText),
    [solverSpecDraft.scenarioSetText],
  );
  const hasPsaStructuringBonds = useMemo(() => {
    try {
      const ir = JSON.parse(irJson || "{}") as {
        bonds?: Array<{ kind?: string; schedule_model_type?: string }>;
      };
      return (
        ir.bonds?.some(
          (b) =>
            (b.kind === "PAC" || b.kind === "TAC")
            && b.schedule_model_type === "PSA",
        ) ?? false
      );
    } catch {
      return false;
    }
  }, [irJson]);
  const psaScheduleStaleInfo = useMemo(
    () => computePsaScheduleStale(irJson, poolDerivationCtx),
    [irJson, poolDerivationCtx],
  );

  const handlePoolDerivationContextChange = useCallback((ctx: api.DerivePsaSchedulesPoolBody | null) => {
    setPoolDerivationCtx(ctx);
  }, []);

  const runPsaScheduleDerivation = useCallback(async (opts?: { silent?: boolean }) => {
    if (!poolDerivationCtx || errors.length > 0 || !irJson.trim()) {
      if (!opts?.silent) {
        toast.error("Need valid IR, collateral pool stats, and no Blockly errors to derive schedules.");
      }
      return;
    }
    setScheduleDeriveBusy(true);
    try {
      const ir = JSON.parse(irJson) as Record<string, unknown>;
      const res = await api.derivePsaSchedules({ ir, pool: poolDerivationCtx });
      setScheduleOverlay(res.overlay as ScheduleOverlay);
      const n = res.derived_bond_names.length;
      if (!opts?.silent) {
        toast.success(n ? `Updated PSA schedules for ${n} tranche(s).` : "No PSA-mode PAC/TAC bonds to derive.");
      }
    } catch (e: unknown) {
      if (!opts?.silent) {
        toast.error(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setScheduleDeriveBusy(false);
    }
  }, [poolDerivationCtx, errors.length, irJson]);

  const psaAutoDeriveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (studioTab !== "design") return;
    if (errors.length > 0 || !poolDerivationCtx || !hasPsaStructuringBonds) return;
    const { stale } = computePsaScheduleStale(irJson, poolDerivationCtx);
    if (!stale) return;
    if (psaAutoDeriveTimerRef.current) clearTimeout(psaAutoDeriveTimerRef.current);
    psaAutoDeriveTimerRef.current = setTimeout(() => {
      psaAutoDeriveTimerRef.current = null;
      void runPsaScheduleDerivation({ silent: true });
    }, 800);
    return () => {
      if (psaAutoDeriveTimerRef.current) clearTimeout(psaAutoDeriveTimerRef.current);
    };
  }, [
    studioTab,
    errors.length,
    poolDerivationCtx,
    hasPsaStructuringBonds,
    irJson,
    runPsaScheduleDerivation,
  ]);
  const selectedStudioDealSummary = useMemo(
    () => studioDeals.find((deal) => deal.deal_id === selectedStudioDealId) ?? null,
    [studioDeals, selectedStudioDealId],
  );
  const newerPoolVersion = useMemo(() => {
    if (!collateralRiskSettings.poolId || collateralRiskSettings.poolVersion == null) return null;
    const summary = poolSnapshots.find((pool) => pool.pool_id === collateralRiskSettings.poolId);
    if (!summary || summary.current_version <= collateralRiskSettings.poolVersion) return null;
    return summary.current_version;
  }, [collateralRiskSettings.poolId, collateralRiskSettings.poolVersion, poolSnapshots]);
  const currentDraftFingerprint = useMemo(
    () =>
      JSON.stringify({
        studioTab,
        dealName,
        irJson,
        solverSpecDraft,
        advancedJson: advancedJson.jsonText,
        sensitivitySweepConfig,
        collateralRiskSettings,
      }),
    [
      studioTab,
      dealName,
      irJson,
      solverSpecDraft,
      advancedJson.jsonText,
      sensitivitySweepConfig,
      collateralRiskSettings,
    ],
  );
  const isDirty = useMemo(
    () => Boolean(lastSavedFingerprint) && currentDraftFingerprint !== lastSavedFingerprint,
    [currentDraftFingerprint, lastSavedFingerprint],
  );

  const serializeWorkspaceState = useCallback(async (): Promise<unknown | null> => {
    if (!workspace) return null;
    try {
      const Blockly = await import("blockly");
      return Blockly.serialization.workspaces.save(workspace);
    } catch {
      return null;
    }
  }, [workspace]);

  const restoreWorkspaceState = useCallback(
    async (workspaceState: unknown | null) => {
      if (!workspace || !workspaceState) return;
      try {
        const Blockly = await import("blockly");
        workspace.clear();
        Blockly.serialization.workspaces.load(workspaceState as any, workspace);
        // Keep reload behavior predictable: always center the viewport after restore.
        workspace.scrollCenter();
      } catch (error) {
        toast.error(
          error instanceof Error
            ? `Unable to restore workspace: ${error.message}`
            : "Unable to restore workspace from saved snapshot.",
        );
      }
    },
    [workspace],
  );

  const refreshRuns = useCallback(async () => {
    setRunsLoading(true);
    setRunsError(null);
    try {
      // Deal sourcing should only reference collateral engine (portfolio) runs.
      const runs = await api.listRuns("portfolio");
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

  const refreshStudioDeals = useCallback(async () => {
    try {
      const deals = await api.listStudioDeals();
      setStudioDeals(deals);
      setSelectedStudioDealId((prev) => prev || deals[0]?.deal_id || "");
    } catch {
      setStudioDeals([]);
    }
  }, []);

  const refreshUploadLibrary = useCallback(async () => {
    try {
      const res = await api.listUploads();
      setUploadLibrary(res.items);
    } catch {
      setUploadLibrary([]);
    }
  }, []);

  const refreshPoolSnapshots = useCallback(async () => {
    try {
      const result = await api.listPoolSnapshots();
      setPoolSnapshots(result.items);
    } catch {
      setPoolSnapshots([]);
    }
  }, []);

  const recomputeIrFromWorkspace = useCallback((ws: any) => {
    if (!ws) return;
    applyDynamicColors(ws);
    try {
      let ir: Record<string, unknown> = generateDealIR(ws) as unknown as Record<string, unknown>;
      ir = mergeScheduleOverlay(ir, scheduleOverlayRef.current) as Record<string, unknown>;
      setIrJson(JSON.stringify(ir, null, 2));
      setErrors([]);
      if (ir?.deal_name && typeof ir.deal_name === "string") {
        setDealName((prev) => (prev === "Deal" ? (ir.deal_name as string) : prev));
      }
    } catch (e: any) {
      setErrors([e.message || "Error generating IR"]);
    }
  }, []);

  const handleWorkspaceChange = useCallback((ws: any) => {
    setWorkspace(ws);
    recomputeIrFromWorkspace(ws);
  }, [recomputeIrFromWorkspace]);

  useEffect(() => {
    if (workspace) recomputeIrFromWorkspace(workspace);
  }, [scheduleOverlay, recomputeIrFromWorkspace]);

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
    const workspaceState = await serializeWorkspaceState();
    ir.solver_presets = {
      source_mode: solverSpecDraft.sourceMode,
      runsetup_ref_run_id: solverSpecDraft.sourceRunId,
      scenario_set: scenarioNames,
      source_scenario_name: solverSpecDraft.sourceScenarioName,
      collateral_risk_settings: collateralRiskSettings,
      sensitivity_sweep: sensitivitySweepConfig,
      solver_spec: solverSpec,
    };
    ir.studio_workspace_state = workspaceState;
    setSaveBusy(true);
    try {
      const res = await api.saveStudioDeal({
        deal_id: savedDealId,
        deal_name: dealName.trim() || "Deal",
        ir,
      });
      setSavedDealId(res.deal_id);
      setSelectedStudioDealId(res.deal_id);
      setSelectedStudioVersion(String(res.version));
      setActiveDealVersion(res.version);
      setPendingCleanMark(true);
      refreshStudioDeals();
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
    collateralRiskSettings,
    serializeWorkspaceState,
    refreshStudioDeals,
  ]);

  const handleLoadStudioDeal = useCallback(async () => {
    if (!selectedStudioDealId) return;
    if (isDirty && !window.confirm("You have unsaved changes. Open another deal anyway?")) {
      return;
    }
    try {
      const snapshot = await api.getStudioDeal(
        selectedStudioDealId,
        selectedStudioVersion ? Number(selectedStudioVersion) : undefined,
      );
      setSavedDealId(snapshot.deal_id);
      setActiveDealVersion(selectedStudioVersion ? Number(selectedStudioVersion) : null);
      setDealName(snapshot.deal_name || "Deal");
      setIrJson(JSON.stringify(snapshot.ir ?? {}, null, 2));
      setErrors([]);
      const presets = (snapshot.ir?.solver_presets ?? {}) as Record<string, unknown>;
      setSolverSpecDraft((prev) => ({
        ...prev,
        sourceMode:
          presets.source_mode === "deal_native" || presets.source_mode === "runsetup_ref"
            ? (presets.source_mode as "deal_native" | "runsetup_ref")
            : prev.sourceMode,
        sourceRunId: typeof presets.runsetup_ref_run_id === "string" ? presets.runsetup_ref_run_id : null,
        sourceScenarioName:
          typeof presets.source_scenario_name === "string" ? presets.source_scenario_name : null,
        scenarioSetText: Array.isArray(presets.scenario_set)
          ? (presets.scenario_set as string[]).join(", ")
          : prev.scenarioSetText,
      }));
      if (presets.solver_spec) {
        setAdvancedJson({
          jsonText: JSON.stringify(presets.solver_spec, null, 2),
          parseError: null,
          lastSyncedAt: new Date().toISOString(),
        });
      }
      const maybeSweep = presets.sensitivity_sweep as SensitivitySweepConfig | undefined;
      if (maybeSweep?.primary) {
        setSensitivitySweepConfig(maybeSweep);
      }
      const maybeRisk = (presets.collateral_risk_settings ??
        presets.pool_assignment) as unknown;
      if (maybeRisk) {
        onCollateralRiskSettingsChange(toCollateralRiskSettings(maybeRisk));
      }
      const workspaceState = (snapshot.ir?.studio_workspace_state as unknown) ?? null;
      if (workspaceState) {
        setPendingWorkspaceState(workspaceState);
        toast.success(`Loaded ${snapshot.deal_name} (${snapshot.deal_id})`);
      } else {
        // Deal has no saved Blockly layout (e.g., seeded via a Python
        // script). Synthesize a layout from the IR so the canvas
        // populates and the user can run/solve/edit. The synthesizer
        // only handles the common rule types (PAY_FEE, PAY_INTEREST,
        // PAY_PRINCIPAL, SPLIT_CASH, trigger wrappers); deals with
        // PAC/TAC/Z schedule rules will get a partial layout (the
        // simpler rules render; schedule-driven rules are skipped
        // until the synthesizer is extended).
        const synthesized = synthesizeWorkspaceState(snapshot.ir ?? {});
        if (workspace) {
          try {
            workspace.clear();
          } catch {
            // Defensive: a stale Blockly workspace can throw on clear
            // during navigation. Non-fatal.
          }
        }
        setPendingWorkspaceState(synthesized);
        if (synthesized) {
          toast.success(
            `Loaded ${snapshot.deal_name} — synthesized blocks from IR. ` +
              `Adjust + save to lock the layout.`,
          );
        } else {
          toast.info(
            `Loaded ${snapshot.deal_name} — IR has no synthesizable rules yet. ` +
              `Use the IR tab to inspect.`,
          );
        }
      }
      setPendingCleanMark(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
  }, [
    isDirty,
    selectedStudioDealId,
    selectedStudioVersion,
    onCollateralRiskSettingsChange,
    workspace,
  ]);

  const persistDealForExecution = useCallback(async (): Promise<{
    dealId: string;
    dealVersion: number | undefined;
  }> => {
    if (savedDealId && !isDirty) {
      return {
        dealId: savedDealId,
        dealVersion: activeDealVersion ?? undefined,
      };
    }
    if (errors.length > 0 || !irJson.trim()) {
      throw new Error("Fix workspace errors or add pay rules before running.");
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
      throw new Error("Solver spec JSON is invalid.");
    }

    ir.deal_name = dealName.trim() || "Deal";
    const workspaceState = await serializeWorkspaceState();
    ir.solver_presets = {
      source_mode: solverSpecDraft.sourceMode,
      runsetup_ref_run_id: solverSpecDraft.sourceRunId,
      scenario_set: scenarioNames,
      source_scenario_name: solverSpecDraft.sourceScenarioName,
      collateral_risk_settings: collateralRiskSettings,
      sensitivity_sweep: sensitivitySweepConfig,
      solver_spec: solverSpec,
    };
    ir.studio_workspace_state = workspaceState;

    const saved = await api.saveStudioDeal({
      deal_id: savedDealId,
      deal_name: dealName.trim() || "Deal",
      ir,
    });
    setSavedDealId(saved.deal_id);
    setSelectedStudioDealId(saved.deal_id);
    setSelectedStudioVersion(String(saved.version));
    setActiveDealVersion(saved.version);
    setPendingCleanMark(true);
    refreshStudioDeals();
    toast.success(`Auto-saved structure before run (${saved.deal_id} v${saved.version})`);
    return {
      dealId: saved.deal_id,
      dealVersion: saved.version,
    };
  }, [
    savedDealId,
    isDirty,
    activeDealVersion,
    errors.length,
    irJson,
    advancedJson.jsonText,
    dealName,
    serializeWorkspaceState,
    solverSpecDraft.sourceMode,
    solverSpecDraft.sourceRunId,
    solverSpecDraft.sourceScenarioName,
    scenarioNames,
    collateralRiskSettings,
    sensitivitySweepConfig,
    refreshStudioDeals,
  ]);

  const verifyStructure = useCallback(
    async (dealId: string, dealVersion?: number) => {
      const verification = await api.verifyDealStructure(dealId, dealVersion ?? null);
      setVerificationState(verification);
      return verification;
    },
    [],
  );

  /**
   * Carry tie-out gate: blocks Run/Solve on BLOCK status until the
   * user explicitly acknowledges. Returns true when the action may
   * proceed, false to abort.
   *
   * The gate is intentionally lightweight (a confirm dialog, not a
   * modal flow) per the design doc: "the user must either edit the
   * structure or click an explicit 'Override and run anyway' action".
   * After acknowledgement, we set `carryBlockOverridden` so subsequent
   * runs in the same edit session don't re-prompt unless the status
   * changes.
   */
  const passCarryTieOutGate = useCallback(
    (actionLabel: string): boolean => {
      if (carryStatus.status !== "BLOCK") return true;
      if (carryBlockOverridden) return true;
      const ok = window.confirm(
        `Carry tie-out blocked: ${carryStatus.reason}\n\n` +
          `${actionLabel} anyway?\n\n` +
          `Tip: open the "Balance the deal" solver template under ` +
          `the Solver tab to find coupons that satisfy the tie-out automatically.`,
      );
      if (ok) {
        setCarryBlockOverridden(true);
      }
      return ok;
    },
    [carryStatus, carryBlockOverridden],
  );

  const handleRunDeal = useCallback(async () => {
    if (!passCarryTieOutGate("Run cashflows")) return;
    setRunBusy(true);
    try {
      const { dealId, dealVersion } = await persistDealForExecution();
      const verification = await verifyStructure(dealId, dealVersion);
      if (!verification.valid) {
        throw new Error(
          `Structuring verification failed: ${verification.errors[0] ?? "Resolve compatibility errors."}`,
        );
      }
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
      const res = await api.runDeal(dealId, {
        deal_version: dealVersion,
        source,
        scenario_names: scenarioNames,
      });
      toast.success(`Deal run created: ${res.run_id ?? dealId}`);
      refreshRuns();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setRunBusy(false);
    }
  }, [
    passCarryTieOutGate,
    persistDealForExecution,
    verifyStructure,
    solverSpecDraft.sourceMode,
    solverSpecDraft.sourceRunId,
    solverSpecDraft.sourceScenarioName,
    solverSpecDraft.nativeRunInputJson,
    scenarioNames,
    refreshRuns,
  ]);


  const handleSolveDeal = useCallback(async () => {
    if (!passCarryTieOutGate("Solve")) return;
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
      const { dealId, dealVersion } = await persistDealForExecution();
      const verification = await verifyStructure(dealId, dealVersion);
      if (!verification.valid) {
        throw new Error(
          `Structuring verification failed: ${verification.errors[0] ?? "Resolve compatibility errors."}`,
        );
      }
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
      const res = await api.solveDeal(dealId, {
        deal_version: dealVersion,
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
            const progress = await api.getDealSolverProgress(dealId, runId);
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
      toast.success(`Solver run started: ${runId ?? dealId}`);
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
    passCarryTieOutGate,
    persistDealForExecution,
    verifyStructure,
    solverSpecDraft.sourceMode,
    solverSpecDraft.sourceRunId,
    solverSpecDraft.sourceScenarioName,
    solverSpecDraft.nativeRunInputJson,
    scenarioNames,
    advancedJson.jsonText,
    refreshRuns,
  ]);

  /**
   * Run a solver template end-to-end:
   *
   *   1. Persist the deal so we have a stable id/version.
   *   2. Verify structure (same gate as the legacy solve flow).
   *   3. Build the same `source` shape `handleSolveDeal` builds so
   *      runsetup_ref / deal_native modes both work.
   *   4. POST to `/deals/{id}/solver-templates/{tid}/instantiate` to
   *      get the resolved SolverSpec.
   *   5. POST that spec to `/deals/{id}/solve` -- same endpoint as the
   *      legacy raw-spec flow, so progress polling, cancellation, and
   *      run history all work unchanged.
   *
   * Returns the result the SolverTemplateCards container needs to
   * render its per-card status (running -> ok / error). The global
   * telemetry on SolverStudioPanel still reflects the same run via
   * the existing polling loop.
   */
  const handleSolveFromTemplate = useCallback(
    async (
      templateId: string,
      request: api.TemplateInstantiationRequest,
    ): Promise<{ ok: boolean; message: string }> => {
      // Auto-tieout is the recovery path -- always let it through
      // even when carry is BLOCK. Any other template depends on a
      // structure that already balances, so gate them on carry.
      if (templateId !== "auto_tieout_carry") {
        if (!passCarryTieOutGate(`Run "${templateId}"`)) {
          return { ok: false, message: "Cancelled by carry tie-out gate." };
        }
      }
      setSolveBusy(true);
      if (progressPollRef.current != null) {
        window.clearInterval(progressPollRef.current);
        progressPollRef.current = null;
      }
      setTelemetryState({
        status: "running",
        stage: `Instantiating template: ${templateId}`,
        iteration: 0,
        objectiveTrajectory: [],
        cancelToken: savedDealId,
        runId: null,
      });
      try {
        const { dealId, dealVersion } = await persistDealForExecution();
        const verification = await verifyStructure(dealId, dealVersion);
        if (!verification.valid) {
          throw new Error(
            `Structuring verification failed: ${verification.errors[0] ?? "Resolve compatibility errors."}`,
          );
        }
        const source =
          solverSpecDraft.sourceMode === "runsetup_ref"
            ? {
                source_mode: "runsetup_ref" as const,
                run_id: solverSpecDraft.sourceRunId ?? "",
                scenario_names: scenarioNames,
              }
            : {
                source_mode: "deal_native" as const,
                scenario_name:
                  solverSpecDraft.sourceScenarioName ?? scenarioNames[0] ?? "Base Case",
                run_input: JSON.parse(solverSpecDraft.nativeRunInputJson || "{}"),
              };
        if (solverSpecDraft.sourceMode === "runsetup_ref" && !solverSpecDraft.sourceRunId) {
          throw new Error("Run Setup ref mode requires selecting a base CF run.");
        }
        const instantiation = await api.instantiateSolverTemplate(
          dealId,
          templateId,
          request,
          dealVersion,
        );
        const scenarioName =
          solverSpecDraft.sourceScenarioName ?? scenarioNames[0] ?? "Base Case";
        const res = await api.solveDeal(dealId, {
          deal_version: dealVersion,
          source,
          scenario_name: scenarioName,
          solver_spec: instantiation.spec,
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
              const progress = await api.getDealSolverProgress(dealId, runId);
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
              }
            } catch (error) {
              if (progressPollRef.current != null) {
                window.clearInterval(progressPollRef.current);
                progressPollRef.current = null;
              }
              setSolveBusy(false);
            }
          }, 1000);
        } else {
          setSolveBusy(false);
        }
        toast.success(`Started: ${instantiation.summary}`);
        return {
          ok: true,
          message: `Started — ${instantiation.summary}`,
        };
      } catch (e: unknown) {
        setTelemetryState((prev) => ({
          ...prev,
          status: "failed",
          stage: "Template solve failed",
        }));
        setSolveBusy(false);
        const msg = e instanceof Error ? e.message : String(e);
        toast.error(msg);
        return { ok: false, message: msg };
      }
    },
    [
      passCarryTieOutGate,
      persistDealForExecution,
      verifyStructure,
      solverSpecDraft.sourceMode,
      solverSpecDraft.sourceRunId,
      solverSpecDraft.sourceScenarioName,
      solverSpecDraft.nativeRunInputJson,
      scenarioNames,
      savedDealId,
      refreshRuns,
    ],
  );

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
    refreshStudioDeals();
  }, [refreshStudioDeals]);

  useEffect(() => {
    refreshUploadLibrary();
  }, [refreshUploadLibrary]);

  useEffect(() => {
    refreshPoolSnapshots();
  }, [refreshPoolSnapshots]);

  useEffect(() => {
    setSelectedStudioVersion("");
  }, [selectedStudioDealId]);

  useEffect(() => {
    if (!initialSourceRunId) return;
    setSolverSpecDraft((prev) => ({
      ...prev,
      sourceMode: "runsetup_ref",
      sourceRunId: prev.sourceRunId ?? initialSourceRunId,
    }));
  }, [initialSourceRunId]);

  useEffect(() => {
    if (!pendingWorkspaceState || !workspace) return;
    restoreWorkspaceState(pendingWorkspaceState).finally(() => {
      setPendingWorkspaceState(null);
    });
  }, [pendingWorkspaceState, restoreWorkspaceState, workspace]);

  useEffect(() => {
    const onColMove = (e: MouseEvent) => {
      const d = colDragRef.current;
      if (!d) return;
      const dx = e.clientX - d.startX;
      setSidebarWidth(Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, d.startW - dx)));
      userResizedSidebarRef.current = true;
    };
    const onColUp = () => {
      colDragRef.current = null;
      document.body.style.removeProperty("cursor");
      document.body.style.removeProperty("user-select");
    };

    window.addEventListener("mousemove", onColMove);
    window.addEventListener("mouseup", onColUp);
    return () => {
      window.removeEventListener("mousemove", onColMove);
      window.removeEventListener("mouseup", onColUp);
    };
  }, []);

  useEffect(() => {
    return () => {
      if (progressPollRef.current != null) {
        window.clearInterval(progressPollRef.current);
      }
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      const workspaceState = await serializeWorkspaceState();
      if (cancelled) return;
      const payload: StudioDraftState = {
        studioTab,
        dealName,
        savedDealId,
        irJson,
        solverSpecDraft,
        advancedJson,
        sensitivitySweepConfig,
        collateralRiskSettings,
        workspaceState,
      };
      sessionStorage.setItem(STUDIO_DRAFT_STORAGE_KEY, JSON.stringify(payload));
    }, 800);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [
    studioTab,
    dealName,
    savedDealId,
    irJson,
    solverSpecDraft,
    advancedJson,
    sensitivitySweepConfig,
    collateralRiskSettings,
    serializeWorkspaceState,
  ]);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(STUDIO_DRAFT_STORAGE_KEY);
      if (!raw) return;
      const draft = JSON.parse(raw) as Partial<StudioDraftState>;
      if (draft.studioTab) setStudioTab(draft.studioTab);
      if (draft.dealName) setDealName(draft.dealName);
      if (draft.savedDealId) setSavedDealId(draft.savedDealId);
      if (typeof draft.irJson === "string") setIrJson(draft.irJson);
      if (draft.solverSpecDraft) {
        setSolverSpecDraft((prev) => ({ ...prev, ...draft.solverSpecDraft }));
      }
      if (draft.advancedJson) {
        setAdvancedJson((prev) => ({ ...prev, ...draft.advancedJson }));
      }
      if (draft.sensitivitySweepConfig) {
        setSensitivitySweepConfig(draft.sensitivitySweepConfig);
      }
      if (draft.collateralRiskSettings) {
        onCollateralRiskSettingsChange(toCollateralRiskSettings(draft.collateralRiskSettings));
      } else if ((draft as any).poolAssignment) {
        onCollateralRiskSettingsChange(toCollateralRiskSettings((draft as any).poolAssignment));
      }
      if (draft.workspaceState) setPendingWorkspaceState(draft.workspaceState);
      setPendingCleanMark(true);
    } catch {
      // ignore invalid draft state
    }
  }, [onCollateralRiskSettingsChange]);

  useEffect(() => {
    if (!pendingCleanMark) return;
    setLastSavedFingerprint(currentDraftFingerprint);
    setPendingCleanMark(false);
  }, [pendingCleanMark, currentDraftFingerprint]);

  useEffect(() => {
    setLastSavedFingerprint((prev) => prev || currentDraftFingerprint);
    // initialize baseline once for new sessions
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!isDirty) return undefined;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
      return "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [isDirty]);

  useEffect(() => {
    onDirtyStateChange?.(isDirty);
  }, [isDirty, onDirtyStateChange]);

  const onColumnResizeStart = (e: React.MouseEvent) => {
    e.preventDefault();
    colDragRef.current = { startX: e.clientX, startW: sidebarWidth };
    userResizedSidebarRef.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  useEffect(() => {
    if (studioTab !== "design") return;
    if (userResizedSidebarRef.current) return;
    const totalWidth = designSplitRef.current?.getBoundingClientRect().width ?? 0;
    if (totalWidth <= 0) return;
    // Keep default shell balanced: Blockly and Properties at roughly 50/50.
    const equalSplit = (totalWidth - 2) / 2;
    setSidebarWidth(Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, equalSplit)));
  }, [studioTab]);

  const handleCloseDealSession = useCallback(() => {
    if (isDirty && !window.confirm("Close deal session and discard unsaved changes?")) {
      return;
    }
    setStudioTab("design");
    setIrJson("");
    setErrors([]);
    setDealName("Deal");
    setSavedDealId(null);
    setActiveDealVersion(null);
    setSelectedStudioDealId("");
    setSelectedStudioVersion("");
    setSolverSpecDraft(getDefaultSolverSpecDraft());
    setAdvancedJson(getDefaultAdvancedJsonState());
    setTelemetryState(getDefaultTelemetryState());
    setSensitivitySweepConfig(getDefaultSensitivitySweepConfig());
    onCollateralRiskSettingsChange(getDefaultCollateralRiskSettings());
    setLastSavedFingerprint("");
    setVerificationState(null);
    setPendingCleanMark(true);
    sessionStorage.removeItem(STUDIO_DRAFT_STORAGE_KEY);
  }, [isDirty, onCollateralRiskSettingsChange]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="flex shrink-0 flex-wrap items-center gap-2 px-1">
        <div className="flex items-center gap-1">
          <FormSelect
            value={selectedStudioDealId}
            onChange={(e) => setSelectedStudioDealId(e.target.value)}
            className="w-auto"
            aria-label="Open saved deal"
          >
            <option value="">Open saved deal...</option>
            {studioDeals.map((deal) => (
              <option key={deal.deal_id} value={deal.deal_id}>
                {fmtNamedId(deal.deal_name, deal.deal_id)}
              </option>
            ))}
          </FormSelect>
          <FormSelect
            value={selectedStudioVersion}
            onChange={(e) => setSelectedStudioVersion(e.target.value)}
            className="w-20"
            aria-label="Saved deal version"
          >
            <option value="">latest</option>
            {selectedStudioDealSummary &&
              Array.from(
                { length: Math.max(0, selectedStudioDealSummary.current_version) },
                (_, i) => i + 1,
              )
                .reverse()
                .map((version) => (
                  <option key={version} value={String(version)}>
                    v{version}
                  </option>
                ))}
          </FormSelect>
          <button
            type="button"
            onClick={handleLoadStudioDeal}
            disabled={!selectedStudioDealId}
            className="px-2.5 py-1 rounded border border-border text-xs text-muted-foreground hover:text-foreground disabled:opacity-40"
          >
            Open
          </button>
        </div>
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
          <span className="text-xs text-muted-foreground" style={MONO}>
            {savedDealId}
          </span>
        )}
        <span
          className={
            isDirty
              ? "text-xs px-2 py-0.5 rounded border border-amber-500/40 bg-amber-500/15 text-amber-200"
              : "text-xs px-2 py-0.5 rounded border border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
          }
        >
          {isDirty ? "Unsaved changes" : "Saved"}
        </span>
        {newerPoolVersion != null && (
          <button
            type="button"
            onClick={() =>
              onCollateralRiskSettingsChange(
                toCollateralRiskSettings({
                  ...collateralRiskSettings,
                  poolVersion: newerPoolVersion,
                }),
              )
            }
            className="text-xs px-2 py-0.5 rounded border border-cyan-500/40 bg-cyan-500/10 text-cyan-200"
          >
            Pool v{newerPoolVersion} available (click to pin)
          </button>
        )}
        <button
          type="button"
          onClick={async () => {
            try {
              const { dealId, dealVersion } = await persistDealForExecution();
              const verification = await verifyStructure(dealId, dealVersion);
              if (verification.valid) {
                toast.success("Structure verification passed.");
              } else {
                toast.error(`Verification failed with ${verification.errors.length} blocking issue(s).`);
              }
            } catch (error) {
              toast.error(error instanceof Error ? error.message : String(error));
            }
          }}
          className="inline-flex items-center gap-1 px-2 py-1 rounded border border-border text-xs text-muted-foreground hover:text-foreground"
        >
          <Settings2 className="w-3.5 h-3.5" />
          Verify Structure
        </button>
        <button
          type="button"
          onClick={handleCloseDealSession}
          className="inline-flex items-center gap-1 px-2 py-1 rounded border border-border text-xs text-muted-foreground hover:text-foreground"
        >
          <XCircle className="w-3.5 h-3.5" />
          Close deal
        </button>
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

      {verificationState && (
        <div
          className={`mx-1 rounded border px-2 py-2 text-xs ${
            verificationState.errors.length > 0
              ? "border-destructive/40 bg-destructive/10"
              : verificationState.warnings.length > 0
                ? "border-amber-500/40 bg-amber-500/10"
                : "border-emerald-500/40 bg-emerald-500/10"
          }`}
        >
          <div
            className={
              verificationState.errors.length > 0
                ? "text-destructive"
                : verificationState.warnings.length > 0
                  ? "text-amber-200"
                  : "text-emerald-200"
            }
          >
            {verificationState.valid
              ? `Structure verification: valid${
                  verificationState.warnings.length
                    ? ` with ${verificationState.warnings.length} warning(s)`
                    : ""
                }`
              : `Structure verification: ${verificationState.errors.length} blocking error(s), ${verificationState.warnings.length} warning(s)`}
          </div>
          {(verificationState.errors.length > 0
            || verificationState.warnings.length > 0
            || verificationState.suggestions.length > 0) && (
            <div className="mt-1.5 max-h-44 overflow-auto space-y-1.5 pr-1">
              {verificationState.errors.map((message, idx) => (
                <div key={`verification-error-${idx}`} className="text-destructive">
                  - Error: {message}
                </div>
              ))}
              {verificationState.warnings.map((message, idx) => (
                <div key={`verification-warning-${idx}`} className="text-amber-100">
                  - Warning: {message}
                </div>
              ))}
              {verificationState.suggestions.map((message, idx) => (
                <div key={`verification-suggestion-${idx}`} className="text-cyan-100">
                  - Suggestion: {message}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {studioTab === "solver" && (
        <div className="flex flex-col gap-4">
          {/* Level-1 + level-2: outcome-led "Solve for X" cards. This is
              the primary entry point per docs/architecture/solver_ux_design.md. */}
          <SolverTemplateCards
            dealId={savedDealId}
            productFamily={collateralRiskSettings.productFamily}
            busy={solveBusy}
            onRunTemplate={handleSolveFromTemplate}
          />

          {/* Level-3 advanced fallback: the legacy raw-knob form. The
              design doc keeps this for power users who want to edit
              the SolverSpec directly. Hidden behind a chevron so it
              doesn't compete with the level-1 cards. */}
          <details className="rounded-lg border border-border">
            <summary className="cursor-pointer px-3 py-2 text-xs text-muted-foreground hover:text-foreground transition-colors">
              Edit raw spec (advanced)
            </summary>
            <div className="border-t border-border p-3">
              <SolverStudioPanel
                savedDealId={savedDealId}
                productFamily={collateralRiskSettings.productFamily}
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
            </div>
          </details>
        </div>
      )}

      {studioTab === "ir" && (
        <div className="flex-1 min-h-0 px-1">
          <pre
            className="h-full min-h-[200px] overflow-auto rounded-md border border-border bg-[#0d1220] px-3 py-2 text-xs leading-relaxed text-secondary-foreground"
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

      <div
        ref={designSplitRef}
        className={studioTab === "design" ? "flex min-h-0 flex-1 gap-0" : "hidden min-h-0 flex-1 gap-0"}
      >
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
            <div className="flex flex-1 flex-col min-h-0 overflow-hidden rounded-md border border-border bg-[#0d1220]">
              <div className="shrink-0 flex items-center gap-1.5 px-3 pt-3 pb-2 border-b border-border/60">
                <Settings2 className="w-3.5 h-3.5 text-muted-foreground" />
                <span className="text-xs font-medium text-foreground">Properties</span>
              </div>
              <div className="flex-1 min-h-0 overflow-auto p-3 pt-2">
                <PropertyPanel
                  workspace={workspace}
                  collateralRiskSettings={collateralRiskSettings}
                  onCollateralRiskSettingsChange={onCollateralRiskSettingsChange}
                  onOpenTape={onOpenTape}
                  onRunCashflow={handleRunDeal}
                  canRunCashflow={!!savedDealId}
                  runCashflowBusy={runBusy}
                  availableRuns={availableRuns}
                  availableTapes={uploadLibrary}
                  poolSnapshots={poolSnapshots}
                  onCarryTieOutStatusChange={handleCarryStatusChange}
                  onPoolDerivationContextChange={handlePoolDerivationContextChange}
                  psaScheduleStale={psaScheduleStaleInfo}
                  showPsaScheduleTools={hasPsaStructuringBonds && !!poolDerivationCtx}
                  onRederivePsaSchedules={() => void runPsaScheduleDerivation()}
                  scheduleDeriveBusy={scheduleDeriveBusy}
                />
              </div>
            </div>
          </div>
      </div>
    </div>
  );
}
