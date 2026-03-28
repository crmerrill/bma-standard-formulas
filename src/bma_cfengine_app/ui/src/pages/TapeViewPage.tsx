import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  BarChart3,
  Hash,
  DollarSign,
  Percent,
  Clock,
  ChevronDown,
  Table2,
  Layers,
  Filter,
  X,
  GripVertical,
  AlertTriangle,
  Check,
  Wrench,
  Eye,
  Loader2,
} from "lucide-react";
import type {
  TapeStats,
  TapePreview,
  StratDimension,
  StratResult,
  DiagnoseResult,
  RepairRule,
  RepairPreview,
} from "../services/api";
import * as api from "../services/api";

const MONO = { fontFamily: "'JetBrains Mono', monospace" } as const;

function fmtCcy(n: number): string {
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(2)}`;
}

function fmtNum(v: unknown, dec = 2): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!isFinite(n)) return "—";
  return n.toLocaleString(undefined, {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  });
}

type Tab = "grid" | "strats";

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
  const [selectedDim, setSelectedDim] = useState("");
  const [stratResult, setStratResult] = useState<StratResult | null>(null);
  const [stratLoading, setStratLoading] = useState(false);

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

  const handleRunStrat = async (dim: string) => {
    setSelectedDim(dim);
    if (!dim) {
      setStratResult(null);
      return;
    }
    setStratLoading(true);
    try {
      const res = await api.computeStrat(uploadId, dim, mappingId);
      setStratResult(res);
    } finally {
      setStratLoading(false);
    }
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
          <StatCard icon={Hash} label="Loans" value={stats.record_count.toLocaleString()} />
          <StatCard icon={DollarSign} label="Total UPB" value={fmtCcy(stats.total_balance)} />
          <StatCard icon={Percent} label="WAC" value={`${stats.wac.toFixed(2)}%`} />
          <StatCard icon={Clock} label="WAM" value={`${stats.wam.toFixed(0)} mo`} />
          <StatCard icon={Clock} label="WALA" value={`${stats.wala.toFixed(0)} mo`} />
          <StatCard
            icon={Percent}
            label="Coupon Range"
            value={`${stats.coupon_min.toFixed(2)}–${stats.coupon_max.toFixed(2)}%`}
          />
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
              <div className="overflow-auto max-h-[250px]">
                <table className="w-full border-collapse text-xs">
                  <thead className="sticky top-0 z-10">
                    <tr className="bg-grid-header text-muted-foreground border-b border-border">
                      {repairPreview.columns.map((col) => (
                        <th key={col} className="text-left px-3 py-1.5 whitespace-nowrap">
                          {col.includes("(computed)") ? (
                            <span className="text-engine-green">{col}</span>
                          ) : col.includes("(current)") ? (
                            <span className="text-engine-amber">{col}</span>
                          ) : (
                            col
                          )}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {repairPreview.rows.map((row, ri) => (
                      <tr
                        key={ri}
                        className={`border-b border-border/50 ${ri % 2 === 1 ? "bg-grid-row-alt" : ""}`}
                      >
                        {repairPreview.columns.map((col) => (
                          <td
                            key={col}
                            className={`px-3 py-1 whitespace-nowrap ${
                              col.includes("(computed)") ? "text-engine-green" :
                              col.includes("(current)") ? "text-engine-amber" : ""
                            }`}
                            style={MONO}
                          >
                            {row[col] == null ? "—" : String(row[col])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
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

      {/* Tab bar */}
      <div className="flex items-center gap-1 border-b border-border">
        <TabBtn icon={Table2} label="Data Grid" active={tab === "grid"} onClick={() => setTab("grid")} />
        <TabBtn icon={Layers} label="Stratifications" active={tab === "strats"} onClick={() => setTab("strats")} />
      </div>

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
          <div className="overflow-auto max-h-[500px]">
            <table className="w-full border-collapse text-xs">
              <thead className="sticky top-0 z-10">
                <tr className="bg-grid-header text-muted-foreground border-b border-border">
                  {preview.columns.map((col) => {
                    const isFiltered = filters.some((f) => f.column === col);
                    return (
                      <th
                        key={col}
                        className="text-left px-3 py-1.5 whitespace-nowrap cursor-pointer hover:text-foreground transition-colors select-none"
                        onClick={() => setOpenFilterCol(openFilterCol === col ? null : col)}
                      >
                        <span className="flex items-center gap-1">
                          {col}
                          <Filter
                            className={`w-2.5 h-2.5 ${
                              isFiltered ? "text-primary" : "opacity-0 group-hover:opacity-30"
                            }`}
                          />
                          {openFilterCol === col && (
                            <ChevronDown className="w-2.5 h-2.5 text-primary" />
                          )}
                        </span>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row, ri) => (
                  <tr
                    key={ri}
                    className={`border-b border-border/50 hover:bg-grid-row-hover transition-colors ${
                      ri % 2 === 1 ? "bg-grid-row-alt" : ""
                    }`}
                  >
                    {preview.columns.map((col) => (
                      <td key={col} className="px-3 py-1 whitespace-nowrap" style={MONO}>
                        {String(row[col] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
                {filteredRows.length === 0 && (
                  <tr>
                    <td
                      colSpan={preview.columns.length}
                      className="px-3 py-8 text-center text-muted-foreground"
                    >
                      No rows match the current filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Strats tab */}
      {tab === "strats" && (
        <div className="space-y-4">
          <div className="bg-card border border-border rounded-lg p-4">
            <h3 className="text-xs font-medium text-foreground flex items-center gap-2 mb-3">
              <Layers className="w-3.5 h-3.5 text-primary" />
              Stratification Dimension
            </h3>
            <div className="flex items-center gap-3 flex-wrap">
              <div className="relative">
                <select
                  value={selectedDim}
                  onChange={(e) => handleRunStrat(e.target.value)}
                  className="appearance-none px-3 py-1.5 pr-8 bg-input-background border border-border rounded text-xs text-foreground min-w-[200px]"
                >
                  <option value="">Select a column to stratify by...</option>
                  {dimensions.map((d) => (
                    <option key={d.column} value={d.column}>
                      {d.column} ({d.type}, {d.unique} unique)
                    </option>
                  ))}
                </select>
                <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
              </div>
              {stratLoading && (
                <span className="text-muted-foreground text-xs">Computing...</span>
              )}
            </div>
          </div>

          {stratResult && !stratLoading && (
            <div className="border border-border rounded-lg overflow-hidden">
              <div className="bg-grid-header px-3 py-2 flex items-center gap-2 text-xs">
                <span className="text-primary" style={MONO}>{stratResult.group_by}</span>
                <span className="text-muted-foreground">— {stratResult.row_count} buckets</span>
              </div>
              <div className="overflow-auto max-h-[500px]">
                <table className="w-full border-collapse text-xs">
                  <thead className="sticky top-0 z-10">
                    <tr className="bg-grid-header text-muted-foreground border-b border-border">
                      {stratResult.columns.map((col) => (
                        <th
                          key={col}
                          className={`px-3 py-1.5 whitespace-nowrap ${col === "bucket" ? "text-left" : "text-right"}`}
                        >
                          {STRAT_COL_LABELS[col] ?? col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {stratResult.rows.map((row, ri) => {
                      const isTotal = row.bucket === "TOTAL";
                      return (
                        <tr
                          key={ri}
                          className={`border-b border-border/50 transition-colors ${
                            isTotal
                              ? "bg-primary/5 font-medium"
                              : ri % 2 === 1
                              ? "bg-grid-row-alt hover:bg-grid-row-hover"
                              : "hover:bg-grid-row-hover"
                          }`}
                        >
                          {stratResult.columns.map((col) => (
                            <td
                              key={col}
                              className={`px-3 py-1.5 whitespace-nowrap ${col === "bucket" ? "text-left" : "text-right"}`}
                              style={MONO}
                            >
                              {formatStratCell(col, row[col])}
                            </td>
                          ))}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {!stratResult && !stratLoading && (
            <div className="text-muted-foreground text-sm p-8 text-center">
              Select a dimension above to generate a stratification table.
            </div>
          )}
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

// ---------------------------------------------------------------------------
// Strat formatting
// ---------------------------------------------------------------------------

const STRAT_COL_LABELS: Record<string, string> = {
  bucket: "Bucket",
  count: "Count",
  count_pct: "Count %",
  orig_bal: "Orig Bal",
  orig_bal_pct: "Orig Bal %",
  curr_bal: "Curr Bal",
  curr_bal_pct: "Curr Bal %",
  factor: "Factor",
  wa_rate: "WA Rate",
  wa_orig_term: "WA Orig Term",
  wa_rem_term: "WA Rem Term",
  wala: "WALA",
};

function formatStratCell(col: string, value: unknown): string {
  if (value == null || value === "") return "—";
  if (col === "bucket") return String(value);
  const n = Number(value);
  if (!isFinite(n)) return String(value);
  if (col === "count") return n.toLocaleString();
  if (col.endsWith("_pct") || col === "factor") return `${n.toFixed(2)}%`;
  if (col === "orig_bal" || col === "curr_bal") {
    if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
    if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
    if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
    return `$${n.toFixed(0)}`;
  }
  if (col === "wa_rate") return `${n.toFixed(3)}%`;
  if (col.startsWith("wa_") || col === "wala") return n.toFixed(1);
  return fmtNum(n);
}

// ---------------------------------------------------------------------------
// Shared components
// ---------------------------------------------------------------------------

function StatCard({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ElementType;
  label: string;
  value: string;
}) {
  return (
    <div className="bg-card border border-border rounded-lg p-3">
      <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
        <Icon className="w-3 h-3" />
        <span className="text-[10px] uppercase tracking-wider">{label}</span>
      </div>
      <p className="text-sm font-medium text-foreground" style={MONO}>
        {value}
      </p>
    </div>
  );
}

function TabBtn({
  icon: Icon,
  label,
  active,
  onClick,
}: {
  icon: React.ElementType;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 px-3 py-2 text-xs border-b-2 transition-colors ${
        active
          ? "border-primary text-primary"
          : "border-transparent text-muted-foreground hover:text-foreground"
      }`}
    >
      <Icon className="w-3.5 h-3.5" />
      {label}
    </button>
  );
}
