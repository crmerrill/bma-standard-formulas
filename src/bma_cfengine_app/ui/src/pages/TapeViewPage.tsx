import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  BarChart3, Hash, DollarSign, Percent, Clock, ChevronDown, Table2,
  Layers, Filter, X, GripVertical, AlertTriangle, Check, Wrench, Eye,
  Loader2, Plus, Trash2, Download, FileSpreadsheet, PieChart, ListTree,
} from "lucide-react";
import type {
  TapeStats, TapePreview, StratDimension, StratResult,
  DiagnoseResult, RepairPreview, TapeSummaryResult, UniqueValuesResult,
} from "../services/api";
import * as api from "../services/api";
import { MONO, fmtCcy, fmtNum, STRAT_COL_LABELS, formatStratCell } from "../lib/format";
import DataTable, { type DataTableColumn } from "../components/DataTable";
import TabBar from "../components/TabBar";
import MetricCard from "../components/MetricCard";
import SummaryRow from "../components/SummaryRow";
import CollapsiblePanel from "../components/CollapsiblePanel";
import LoadingState from "../components/LoadingState";
import EmptyState from "../components/EmptyState";
import MonoChip from "../components/MonoChip";

type Tab = "grid" | "summary" | "strats";

interface ColumnFilter {
  column: string;
  selected: Set<string>;
}

interface Props {
  uploadId: string;
  mappingId: string;
}

