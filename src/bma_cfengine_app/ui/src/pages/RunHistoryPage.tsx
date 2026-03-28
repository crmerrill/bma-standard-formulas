import React, { useEffect, useState } from "react";
import { Clock, Eye, Play, Loader2, Check, X, AlertTriangle } from "lucide-react";
import type { RunListItem } from "../services/api";
import * as api from "../services/api";

const MONO = { fontFamily: "'JetBrains Mono', monospace" } as const;

function fmtCcy(n: number): string {
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

function fmtDate(iso: string): string {
  if (!iso) return "\u2014";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso.slice(0, 19);
  }
}

interface Props {
  onViewRun: (runId: string) => void;
  onRerun: (runId: string) => void;
}

export default function RunHistoryPage({ onViewRun, onRerun }: Props) {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.listRuns().then(setRuns).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm p-8">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading run history...
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="text-muted-foreground text-sm p-8 text-center">
        No runs yet. Go to Run Setup to execute your first cashflow run.
      </div>
    );
  }

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="bg-grid-header px-3 py-2 text-xs text-muted-foreground flex items-center gap-2">
        <Clock className="w-3.5 h-3.5" />
        {runs.length} run{runs.length !== 1 ? "s" : ""}
      </div>
      <div className="overflow-auto">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 z-10">
            <tr className="bg-grid-header text-muted-foreground border-b border-border">
              <th className="text-left px-3 py-1.5">Run ID</th>
              <th className="text-left px-3 py-1.5">Date</th>
              <th className="text-center px-3 py-1.5">Status</th>
              <th className="text-right px-3 py-1.5">Loans</th>
              <th className="text-right px-3 py-1.5">Groups</th>
              <th className="text-right px-3 py-1.5">Balance</th>
              <th className="text-right px-3 py-1.5">WAC</th>
              <th className="text-left px-3 py-1.5">Scenarios</th>
              <th className="text-right px-3 py-1.5">Runtime</th>
              <th className="text-center px-3 py-1.5">Actions</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r, ri) => (
              <tr
                key={r.run_id}
                className={`border-b border-border/50 hover:bg-grid-row-hover transition-colors ${
                  ri % 2 === 1 ? "bg-grid-row-alt" : ""
                }`}
              >
                <td className="px-3 py-1.5 text-primary" style={MONO}>
                  {r.run_id.replace("run_", "").slice(0, 8)}
                </td>
                <td className="px-3 py-1.5 text-muted-foreground">{fmtDate(r.created_at)}</td>
                <td className="px-3 py-1.5 text-center">
                  <StatusBadge status={r.status} />
                </td>
                <td className="px-3 py-1.5 text-right" style={MONO}>{r.loan_count.toLocaleString()}</td>
                <td className="px-3 py-1.5 text-right" style={MONO}>{r.group_count}</td>
                <td className="px-3 py-1.5 text-right" style={MONO}>{fmtCcy(r.total_balance)}</td>
                <td className="px-3 py-1.5 text-right" style={MONO}>{r.wac ? `${r.wac.toFixed(2)}%` : "\u2014"}</td>
                <td className="px-3 py-1.5">
                  {r.scenario_names.length > 0 ? (
                    <span className="text-muted-foreground">{r.scenario_names.join(", ")}</span>
                  ) : "\u2014"}
                </td>
                <td className="px-3 py-1.5 text-right" style={MONO}>
                  {r.elapsed_seconds != null ? `${r.elapsed_seconds.toFixed(2)}s` : "\u2014"}
                </td>
                <td className="px-3 py-1.5 text-center">
                  <div className="flex items-center justify-center gap-1">
                    {r.status === "completed" && (
                      <button
                        onClick={() => onViewRun(r.run_id)}
                        className="px-2 py-0.5 rounded border border-border text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors flex items-center gap-1"
                        title="View results"
                      >
                        <Eye className="w-3 h-3" /> View
                      </button>
                    )}
                    {r.status === "completed" && (
                      <button
                        onClick={() => onRerun(r.run_id)}
                        className="px-2 py-0.5 rounded border border-primary/20 bg-primary/5 text-primary hover:bg-primary/10 transition-colors flex items-center gap-1"
                        title="Load config into Run Setup"
                      >
                        <Play className="w-3 h-3" /> Re-run
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  if (status === "completed") {
    return <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-engine-green/10 text-engine-green text-[9px]"><Check className="w-2.5 h-2.5" /> Done</span>;
  }
  if (status === "failed") {
    return <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-engine-red/10 text-engine-red text-[9px]"><X className="w-2.5 h-2.5" /> Failed</span>;
  }
  if (status === "running") {
    return <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-engine-amber/10 text-engine-amber text-[9px]"><Loader2 className="w-2.5 h-2.5 animate-spin" /> Running</span>;
  }
  return <span className="text-muted-foreground text-[9px]">{status}</span>;
}
