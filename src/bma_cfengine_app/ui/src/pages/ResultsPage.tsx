import React, { useEffect, useState } from "react";
import {
  BarChart3, Download, Table2, TrendingUp,
  Hash, DollarSign, Clock, Percent, Layers, Timer,
  FileInput, ArrowRight, Settings2,
} from "lucide-react";
import type {
  RunResponse, CashflowPreview, RiskResponse, RunListItem,
  RunInputAssumptions, RunInputMappings,
} from "../services/api";
import * as api from "../services/api";
import { MONO, fmtCcy, fmtNum } from "../lib/format";
import DataTable, { type DataTableColumn } from "../components/DataTable";
import TabBar from "../components/TabBar";
import PillToggle from "../components/PillToggle";
import MetricCard from "../components/MetricCard";
import SummaryRow from "../components/SummaryRow";
import CollapsiblePanel from "../components/CollapsiblePanel";
import LoadingState from "../components/LoadingState";
import EmptyState from "../components/EmptyState";
import RiskCell from "../components/RiskCell";
import MonoChip from "../components/MonoChip";

type Tab = "summary" | "inputs" | "portfolio" | "groups" | "risk";

interface Props {
  run: RunResponse;
  onSwitchRun?: (runId: string) => void;
}

type CfView = "actual" | "scheduled";

const TABS = [
  { id: "summary", label: "Summary", icon: BarChart3 },
  { id: "inputs", label: "Run Inputs", icon: FileInput },
  { id: "portfolio", label: "Portfolio CF", icon: Table2 },
  { id: "groups", label: "Group CF", icon: Layers },
  { id: "risk", label: "Risk", icon: TrendingUp },
] as const;

