import React, { useEffect, useMemo, useState } from "react";
import { Activity, BarChart3, Layers, ShieldAlert, Sigma } from "lucide-react";
import type { CashflowPreview, RunListItem } from "../services/api";
import * as api from "../services/api";
import TabBar from "../components/TabBar";
import DataTable, { type DataTableColumn } from "../components/DataTable";
import MetricCard from "../components/MetricCard";
import CollapsiblePanel from "../components/CollapsiblePanel";
import LoadingState from "../components/LoadingState";
import EmptyState from "../components/EmptyState";
import { fmtCcy, fmtNum } from "../lib/format";

type AnalysisTab = "bond_cashflows" | "waterfall" | "bond_risk" | "deal_risk" | "solver_runs";

interface Props {
  runId?: string | null;
}

const TABS = [
  { id: "bond_cashflows", label: "Bond Cashflows", icon: BarChart3 },
  { id: "waterfall", label: "Waterfall + Triggers", icon: Layers },
  { id: "bond_risk", label: "Bond Risk", icon: ShieldAlert },
  { id: "deal_risk", label: "Deal Risk", icon: Activity },
  { id: "solver_runs", label: "Solver Runs", icon: Sigma },
] as const;

export default function StructuredDealAnalysisPage({ runId }: Props) {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>(runId ?? "");
  const [tab, setTab] = useState<AnalysisTab>("bond_cashflows");
  const [artifacts, setArtifacts] = useState<string[]>([]);
  const [activeArtifact, setActiveArtifact] = useState<string>("");
  const [preview, setPreview] = useState<CashflowPreview | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.listRuns("structured_deal").then((rows) => {
      setRuns(rows);
      if (!selectedRunId && rows[0]) setSelectedRunId(rows[0].run_id);
    });
  }, [selectedRunId]);

  useEffect(() => {
    if (!runId) return;
    setSelectedRunId(runId);
  }, [runId]);

  useEffect(() => {
    if (!selectedRunId) return;
    api.getArtifacts(selectedRunId).then((res) => {
      setArtifacts(res.artifacts);
    });
  }, [selectedRunId]);

  const filteredArtifacts = useMemo(() => {
    const byTab = {
      bond_cashflows: artifacts.filter((a) => a.endsWith("_bond_cashflows")),
      waterfall: artifacts.filter((a) => a.includes("waterfall_trace") || a.includes("trigger_state_history")),
      bond_risk: artifacts.filter((a) => a.includes("tranche_risk_summary") || a.includes("credit_enhancement")),
      deal_risk: artifacts.filter((a) => a.includes("decrement_table") || a.includes("stress_matrix")),
      solver_runs: artifacts.filter((a) => a.includes("solver_iterations")),
    } as const;
    return byTab[tab];
  }, [artifacts, tab]);

  useEffect(() => {
    if (!filteredArtifacts.length) {
      setActiveArtifact("");
      setPreview(null);
      return;
    }
    setActiveArtifact((prev) => (prev && filteredArtifacts.includes(prev) ? prev : filteredArtifacts[0]));
  }, [filteredArtifacts]);

  useEffect(() => {
    if (!selectedRunId || !activeArtifact) return;
    setLoading(true);
    api.getPreview(selectedRunId, activeArtifact)
      .then(setPreview)
      .finally(() => setLoading(false));
  }, [selectedRunId, activeArtifact]);

  if (!runs.length) {
    return <EmptyState message="No structured deal runs yet. Execute a deal run from Structuring Studio first." />;
  }

  const selectedRun = runs.find((r) => r.run_id === selectedRunId) ?? runs[0];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">Run:</span>
        <select
          value={selectedRunId}
          onChange={(e) => setSelectedRunId(e.target.value)}
          className="px-2 py-1 bg-input-background border border-border rounded text-xs text-foreground"
        >
          {runs.map((run) => (
            <option key={run.run_id} value={run.run_id}>
              {(run.deal_name ?? run.run_id)} :: {(run.scenario_names ?? []).join(", ") || "Base Case"}
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard icon={Layers} label="Deal" value={selectedRun.deal_name ?? "Structured Deal"} />
        <MetricCard icon={BarChart3} label="Scenarios" value={String((selectedRun.scenario_names ?? []).length || 1)} />
        <MetricCard icon={ShieldAlert} label="Status" value={selectedRun.status} />
        <MetricCard icon={Activity} label="Runtime" value={selectedRun.elapsed_seconds != null ? `${selectedRun.elapsed_seconds.toFixed(2)}s` : "—"} />
      </div>

      <TabBar tabs={TABS as any} active={tab} onSelect={(id) => setTab(id as AnalysisTab)} />

      <CollapsiblePanel title="Artifacts" defaultOpen>
        <div className="p-3">
          {!filteredArtifacts.length ? (
            <EmptyState message="No artifacts available for this view in the selected run." />
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Artifact:</span>
              <select
                value={activeArtifact}
                onChange={(e) => setActiveArtifact(e.target.value)}
                className="px-2 py-1 bg-input-background border border-border rounded text-xs text-foreground"
              >
                {filteredArtifacts.map((artifact) => (
                  <option key={artifact} value={artifact}>
                    {artifact}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      </CollapsiblePanel>

      <CollapsiblePanel title="Data Preview" defaultOpen>
        <div className="p-3">
          {loading && <LoadingState message="Loading artifact preview..." />}
          {!loading && !preview && <EmptyState message="Select an artifact to inspect." />}
          {!loading && preview && (
            <DataTable
              tableId={`structured_${tab}_${preview.section}`}
              maxHeight="520px"
              columns={preview.columns.map((col, idx): DataTableColumn<Record<string, unknown>> => ({
                id: col,
                header: col,
                accessorKey: col,
                align: idx === 0 ? "left" : "right",
                cell: (value) => formatCell(value),
              }))}
              data={preview.rows}
            />
          )}
        </div>
      </CollapsiblePanel>
    </div>
  );
}

function formatCell(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "number") {
    if (Math.abs(value) >= 1000) return fmtCcy(value).replace("$", "");
    return fmtNum(value, 4);
  }
  return String(value);
}
