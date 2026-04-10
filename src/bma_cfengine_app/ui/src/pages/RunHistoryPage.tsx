import React, { useEffect, useState } from "react";
import { Clock, Eye, Play } from "lucide-react";
import type { RunListItem } from "../services/api";
import * as api from "../services/api";
import { fmtCcy, fmtDate } from "../lib/format";
import DataTable, { type DataTableColumn } from "../components/DataTable";
import LoadingState from "../components/LoadingState";
import EmptyState from "../components/EmptyState";
import StatusBadge from "../components/StatusBadge";
import TabBar from "../components/TabBar";

interface Props {
  onViewRun: (runId: string, runType?: "portfolio" | "structured_deal") => void;
  onRerun: (runId: string) => void;
}

export default function RunHistoryPage({ onViewRun, onRerun }: Props) {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [runTypeFilter, setRunTypeFilter] = useState<"all" | "portfolio" | "structured_deal">("all");

  useEffect(() => {
    setLoading(true);
    api.listRuns().then(setRuns).finally(() => setLoading(false));
  }, []);

  const filteredRuns = runs.filter((run) => {
    if (runTypeFilter === "all") return true;
    return (run.run_type ?? "portfolio") === runTypeFilter;
  });

  if (loading) return <LoadingState message="Loading run history..." />;
  if (runs.length === 0) return <EmptyState message="No runs yet. Go to Run Setup to execute your first cashflow run." />;

  return (
    <div className="space-y-3">
      <TabBar
        tabs={[
          { id: "all", label: "All Runs" },
          { id: "portfolio", label: "Portfolio" },
          { id: "structured_deal", label: "Structured Deal" },
        ]}
        active={runTypeFilter}
        onSelect={(id) => setRunTypeFilter(id as typeof runTypeFilter)}
      />
      <div className="border border-border rounded-lg overflow-hidden">
      <div className="bg-grid-header px-3 py-2 text-xs text-muted-foreground flex items-center gap-2">
        <Clock className="w-3.5 h-3.5" />
        {filteredRuns.length} run{filteredRuns.length !== 1 ? "s" : ""}
      </div>
      <DataTable
        tableId="run_history"
        columns={[
          { id: "run_id", header: "Run ID", accessorFn: (r: RunListItem) => r.run_id.replace("run_", "").slice(0, 8), cell: (v) => <span className="text-primary">{String(v)}</span> },
          { id: "run_type", header: "Type", accessorFn: (r: RunListItem) => (r.run_type ?? "portfolio").replace("_", " "), mono: false },
          { id: "deal_name", header: "Deal / Run", accessorFn: (r: RunListItem) => r.deal_name ?? "Portfolio Run", mono: false },
          { id: "created_at", header: "Date", accessorKey: "created_at", mono: false, cell: (v) => fmtDate(String(v ?? "")) },
          { id: "status", header: "Status", accessorKey: "status", align: "center", mono: false, cell: (_v, r: RunListItem) => <StatusBadge status={r.status} /> },
          { id: "loan_count", header: "Loans", accessorKey: "loan_count", align: "right", cell: (v) => Number(v).toLocaleString() },
          { id: "group_count", header: "Groups", accessorKey: "group_count", align: "right" },
          { id: "total_balance", header: "Balance", accessorKey: "total_balance", align: "right", cell: (v) => fmtCcy(Number(v)) },
          { id: "wac", header: "WAC", accessorKey: "wac", align: "right", cell: (v) => v ? `${Number(v).toFixed(2)}%` : "—" },
          { id: "scenarios", header: "Scenarios", accessorFn: (r: RunListItem) => r.scenario_names.join(", ") || "—", mono: false },
          { id: "elapsed", header: "Runtime", accessorKey: "elapsed_seconds", align: "right", cell: (v) => v != null ? `${Number(v).toFixed(2)}s` : "—" },
          { id: "actions", header: "Actions", align: "center", enableResizing: false, mono: false, accessorFn: () => "", cell: (_v, r: RunListItem) => (
            <div className="flex items-center justify-center gap-1">
              {r.status === "completed" && (
                <button onClick={() => onViewRun(r.run_id, (r.run_type ?? "portfolio") as "portfolio" | "structured_deal")} className="px-2 py-0.5 rounded border border-border text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors flex items-center gap-1" title="View results">
                  <Eye className="w-3 h-3" /> View
                </button>
              )}
              {r.status === "completed" && (r.run_type ?? "portfolio") === "portfolio" && (
                <button onClick={() => onRerun(r.run_id)} className="px-2 py-0.5 rounded border border-primary/20 bg-primary/5 text-primary hover:bg-primary/10 transition-colors flex items-center gap-1" title="Load config into Run Setup">
                  <Play className="w-3 h-3" /> Re-run
                </button>
              )}
            </div>
          )},
        ] as DataTableColumn<RunListItem>[]}
        data={filteredRuns}
        getRowId={(r) => r.run_id}
      />
    </div>
    </div>
  );
}
