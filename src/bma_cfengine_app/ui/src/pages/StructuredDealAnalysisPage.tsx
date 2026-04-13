import React, { useEffect, useMemo, useState } from "react";
import { Activity, BarChart3, Layers, ShieldAlert, Sigma } from "lucide-react";
import type { CashflowPreview, RunListItem } from "../services/api";
import * as api from "../services/api";
import TabBar from "../components/TabBar";
import DataTable, { type DataTableColumn } from "../components/DataTable";
import FormSelect from "../components/FormSelect";
import MetricCard from "../components/MetricCard";
import CollapsiblePanel from "../components/CollapsiblePanel";
import PillToggle from "../components/PillToggle";
import LoadingState from "../components/LoadingState";
import EmptyState from "../components/EmptyState";
import { fmtNamedId, fmtNum } from "../lib/format";
import CollateralRiskSettingsEditor from "../features/deals/shared/CollateralRiskSettingsEditor";
import type { CollateralRiskSettings } from "../features/deals/shared/riskSettings";
import PageStack from "../components/system/PageStack";
import SectionHeader from "../components/system/SectionHeader";
import SurfaceCard from "../components/system/SurfaceCard";
import { text } from "../components/system/ui";
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from "recharts";

type AnalysisTab = "bond_cashflows" | "waterfall" | "bond_risk" | "deal_risk" | "solver_runs";
type ChartPreset = "balance_payments" | "principal_interest" | "loss_shortfall";
const STRUCTURED_PREVIEW_MAX_ROWS = 20000;

interface Props {
  runId?: string | null;
  collateralRiskSettings: CollateralRiskSettings;
  onCollateralRiskSettingsChange: (next: CollateralRiskSettings) => void;
}

const TABS = [
  { id: "bond_cashflows", label: "Bond Cashflows", icon: BarChart3 },
  { id: "waterfall", label: "Waterfall + Triggers", icon: Layers },
  { id: "bond_risk", label: "Bond Risk", icon: ShieldAlert },
  { id: "deal_risk", label: "Deal Risk", icon: Activity },
  { id: "solver_runs", label: "Solver Runs", icon: Sigma },
] as const;
const CHART_PRESET_STORAGE_KEY = "structured_analysis_chart_presets_v1";

