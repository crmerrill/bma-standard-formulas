import React, { useCallback, useEffect, useState } from "react";
import { Calendar } from "lucide-react";
import Layout, { type Page } from "./components/Layout";
import TapeIntakePage from "./pages/TapeIntakePage";
import TapeViewPage from "./pages/TapeViewPage";
import RunSetupPage from "./pages/RunSetupPage";
import ResultsPage from "./pages/ResultsPage";
import RunHistoryPage from "./pages/RunHistoryPage";
import DealEditor from "./features/deals/DealEditor";
import StructuredDealAnalysisPage from "./pages/StructuredDealAnalysisPage";
import type { FieldMapping, RunResponse } from "./services/api";
import * as api from "./services/api";
import { MONO } from "./lib/format";
import {
  getDefaultCollateralRiskSettings,
  validateCollateralRiskSettings,
  type CollateralRiskSettings,
} from "./features/deals/shared/riskSettings";

const PAGE_TITLES: Record<Page, string> = {
  intake: "Tape Intake",
  tape: "Tape View",
  setup: "Run Setup",
  results: "Results",
  history: "Run History",
  structuring: "Structuring Studio",
  structured_analysis: "Structured Deal Analysis",
};

// ---------------------------------------------------------------------------
// sessionStorage persistence
// ---------------------------------------------------------------------------

const STORAGE_KEY = "bma_cfengine_session";

interface SessionState {
  page: Page;
  uploadId: string | null;
  mappingId: string | null;
  mappings: FieldMapping[];
  run: RunResponse | null;
  asofDate: string;
  groupKeys: string[];
  structuredRunId: string | null;
  collateralRiskSettings: CollateralRiskSettings;
}

const DEFAULTS: SessionState = {
  page: "intake",
  uploadId: null,
  mappingId: null,
  mappings: [],
  run: null,
  asofDate: new Date().toISOString().slice(0, 10),
  groupKeys: [],
  structuredRunId: null,
  collateralRiskSettings: getDefaultCollateralRiskSettings(),
};

function normalizeCollateralRiskSettings(value: unknown): CollateralRiskSettings {
  const fallback = getDefaultCollateralRiskSettings();
  if (!value || typeof value !== "object") {
    return {
      ...fallback,
      validation: validateCollateralRiskSettings(fallback),
    };
  }
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
    validation: fallback.validation,
  };
  return {
    ...merged,
    validation: validateCollateralRiskSettings(merged),
  };
}

function loadSession(): SessionState {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    /* corrupt data — ignore */
  }
  return { ...DEFAULTS };
}