export default function ResultsPage({ run, onSwitchRun }: Props) {
  const [tab, setTab] = useState<Tab>("summary");
  const [cfPreview, setCfPreview] = useState<CashflowPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [cfView, setCfView] = useState<CfView>("actual");

  const [allRuns, setAllRuns] = useState<RunListItem[]>([]);
  useEffect(() => {
    api.listRuns().then((runs) => setAllRuns(runs.filter((r) => r.status === "completed")));
  }, [run.run_id]);

  const [scenarioNames, setScenarioNames] = useState<string[]>([]);
  const [selectedScenario, setSelectedScenario] = useState<string>("");

  const [groupNames, setGroupNames] = useState<string[]>([]);
  const [groupArtifacts, setGroupArtifacts] = useState<Record<string, string>>({});
  const [selectedGroup, setSelectedGroup] = useState<string>("");
  const [groupPreview, setGroupPreview] = useState<CashflowPreview | null>(null);
  const [groupLoading, setGroupLoading] = useState(false);

  const [riskData, setRiskData] = useState<RiskResponse | null>(null);
  const [riskLoading, setRiskLoading] = useState(false);
  const [riskInputKind, setRiskInputKind] = useState<"yield" | "price">("yield");
  const [riskBaseValue, setRiskBaseValue] = useState("6.0");
  const [riskSensStep, setRiskSensStep] = useState("1.0");
  const [riskSensSteps, setRiskSensSteps] = useState("4");

  const [inputTape, setInputTape] = useState<CashflowPreview | null>(null);
  const [inputAssumptions, setInputAssumptions] = useState<RunInputAssumptions | null>(null);
  const [inputMappings, setInputMappings] = useState<RunInputMappings | null>(null);
  const [inputsLoading, setInputsLoading] = useState(false);
  const [inputSubTab, setInputSubTab] = useState<"tape" | "assumptions" | "mappings">("tape");

  useEffect(() => {
    setInputTape(null);
    setInputAssumptions(null);
    setInputMappings(null);
    setInputsLoading(false);
    Promise.all([
      api.getRunScenarios(run.run_id),
      api.getRunGroups(run.run_id),
    ]).then(([scRes, grRes]) => {
      const scNames = scRes.scenarios;
      setScenarioNames(scNames);
      setSelectedScenario(scNames[0] || "Base Case");
      setGroupNames(grRes.groups);
      setGroupArtifacts(grRes.group_artifacts || {});
      if (grRes.groups.length > 0) setSelectedGroup(grRes.groups[0]);
    });
  }, [run.run_id]);

  const scPrefix = selectedScenario.replace(/[/\\ ]/g, "_").slice(0, 80);

  useEffect(() => {
    if (!selectedScenario) return;
    setLoading(true);
    api.getPreview(run.run_id, `${scPrefix}_portfolio_${cfView}`)
      .then(setCfPreview)
      .catch(() => api.getPreview(run.run_id, `${scPrefix}_portfolio`).then(setCfPreview).catch(() => setCfPreview(null)))
      .finally(() => setLoading(false));
  }, [selectedScenario, cfView, run.run_id]);

  useEffect(() => {
    if (!selectedGroup || !selectedScenario) return;
    const artifactKey = groupArtifacts[selectedGroup];
    if (!artifactKey) { setGroupPreview(null); return; }
    setGroupLoading(true);
    const viewKey = artifactKey.replace(/_actual$/, `_${cfView}`);
    api.getPreview(run.run_id, viewKey)
      .then(setGroupPreview)
      .catch(() => api.getPreview(run.run_id, artifactKey).then(setGroupPreview).catch(() => setGroupPreview(null)))
      .finally(() => setGroupLoading(false));
  }, [selectedGroup, selectedScenario, cfView, run.run_id, groupArtifacts]);

  useEffect(() => {
    if (tab !== "inputs" || inputTape || inputsLoading) return;
    setInputsLoading(true);
    Promise.all([
      api.getRunInputTape(run.run_id).catch(() => null),
      api.getRunInputAssumptions(run.run_id).catch(() => null),
      api.getRunInputMappings(run.run_id).catch(() => null),
    ]).then(([tape, assumptions, mappings]) => {
      setInputTape(tape);
      setInputAssumptions(assumptions);
      setInputMappings(mappings);
    }).finally(() => setInputsLoading(false));
  }, [tab, run.run_id]);

  const handleRisk = async () => {
    setRiskLoading(true);
    try {
      const base = parseFloat(riskBaseValue) || 6.0;
      const step = parseFloat(riskSensStep) || 1.0;
      const steps = parseInt(riskSensSteps) || 4;
      const sensInputs: number[] = [];
      for (let i = -steps; i <= steps; i++) sensInputs.push(Math.round((base + i * step) * 1000) / 1000);
      const res = await api.computeRisk(run.run_id, {
        analytics: ["price_yield_table", "risk_metrics"],
        input_kind: riskInputKind,
        base_value: base,
        column_inputs: sensInputs.filter((v) => v > 0),
      });
      setRiskData(res);
      setTab("risk");
    } finally { setRiskLoading(false); }
  };

  const summary = run.summary;
  const hasGroups = groupNames.length > 0;

  const groupsLabel = `Group CF${hasGroups ? ` (${groupNames.length})` : ""}`;
  const tabDefs = TABS.map((t) => t.id === "groups" ? { ...t, label: groupsLabel } : t);

  return (
    <div className="space-y-4">
      {/* Run selector */}
      {allRuns.length > 1 && onSwitchRun && (
        <div className="flex items-center gap-2 text-xs">
          <Clock className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-muted-foreground">Run:</span>
          <select value={run.run_id} onChange={(e) => onSwitchRun(e.target.value)}
            className="px-2 py-1 bg-input-background border border-border rounded text-xs text-foreground" style={MONO}>
            {allRuns.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.run_id.replace("run_", "").slice(0, 8)} — {r.scenario_names.join(", ") || "Base"} — {r.loan_count} loans — {new Date(r.created_at).toLocaleString()}
              </option>
            ))}
          </select>
        </div>
      )}

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <MetricCard icon={Hash} label="Loans" value={summary.loan_count.toLocaleString()} />
          <MetricCard icon={DollarSign} label="Total UPB" value={fmtCcy(summary.total_balance)} />
          <MetricCard icon={Percent} label="WAC" value={`${summary.wac.toFixed(2)}%`} />
          <MetricCard icon={Clock} label="WAM" value={`${summary.wam.toFixed(0)} mo`} />
          <MetricCard icon={Layers} label="Groups" value={summary.group_count.toString()} />
          {summary.elapsed_seconds != null && (
            <MetricCard icon={Timer} label="Runtime" value={`${summary.elapsed_seconds.toFixed(2)}s`} />
          )}
        </div>
      )}

      <TabBar tabs={tabDefs} active={tab} onSelect={(id) => setTab(id as Tab)} />

      {/* Summary tab */}
      {tab === "summary" && summary && (
        <div className="bg-card border border-border rounded-lg p-4 space-y-3">
          <h3 className="text-xs font-medium text-foreground">Run Summary</h3>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <SummaryRow label="Run ID" value={run.run_id} />
            <SummaryRow label="Status" value={run.status} />
            <SummaryRow label="Loans" value={summary.loan_count.toLocaleString()} />
            <SummaryRow label="Groups" value={summary.group_count.toString()} />
            <SummaryRow label="Total Balance" value={fmtCcy(summary.total_balance)} />
            <SummaryRow label="WAC" value={`${summary.wac.toFixed(4)}%`} />
            <SummaryRow label="WAM" value={`${summary.wam.toFixed(1)} months`} />
            <SummaryRow label="Sections" value={run.sections.join(", ")} />
            {summary.elapsed_seconds != null && (
              <SummaryRow label="Runtime" value={`${summary.elapsed_seconds.toFixed(3)} seconds`} />
            )}
          </div>
          {hasGroups && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mt-3 mb-1">Groups</p>
              <div className="flex flex-wrap gap-1.5">
                {groupNames.map((g) => <MonoChip key={g}>{g}</MonoChip>)}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Run Inputs tab */}
      {tab === "inputs" && (
        inputsLoading ? <LoadingState /> : (
          <div className="space-y-3">
            <PillToggle
              options={[
                { id: "tape", label: "Loan Tape" },
                { id: "assumptions", label: "Assumptions" },
                { id: "mappings", label: "Column Mappings" },
              ]}
              selected={inputSubTab}
              onSelect={(id) => setInputSubTab(id as typeof inputSubTab)}
            />

            {inputSubTab === "tape" && (
              inputTape ? (
                <div className="space-y-2">
                  <p className="text-xs text-muted-foreground">
                    The loan tape as it was at run time — {inputTape.row_count.toLocaleString()} rows, {inputTape.columns.length} columns
                    {inputTape.truncated && " (showing first 500)"}
                  </p>
                  <CashflowTable preview={inputTape} runId={run.run_id} />
                </div>
              ) : <EmptyState message="Tape snapshot not available for this run (older run format)." />
            )}

            {inputSubTab === "assumptions" && (
              inputAssumptions ? (
                <div className="space-y-3">
                  <div className="bg-card border border-border rounded-lg p-4 space-y-3">
                    <div className="flex items-center gap-2 text-xs">
                      <Settings2 className="w-3.5 h-3.5 text-primary" />
                      <span className="font-medium">Run Mode:</span>
                      <MonoChip>{inputAssumptions.run_mode}</MonoChip>
                      {inputAssumptions.grouping && (
                        <>
                          <span className="text-muted-foreground ml-2">Grouping:</span>
                          <MonoChip>{inputAssumptions.grouping.keys.join(", ")}</MonoChip>
                        </>
                      )}
                    </div>
                  </div>
                  {(inputAssumptions.scenarios || []).map((sc, si) => (
                    <div key={si} className="bg-card border border-border rounded-lg p-4 space-y-2">
                      <h4 className="text-xs font-medium text-foreground flex items-center gap-2">
                        Scenario: <span className="text-primary" style={MONO}>{sc.name}</span>
                        <span className="text-muted-foreground font-normal ml-1">({sc.run_mode})</span>
                      </h4>
                      <AssumptionsDetail data={sc.assumptions} />
                    </div>
                  ))}
                  {!inputAssumptions.scenarios?.length && inputAssumptions.base_assumptions && (
                    <div className="bg-card border border-border rounded-lg p-4 space-y-2">
                      <h4 className="text-xs font-medium text-foreground">Base Assumptions</h4>
                      <AssumptionsDetail data={inputAssumptions.base_assumptions} />
                    </div>
                  )}
                </div>
              ) : <EmptyState message="Assumptions not available for this run." />
            )}

            {inputSubTab === "mappings" && (
              inputMappings ? (
                <div className="space-y-3">
                  {inputMappings.asof_date && (
                    <div className="flex items-center gap-2 text-xs">
                      <span className="text-muted-foreground">As-of Date:</span>
                      <span style={MONO}>{inputMappings.asof_date}</span>
                    </div>
                  )}
                  <div className="border border-border rounded-lg overflow-hidden">
                    <div className="bg-grid-header px-3 py-2 text-xs text-muted-foreground">
                      {inputMappings.mappings.length} column mapping{inputMappings.mappings.length !== 1 ? "s" : ""}
                    </div>
                    <DataTable
                      tableId="input_mappings"
                      maxHeight="400px"
                      columns={[
                        { id: "source_column", header: "Source Column", accessorKey: "source_column" },
                        { id: "arrow", header: "", accessorFn: () => "", align: "center", size: 40, enableResizing: false, cell: () => <ArrowRight className="w-3 h-3 inline text-muted-foreground" /> },
                        { id: "canonical_field", header: "Canonical Field", accessorKey: "canonical_field", cell: (v) => <span className="text-primary">{String(v)}</span> },
                      ] as DataTableColumn<any>[]}
                      data={inputMappings.mappings}
                    />
                  </div>
                </div>
              ) : <EmptyState message="Mapping data not available for this run." />
            )}
          </div>
        )
      )}

      {/* Portfolio cashflows tab */}
      {tab === "portfolio" && (
        <div className="space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            {scenarioNames.length > 1 && (
              <PillToggle label="Scenario:" options={scenarioNames.map((s) => ({ id: s, label: s }))} selected={selectedScenario} onSelect={setSelectedScenario} />
            )}
            <PillToggle label="View:" options={[{ id: "actual", label: "Actual" }, { id: "scheduled", label: "Scheduled" }]} selected={cfView} onSelect={(v) => setCfView(v as CfView)} />
          </div>
          {loading ? <LoadingState /> : cfPreview ? (
            <CashflowTable preview={cfPreview} runId={run.run_id} artifactName={`${scPrefix}_portfolio_${cfView}`} />
          ) : <EmptyState message="No cashflow data." />}
        </div>
      )}

      {/* Group cashflows tab */}
      {tab === "groups" && (
        hasGroups ? (
          <div className="space-y-3">
            <div className="flex items-center gap-3 flex-wrap">
              {scenarioNames.length > 1 && (
                <PillToggle label="Scenario:" options={scenarioNames.map((s) => ({ id: s, label: s }))} selected={selectedScenario} onSelect={setSelectedScenario} />
              )}
              <PillToggle label="View:" options={[{ id: "actual", label: "Actual" }, { id: "scheduled", label: "Scheduled" }]} selected={cfView} onSelect={(v) => setCfView(v as CfView)} />
            </div>
            <div className="flex gap-3" style={{ minHeight: 400 }}>
              <div className="w-56 shrink-0 border border-border rounded-lg overflow-hidden">
                <div className="bg-grid-header px-3 py-2 text-xs font-medium text-muted-foreground flex items-center gap-2">
                  <Layers className="w-3.5 h-3.5 text-engine-blue" />
                  Groups ({groupNames.length})
                </div>
                <div className="overflow-auto max-h-[500px]">
                  {groupNames.map((g) => (
                    <button key={g} onClick={() => setSelectedGroup(g)}
                      className={`w-full text-left px-3 py-1.5 text-xs transition-colors border-b border-border/30 ${
                        selectedGroup === g ? "bg-primary/10 text-primary border-r-2 border-r-primary" : "text-foreground hover:bg-grid-row-hover"
                      }`} style={MONO}>
                      {g}
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex-1 min-w-0">
                {groupLoading ? <LoadingState /> : groupPreview ? (
                  <CashflowTable preview={groupPreview} runId={run.run_id} artifactName={groupArtifacts[selectedGroup]} />
                ) : <EmptyState message="Select a group from the list." />}
              </div>
            </div>
          </div>
        ) : <EmptyState message="No groups were defined for this run. Add grouping keys on the Run Setup page before running." />
      )}

      {/* Risk tab */}
      {tab === "risk" && (
        <div className="space-y-4">
          <div className="bg-card border border-border rounded-lg p-4 space-y-3">
            <h3 className="text-xs font-medium text-foreground flex items-center gap-2">
              <BarChart3 className="w-3.5 h-3.5 text-primary" /> Risk Analytics
              {hasGroups && <span className="text-muted-foreground font-normal ml-1">(portfolio + {groupNames.length} groups)</span>}
            </h3>
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground w-20 shrink-0">Quote Type</span>
              <PillToggle
                options={[{ id: "yield", label: "Yield" }, { id: "price", label: "Price" }]}
                selected={riskInputKind}
                onSelect={(v) => { setRiskInputKind(v as "yield" | "price"); setRiskBaseValue(v === "yield" ? "6.0" : "100.0"); setRiskSensStep(v === "yield" ? "1.0" : "5.0"); }}
              />
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground w-20 shrink-0">
                Base {riskInputKind === "yield" ? "Yield %" : "Price"}
              </span>
              <input type="text" value={riskBaseValue} onChange={(e) => setRiskBaseValue(e.target.value)}
                className="w-24 px-2 py-1 bg-input-background border border-border rounded text-xs" style={MONO}
                placeholder={riskInputKind === "yield" ? "6.0" : "100.0"} />
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground w-20 shrink-0">Sensitivity</span>
              <span className="text-xs text-muted-foreground">&plusmn;</span>
              <input type="text" value={riskSensSteps} onChange={(e) => setRiskSensSteps(e.target.value)}
                className="w-14 px-2 py-1 bg-input-background border border-border rounded text-xs" style={MONO} placeholder="4" />
              <span className="text-xs text-muted-foreground">steps of</span>
              <input type="text" value={riskSensStep} onChange={(e) => setRiskSensStep(e.target.value)}
                className="w-16 px-2 py-1 bg-input-background border border-border rounded text-xs" style={MONO}
                placeholder={riskInputKind === "yield" ? "1.0" : "5.0"} />
              <span className="text-xs text-muted-foreground">{riskInputKind === "yield" ? "%" : "pts"}</span>
            </div>
            <button onClick={handleRisk} disabled={riskLoading}
              className="px-4 py-2 rounded bg-primary/10 border border-primary/20 text-primary text-xs hover:bg-primary/20 transition-colors disabled:opacity-40 flex items-center gap-1.5">
              {riskLoading ? <LoadingState message="" /> : <TrendingUp className="w-3 h-3" />} Compute Risk
            </button>
          </div>

          {riskData?.risk_metrics && (() => {
            const portfolioMetrics = riskData.risk_metrics["Portfolio"];
            const groupEntries = Object.entries(riskData.risk_metrics).filter(([k]) => k !== "Portfolio");
            return (
              <>
                {portfolioMetrics && (
                  <div className="bg-card border border-primary/20 rounded-lg p-4">
                    <h4 className="text-xs font-medium text-primary mb-1 flex items-center gap-2">
                      <TrendingUp className="w-3.5 h-3.5" /> Portfolio Risk
                      <span className="text-muted-foreground font-normal ml-auto text-[10px]">
                        Quoted at {riskInputKind === "yield" ? `yield = ${riskBaseValue}%` : `price = ${riskBaseValue}`}
                      </span>
                    </h4>
                    <div className="grid grid-cols-6 gap-4 mt-3">
                      <RiskCell label={riskInputKind === "price" ? "Price (input)" : "Price (solved)"} value={portfolioMetrics.price.toFixed(4)} highlight={riskInputKind === "price"} />
                      <RiskCell label={riskInputKind === "yield" ? "Yield (input)" : "Yield (solved)"} value={`${portfolioMetrics.yield_pct.toFixed(4)}%`} highlight={riskInputKind === "yield"} />
                      <RiskCell label="Mac Duration (yr)" value={portfolioMetrics.macaulay_duration_years.toFixed(4)} />
                      <RiskCell label="Mod Duration (yr)" value={portfolioMetrics.modified_duration_years.toFixed(4)} />
                      <RiskCell label="Convexity (raw)" value={portfolioMetrics.convexity_years2.toFixed(4)} />
                      <RiskCell label="Convexity (yr)" value={Math.sqrt(Math.abs(portfolioMetrics.convexity_years2)).toFixed(4)} />
                    </div>
                  </div>
                )}

                {groupEntries.length > 0 && (
                  <div className="border border-border rounded-lg overflow-hidden">
                    <div className="bg-grid-header px-3 py-2 text-xs flex items-center gap-2">
                      <Layers className="w-3.5 h-3.5 text-engine-blue" />
                      <span className="text-muted-foreground">Group Risk Metrics ({groupEntries.length} groups)</span>
                    </div>
                    <DataTable
                      tableId="group_risk_metrics"
                      maxHeight="400px"
                      columns={[
                        { id: "group", header: "Group", accessorFn: (r: any) => r[0] },
                        { id: "price", header: "Price", accessorFn: (r: any) => r[1].price.toFixed(4), align: "right" },
                        { id: "yield_pct", header: "Yield %", accessorFn: (r: any) => `${r[1].yield_pct.toFixed(4)}%`, align: "right" },
                        { id: "mac_dur", header: "Mac Dur (yr)", accessorFn: (r: any) => r[1].macaulay_duration_years.toFixed(4), align: "right" },
                        { id: "mod_dur", header: "Mod Dur (yr)", accessorFn: (r: any) => r[1].modified_duration_years.toFixed(4), align: "right" },
                        { id: "cvx_raw", header: "Cvx (raw)", accessorFn: (r: any) => r[1].convexity_years2.toFixed(4), align: "right" },
                        { id: "cvx_yr", header: "Cvx (yr)", accessorFn: (r: any) => Math.sqrt(Math.abs(r[1].convexity_years2)).toFixed(4), align: "right" },
                      ] as DataTableColumn<any>[]}
                      data={groupEntries}
                      getRowId={(r: any) => r[0]}
                    />
                  </div>
                )}
              </>
            );
          })()}

          {riskData?.price_yield_table && (() => {
            const pyt = riskData.price_yield_table!;
            const pytData = pyt.scenarios.map((sc, si) => ({ scenario: sc, values: pyt.values[si] }));
            return (
              <div className="border border-border rounded-lg overflow-hidden">
                <div className="bg-grid-header px-3 py-2 text-xs text-muted-foreground">
                  {pyt.input_kind === "yield" ? "Yield" : "Price"} &rarr; {pyt.value_kind === "price" ? "Price" : "Yield"} Table
                </div>
                <DataTable
                  tableId="price_yield_table"
                  columns={[
                    { id: "scenario", header: "Scenario", accessorKey: "scenario" },
                    ...pyt.column_inputs.map((inp, i): DataTableColumn<any> => ({
                      id: `col_${i}`, header: inp.toFixed(2),
                      accessorFn: (r: any) => r.values[i]?.toFixed(4) ?? "—", align: "right",
                    })),
                  ] as DataTableColumn<any>[]}
                  data={pytData}
                  rowClassName={(row: any) => row.scenario === "Portfolio" ? "bg-primary/5 font-medium border-b border-border/50" : ""}
                  getRowId={(r: any) => r.scenario}
                />
              </div>
            );
          })()}

          {!riskData && <EmptyState message="Configure inputs above and click Compute." />}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page-local components
// ---------------------------------------------------------------------------

function CashflowTable({ preview, runId, artifactName }: { preview: CashflowPreview; runId: string; artifactName?: string }) {
  const downloadCsv = () => {
    const name = artifactName || preview.section;
    window.open(`/api/runs/${runId}/download/${name}?format=csv`, "_blank");
  };

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="bg-grid-header px-3 py-2 flex items-center gap-2 text-xs">
        <span className="text-muted-foreground">
          {preview.row_count} periods{preview.truncated && " (truncated)"}
        </span>
        <div className="flex-1" />
        <button onClick={downloadCsv}
          className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors">
          <Download className="w-3 h-3" /> CSV
        </button>
      </div>
      <DataTable
        tableId={`cashflow_${preview.section}`}
        maxHeight="450px"
        columns={preview.columns.map((col, ci): DataTableColumn<Record<string, unknown>> => ({
          id: col, header: col, accessorKey: col,
          align: ci === 0 ? "left" : "right",
          cell: (v) => fmtNum(v, 2),
        }))}
        data={preview.rows}
      />
    </div>
  );
}

function AssumptionsDetail({ data }: { data: Record<string, unknown> }) {
  const renderValue = (val: unknown, depth = 0): React.ReactNode => {
    if (val == null) return <span className="text-muted-foreground italic">null</span>;
    if (typeof val === "string" || typeof val === "number" || typeof val === "boolean")
      return <span style={MONO}>{String(val)}</span>;
    if (Array.isArray(val)) {
      if (val.length === 0) return <span className="text-muted-foreground italic">[]</span>;
      if (val.length <= 5 && val.every((v) => typeof v !== "object"))
        return <span style={MONO}>[{val.join(", ")}]</span>;
      return <span style={MONO}>[{val.length} items]</span>;
    }
    if (typeof val === "object") {
      const entries = Object.entries(val as Record<string, unknown>);
      if (depth > 1) return <span className="text-muted-foreground">{`{${entries.length} fields}`}</span>;
      return (
        <div className={depth > 0 ? "ml-4 border-l border-border/50 pl-3 mt-1" : ""}>
          {entries.map(([k, v]) => (
            <div key={k} className="flex items-baseline gap-2 py-0.5">
              <span className="text-muted-foreground shrink-0">{k}:</span>
              {renderValue(v, depth + 1)}
            </div>
          ))}
        </div>
      );
    }
    return <span>{String(val)}</span>;
  };
  return <div className="text-xs">{renderValue(data)}</div>;
}