export default function StructuredDealAnalysisPage({
  runId,
  collateralRiskSettings,
  onCollateralRiskSettingsChange,
}: Props) {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [portfolioRuns, setPortfolioRuns] = useState<RunListItem[]>([]);
  const [uploadLibrary, setUploadLibrary] = useState<api.UploadLibraryItem[]>([]);
  const [poolSnapshots, setPoolSnapshots] = useState<api.PoolSnapshotSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>(runId ?? "");
  const [compareRunId, setCompareRunId] = useState<string>("");
  const [tab, setTab] = useState<AnalysisTab>("bond_cashflows");
  const [artifacts, setArtifacts] = useState<string[]>([]);
  const [activeArtifact, setActiveArtifact] = useState<string>("");
  const [preview, setPreview] = useState<CashflowPreview | null>(null);
  const [comparePreview, setComparePreview] = useState<CashflowPreview | null>(null);
  const [triggerDefaultActive, setTriggerDefaultActive] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);
  const [bondCashflowView, setBondCashflowView] = useState<string>("portfolio");
  const [dealBondIdsByDealId, setDealBondIdsByDealId] = useState<Record<string, string[]>>({});
  const [chartPresetByView, setChartPresetByView] = useState<Record<string, ChartPreset>>(() => {
    try {
      const raw = localStorage.getItem(CHART_PRESET_STORAGE_KEY);
      if (!raw) return {};
      return JSON.parse(raw) as Record<string, ChartPreset>;
    } catch {
      return {};
    }
  });
  useEffect(() => {
    api.listRuns("structured_deal").then((rows) => {
      setRuns(rows);
      if (!selectedRunId && rows[0]) setSelectedRunId(rows[0].run_id);
    });
    api.listRuns("portfolio").then(setPortfolioRuns).catch(() => setPortfolioRuns([]));
    api.listUploads().then((res) => setUploadLibrary(res.items)).catch(() => setUploadLibrary([]));
    api.listPoolSnapshots().then((res) => setPoolSnapshots(res.items)).catch(() => setPoolSnapshots([]));
    // load once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!runId) return;
    setSelectedRunId(runId);
  }, [runId]);

  const selectedRun = useMemo(
    () => runs.find((r) => r.run_id === selectedRunId) ?? runs[0] ?? null,
    [runs, selectedRunId],
  );

  useEffect(() => {
    if (!selectedRunId) return;
    api.getArtifacts(selectedRunId).then((res) => {
      setArtifacts(res.artifacts);
    });
  }, [selectedRunId]);

  useEffect(() => {
    if (!selectedRunId) {
      setTriggerDefaultActive(null);
      return;
    }
    const triggerArtifact = artifacts.find((a) => a.includes("trigger_state_history"));
    if (!triggerArtifact) {
      setTriggerDefaultActive(false);
      return;
    }
    api.getPreview(selectedRunId, triggerArtifact, STRUCTURED_PREVIEW_MAX_ROWS)
      .then((triggerPreview) => {
        const hasTriggerBreach = triggerPreview.rows.some((row) => {
          const state = String(row.state ?? "").trim().toLowerCase();
          if (!state) return false;
          return !["inactive", "pass", "ok", "false", "0"].includes(state);
        });
        setTriggerDefaultActive(hasTriggerBreach);
      })
      .catch(() => setTriggerDefaultActive(null));
  }, [selectedRunId, artifacts]);

  useEffect(() => {
    const dealId = selectedRun?.deal_id ?? null;
    if (!dealId || dealBondIdsByDealId[dealId]) return;
    api.getStudioDeal(dealId)
      .then((snapshot) => {
        const ir = snapshot.ir as Record<string, unknown>;
        const bonds = Array.isArray(ir?.bonds) ? ir.bonds : [];
        const names: string[] = [];
        for (const node of bonds as Array<Record<string, unknown>>) {
          const name = String(node?.name ?? "").trim();
          if (!name) continue;
          const trancheType = String(node?.tranche_type ?? "").toUpperCase();
          if (trancheType === "PSEUDO") continue;
          names.push(name);
        }
        setDealBondIdsByDealId((prev) => ({ ...prev, [dealId]: Array.from(new Set(names)) }));
      })
      .catch(() => {
        setDealBondIdsByDealId((prev) => ({ ...prev, [dealId]: [] }));
      });
  }, [selectedRun?.deal_id, dealBondIdsByDealId]);

  const filteredArtifacts = useMemo(() => {
    const byTab = {
      bond_cashflows: artifacts.filter((a) => a.endsWith("_bond_cashflows")),
      waterfall: artifacts.filter((a) => a.includes("waterfall_trace") || a.includes("trigger_state_history")),
      bond_risk: artifacts.filter((a) => a.includes("tranche_risk_summary") || a.includes("credit_enhancement")),
      deal_risk: artifacts.filter(
        (a) =>
          a.includes("decrement_table")
          || a.includes("stress_matrix")
          || a.includes("pac_tac_diagnostics")
          || a.includes("structure_composition"),
      ),
      solver_runs: artifacts.filter(
        (a) =>
          a.includes("solver_iterations")
          || a.includes("solver_selected_solution")
          || a.includes("solver_ce_ladder")
          || a.includes("solver_loss_multiple_coverage")
          || a.includes("solver_trigger_breach_timeline")
          || a.includes("solver_stepdown_gate_status")
          || a.includes("solver_pac_tac_behavior")
          || a.includes("solver_z_support_profile"),
      ),
      solver_runs_sensitivity: artifacts.filter((a) => a.includes("solver_sensitivity")),
    } as const;
    if (tab !== "solver_runs") return byTab[tab];
    return [...byTab.solver_runs, ...byTab.solver_runs_sensitivity];
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
    api.getPreview(selectedRunId, activeArtifact, STRUCTURED_PREVIEW_MAX_ROWS)
      .then(setPreview)
      .finally(() => setLoading(false));
  }, [selectedRunId, activeArtifact]);

  useEffect(() => {
    if (!compareRunId || !activeArtifact || tab !== "solver_runs") {
      setComparePreview(null);
      return;
    }
    api.getPreview(compareRunId, activeArtifact, STRUCTURED_PREVIEW_MAX_ROWS)
      .then(setComparePreview)
      .catch(() => setComparePreview(null));
  }, [compareRunId, activeArtifact, tab]);

  useEffect(() => {
    try {
      localStorage.setItem(CHART_PRESET_STORAGE_KEY, JSON.stringify(chartPresetByView));
    } catch {
      // ignore storage errors
    }
  }, [chartPresetByView]);

  const bondIdColumn = useMemo(() => {
    if (tab !== "bond_cashflows" || !preview) return null;
    const candidates = ["tranche_id", "bond_id", "bond", "tranche", "name", "class"];
    for (const c of candidates) {
      if (preview.columns.includes(c)) return c;
    }
    return null;
  }, [tab, preview]);

  const periodColumn = useMemo(() => {
    if (!preview) return null;
    const candidates = ["period", "month", "time"];
    for (const c of candidates) {
      if (preview.columns.includes(c)) return c;
    }
    return null;
  }, [preview]);

  const bondIds = useMemo(() => {
    if (!preview || !bondIdColumn) return [];
    const values = new Set<string>();
    for (const row of preview.rows) {
      const raw = row[bondIdColumn];
      if (raw == null) continue;
      values.add(String(raw));
    }
    const rawIds = Array.from(values);
    const dealId = selectedRun?.deal_id ?? null;
    const configuredBondIds = dealId ? (dealBondIdsByDealId[dealId] ?? null) : null;
    if (configuredBondIds && configuredBondIds.length > 0) {
      const allowed = new Set(configuredBondIds);
      const filtered = rawIds.filter((id) => allowed.has(id));
      if (filtered.length > 0) return filtered;
    }
    return rawIds;
  }, [preview, bondIdColumn, selectedRun?.deal_id, dealBondIdsByDealId]);

  useEffect(() => {
    if (tab !== "bond_cashflows") return;
    if (bondCashflowView === "portfolio") return;
    if (!bondIds.includes(bondCashflowView)) {
      setBondCashflowView("portfolio");
    }
  }, [tab, bondCashflowView, bondIds]);

  const displayedPreview = useMemo(() => {
    if (!preview || tab !== "bond_cashflows") return preview;
    if (bondCashflowView === "portfolio") {
      if (!periodColumn) return preview;
      const grouped = new Map<string, Record<string, unknown>>();
      const numericColumns = preview.columns.filter(
        (col) => col !== periodColumn && col !== bondIdColumn && col !== "scenario_name",
      );
      for (const row of preview.rows) {
        const periodKey = String(row[periodColumn] ?? "");
        if (!grouped.has(periodKey)) {
          const seed: Record<string, unknown> = { [periodColumn]: row[periodColumn] ?? periodKey };
          for (const col of numericColumns) seed[col] = 0;
          grouped.set(periodKey, seed);
        }
        const agg = grouped.get(periodKey)!;
        for (const col of numericColumns) {
          const v = Number(row[col]);
          if (Number.isFinite(v)) {
            agg[col] = Number(agg[col] ?? 0) + v;
          }
        }
      }
      const rows = Array.from(grouped.values()).sort(
        (a, b) => Number(a[periodColumn] ?? 0) - Number(b[periodColumn] ?? 0),
      );
      return {
        ...preview,
        section: `${preview.section}_portfolio`,
        rows,
        row_count: rows.length,
      };
    }
    if (!bondIdColumn) return preview;
    const rows = preview.rows.filter((row) => String(row[bondIdColumn] ?? "") === bondCashflowView);
    return {
      ...preview,
      section: `${preview.section}_${bondCashflowView}`,
      rows,
      row_count: rows.length,
    };
  }, [preview, tab, bondCashflowView, periodColumn, bondIdColumn]);

  const portfolioRiskRows = useMemo(() => {
    if (!preview || tab !== "bond_cashflows" || !bondIdColumn || !periodColumn) return [];
    const byBond = new Map<string, Record<string, unknown>[]>();
    for (const row of preview.rows) {
      const bond = String(row[bondIdColumn] ?? "");
      if (!bond) continue;
      if (!byBond.has(bond)) byBond.set(bond, []);
      byBond.get(bond)!.push(row);
    }
    const sumColumn = (rows: Record<string, unknown>[], candidates: string[]): number => {
      const key = candidates.find((c) => preview.columns.includes(c));
      if (!key) return 0;
      return rows.reduce((acc, r) => {
        const v = Number(r[key]);
        return Number.isFinite(v) ? acc + v : acc;
      }, 0);
    };
    const maxColumn = (rows: Record<string, unknown>[], candidates: string[]): number => {
      const key = candidates.find((c) => preview.columns.includes(c));
      if (!key) return 0;
      return rows.reduce((acc, r) => {
        const v = Number(r[key]);
        return Number.isFinite(v) ? Math.max(acc, v) : acc;
      }, 0);
    };
    const lastColumn = (rows: Record<string, unknown>[], candidates: string[]): number => {
      const key = candidates.find((c) => preview.columns.includes(c));
      if (!key || rows.length === 0) return 0;
      const sorted = [...rows].sort(
        (a, b) => Number(a[periodColumn] ?? 0) - Number(b[periodColumn] ?? 0),
      );
      const v = Number(sorted[sorted.length - 1][key]);
      return Number.isFinite(v) ? v : 0;
    };

    return Array.from(byBond.entries()).map(([bond, rows]) => {
      const totalPrincipal = sumColumn(rows, ["total_principal", "principal_paid", "principal"]);
      const walNumerator = rows.reduce((acc, r) => {
        const p = Number(r["total_principal"]);
        const t = Number(r[periodColumn]);
        if (!Number.isFinite(p) || !Number.isFinite(t)) return acc;
        return acc + t * p;
      }, 0);
      const walYears = totalPrincipal > 0 ? walNumerator / totalPrincipal / 12 : 0;
      return {
        bond,
        total_interest: sumColumn(rows, ["interest_paid", "total_interest", "interest"]),
        total_principal: totalPrincipal,
        principal_loss: sumColumn(rows, ["writedown", "principal_loss"]),
        shortfall_peak: maxColumn(rows, ["interest_shortfall", "shortfall"]),
        ending_balance: lastColumn(rows, ["end_balance", "balance"]),
        wal_years: walYears,
        interest_default: maxColumn(rows, ["interest_shortfall", "shortfall"]) > 0.0001,
        principal_default:
          sumColumn(rows, ["writedown", "principal_loss"]) > 0.0001 ||
          lastColumn(rows, ["end_balance", "balance"]) > 0.01,
      };
    });
  }, [preview, tab, bondIdColumn, periodColumn]);

  const currentViewKey = tab === "bond_cashflows" ? bondCashflowView : "portfolio";
  const activeChartPreset: ChartPreset = chartPresetByView[currentViewKey] ?? "balance_payments";
  const setActiveChartPreset = (preset: string) => {
    setChartPresetByView((prev) => ({ ...prev, [currentViewKey]: preset as ChartPreset }));
  };

  const selectedRiskSnapshot = useMemo(() => {
    if (tab !== "bond_cashflows") return null;
    if (bondCashflowView === "portfolio") {
      if (!portfolioRiskRows.length) return null;
      const totalPrincipal = portfolioRiskRows.reduce((acc, row) => acc + Number(row.total_principal || 0), 0);
      const weightedWal = portfolioRiskRows.reduce(
        (acc, row) => acc + Number(row.wal_years || 0) * Number(row.total_principal || 0),
        0,
      );
      return {
        scope: "Portfolio",
        total_interest: portfolioRiskRows.reduce((acc, row) => acc + Number(row.total_interest || 0), 0),
        total_principal: totalPrincipal,
        principal_loss: portfolioRiskRows.reduce((acc, row) => acc + Number(row.principal_loss || 0), 0),
        shortfall_peak: portfolioRiskRows.reduce(
          (acc, row) => Math.max(acc, Number(row.shortfall_peak || 0)),
          0,
        ),
        ending_balance: portfolioRiskRows.reduce((acc, row) => acc + Number(row.ending_balance || 0), 0),
        wal_years: totalPrincipal > 0 ? weightedWal / totalPrincipal : 0,
        interest_default: portfolioRiskRows.some((row) => Boolean(row.interest_default)),
        principal_default: portfolioRiskRows.some((row) => Boolean(row.principal_default)),
        interest_default_count: portfolioRiskRows.filter((row) => Boolean(row.interest_default)).length,
        principal_default_count: portfolioRiskRows.filter((row) => Boolean(row.principal_default)).length,
      };
    }
    const bond = portfolioRiskRows.find((row) => row.bond === bondCashflowView);
    if (!bond) return null;
    return {
      scope: bondCashflowView,
      ...bond,
      interest_default_count: bond.interest_default ? 1 : 0,
      principal_default_count: bond.principal_default ? 1 : 0,
    };
  }, [tab, bondCashflowView, portfolioRiskRows]);

  if (!runs.length) {
    return (
      <PageStack>
        <CollapsiblePanel title="Collateral Risk Source" defaultOpen>
          <div className="p-3">
            <CollateralRiskSettingsEditor
              value={collateralRiskSettings}
              onChange={onCollateralRiskSettingsChange}
              availableRuns={portfolioRuns}
              availableTapes={uploadLibrary}
              poolSnapshots={poolSnapshots}
              title="Mirrored risk settings"
            />
          </div>
        </CollapsiblePanel>
        <EmptyState message="No structured deal runs yet. Configure risk here, then execute from Structuring Studio." />
      </PageStack>
    );
  }

  if (!selectedRun) return null;

  return (
    <PageStack>
      <CollapsiblePanel title="Collateral Risk Source" defaultOpen>
        <div className="p-3">
          <CollateralRiskSettingsEditor
            value={collateralRiskSettings}
            onChange={onCollateralRiskSettingsChange}
            availableRuns={portfolioRuns}
            availableTapes={uploadLibrary}
            poolSnapshots={poolSnapshots}
            title="Mirrored risk settings"
          />
        </div>
      </CollapsiblePanel>

      <SurfaceCard>
        <SectionHeader
          title="Run Selection"
          subtitle="Pick the base run and optional compare run for solver diagnostics."
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className={text.label}>Run:</span>
          <FormSelect
            value={selectedRunId}
            onChange={(e) => setSelectedRunId(e.target.value)}
            className="w-auto min-w-[280px]"
          >
            {runs.map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {`${fmtNamedId(run.deal_name ?? "Structured Deal", run.run_id)} - ${(run.scenario_names ?? []).join(", ") || "Base Case"}`}
              </option>
            ))}
          </FormSelect>
          {tab === "solver_runs" && (
            <>
              <span className={`${text.label} ml-2`}>Compare:</span>
              <FormSelect
                value={compareRunId}
                onChange={(e) => setCompareRunId(e.target.value)}
                className="w-auto min-w-[240px]"
              >
                <option value="">None</option>
                {runs
                  .filter((run) => run.run_id !== selectedRunId && run.run_kind === "solver")
                  .map((run) => (
                    <option key={run.run_id} value={run.run_id}>
                      {`${fmtNamedId(run.deal_name ?? "Structured Deal", run.run_id)} - ${(run.scenario_names ?? []).join(", ") || "Base Case"}`}
                    </option>
                  ))}
              </FormSelect>
            </>
          )}
        </div>
      </SurfaceCard>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard icon={Layers} label="Deal" value={selectedRun.deal_name ?? "Structured Deal"} />
        <MetricCard icon={BarChart3} label="Scenarios" value={String((selectedRun.scenario_names ?? []).length || 1)} />
        <MetricCard icon={ShieldAlert} label="Status" value={selectedRun.status} />
        <MetricCard icon={Activity} label="Runtime" value={selectedRun.elapsed_seconds != null ? `${selectedRun.elapsed_seconds.toFixed(2)}s` : "—"} />
      </div>

      <TabBar tabs={TABS as any} active={tab} onSelect={(id) => setTab(id as AnalysisTab)} />

      <CollapsiblePanel title="Artifacts" defaultOpen>
        <div className="p-3">
          <SectionHeader title="Artifacts" />
          <p className="text-xs text-muted-foreground mt-2 mb-2">
            {tab === "bond_cashflows" && "Scenario-level tranche cashflow paths."}
            {tab === "waterfall" && "Waterfall trace and trigger timelines."}
            {tab === "bond_risk" && "Per-tranche WAL, CE and risk metrics."}
            {tab === "deal_risk" && "Stress/decrement diagnostics plus PAC/TAC schedule and Z/support composition views."}
            {tab === "solver_runs"
              && "Solver iteration trajectory plus CE ladders, loss-multiple coverage, trigger breach timelines, step-down diagnostics, and PAC/TAC/Z behavior diagnostics."}
          </p>
          {!filteredArtifacts.length ? (
            <EmptyState message="No artifacts available for this view in the selected run." />
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Artifact:</span>
              <FormSelect
                value={activeArtifact}
                onChange={(e) => setActiveArtifact(e.target.value)}
                className="w-auto"
              >
                {filteredArtifacts.map((artifact) => (
                  <option key={artifact} value={artifact}>
                    {artifact}
                  </option>
                ))}
              </FormSelect>
            </div>
          )}
        </div>
      </CollapsiblePanel>

      <CollapsiblePanel title="Data Preview" defaultOpen>
        <div className="p-3">
          {loading && <LoadingState message="Loading artifact preview..." />}
          {!loading && !preview && <EmptyState message="Select an artifact to inspect." />}
          {!loading && preview && tab === "bond_cashflows" && (
            <>
              <div className="sticky top-0 z-20 bg-[#0d1220]/95 backdrop-blur-sm border-b border-border mb-3 pb-2 pt-1">
                <PillToggle
                  label="Cashflow View"
                  selected={bondCashflowView}
                  onSelect={setBondCashflowView}
                  options={[
                    { id: "portfolio", label: "Portfolio" },
                    ...bondIds.map((bondId) => ({ id: bondId, label: bondId })),
                  ]}
                />
              </div>
              {bondCashflowView === "portfolio" && portfolioRiskRows.length > 0 && (
                <div className="mb-4">
                  <DataTable
                    tableId={`structured_portfolio_risk_${selectedRunId}`}
                    maxHeight="280px"
                    columns={[
                      { id: "bond", header: "Bond", accessorKey: "bond", align: "left" },
                      {
                        id: "total_interest",
                        header: "Total Interest",
                        accessorKey: "total_interest",
                        align: "right",
                        cell: (value) => formatCell(value, "interest"),
                      },
                      {
                        id: "total_principal",
                        header: "Total Principal",
                        accessorKey: "total_principal",
                        align: "right",
                        cell: (value) => formatCell(value, "principal"),
                      },
                      {
                        id: "principal_loss",
                        header: "Principal Loss",
                        accessorKey: "principal_loss",
                        align: "right",
                        cell: (value) => formatCell(value, "loss"),
                      },
                      {
                        id: "shortfall_peak",
                        header: "Shortfall Peak",
                        accessorKey: "shortfall_peak",
                        align: "right",
                        cell: (value) => formatCell(value, "shortfall"),
                      },
                      {
                        id: "ending_balance",
                        header: "Ending Balance",
                        accessorKey: "ending_balance",
                        align: "right",
                        cell: (value) => formatCell(value, "balance"),
                      },
                      {
                        id: "wal_years",
                        header: "WAL (yrs)",
                        accessorKey: "wal_years",
                        align: "right",
                        cell: (value) => formatCell(value, "wal_years"),
                      },
                      {
                        id: "interest_default",
                        header: "Interest Default",
                        accessorKey: "interest_default",
                        align: "center",
                        cell: (value) => (value ? "Yes" : "No"),
                      },
                      {
                        id: "principal_default",
                        header: "Principal Default",
                        accessorKey: "principal_default",
                        align: "center",
                        cell: (value) => (value ? "Yes" : "No"),
                      },
                    ]}
                    data={portfolioRiskRows}
                  />
                </div>
              )}
            </>
          )}
          {!loading && displayedPreview && (
            <DataTable
              tableId={`structured_${tab}_${displayedPreview.section}`}
              maxHeight="520px"
              columns={displayedPreview.columns.map((col, idx): DataTableColumn<Record<string, unknown>> => ({
                id: col,
                header: col,
                accessorKey: col,
                align: idx === 0 ? "left" : "right",
                cell: (value) => formatCell(value, col),
              }))}
              data={displayedPreview.rows}
            />
          )}
          {!loading && displayedPreview && tab === "bond_cashflows" && (
            <SurfaceCard className="mt-3" padded={false}>
              <div className="p-3">
                <SectionHeader
                  title={bondCashflowView === "portfolio" ? "Portfolio Cashflow Visuals" : `${bondCashflowView} Cashflow Visuals`}
                  subtitle="Balance path and payment streams by period."
                />
              </div>
              {selectedRiskSnapshot && (
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2 px-3 pb-3">
                  <MetricCard icon={Layers} label="Scope" value={selectedRiskSnapshot.scope} />
                  <MetricCard icon={BarChart3} label="Tot Principal" value={fmtNum(selectedRiskSnapshot.total_principal, 2)} />
                  <MetricCard icon={BarChart3} label="Tot Interest" value={fmtNum(selectedRiskSnapshot.total_interest, 2)} />
                  <MetricCard icon={ShieldAlert} label="Prin Loss" value={fmtNum(selectedRiskSnapshot.principal_loss, 2)} />
                  <MetricCard icon={Activity} label="Peak Shortfall" value={fmtNum(selectedRiskSnapshot.shortfall_peak, 2)} />
                  <MetricCard icon={Layers} label="End Balance" value={fmtNum(selectedRiskSnapshot.ending_balance, 2)} />
                  <MetricCard icon={Sigma} label="WAL (yrs)" value={fmtNum(selectedRiskSnapshot.wal_years, 3)} />
                </div>
              )}
              {selectedRiskSnapshot && (
                <div className="px-3 pb-3">
                  <SectionHeader
                    title="Base-Case Default Diagnostics"
                    subtitle="Flags highlight trigger breaches, interest shortfalls, and principal impairment/maturity shortfalls."
                  />
                  <div className="mt-2 grid grid-cols-1 md:grid-cols-3 gap-2">
                    <DefaultFlagCard
                      label="Trigger Default"
                      active={Boolean(triggerDefaultActive)}
                      detail={triggerDefaultActive === null ? "Unknown" : triggerDefaultActive ? "Breached" : "No breach"}
                    />
                    <DefaultFlagCard
                      label="Interest Default"
                      active={Boolean(selectedRiskSnapshot.interest_default)}
                      detail={
                        selectedRiskSnapshot.scope === "Portfolio"
                          ? `${selectedRiskSnapshot.interest_default_count} bond(s) with shortfall`
                          : selectedRiskSnapshot.interest_default
                            ? "Interest shortfall present"
                            : "No shortfall"
                      }
                    />
                    <DefaultFlagCard
                      label="Principal Default"
                      active={Boolean(selectedRiskSnapshot.principal_default)}
                      detail={
                        selectedRiskSnapshot.scope === "Portfolio"
                          ? `${selectedRiskSnapshot.principal_default_count} bond(s) with loss/ending balance`
                          : selectedRiskSnapshot.principal_default
                            ? "Principal loss or ending balance > 0"
                            : "Fully repaid without loss"
                      }
                    />
                  </div>
                </div>
              )}
              <div className="px-3 pb-3">
                <PillToggle
                  label="Chart Preset"
                  selected={activeChartPreset}
                  onSelect={setActiveChartPreset}
                  options={[
                    { id: "balance_payments", label: "Balance + Payments" },
                    { id: "principal_interest", label: "Principal vs Interest" },
                    { id: "loss_shortfall", label: "Loss + Shortfall" },
                  ]}
                />
              </div>
              <div className="h-64 px-3 pb-3">
                <CashflowVisualChart preview={displayedPreview} preset={activeChartPreset} />
              </div>
            </SurfaceCard>
          )}
        </div>
      </CollapsiblePanel>

      {tab === "solver_runs" && comparePreview && preview && (
        <CollapsiblePanel title="Compare Runs (Selected Solution Diff)" defaultOpen>
          <div className="p-3">
            <DataTable
              tableId={`solver_compare_${selectedRunId}_${compareRunId}_${activeArtifact}`}
              columns={[
                { id: "metric", header: "Metric", accessorKey: "metric", mono: false },
                { id: "base", header: "Selected", accessorKey: "base", align: "right" },
                { id: "compare", header: "Compare", accessorKey: "compare", align: "right" },
                { id: "delta", header: "Delta", accessorKey: "delta", align: "right" },
              ]}
              data={buildComparisonRows(preview, comparePreview)}
              emptyMessage="No comparable numeric metrics."
            />
          </div>
        </CollapsiblePanel>
      )}
    </PageStack>
  );
}

