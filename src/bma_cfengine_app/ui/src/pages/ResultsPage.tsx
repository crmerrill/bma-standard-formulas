import React, { useEffect, useState } from "react";
import {
  BarChart3, Download, Table2, TrendingUp, Loader2,
  Hash, DollarSign, Clock, Percent, Layers, ChevronDown, Timer,
} from "lucide-react";
import type {
  RunResponse, CashflowPreview, RiskResponse, RiskMetricsResult,
} from "../services/api";
import * as api from "../services/api";

const MONO = { fontFamily: "'JetBrains Mono', monospace" } as const;

function fmtCcy(n: number): string {
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(2)}`;
}

function fmtNum(n: unknown, dec = 4): string {
  if (n == null) return "\u2014";
  const v = Number(n);
  if (!isFinite(v)) return "\u2014";
  return v.toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

type Tab = "summary" | "portfolio" | "groups" | "risk";

interface Props { run: RunResponse; }

type CfView = "actual" | "scheduled";

export default function ResultsPage({ run }: Props) {
  const [tab, setTab] = useState<Tab>("summary");
  const [cfPreview, setCfPreview] = useState<CashflowPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [cfView, setCfView] = useState<CfView>("actual");

  // Scenarios
  const [scenarioNames, setScenarioNames] = useState<string[]>([]);
  const [selectedScenario, setSelectedScenario] = useState<string>("");

  // Groups
  const [groupNames, setGroupNames] = useState<string[]>([]);
  const [groupArtifacts, setGroupArtifacts] = useState<Record<string, string>>({});
  const [selectedGroup, setSelectedGroup] = useState<string>("");
  const [groupPreview, setGroupPreview] = useState<CashflowPreview | null>(null);
  const [groupLoading, setGroupLoading] = useState(false);

  // Risk
  const [riskData, setRiskData] = useState<RiskResponse | null>(null);
  const [riskLoading, setRiskLoading] = useState(false);
  const [riskInputKind, setRiskInputKind] = useState<"yield" | "price">("yield");
  const [riskBaseValue, setRiskBaseValue] = useState("6.0");
  const [riskSensStep, setRiskSensStep] = useState("1.0");
  const [riskSensSteps, setRiskSensSteps] = useState("4");

  useEffect(() => {
    Promise.all([
      api.getRunScenarios(run.run_id),
      api.getRunGroups(run.run_id),
    ]).then(([scRes, grRes]) => {
      const scNames = scRes.scenarios;
      setScenarioNames(scNames);
      const firstSc = scNames[0] || "Base Case";
      setSelectedScenario(firstSc);
      setGroupNames(grRes.groups);
      setGroupArtifacts(grRes.group_artifacts || {});
      if (grRes.groups.length > 0) setSelectedGroup(grRes.groups[0]);
    });
  }, [run.run_id]);

  const scPrefix = selectedScenario.replace(/\//g, "_").replace(/\\/g, "_").replace(/ /g, "_").slice(0, 80);

  useEffect(() => {
    if (!selectedScenario) return;
    setLoading(true);
    api.getPreview(run.run_id, `${scPrefix}_portfolio_${cfView}`)
      .then(setCfPreview)
      .catch(() => {
        api.getPreview(run.run_id, `${scPrefix}_portfolio`)
          .then(setCfPreview)
          .catch(() => setCfPreview(null));
      })
      .finally(() => setLoading(false));
  }, [selectedScenario, cfView, run.run_id]);

  useEffect(() => {
    if (!selectedGroup || !selectedScenario) return;
    const artifactKey = groupArtifacts[selectedGroup];
    if (!artifactKey) {
      setGroupPreview(null);
      return;
    }
    setGroupLoading(true);
    const viewKey = artifactKey.replace(/_actual$/, `_${cfView}`);
    api.getPreview(run.run_id, viewKey)
      .then(setGroupPreview)
      .catch(() => {
        api.getPreview(run.run_id, artifactKey)
          .then(setGroupPreview)
          .catch(() => setGroupPreview(null));
      })
      .finally(() => setGroupLoading(false));
  }, [selectedGroup, selectedScenario, cfView, run.run_id, groupArtifacts]);

  const handleRisk = async () => {
    setRiskLoading(true);
    try {
      const base = parseFloat(riskBaseValue) || 6.0;
      const step = parseFloat(riskSensStep) || 1.0;
      const steps = parseInt(riskSensSteps) || 4;

      const sensInputs: number[] = [];
      for (let i = -steps; i <= steps; i++) {
        sensInputs.push(Math.round((base + i * step) * 1000) / 1000);
      }

      const res = await api.computeRisk(run.run_id, {
        analytics: ["price_yield_table", "risk_metrics"],
        input_kind: riskInputKind,
        base_value: base,
        column_inputs: sensInputs.filter((v) => v > 0),
      });
      setRiskData(res);
      setTab("risk");
    } finally {
      setRiskLoading(false);
    }
  };

  const summary = run.summary;
  const hasGroups = groupNames.length > 0;

  return (
    <div className="space-y-4">
      {/* Summary banner */}
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

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-border">
        <TabBtn icon={BarChart3} label="Summary" active={tab === "summary"} onClick={() => setTab("summary")} />
        <TabBtn icon={Table2} label="Portfolio CF" active={tab === "portfolio"} onClick={() => setTab("portfolio")} />
        <TabBtn
          icon={Layers}
          label={`Group CF${hasGroups ? ` (${groupNames.length})` : ""}`}
          active={tab === "groups"}
          onClick={() => setTab("groups")}
        />
        <TabBtn icon={TrendingUp} label="Risk" active={tab === "risk"} onClick={() => setTab("risk")} />
      </div>

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
                {groupNames.map((g) => (
                  <span key={g} className="px-2 py-0.5 rounded bg-secondary text-xs" style={MONO}>{g}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Portfolio cashflows tab */}
      {tab === "portfolio" && (
        <div className="space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            {scenarioNames.length > 1 && (
              <ScenarioSelector scenarios={scenarioNames} selected={selectedScenario} onSelect={setSelectedScenario} />
            )}
            <ViewToggle view={cfView} onChange={setCfView} />
          </div>
          {loading ? <LoadingMsg /> : cfPreview ? (
            <CashflowTable
              preview={cfPreview}
              runId={run.run_id}
              artifactName={`${scPrefix}_portfolio_${cfView}`}
            />
          ) : <EmptyMsg text="No cashflow data." />}
        </div>
      )}

      {/* Group cashflows tab */}
      {tab === "groups" && (
        hasGroups ? (
          <div className="space-y-3">
            <div className="flex items-center gap-3 flex-wrap">
              {scenarioNames.length > 1 && (
                <ScenarioSelector scenarios={scenarioNames} selected={selectedScenario} onSelect={setSelectedScenario} />
              )}
              <ViewToggle view={cfView} onChange={setCfView} />
            </div>
            <div className="flex gap-3" style={{ minHeight: 400 }}>
              {/* Group tree panel */}
              <div className="w-56 shrink-0 border border-border rounded-lg overflow-hidden">
                <div className="bg-grid-header px-3 py-2 text-xs font-medium text-muted-foreground flex items-center gap-2">
                  <Layers className="w-3.5 h-3.5 text-engine-blue" />
                  Groups ({groupNames.length})
                </div>
                <div className="overflow-auto max-h-[500px]">
                  {groupNames.map((g) => (
                    <button
                      key={g}
                      onClick={() => setSelectedGroup(g)}
                      className={`w-full text-left px-3 py-1.5 text-xs transition-colors border-b border-border/30 ${
                        selectedGroup === g
                          ? "bg-primary/10 text-primary border-r-2 border-r-primary"
                          : "text-foreground hover:bg-grid-row-hover"
                      }`}
                      style={MONO}
                    >
                      {g}
                    </button>
                  ))}
                </div>
              </div>
              {/* Cashflow table */}
              <div className="flex-1 min-w-0">
                {groupLoading ? <LoadingMsg /> : groupPreview ? (
                  <CashflowTable
                    preview={groupPreview}
                    runId={run.run_id}
                    artifactName={groupArtifacts[selectedGroup]}
                  />
                ) : <EmptyMsg text="Select a group from the list." />}
              </div>
            </div>
          </div>
        ) : (
          <EmptyMsg text="No groups were defined for this run. Add grouping keys on the Run Setup page before running." />
        )
      )}

      {/* Risk tab */}
      {tab === "risk" && (
        <div className="space-y-4">
          {/* Input controls */}
          <div className="bg-card border border-border rounded-lg p-4 space-y-3">
            <h3 className="text-xs font-medium text-foreground flex items-center gap-2">
              <BarChart3 className="w-3.5 h-3.5 text-primary" /> Risk Analytics
              {hasGroups && <span className="text-muted-foreground font-normal ml-1">(portfolio + {groupNames.length} groups)</span>}
            </h3>

            {/* Base pricing scenario */}
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground w-20 shrink-0">Quote Type</span>
              <div className="flex gap-1">
                {(["yield", "price"] as const).map((kind) => (
                  <button key={kind} onClick={() => {
                    setRiskInputKind(kind);
                    setRiskBaseValue(kind === "yield" ? "6.0" : "100.0");
                    setRiskSensStep(kind === "yield" ? "1.0" : "5.0");
                  }}
                    className={`px-2.5 py-1 rounded border text-xs capitalize transition-colors ${
                      riskInputKind === kind
                        ? "bg-primary/15 text-primary border-primary/30"
                        : "text-muted-foreground border-border hover:text-foreground"
                    }`}>
                    {kind}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground w-20 shrink-0">
                Base {riskInputKind === "yield" ? "Yield %" : "Price"}
              </span>
              <input type="text" value={riskBaseValue} onChange={(e) => setRiskBaseValue(e.target.value)}
                className="w-24 px-2 py-1 bg-input-background border border-border rounded text-xs" style={MONO}
                placeholder={riskInputKind === "yield" ? "6.0" : "100.0"} />
            </div>

            {/* Sensitivity grid */}
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground w-20 shrink-0">Sensitivity</span>
              <span className="text-xs text-muted-foreground">&plusmn;</span>
              <input type="text" value={riskSensSteps} onChange={(e) => setRiskSensSteps(e.target.value)}
                className="w-14 px-2 py-1 bg-input-background border border-border rounded text-xs" style={MONO}
                placeholder="4" />
              <span className="text-xs text-muted-foreground">steps of</span>
              <input type="text" value={riskSensStep} onChange={(e) => setRiskSensStep(e.target.value)}
                className="w-16 px-2 py-1 bg-input-background border border-border rounded text-xs" style={MONO}
                placeholder={riskInputKind === "yield" ? "1.0" : "5.0"} />
              <span className="text-xs text-muted-foreground">
                {riskInputKind === "yield" ? "%" : "pts"}
              </span>
            </div>

            <button onClick={handleRisk} disabled={riskLoading}
              className="px-4 py-2 rounded bg-primary/10 border border-primary/20 text-primary text-xs hover:bg-primary/20 transition-colors disabled:opacity-40 flex items-center gap-1.5">
              {riskLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <TrendingUp className="w-3 h-3" />} Compute Risk
            </button>
          </div>

          {riskData?.risk_metrics && (() => {
            const portfolioMetrics = riskData.risk_metrics["Portfolio"];
            const groupEntries = Object.entries(riskData.risk_metrics).filter(([k]) => k !== "Portfolio");
            return (
              <>
                {/* Portfolio headline card */}
                {portfolioMetrics && (
                  <div className="bg-card border border-primary/20 rounded-lg p-4">
                    <h4 className="text-xs font-medium text-primary mb-1 flex items-center gap-2">
                      <TrendingUp className="w-3.5 h-3.5" /> Portfolio Risk
                      <span className="text-muted-foreground font-normal ml-auto text-[10px]">
                        Quoted at {riskInputKind === "yield" ? `yield = ${riskBaseValue}%` : `price = ${riskBaseValue}`}
                      </span>
                    </h4>
                    <div className="grid grid-cols-6 gap-4 mt-3">
                      <RiskCell
                        label={riskInputKind === "price" ? "Price (input)" : "Price (solved)"}
                        value={portfolioMetrics.price.toFixed(4)}
                        highlight={riskInputKind === "price"}
                      />
                      <RiskCell
                        label={riskInputKind === "yield" ? "Yield (input)" : "Yield (solved)"}
                        value={`${portfolioMetrics.yield_pct.toFixed(4)}%`}
                        highlight={riskInputKind === "yield"}
                      />
                      <RiskCell label="Mac Duration (yr)" value={portfolioMetrics.macaulay_duration_years.toFixed(4)} />
                      <RiskCell label="Mod Duration (yr)" value={portfolioMetrics.modified_duration_years.toFixed(4)} />
                      <RiskCell label="Convexity (raw)" value={portfolioMetrics.convexity_years2.toFixed(4)} />
                      <RiskCell label="Convexity (yr)" value={Math.sqrt(Math.abs(portfolioMetrics.convexity_years2)).toFixed(4)} />
                    </div>
                  </div>
                )}

                {/* Group risk table */}
                {groupEntries.length > 0 && (
                  <div className="border border-border rounded-lg overflow-hidden">
                    <div className="bg-grid-header px-3 py-2 text-xs flex items-center gap-2">
                      <Layers className="w-3.5 h-3.5 text-engine-blue" />
                      <span className="text-muted-foreground">Group Risk Metrics ({groupEntries.length} groups)</span>
                    </div>
                    <div className="overflow-auto max-h-[400px]">
                      <table className="w-full border-collapse text-xs">
                        <thead className="sticky top-0 z-10">
                          <tr className="bg-grid-header text-muted-foreground border-b border-border">
                            <th className="text-left px-3 py-1.5">Group</th>
                            <th className="text-right px-3 py-1.5">Price</th>
                            <th className="text-right px-3 py-1.5">Yield %</th>
                            <th className="text-right px-3 py-1.5">Mac Dur (yr)</th>
                            <th className="text-right px-3 py-1.5">Mod Dur (yr)</th>
                            <th className="text-right px-3 py-1.5">Cvx (raw)</th>
                            <th className="text-right px-3 py-1.5">Cvx (yr)</th>
                          </tr>
                        </thead>
                        <tbody>
                          {groupEntries.map(([label, m], ri) => (
                            <tr key={label} className={`border-b border-border/50 hover:bg-grid-row-hover ${ri % 2 === 1 ? "bg-grid-row-alt" : ""}`}>
                              <td className="px-3 py-1.5 text-foreground" style={MONO}>{label}</td>
                              <td className="text-right px-3 py-1.5" style={MONO}>{m.price.toFixed(4)}</td>
                              <td className="text-right px-3 py-1.5" style={MONO}>{m.yield_pct.toFixed(4)}%</td>
                              <td className="text-right px-3 py-1.5" style={MONO}>{m.macaulay_duration_years.toFixed(4)}</td>
                              <td className="text-right px-3 py-1.5" style={MONO}>{m.modified_duration_years.toFixed(4)}</td>
                              <td className="text-right px-3 py-1.5" style={MONO}>{m.convexity_years2.toFixed(4)}</td>
                              <td className="text-right px-3 py-1.5" style={MONO}>{Math.sqrt(Math.abs(m.convexity_years2)).toFixed(4)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            );
          })()}

          {/* Price/yield table */}
          {riskData?.price_yield_table && (
            <div className="border border-border rounded-lg overflow-hidden">
              <div className="bg-grid-header px-3 py-2 text-xs text-muted-foreground">
                {riskData.price_yield_table.input_kind === "yield" ? "Yield" : "Price"} &rarr; {riskData.price_yield_table.value_kind === "price" ? "Price" : "Yield"} Table
              </div>
              <div className="overflow-auto">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="bg-grid-header text-muted-foreground border-b border-border">
                      <th className="text-left px-3 py-1.5">Scenario</th>
                      {riskData.price_yield_table.column_inputs.map((v) => (
                        <th key={v} className="text-right px-3 py-1.5" style={MONO}>{v.toFixed(2)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {riskData.price_yield_table.scenarios.map((sc, si) => (
                      <tr key={sc} className={`border-b border-border/50 hover:bg-grid-row-hover ${
                        sc === "Portfolio" ? "bg-primary/5 font-medium" : si % 2 === 1 ? "bg-grid-row-alt" : ""
                      }`}>
                        <td className="px-3 py-1.5 text-foreground" style={MONO}>{sc}</td>
                        {riskData.price_yield_table!.values[si].map((v, vi) => (
                          <td key={vi} className="text-right px-3 py-1.5" style={MONO}>{v.toFixed(4)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {!riskData && <EmptyMsg text="Configure inputs above and click Compute." />}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared components
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
      <div className="overflow-auto max-h-[450px]">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 z-10">
            <tr className="bg-grid-header text-muted-foreground border-b border-border">
              {preview.columns.map((col) => (
                <th key={col} className="text-right px-3 py-1.5 whitespace-nowrap first:text-left">{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row, ri) => (
              <tr key={ri} className={`border-b border-border/50 hover:bg-grid-row-hover transition-colors ${ri % 2 === 1 ? "bg-grid-row-alt" : ""}`}>
                {preview.columns.map((col, ci) => (
                  <td key={col} className={`px-3 py-1 whitespace-nowrap ${ci === 0 ? "text-left" : "text-right"}`} style={MONO}>
                    {fmtNum(row[col], 2)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MetricCard({ icon: Icon, label, value }: { icon: React.ElementType; label: string; value: string }) {
  return (
    <div className="bg-card border border-border rounded-lg p-3">
      <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
        <Icon className="w-3 h-3" />
        <span className="text-[10px] uppercase tracking-wider">{label}</span>
      </div>
      <p className="text-sm font-medium text-foreground" style={MONO}>{value}</p>
    </div>
  );
}

function RiskCell({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div>
      <span className={`text-[10px] block ${highlight ? "text-primary" : "text-muted-foreground"}`}>{label}</span>
      <span className={`text-base font-medium ${highlight ? "text-primary" : "text-foreground"}`} style={MONO}>{value}</span>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-muted-foreground">{label}:</span>{" "}
      <span style={MONO}>{value}</span>
    </div>
  );
}

function TabBtn({ icon: Icon, label, active, onClick }: { icon: React.ElementType; label: string; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick}
      className={`flex items-center gap-1.5 px-3 py-2 text-xs border-b-2 transition-colors ${
        active ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
      }`}>
      <Icon className="w-3.5 h-3.5" />{label}
    </button>
  );
}

function LoadingMsg() {
  return (
    <div className="flex items-center gap-2 text-muted-foreground text-sm p-8">
      <Loader2 className="w-4 h-4 animate-spin" /> Loading...
    </div>
  );
}

function EmptyMsg({ text }: { text: string }) {
  return <div className="text-muted-foreground text-sm p-8 text-center">{text}</div>;
}

function ViewToggle({ view, onChange }: { view: CfView; onChange: (v: CfView) => void }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">View:</span>
      <div className="flex gap-1">
        {(["actual", "scheduled"] as CfView[]).map((v) => (
          <button key={v} onClick={() => onChange(v)}
            className={`px-2.5 py-1 rounded border text-xs capitalize transition-colors ${
              view === v
                ? "bg-primary/15 text-primary border-primary/30"
                : "text-muted-foreground border-border hover:text-foreground hover:bg-white/5"
            }`}>
            {v}
          </button>
        ))}
      </div>
    </div>
  );
}

function ScenarioSelector({
  scenarios, selected, onSelect,
}: {
  scenarios: string[];
  selected: string;
  onSelect: (s: string) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">Scenario:</span>
      <div className="flex gap-1">
        {scenarios.map((s) => (
          <button key={s} onClick={() => onSelect(s)}
            className={`px-2.5 py-1 rounded border text-xs transition-colors ${
              selected === s
                ? "bg-primary/15 text-primary border-primary/30"
                : "text-muted-foreground border-border hover:text-foreground hover:bg-white/5"
            }`}>
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