function saveSession(state: SessionState) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* quota exceeded — non-critical */
  }
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  const [initial] = useState(loadSession);
  const [page, setPage] = useState<Page>(initial.page);
  const [uploadId, setUploadId] = useState<string | null>(initial.uploadId);
  const [mappingId, setMappingId] = useState<string | null>(initial.mappingId);
  const [mappings, setMappings] = useState<FieldMapping[]>(initial.mappings);
  const [run, setRun] = useState<RunResponse | null>(initial.run);
  const [asofDate, setAsofDate] = useState<string>(initial.asofDate);
  const [groupKeys, setGroupKeys] = useState<string[]>(initial.groupKeys);
  const [structuredRunId, setStructuredRunId] = useState<string | null>(initial.structuredRunId);
  const [collateralRiskSettings, setCollateralRiskSettings] = useState<CollateralRiskSettings>(
    normalizeCollateralRiskSettings(initial.collateralRiskSettings),
  );
  const [structuringDirty, setStructuringDirty] = useState(false);

  useEffect(() => {
    saveSession({
      page,
      uploadId,
      mappingId,
      mappings,
      run,
      asofDate,
      groupKeys,
      structuredRunId,
      collateralRiskSettings,
    });
  }, [page, uploadId, mappingId, mappings, run, asofDate, groupKeys, structuredRunId, collateralRiskSettings]);

  const handleCollateralRiskSettingsChange = useCallback((next: CollateralRiskSettings) => {
    setCollateralRiskSettings({
      ...next,
      validation: validateCollateralRiskSettings(next),
    });
  }, []);

  const enabledPages = new Set<Page>(["intake", "history", "structuring", "structured_analysis"]);
  if (uploadId && mappingId) {
    enabledPages.add("tape");
    enabledPages.add("setup");
  }
  if (run?.status === "completed") {
    enabledPages.add("results");
  }

  const handleIntakeComplete = useCallback(
    (uid: string, mid: string, maps: FieldMapping[]) => {
      setUploadId(uid);
      setMappingId(mid);
      setMappings(maps);
      setPage("tape");
    },
    []
  );

  const handleRunComplete = useCallback((r: RunResponse) => {
    setRun(r);
    setPage("results");
  }, []);

  const handleReset = useCallback(() => {
    setUploadId(null);
    setMappingId(null);
    setMappings([]);
    setRun(null);
    setStructuredRunId(null);
    setCollateralRiskSettings(getDefaultCollateralRiskSettings());
    setStructuringDirty(false);
    setAsofDate(new Date().toISOString().slice(0, 10));
    setGroupKeys([]);
    setPage("intake");
    sessionStorage.removeItem(STORAGE_KEY);
  }, []);

  useEffect(() => {
    if (page !== "structuring" && structuringDirty) {
      setStructuringDirty(false);
    }
  }, [page, structuringDirty]);

  const handleViewRun = useCallback(async (runId: string) => {
    try {
      const [r, cfg] = await Promise.all([
        api.getRun(runId),
        api.getRunConfig(runId),
      ]);
      const rc = cfg.run_config;
      if (rc.upload_id) setUploadId(rc.upload_id);
      if (rc.mapping_id) setMappingId(rc.mapping_id);
      if (rc.mappings) setMappings(rc.mappings);
      if (rc.grouping?.keys) setGroupKeys(rc.grouping.keys);
      if (rc.asof_date) setAsofDate(rc.asof_date);
      setRun(r);
      setPage("results");
      setStructuredRunId(null);
    } catch {
      /* ignore */
    }
  }, []);

  const handleViewHistoryRun = useCallback(async (runId: string, runType?: "portfolio" | "structured_deal") => {
    if (runType === "structured_deal") {
      setStructuredRunId(runId);
      setPage("structured_analysis");
      return;
    }
    await handleViewRun(runId);
  }, [handleViewRun]);

  const handleRerun = useCallback(async (runId: string) => {
    try {
      const cfg = await api.getRunConfig(runId);
      const rc = cfg.run_config;
      if (rc.upload_id) setUploadId(rc.upload_id);
      if (rc.mapping_id) setMappingId(rc.mapping_id);
      if (rc.mappings) setMappings(rc.mappings);
      if (rc.grouping?.keys) setGroupKeys(rc.grouping.keys);
      else setGroupKeys([]);
      if (rc.asof_date) setAsofDate(rc.asof_date);
      setPage("setup");
    } catch {
      /* ignore */
    }
  }, []);

  const handleOpenSolverStudio = useCallback((runId: string) => {
    setStructuredRunId(runId);
    setPage("structuring");
  }, []);

  const handleOpenTapeLibraryItem = useCallback(
    async (nextUploadId: string, nextMappingId: string) => {
      const mapping = await api.getSavedMapping(nextUploadId, nextMappingId);
      setUploadId(nextUploadId);
      setMappingId(nextMappingId);
      setMappings(mapping.mappings ?? []);
      if (mapping.asof_date) setAsofDate(mapping.asof_date);
      setPage("tape");
    },
    [],
  );

  const handleNavigate = useCallback(
    (nextPage: Page) => {
      if (
        page === "structuring"
        && nextPage !== "structuring"
        && structuringDirty
        && !window.confirm("You have unsaved structuring changes. Leave this page?")
      ) {
        return;
      }
      setPage(nextPage);
    },
    [page, structuringDirty],
  );

  const asofAction = (
    <div className="flex items-center gap-2">
      <Calendar className="w-3.5 h-3.5 text-muted-foreground" />
      <span className="text-xs text-muted-foreground uppercase tracking-wider">
        As-of
      </span>
      <input
        type="date"
        aria-label="As-of date"
        value={asofDate}
        onChange={(e) => setAsofDate(e.target.value)}
        className="px-2 py-0.5 bg-input-background border border-border rounded text-xs text-foreground"
        style={MONO}
      />
    </div>
  );

  return (
    <Layout
      currentPage={page}
      onNavigate={handleNavigate}
      pageTitle={PAGE_TITLES[page]}
      enabledPages={enabledPages}
      onReset={handleReset}
      actions={asofAction}
    >
      {page === "intake" && (
        <TapeIntakePage
          onComplete={handleIntakeComplete}
          asofDate={asofDate}
        />
      )}
      {page === "tape" && uploadId && mappingId && (
        <TapeViewPage
          uploadId={uploadId}
          mappingId={mappingId}
          onOpenTape={handleOpenTapeLibraryItem}
        />
      )}
      {page === "setup" && uploadId && mappingId && (
        <RunSetupPage
          uploadId={uploadId}
          mappingId={mappingId}
          mappings={mappings}
          asofDate={asofDate}
          groupKeys={groupKeys}
          onGroupKeysChange={setGroupKeys}
          onRunComplete={handleRunComplete}
        />
      )}
      {page === "results" && run && (
        <ResultsPage
          run={run}
          onSwitchRun={handleViewRun}
          onBackToHistory={() => setPage("history")}
        />
      )}
      {page === "history" && (
        <RunHistoryPage
          onViewRun={handleViewHistoryRun}
          onRerun={handleRerun}
          onOpenSolverStudio={handleOpenSolverStudio}
        />
      )}
      {page === "structuring" && (
        <DealEditor
          initialSourceRunId={structuredRunId}
          collateralRiskSettings={collateralRiskSettings}
          onCollateralRiskSettingsChange={handleCollateralRiskSettingsChange}
          onOpenTape={handleOpenTapeLibraryItem}
          onDirtyStateChange={setStructuringDirty}
        />
      )}
      {page === "structured_analysis" && (
        <StructuredDealAnalysisPage
          runId={structuredRunId}
          collateralRiskSettings={collateralRiskSettings}
          onCollateralRiskSettingsChange={handleCollateralRiskSettingsChange}
        />
      )}
    </Layout>
  );
}