function DefaultFlagCard({ label, active, detail }: { label: string; active: boolean; detail: string }) {
  return (
    <div className={`rounded-md border px-3 py-2 ${active ? "border-red-500/50 bg-red-500/10" : "border-emerald-500/50 bg-emerald-500/10"}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className={`text-xs font-semibold ${active ? "text-red-300" : "text-emerald-300"}`}>
          {active ? "Default" : "OK"}
        </span>
      </div>
      <div className="text-xs mt-1">{detail}</div>
    </div>
  );
}

function formatCell(value: unknown, column: string): string {
  if (value == null) return "—";
  if (typeof value === "number") {
    const lower = column.toLowerCase();
    // Cashflow and balance figures should always show full precision, no K/M/B abbreviation.
    if (
      lower.includes("cash") ||
      lower.includes("balance") ||
      lower.includes("principal") ||
      lower.includes("interest") ||
      lower.includes("loss") ||
      lower.includes("recovery") ||
      lower.includes("amount")
    ) {
      return fmtNum(value, 2);
    }
    return fmtNum(value, 4);
  }
  return String(value);
}

function CashflowVisualChart({ preview, preset }: { preview: CashflowPreview; preset: ChartPreset }) {
  const periodKey =
    preview.columns.find((c) => c === "period" || c === "month" || c === "time") ?? preview.columns[0];
  const balanceKey = preview.columns.find((c) => c === "end_balance" || c === "balance");
  const principalKey = preview.columns.find((c) => c === "total_principal" || c === "principal_paid");
  const interestKey = preview.columns.find((c) => c === "interest_paid" || c === "total_interest");
  const lossKey = preview.columns.find((c) => c === "writedown" || c === "principal_loss" || c === "loss");
  const shortfallKey = preview.columns.find((c) => c === "interest_shortfall" || c === "shortfall");
  const chartRows = preview.rows
    .slice(0, 240)
    .map((row) => ({
      period: Number(row[periodKey] ?? 0),
      end_balance: Number(balanceKey ? row[balanceKey] : 0) || 0,
      principal: Number(principalKey ? row[principalKey] : 0) || 0,
      interest: Number(interestKey ? row[interestKey] : 0) || 0,
      principal_loss: Number(lossKey ? row[lossKey] : 0) || 0,
      shortfall: Number(shortfallKey ? row[shortfallKey] : 0) || 0,
    }))
    .sort((a, b) => a.period - b.period);
  if (!chartRows.length) return <EmptyState message="No chartable cashflow rows." />;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={chartRows}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
        <XAxis dataKey="period" tick={{ fontSize: 11 }} />
        <YAxis yAxisId="left" tick={{ fontSize: 11 }} tickFormatter={(v) => fmtNum(v, 0)} />
        <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} tickFormatter={(v) => fmtNum(v, 0)} />
        <Tooltip formatter={(v: unknown) => (typeof v === "number" ? fmtNum(v, 2) : String(v))} />
        <Legend />
        {preset === "balance_payments" && (
          <>
            <Bar yAxisId="right" dataKey="principal" name="Principal" fill="#3b82f6" />
            <Bar yAxisId="right" dataKey="interest" name="Interest" fill="#f59e0b" />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="end_balance"
              name="End Balance"
              stroke="#22c55e"
              dot={false}
              strokeWidth={2}
            />
          </>
        )}
        {preset === "principal_interest" && (
          <>
            <Bar yAxisId="left" dataKey="principal" name="Principal" fill="#2563eb" />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="interest"
              name="Interest"
              stroke="#f97316"
              dot={false}
              strokeWidth={2}
            />
          </>
        )}
        {preset === "loss_shortfall" && (
          <>
            <Bar yAxisId="left" dataKey="principal_loss" name="Principal Loss" fill="#ef4444" />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="shortfall"
              name="Interest Shortfall"
              stroke="#f59e0b"
              dot={false}
              strokeWidth={2}
            />
          </>
        )}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function buildComparisonRows(base: CashflowPreview, compare: CashflowPreview): Array<{
  metric: string;
  base: string;
  compare: string;
  delta: string;
}> {
  const b0 = (base.rows?.[0] ?? {}) as Record<string, unknown>;
  const c0 = (compare.rows?.[0] ?? {}) as Record<string, unknown>;
  const columns = new Set([...Object.keys(b0), ...Object.keys(c0)]);
  const rows: Array<{ metric: string; base: string; compare: string; delta: string }> = [];
  for (const col of columns) {
    const bv = Number(b0[col]);
    const cv = Number(c0[col]);
    if (!Number.isFinite(bv) || !Number.isFinite(cv)) continue;
    rows.push({
      metric: col,
      base: fmtNum(bv, 4),
      compare: fmtNum(cv, 4),
      delta: fmtNum(bv - cv, 4),
    });
  }
  return rows;
}

