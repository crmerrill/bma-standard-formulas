import React, { useCallback, useEffect, useState } from "react";
import { Calendar } from "lucide-react";
import Layout, { type Page } from "./components/Layout";
import TapeIntakePage from "./pages/TapeIntakePage";
import TapeViewPage from "./pages/TapeViewPage";
import RunSetupPage from "./pages/RunSetupPage";
import ResultsPage from "./pages/ResultsPage";
import type { FieldMapping, RunResponse } from "./services/api";

const MONO = { fontFamily: "'JetBrains Mono', monospace" } as const;

const PAGE_TITLES: Record<Page, string> = {
  intake: "Tape Intake",
  tape: "Tape View",
  setup: "Run Setup",
  results: "Results",
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
}

const DEFAULTS: SessionState = {
  page: "intake",
  uploadId: null,
  mappingId: null,
  mappings: [],
  run: null,
  asofDate: new Date().toISOString().slice(0, 10),
  groupKeys: [],
};

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

  useEffect(() => {
    saveSession({ page, uploadId, mappingId, mappings, run, asofDate, groupKeys });
  }, [page, uploadId, mappingId, mappings, run, asofDate, groupKeys]);

  const enabledPages = new Set<Page>(["intake"]);
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
    setAsofDate(new Date().toISOString().slice(0, 10));
    setGroupKeys([]);
    setPage("intake");
    sessionStorage.removeItem(STORAGE_KEY);
  }, []);

  const asofAction = (
    <div className="flex items-center gap-2">
      <Calendar className="w-3.5 h-3.5 text-muted-foreground" />
      <span className="text-[10px] text-muted-foreground uppercase tracking-wider">
        As-of
      </span>
      <input
        type="date"
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
      onNavigate={setPage}
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
        <TapeViewPage uploadId={uploadId} mappingId={mappingId} />
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
      {page === "results" && run && <ResultsPage run={run} />}
    </Layout>
  );
}