export default function TapeViewPage({ uploadId, mappingId }: Props) {
  const [stats, setStats] = useState<TapeStats | null>(null);
  const [preview, setPreview] = useState<TapePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("grid");

  const [filters, setFilters] = useState<ColumnFilter[]>([]);
  const [openFilterCol, setOpenFilterCol] = useState<string | null>(null);

  const [dimensions, setDimensions] = useState<StratDimension[]>([]);
  const [tapeSummary, setTapeSummary] = useState<TapeSummaryResult | null>(null);
  const [uniqueValues, setUniqueValues] = useState<UniqueValuesResult | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  interface DrillDown {
    parentBucket: string;
    filterCol: string;
    filterVal: string;
    dimension: string;
    result: StratResult | null;
    loading: boolean;
  }

  interface StratGroup {
    id: number;
    dimensions: string[];
    result: StratResult | null;
    loading: boolean;
    drillDown: DrillDown | null;
  }
  const [stratGroups, setStratGroups] = useState<StratGroup[]>([
    { id: 0, dimensions: [], result: null, loading: false, drillDown: null },
  ]);
  const nextStratId = useRef(1);

  const [diagnosis, setDiagnosis] = useState<DiagnoseResult | null>(null);
  const [repairPreview, setRepairPreview] = useState<RepairPreview | null>(null);
  const [previewingRule, setPreviewingRule] = useState<string | null>(null);
  const [applyingRule, setApplyingRule] = useState<string | null>(null);
  const [hasWorkingCopy, setHasWorkingCopy] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const reload = () => {
    setLoading(true);
    Promise.all([
      api.getTapeStats(uploadId, mappingId),
      api.getTapePreview(uploadId, 500, mappingId),
      api.getStratDimensions(uploadId, mappingId),
      api.diagnoseTape(uploadId, mappingId),
      api.getUploadStatus(uploadId),
    ])
      .then(([s, p, dims, diag, status]) => {
        setStats(s);
        setPreview(p);
        setDimensions(dims);
        setDiagnosis(diag);
        setHasWorkingCopy(status.has_working_copy);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    reload();
  }, [uploadId, mappingId, refreshKey]);

  const handlePreviewRepair = async (ruleId: string) => {
    setPreviewingRule(ruleId);
    try {
      const pv = await api.getRepairPreview(uploadId, ruleId, mappingId);
      setRepairPreview(pv);
    } finally {
      setPreviewingRule(null);
    }
  };

  const handleApplyRepair = async (ruleId: string) => {
    setApplyingRule(ruleId);
    try {
      const res = await api.applyRepair(uploadId, ruleId, mappingId);
      setHasWorkingCopy(res.has_working_copy);
      setRepairPreview(null);
      setRefreshKey((k) => k + 1);
    } finally {
      setApplyingRule(null);
    }
  };

  const handleRevert = async () => {
    await api.revertToRaw(uploadId);
    setHasWorkingCopy(false);
    setRepairPreview(null);
    setRefreshKey((k) => k + 1);
  };

  const allUniqueValues = useMemo(() => {
    if (!preview) return {};
    const map: Record<string, string[]> = {};
    for (const col of preview.columns) {
      const vals = new Set<string>();
      for (const row of preview.rows) {
        vals.add(String(row[col] ?? ""));
      }
      map[col] = Array.from(vals).sort();
    }
    return map;
  }, [preview]);

  const filteredRows = useMemo(() => {
    if (!preview) return [];
    if (filters.length === 0) return preview.rows;
    return preview.rows.filter((row) =>
      filters.every((f) => f.selected.has(String(row[f.column] ?? "")))
    );
  }, [preview, filters]);

  const contextualUniqueValues = useMemo(() => {
    if (!preview) return {};
    const map: Record<string, string[]> = {};
    for (const col of preview.columns) {
      const otherFilters = filters.filter((f) => f.column !== col);
      const subset =
        otherFilters.length === 0
          ? preview.rows
          : preview.rows.filter((row) =>
              otherFilters.every((f) =>
                f.selected.has(String(row[f.column] ?? ""))
              )
            );
      const vals = new Set<string>();
      for (const row of subset) {
        vals.add(String(row[col] ?? ""));
      }
      map[col] = Array.from(vals).sort();
    }
    return map;
  }, [preview, filters]);

  const toggleFilterValue = (column: string, value: string) => {
    setFilters((prev) => {
      const existing = prev.find((f) => f.column === column);
      if (!existing) {
        const allVals = new Set(allUniqueValues[column] ?? []);
        allVals.delete(value);
        return [...prev, { column, selected: allVals }];
      }
      const next = new Set(existing.selected);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      if (next.size === (allUniqueValues[column]?.length ?? 0)) {
        return prev.filter((f) => f.column !== column);
      }
      return prev.map((f) => (f.column === column ? { ...f, selected: next } : f));
    });
  };

  const selectAllForColumn = (column: string) => {
    setFilters((prev) => prev.filter((f) => f.column !== column));
  };

  const selectNoneForColumn = (column: string) => {
    setFilters((prev) => {
      const existing = prev.find((f) => f.column === column);
      if (existing) {
        return prev.map((f) =>
          f.column === column ? { ...f, selected: new Set<string>() } : f
        );
      }
      return [...prev, { column, selected: new Set<string>() }];
    });
  };

  const removeFilter = (column: string) => {
    setFilters((prev) => prev.filter((f) => f.column !== column));
    setOpenFilterCol(null);
  };

  const clearAllFilters = () => {
    setFilters([]);
    setOpenFilterCol(null);
  };

  // Drag reorder for filter chips
  const dragIdx = useRef<number | null>(null);
  const [dragOverIdx, setDragOverIdx] = useState<number | null>(null);

  const handleChipDragStart = (idx: number) => {
    dragIdx.current = idx;
  };
  const handleChipDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault();
    setDragOverIdx(idx);
  };
  const handleChipDrop = (idx: number) => {
    if (dragIdx.current !== null && dragIdx.current !== idx) {
      setFilters((prev) => {
        const next = [...prev];
        const [moved] = next.splice(dragIdx.current!, 1);
        next.splice(idx, 0, moved);
        return next;
      });
    }
    dragIdx.current = null;
    setDragOverIdx(null);
  };

  useEffect(() => {
    if (tab !== "summary" || tapeSummary || summaryLoading) return;
    setSummaryLoading(true);
    Promise.all([
      api.getTapeSummary(uploadId, mappingId),
      api.getUniqueValues(uploadId, mappingId),
    ])
      .then(([ts, uv]) => { setTapeSummary(ts); setUniqueValues(uv); })
      .finally(() => setSummaryLoading(false));
  }, [tab, uploadId, mappingId]);

  const runStratForGroup = async (groupId: number, dims: string[]) => {
    setStratGroups((prev) =>
      prev.map((g) => (g.id === groupId ? { ...g, dimensions: dims, result: null, loading: dims.length > 0, drillDown: null } : g))
    );
    if (dims.length === 0) return;
    try {
      const groupBy = dims.length === 1 ? dims[0] : dims;
      const res = await api.computeStrat(uploadId, groupBy, mappingId);
      setStratGroups((prev) =>
        prev.map((g) => (g.id === groupId ? { ...g, result: res, loading: false } : g))
      );
    } catch {
      setStratGroups((prev) =>
        prev.map((g) => (g.id === groupId ? { ...g, loading: false } : g))
      );
    }
  };

  const handleSetDimension = (groupId: number, index: number, dim: string) => {
    setStratGroups((prev) => {
      const g = prev.find((x) => x.id === groupId);
      if (!g) return prev;
      const next = [...g.dimensions];
      if (dim) {
        next[index] = dim;
      } else {
        next.splice(index, 1);
      }
      return prev.map((x) => (x.id === groupId ? { ...x, dimensions: next } : x));
    });
  };

  const handleRunStrat = (groupId: number) => {
    const g = stratGroups.find((x) => x.id === groupId);
    if (g) runStratForGroup(groupId, g.dimensions.filter(Boolean));
  };

  const handleAddDimToGroup = (groupId: number) => {
    setStratGroups((prev) =>
      prev.map((g) => (g.id === groupId ? { ...g, dimensions: [...g.dimensions, ""] } : g))
    );
  };

  const handleDrillDown = async (groupId: number, bucket: string, filterCol: string, filterVal: string) => {
    setStratGroups((prev) =>
      prev.map((g) => (g.id === groupId ? { ...g, drillDown: { parentBucket: bucket, filterCol, filterVal, dimension: "", result: null, loading: false } } : g))
    );
  };

  const handleRunDrillDown = async (groupId: number, dim: string) => {
    const g = stratGroups.find((x) => x.id === groupId);
    if (!g?.drillDown) return;
    const dd = g.drillDown;
    setStratGroups((prev) =>
      prev.map((x) => (x.id === groupId ? { ...x, drillDown: { ...dd, dimension: dim, result: null, loading: !!dim } } : x))
    );
    if (!dim) return;
    try {
      const res = await api.computeStrat(uploadId, dim, mappingId, 10, { [dd.filterCol]: dd.filterVal });
      setStratGroups((prev) =>
        prev.map((x) => (x.id === groupId ? { ...x, drillDown: { ...dd, dimension: dim, result: res, loading: false } } : x))
      );
    } catch {
      setStratGroups((prev) =>
        prev.map((x) => (x.id === groupId ? { ...x, drillDown: { ...(x.drillDown!), loading: false } } : x))
      );
    }
  };

  const addStratGroup = () => {
    const id = nextStratId.current++;
    setStratGroups((prev) => [...prev, { id, dimensions: [], result: null, loading: false, drillDown: null }]);
  };

  const removeStratGroup = (groupId: number) => {
    setStratGroups((prev) => prev.filter((g) => g.id !== groupId));
  };

  if (loading) {
    return (
      <div className="text-muted-foreground text-sm p-8">
        Loading tape data...
      </div>
    );
  }

  const hasFilters = filters.length > 0;

  return (
    <div className="space-y-4">
      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          <MetricCard icon={Hash} label="Loans" value={stats.record_count.toLocaleString()} />
          <MetricCard icon={DollarSign} label="Total UPB" value={fmtCcy(stats.total_balance)} />
          <MetricCard icon={Percent} label="WAC" value={`${stats.wac.toFixed(2)}%`} />
          <MetricCard icon={Clock} label="WAM" value={`${stats.wam.toFixed(0)} mo`} />
          <MetricCard icon={Clock} label="WALA" value={`${stats.wala.toFixed(0)} mo`} />
          <MetricCard icon={Percent} label="Coupon Range" value={`${stats.coupon_min.toFixed(2)}–${stats.coupon_max.toFixed(2)}%`} />
        </div>
      )}

      {/* Rate type distribution */}
      {stats && Object.keys(stats.rate_type_distribution).length > 0 && (
        <div className="bg-card border border-border rounded-lg p-3">
          <h3 className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-2">
            <BarChart3 className="w-3.5 h-3.5" />
            Rate Type Distribution
          </h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.rate_type_distribution).map(([key, count]) => (
              <div
                key={key}
                className="px-2 py-1 rounded bg-secondary text-xs flex items-center gap-1.5"
              >
                <span className="text-foreground">{key}</span>
                <span className="text-muted-foreground" style={MONO}>
                  {count}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Data quality panel */}
      {diagnosis && (diagnosis.issues.length > 0 || diagnosis.available_repairs.length > 0) && (
        <div className="bg-card border border-border rounded-lg p-4 space-y-3">
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-medium text-foreground flex items-center gap-2">
              <AlertTriangle className="w-3.5 h-3.5 text-engine-amber" />
              Data Quality
            </h3>
            {hasWorkingCopy && (
              <>
                <span className="px-1.5 py-0.5 rounded bg-engine-blue/10 border border-engine-blue/20 text-engine-blue text-[9px]">
                  Working Copy
                </span>
                <button
                  onClick={handleRevert}
                  className="text-[10px] text-muted-foreground hover:text-engine-red transition-colors ml-auto"
                >
                  Revert to original
                </button>
              </>
            )}
          </div>

          {/* Missing values summary */}
          {diagnosis.issues.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
                Missing Values
              </p>
              <div className="flex flex-wrap gap-2">
                {diagnosis.issues.map((issue) => (
                  <div
                    key={issue.column}
                    className="px-2 py-1 rounded border border-engine-amber/20 bg-engine-amber/5 text-xs flex items-center gap-1.5"
                  >
                    <span className="text-foreground" style={MONO}>{issue.column}</span>
                    <span className="text-engine-amber" style={MONO}>
                      {issue.missing_count}
                    </span>
                    <span className="text-muted-foreground text-[9px]">
                      ({issue.missing_pct}%)
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Available repairs */}
          {diagnosis.available_repairs.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
                Available Fixes
              </p>
              <div className="space-y-2">
                {diagnosis.available_repairs.map((rule) => (
                  <div
                    key={rule.id}
                    className="flex items-start gap-3 px-3 py-2 rounded border border-border bg-background text-xs"
                  >
                    <Wrench className="w-3.5 h-3.5 text-engine-blue mt-0.5 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-foreground">{rule.description}</p>
                      <p className="text-muted-foreground mt-0.5">
                        <span style={MONO}>{rule.formula}</span>
                        {" — "}
                        <span className="text-engine-green">{rule.fixable_count}</span> of{" "}
                        {rule.missing_count} missing values can be computed
                      </p>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        onClick={() => handlePreviewRepair(rule.id)}
                        disabled={previewingRule === rule.id}
                        className="px-2 py-1 rounded border border-border text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors flex items-center gap-1"
                      >
                        {previewingRule === rule.id ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <Eye className="w-3 h-3" />
                        )}
                        Preview
                      </button>
                      <button
                        onClick={() => handleApplyRepair(rule.id)}
                        disabled={applyingRule === rule.id}
                        className="px-2 py-1 rounded border border-engine-green/30 bg-engine-green/5 text-engine-green hover:bg-engine-green/10 transition-colors flex items-center gap-1"
                      >
                        {applyingRule === rule.id ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <Check className="w-3 h-3" />
                        )}
                        Apply
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Repair preview table */}
          {repairPreview && (
            <div className="border border-border rounded overflow-hidden">
              <div className="bg-grid-header px-3 py-2 flex items-center gap-2 text-xs">
                <Eye className="w-3.5 h-3.5 text-engine-blue" />
                <span className="text-foreground">
                  Preview: <span style={MONO}>{repairPreview.rule.formula}</span>
                </span>
                <span className="text-muted-foreground ml-auto">
                  Showing {repairPreview.showing} of {repairPreview.total_fixable} fixable rows
                </span>
                <button onClick={() => setRepairPreview(null)} className="text-muted-foreground hover:text-foreground">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              <DataTable
                tableId="repair_preview"
                maxHeight="250px"
                columns={repairPreview.columns.map((col): DataTableColumn<Record<string, unknown>> => ({
                  id: col,
                  header: col.includes("(computed)") ? <span className="text-engine-green">{col}</span> : col.includes("(current)") ? <span className="text-engine-amber">{col}</span> : col,
                  accessorKey: col,
                  cell: (v) => v == null ? "—" : String(v),
                  className: col.includes("(computed)") ? "text-engine-green" : col.includes("(current)") ? "text-engine-amber" : "",
                }))}
                data={repairPreview.rows}
              />
            </div>
          )}

          {diagnosis.issues.length === 0 && (
            <div className="flex items-center gap-2 text-engine-green text-xs">
              <Check className="w-4 h-4" />
              No missing values detected
            </div>
          )}
        </div>
      )}

      <TabBar
        tabs={[
          { id: "grid", label: "Data Grid", icon: Table2 },
          { id: "summary", label: "Summary", icon: PieChart },
          { id: "strats", label: "Stratifications", icon: Layers },
        ]}
        active={tab}
        onSelect={(id) => setTab(id as Tab)}
      />

      {/* Data grid tab */}
      {tab === "grid" && preview && (
        <div className="border border-border rounded-lg overflow-hidden">
          {/* Filter bar */}
          <div className="bg-grid-header px-3 py-2 flex items-center gap-2 text-xs border-b border-border min-h-[36px]">
            <Filter className={`w-3.5 h-3.5 shrink-0 ${hasFilters ? "text-primary" : "text-muted-foreground/50"}`} />
            <span className={`text-[10px] uppercase tracking-wider shrink-0 ${hasFilters ? "text-primary" : "text-muted-foreground/50"}`}>
              Filtered By
            </span>
            {hasFilters ? (
              <>
                <div className="flex items-center gap-1.5 flex-wrap flex-1">
                  {filters.map((f, idx) => {
                    const totalForCol = allUniqueValues[f.column]?.length ?? 0;
                    const availableInContext = contextualUniqueValues[f.column]?.length ?? totalForCol;
                    return (
                      <div
                        key={f.column}
                        draggable
                        onDragStart={() => handleChipDragStart(idx)}
                        onDragOver={(e) => handleChipDragOver(e, idx)}
                        onDrop={() => handleChipDrop(idx)}
                        onDragEnd={() => { dragIdx.current = null; setDragOverIdx(null); }}
                        className={`flex items-center gap-1 px-1.5 py-0.5 rounded border cursor-grab active:cursor-grabbing transition-colors ${
                          dragOverIdx === idx
                            ? "border-primary bg-primary/10"
                            : "border-primary/30 bg-primary/5"
                        }`}
                      >
                        <GripVertical className="w-2.5 h-2.5 text-muted-foreground/50" />
                        <button
                          onClick={() => setOpenFilterCol(openFilterCol === f.column ? null : f.column)}
                          className="text-primary hover:text-primary/80"
                          style={MONO}
                        >
                          {f.column}
                        </button>
                        <span className="text-muted-foreground text-[9px]">
                          ({f.selected.size}/{totalForCol}{availableInContext < totalForCol ? ` · ${availableInContext} in view` : ""})
                        </span>
                        <button
                          onClick={() => removeFilter(f.column)}
                          className="text-muted-foreground hover:text-engine-red"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </div>
                    );
                  })}
                </div>
                <button
                  onClick={clearAllFilters}
                  className="text-muted-foreground hover:text-foreground text-[10px] shrink-0"
                >
                  Clear all
                </button>
              </>
            ) : (
              <span className="text-muted-foreground/40 text-[10px] flex-1">
                Click column headers to add filters
              </span>
            )}
            <div className="border-l border-border pl-2 ml-auto shrink-0 text-muted-foreground">
              {filteredRows.length.toLocaleString()}
              {hasFilters && ` / ${preview.total_rows.toLocaleString()}`}
              {" "}rows
            </div>
          </div>

          {/* Open filter dropdown */}
          {openFilterCol && (
            <FilterDropdown
              column={openFilterCol}
              allValues={allUniqueValues[openFilterCol] ?? []}
              contextValues={new Set(contextualUniqueValues[openFilterCol] ?? [])}
              filter={filters.find((f) => f.column === openFilterCol) ?? null}
              onToggle={(val) => toggleFilterValue(openFilterCol, val)}
              onSelectAll={() => selectAllForColumn(openFilterCol)}
              onSelectNone={() => selectNoneForColumn(openFilterCol)}
              onClose={() => setOpenFilterCol(null)}
            />
          )}

          {/* Table */}
          <DataTable
            tableId="tape_data_grid"
            maxHeight="500px"
            columns={preview.columns.map((col): DataTableColumn<Record<string, unknown>> => ({
              id: col,
              header: <span className="flex items-center gap-1">
                {col}
                <Filter className={`w-2.5 h-2.5 ${filters.some((f) => f.column === col) ? "text-primary" : "opacity-0 group-hover:opacity-30"}`} />
                {openFilterCol === col && <ChevronDown className="w-2.5 h-2.5 text-primary" />}
              </span>,
              accessorKey: col,
              cell: (v) => String(v ?? ""),
            }))}
            data={filteredRows}
            onHeaderClick={(colId) => setOpenFilterCol(openFilterCol === colId ? null : colId)}
            emptyMessage="No rows match the current filters."
          />
        </div>
      )}

      {/* Summary tab */}
      {tab === "summary" && (
        summaryLoading ? (
          <div className="flex items-center gap-2 text-muted-foreground text-sm p-8">
            <Loader2 className="w-4 h-4 animate-spin" /> Computing tape summary...
          </div>
        ) : (
          <div className="space-y-3">
            {/* Aggregate tape stats */}
            {stats && (
              <CollapsiblePanel icon={PieChart} title="Tape Aggregates">
                <div className="p-4">
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-x-8 gap-y-2 text-xs">
                    <SummaryRow label="Record Count" value={stats.record_count.toLocaleString()} />
                    <SummaryRow label="Total UPB" value={fmtCcy(stats.total_balance)} />
                    <SummaryRow label="WAC" value={`${stats.wac.toFixed(4)}%`} />
                    <SummaryRow label="WAM" value={`${stats.wam.toFixed(1)} months`} />
                    <SummaryRow label="WALA" value={`${stats.wala.toFixed(1)} months`} />
                    <SummaryRow label="Coupon Range" value={`${stats.coupon_min.toFixed(3)}% – ${stats.coupon_max.toFixed(3)}%`} />
                    <SummaryRow label="Balance Range" value={`${fmtCcy(stats.balance_min)} – ${fmtCcy(stats.balance_max)}`} />
                  </div>
                </div>
              </CollapsiblePanel>
            )}

            {/* Missing value analysis */}
            {tapeSummary && (() => {
              const withMissing = tapeSummary.rows.filter((r) => r.missing > 0).sort((a, b) => b.missing_pct - a.missing_pct);
              const totalCells = tapeSummary.rows.reduce((s, r) => s + r.count + r.missing, 0);
              const totalMissing = tapeSummary.rows.reduce((s, r) => s + r.missing, 0);
              const overallPct = totalCells > 0 ? (totalMissing / totalCells * 100) : 0;
              return (
                <CollapsiblePanel
                  icon={AlertTriangle}
                  title="Missing Value Analysis"
                  badge={withMissing.length > 0 ? `${withMissing.length} columns with missing data (${overallPct.toFixed(1)}% overall)` : "No missing values"}
                >
                  {withMissing.length > 0 ? (
                    <DataTable
                      tableId="missing_values"
                      maxHeight="400px"
                      columns={[
                        { id: "column", header: "Column", accessorKey: "column" },
                        { id: "dtype", header: "Type", accessorKey: "dtype", mono: false },
                        { id: "total", header: "Total", accessorFn: (r: any) => (r.count + r.missing).toLocaleString(), align: "right" },
                        { id: "missing", header: "Missing", accessorFn: (r: any) => r.missing.toLocaleString(), align: "right", cell: (v, r: any) => <span style={{ color: "var(--engine-amber)" }}>{r.missing.toLocaleString()}</span> },
                        { id: "missing_pct", header: "Missing %", accessorKey: "missing_pct", align: "right", cell: (v, r: any) => <span style={{ color: r.missing_pct > 50 ? "var(--engine-red)" : "var(--engine-amber)" }}>{r.missing_pct.toFixed(1)}%</span> },
                        { id: "coverage", header: "Coverage", accessorKey: "missing_pct", align: "left", size: 200, mono: false, cell: (_v, r: any) => (
                          <div className="flex items-center gap-2">
                            <div className="flex-1 bg-secondary rounded-full h-2 overflow-hidden">
                              <div className="h-2 rounded-full" style={{ width: `${100 - r.missing_pct}%`, backgroundColor: r.missing_pct > 50 ? "var(--engine-red)" : r.missing_pct > 10 ? "var(--engine-amber)" : "var(--engine-green)" }} />
                            </div>
                            <span className="text-[10px] text-muted-foreground w-10 text-right shrink-0">{(100 - r.missing_pct).toFixed(0)}%</span>
                          </div>
                        )},
                      ] as DataTableColumn<any>[]}
                      data={withMissing}
                    />
                  ) : (
                    <div className="flex items-center gap-2 text-engine-green text-xs p-4">
                      <Check className="w-4 h-4" /> All columns are fully populated — no missing values detected.
                    </div>
                  )}
                </CollapsiblePanel>
              );
            })()}

            {/* Per-column descriptive statistics */}
            {tapeSummary && (
              <CollapsiblePanel icon={Table2} title="Column Statistics" badge={`${tapeSummary.row_count} columns`}>
                <DataTable
                  tableId="column_statistics"
                  maxHeight="600px"
                  columns={[
                    { id: "column", header: "Column", accessorKey: "column", pinLeft: true, size: 160 },
                    { id: "dtype", header: "Type", accessorKey: "dtype", mono: false, size: 80 },
                    { id: "count", header: "Count", accessorKey: "count", align: "right", size: 70 },
                    { id: "missing", header: "Missing", accessorKey: "missing", align: "right", size: 80, cell: (v, r: any) => <span style={{ color: r.missing > 0 ? "var(--engine-amber)" : undefined }}>{r.missing}</span> },
                    { id: "missing_pct", header: "Missing %", accessorKey: "missing_pct", align: "right", size: 90, cell: (v, r: any) => r.missing_pct > 0 ? <span style={{ color: r.missing_pct > 5 ? "var(--engine-red)" : "var(--engine-amber)" }}>{r.missing_pct.toFixed(1)}%</span> : "—" },
                    { id: "unique", header: "Unique", accessorKey: "unique", align: "right", size: 80 },
                    { id: "mean", header: "Mean", accessorKey: "mean", align: "right", size: 90, cell: (v) => v != null ? fmtNum(v) : "—" },
                    { id: "std", header: "Std", accessorKey: "std", align: "right", size: 90, cell: (v) => v != null ? fmtNum(v) : "—" },
                    { id: "min", header: "Min", accessorKey: "min", align: "right", size: 90, cell: (v) => v != null ? fmtNum(v) : "—" },
                    { id: "q25", header: "Q25", accessorKey: "q25", align: "right", size: 90, cell: (v) => v != null ? fmtNum(v) : "—" },
                    { id: "median", header: "Median", accessorKey: "median", align: "right", size: 90, cell: (v) => v != null ? fmtNum(v) : "—" },
                    { id: "q75", header: "Q75", accessorKey: "q75", align: "right", size: 90, cell: (v) => v != null ? fmtNum(v) : "—" },
                    { id: "p95", header: "P95", accessorKey: "p95", align: "right", size: 90, cell: (v) => v != null ? fmtNum(v) : "—" },
                    { id: "p99", header: "P99", accessorKey: "p99", align: "right", size: 90, cell: (v) => v != null ? fmtNum(v) : "—" },
                    { id: "max", header: "Max", accessorKey: "max", align: "right", size: 90, cell: (v) => v != null ? fmtNum(v) : "—" },
                    { id: "top_values", header: "Top Values", accessorKey: "top_values", size: 200, cell: (v: any) => v?.length > 0 ? v.slice(0, 5).map(String).join(", ") : "—" },
                  ] as DataTableColumn<any>[]}
                  data={tapeSummary.rows}
                  getRowId={(r: any) => r.column}
                />
              </CollapsiblePanel>
            )}

            {/* Unique values analysis */}
            {uniqueValues && (
              <CollapsiblePanel icon={ListTree} title="Unique Values" badge={`${uniqueValues.row_count} columns`} defaultOpen={false}>
                <DataTable
                  tableId="unique_values"
                  maxHeight="600px"
                  columns={[
                    { id: "column", header: "Column", accessorKey: "column", pinLeft: true, size: 160 },
                    { id: "dtype", header: "Type", accessorKey: "dtype", mono: false, size: 80 },
                    { id: "count", header: "Count", accessorKey: "count", align: "right", size: 70 },
                    { id: "missing", header: "Missing", accessorKey: "missing", align: "right", size: 80, cell: (v, r: any) => <span style={{ color: r.missing > 0 ? "var(--engine-amber)" : undefined }}>{r.missing}</span> },
                    { id: "missing_pct", header: "Missing %", accessorKey: "missing_pct", align: "right", size: 90, cell: (v, r: any) => r.missing_pct > 0 ? <span style={{ color: r.missing_pct > 5 ? "var(--engine-red)" : "var(--engine-amber)" }}>{r.missing_pct.toFixed(1)}%</span> : "—" },
                    { id: "unique", header: "Unique", accessorKey: "unique", align: "right", size: 80 },
                    { id: "top_values", header: "Top Values (by frequency)", accessorKey: "top_values", size: 400, mono: false, cell: (v: any) => v?.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {v.slice(0, 15).map((val: unknown, vi: number) => (
                          <span key={vi} className="px-1.5 py-0.5 rounded bg-secondary text-[10px]" style={MONO}>{String(val)}</span>
                        ))}
                        {v.length > 15 && <span className="text-[10px] text-muted-foreground/60">+{v.length - 15} more</span>}
                      </div>
                    ) : <span className="text-muted-foreground/40 italic">too many unique values</span> },
                  ] as DataTableColumn<any>[]}
                  data={uniqueValues.rows}
                  getRowId={(r: any) => r.column}
                />
              </CollapsiblePanel>
            )}
          </div>
        )
      )}

      {/* Strats tab */}
      {tab === "strats" && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <button
              onClick={addStratGroup}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-dashed border-border text-xs text-muted-foreground hover:text-foreground hover:border-primary/30 transition-colors"
            >
              <Plus className="w-3.5 h-3.5" /> Add Stratification
            </button>
            {stratGroups.some((g) => g.result) && (
              <>
                <button
                  onClick={() => {
                    const dims = stratGroups.filter((g) => g.dimensions.length > 0 && g.result).flatMap((g) => g.dimensions.filter(Boolean));
                    if (dims.length > 0) api.exportStrats(uploadId, dims, mappingId, "xlsx");
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-border text-xs text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors"
                >
                  <FileSpreadsheet className="w-3.5 h-3.5" /> Export Excel
                </button>
                <button
                  onClick={() => {
                    const dims = stratGroups.filter((g) => g.dimensions.length > 0 && g.result).flatMap((g) => g.dimensions.filter(Boolean));
                    if (dims.length > 0) api.exportStrats(uploadId, dims, mappingId, "csv");
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-border text-xs text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors"
                >
                  <Download className="w-3.5 h-3.5" /> Export CSV
                </button>
              </>
            )}
          </div>

          {stratGroups.map((sg, gi) => {
            const dims = sg.dimensions.length > 0 ? sg.dimensions : [""];
            const groupByLabel = Array.isArray(sg.result?.group_by)
              ? (sg.result!.group_by as string[]).join(" × ")
              : sg.result?.group_by ?? "";

            return (
            <div key={sg.id} className="space-y-2">
              <div className="bg-card border border-border rounded-lg p-4 space-y-2">
                {dims.map((dim, di) => (
                  <div key={di} className="flex items-center gap-3 flex-wrap">
                    {di === 0 && <Layers className="w-3.5 h-3.5 text-primary shrink-0" />}
                    {di > 0 && <span className="w-3.5 text-center text-[10px] text-muted-foreground shrink-0">×</span>}
                    <div className="relative">
                      <select
                        value={dim}
                        onChange={(e) => handleSetDimension(sg.id, di, e.target.value)}
                        className="appearance-none px-3 py-1.5 pr-8 bg-input-background border border-border rounded text-xs text-foreground min-w-[240px]"
                      >
                        <option value="">Select a column...</option>
                        {dimensions.map((d) => (
                          <option key={d.column} value={d.column}>
                            {d.column} ({d.type}, {d.unique} unique)
                          </option>
                        ))}
                      </select>
                      <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
                    </div>
                    {di > 0 && (
                      <button
                        onClick={() => handleSetDimension(sg.id, di, "")}
                        className="text-muted-foreground hover:text-engine-red p-0.5"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    )}
                  </div>
                ))}
                <div className="flex items-center gap-2 pt-1">
                  <button
                    onClick={() => handleAddDimToGroup(sg.id)}
                    className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <Plus className="w-3 h-3" /> Add dimension
                  </button>
                  <button
                    onClick={() => handleRunStrat(sg.id)}
                    disabled={sg.loading || dims.filter(Boolean).length === 0}
                    className="px-3 py-1 rounded border border-primary/20 bg-primary/10 text-primary text-[10px] hover:bg-primary/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {sg.loading ? "Computing..." : "Run Strat"}
                  </button>
                  {sg.loading && (
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />
                  )}
                  {stratGroups.length > 1 && (
                    <button
                      onClick={() => removeStratGroup(sg.id)}
                      className="ml-auto text-muted-foreground hover:text-engine-red transition-colors p-1"
                      title="Remove this stratification"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>

              {sg.result && !sg.loading && (
                <CollapsiblePanel
                  icon={Layers}
                  title={groupByLabel}
                  badge={`${sg.result.row_count} buckets`}
                >
                  <DataTable
                    tableId={`strat_${sg.id}`}
                    maxHeight="500px"
                    columns={sg.result.columns.map((col): DataTableColumn<Record<string, unknown>> => ({
                      id: col,
                      header: STRAT_COL_LABELS[col] ?? col,
                      accessorKey: col,
                      align: col === "bucket" ? "left" : "right",
                      cell: (v) => formatStratCell(col, v),
                    }))}
                    data={sg.result.rows}
                    rowClassName={(row) => {
                      const isTotal = (row as any).bucket === "TOTAL";
                      return isTotal ? "bg-primary/5 font-medium border-b border-border/50" : "";
                    }}
                    onRowClick={(row) => {
                      const bucket = (row as any).bucket;
                      if (bucket === "TOTAL") return;
                      const firstDim = sg.dimensions[0];
                      if (!firstDim) return;
                      const filterCol = `${firstDim}_bucket`;
                      handleDrillDown(sg.id, bucket, filterCol, bucket);
                    }}
                  />
                  {sg.dimensions.length === 1 && (
                    <div className="px-3 py-1.5 text-[10px] text-muted-foreground border-t border-border">
                      Click a row to drill down within that bucket.
                    </div>
                  )}
                </CollapsiblePanel>
              )}

              {/* Drill-down sub-strat */}
              {sg.drillDown && (
                <div className="ml-6 border-l-2 border-primary/20 pl-4 space-y-2">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Filter className="w-3 h-3 text-primary" />
                    <span>Drill-down: <span className="text-foreground font-medium">{sg.drillDown.parentBucket}</span></span>
                    <button
                      onClick={() => setStratGroups((prev) =>
                        prev.map((g) => (g.id === sg.id ? { ...g, drillDown: null } : g))
                      )}
                      className="text-muted-foreground hover:text-engine-red"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="relative">
                      <select
                        value={sg.drillDown.dimension}
                        onChange={(e) => handleRunDrillDown(sg.id, e.target.value)}
                        className="appearance-none px-3 py-1.5 pr-8 bg-input-background border border-border rounded text-xs text-foreground min-w-[240px]"
                      >
                        <option value="">Select drill-down dimension...</option>
                        {dimensions.map((d) => (
                          <option key={d.column} value={d.column}>
                            {d.column} ({d.type}, {d.unique} unique)
                          </option>
                        ))}
                      </select>
                      <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
                    </div>
                    {sg.drillDown.loading && (
                      <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />
                    )}
                  </div>
                  {sg.drillDown.result && !sg.drillDown.loading && (
                    <CollapsiblePanel
                      icon={Filter}
                      title={`${sg.drillDown.parentBucket} → ${sg.drillDown.dimension}`}
                      badge={`${sg.drillDown.result.row_count} buckets`}
                    >
                      <DataTable
                        tableId={`strat_dd_${sg.id}`}
                        maxHeight="400px"
                        columns={sg.drillDown.result.columns.map((col): DataTableColumn<Record<string, unknown>> => ({
                          id: col,
                          header: STRAT_COL_LABELS[col] ?? col,
                          accessorKey: col,
                          align: col === "bucket" ? "left" : "right",
                          cell: (v) => formatStratCell(col, v),
                        }))}
                        data={sg.drillDown.result.rows}
                        rowClassName={(row) => {
                          const isTotal = (row as any).bucket === "TOTAL";
                          return isTotal ? "bg-primary/5 font-medium" : "";
                        }}
                      />
                    </CollapsiblePanel>
                  )}
                </div>
              )}

              {sg.dimensions.filter(Boolean).length === 0 && !sg.loading && gi === stratGroups.length - 1 && stratGroups.length === 1 && (
                <div className="text-muted-foreground text-sm p-8 text-center">
                  Select a dimension above to generate a stratification table.
                </div>
              )}
            </div>
          );
          })}

        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Filter dropdown
// ---------------------------------------------------------------------------

function FilterDropdown({
  column,
  allValues,
  contextValues,
  filter,
  onToggle,
  onSelectAll,
  onSelectNone,
  onClose,
}: {
  column: string;
  allValues: string[];
  contextValues: Set<string>;
  filter: ColumnFilter | null;
  onToggle: (val: string) => void;
  onSelectAll: () => void;
  onSelectNone: () => void;
  onClose: () => void;
}) {
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  const displayed = search
    ? allValues.filter((v) => v.toLowerCase().includes(search.toLowerCase()))
    : allValues;

  const isChecked = (val: string) => {
    if (!filter) return true;
    return filter.selected.has(val);
  };

  const inContextCount = displayed.filter((v) => contextValues.has(v)).length;

  return (
    <div
      ref={ref}
      className="border-b border-border bg-[#0d1220] px-3 py-2 space-y-2"
    >
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-foreground" style={MONO}>
          {column}
        </span>
        <div className="flex-1" />
        <button
          onClick={onSelectAll}
          className="text-[10px] text-muted-foreground hover:text-foreground"
        >
          All
        </button>
        <button
          onClick={onSelectNone}
          className="text-[10px] text-muted-foreground hover:text-foreground"
        >
          None
        </button>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      {allValues.length > 10 && (
        <input
          type="text"
          placeholder="Search values..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full px-2 py-1 bg-input-background border border-border rounded text-xs text-foreground placeholder:text-muted-foreground"
          autoFocus
        />
      )}
      <div className="max-h-[180px] overflow-auto space-y-0.5">
        {displayed.map((val) => {
          const inContext = contextValues.has(val);
          return (
            <label
              key={val}
              className={`flex items-center gap-2 px-1 py-0.5 rounded hover:bg-white/5 cursor-pointer text-xs ${
                !inContext ? "opacity-35" : ""
              }`}
            >
              <input
                type="checkbox"
                checked={isChecked(val)}
                onChange={() => onToggle(val)}
                className="accent-primary w-3 h-3"
              />
              <span className="text-foreground truncate" style={MONO}>
                {val || "(blank)"}
              </span>
              {!inContext && (
                <span className="text-[9px] text-muted-foreground ml-auto shrink-0">
                  filtered out
                </span>
              )}
            </label>
          );
        })}
        {displayed.length === 0 && (
          <div className="text-muted-foreground text-[10px] py-2 text-center">
            No matching values
          </div>
        )}
      </div>
      <div className="text-[10px] text-muted-foreground">
        {inContextCount} of {allValues.length} values in current view
      </div>
    </div>
  );
}

// Strat formatting and shared components now imported from lib/format and components/
