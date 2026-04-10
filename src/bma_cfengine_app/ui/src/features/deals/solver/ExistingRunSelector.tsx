import React, { useMemo, useState } from "react";
import { RotateCw, Search } from "lucide-react";
import { fmtDate } from "../../../lib/format";
import type { RunListItem } from "../../../services/api";

interface Props {
  runs: RunListItem[];
  loading: boolean;
  error: string | null;
  value: string | null;
  onChange: (runId: string | null) => void;
  onRetry: () => void;
  pageSize?: number;
}

function shortRunId(runId: string): string {
  return runId.replace("run_", "").slice(0, 8);
}

export default function ExistingRunSelector({
  runs,
  loading,
  error,
  value,
  onChange,
  onRetry,
  pageSize = 12,
}: Props) {
  const [query, setQuery] = useState("");
  const [completedOnly, setCompletedOnly] = useState(true);
  const [structuredOnly, setStructuredOnly] = useState(false);
  const [solverOnly, setSolverOnly] = useState(false);
  const [page, setPage] = useState(0);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return runs
      .filter((run) => (completedOnly ? run.status === "completed" : true))
      .filter((run) => (structuredOnly ? run.run_type === "structured_deal" : true))
      .filter((run) => (solverOnly ? run.run_kind === "solver" : true))
      .filter((run) => {
        if (!q) return true;
        const haystack = [
          run.deal_name ?? "",
          run.run_id,
          run.scenario_names?.join(" ") ?? "",
        ]
          .join(" ")
          .toLowerCase();
        return haystack.includes(q);
      })
      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  }, [runs, completedOnly, structuredOnly, solverOnly, query]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages - 1);
  const pageRuns = filtered.slice(safePage * pageSize, safePage * pageSize + pageSize);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="w-3.5 h-3.5 absolute left-2 top-1.5 text-muted-foreground" />
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(0);
            }}
            placeholder="Search deal name, run id, scenario"
            className="w-full pl-7 pr-2 py-1 rounded border border-border bg-input-background text-foreground text-xs"
            aria-label="Search existing runs"
          />
        </div>
        <button
          type="button"
          onClick={onRetry}
          className="px-2 py-1 rounded border border-border text-xs text-muted-foreground hover:text-foreground"
        >
          <RotateCw className="w-3 h-3" />
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        <Toggle value={completedOnly} onChange={setCompletedOnly} label="Completed only" />
        <Toggle value={structuredOnly} onChange={setStructuredOnly} label="Structured only" />
        <Toggle value={solverOnly} onChange={setSolverOnly} label="Solver only" />
      </div>

      {loading && <div className="text-xs text-muted-foreground">Loading runs...</div>}
      {!loading && error && (
        <div className="text-xs text-destructive">
          {error}{" "}
          <button type="button" onClick={onRetry} className="underline underline-offset-2">
            Retry
          </button>
        </div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="text-xs text-muted-foreground">
          No runs matched. Execute a run first, then refresh.
        </div>
      )}

      {!loading && !error && filtered.length > 0 && (
        <>
          <select
            value={value ?? ""}
            onChange={(e) => onChange(e.target.value || null)}
            className="w-full px-2 py-1 rounded border border-border bg-input-background text-foreground text-xs"
            aria-label="Select existing run"
          >
            <option value="">Select base CF run</option>
            {pageRuns.map((run) => {
              const runLabel = run.deal_name ?? "Portfolio run";
              const scenarios = run.scenario_names?.join(", ") || "Base Case";
              return (
                <option key={run.run_id} value={run.run_id}>
                  {`${runLabel} :: ${scenarios} | ${shortRunId(run.run_id)} | ${fmtDate(run.created_at)} | ${run.status} | ${run.run_kind ?? "run"}`}
                </option>
              );
            })}
          </select>
          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <span>
              {filtered.length} result{filtered.length === 1 ? "" : "s"}
            </span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={safePage === 0}
                className="px-1.5 py-0.5 rounded border border-border disabled:opacity-40"
              >
                Prev
              </button>
              <span>
                {safePage + 1}/{totalPages}
              </span>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={safePage >= totalPages - 1}
                className="px-1.5 py-0.5 rounded border border-border disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Toggle({
  value,
  onChange,
  label,
}: {
  value: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <label className="inline-flex items-center gap-1.5">
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}
