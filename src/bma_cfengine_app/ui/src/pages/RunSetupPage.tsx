import React, { useCallback, useEffect, useState } from "react";
import {
  Play, Settings2, Layers, AlertTriangle, Loader2,
  ChevronDown, ChevronRight, Check, X, Upload,
  TrendingUp, Plus, Copy, Trash2, FileSpreadsheet,
  GitBranch, BarChart3,
} from "lucide-react";
import type { FieldMapping, RunResponse, GroupPreview, RatesPreflight, CurvePreviewResult, RunPreflightResult } from "../services/api";
import * as api from "../services/api";
import { MONO } from "../lib/format";
import DataTable, { type DataTableColumn } from "../components/DataTable";
import CollapsiblePanel from "../components/CollapsiblePanel";
import FormSelect from "../components/FormSelect";
import LoadingState from "../components/LoadingState";

interface Props {
  uploadId: string;
  mappingId: string;
  mappings: FieldMapping[];
  asofDate: string;
  groupKeys: string[];
  onGroupKeysChange: (keys: string[]) => void;
  onRunComplete: (run: RunResponse) => void;
}

type RunMode = "scheduled" | "actual" | "paired";
type CurveType = "constant" | "psa" | "sda" | "vector" | "ramp";

interface CurveInput {
  type: CurveType;
  value: string;
}

interface AssumptionSetState {
  smm: CurveInput;
  mdr: CurveInput;
  severity: CurveInput;
  severity_lag_months: string;
  months_to_liquidation: string;
}

interface ScenarioState {
  name: string;
  assumptions: AssumptionSetState;
  run_mode: RunMode;
  group_overrides: Record<string, Partial<AssumptionSetState>>;
}

const DEFAULT_ASSUMPTIONS: AssumptionSetState = {
  smm: { type: "constant", value: "0.006" },
  mdr: { type: "constant", value: "0.001" },
  severity: { type: "constant", value: "0.35" },
  severity_lag_months: "12",
  months_to_liquidation: "12",
};

function cloneAssumptions(a: AssumptionSetState): AssumptionSetState {
  return JSON.parse(JSON.stringify(a));
}

export default function RunSetupPage({ uploadId, mappingId, mappings, asofDate, groupKeys, onGroupKeysChange, onRunComplete }: Props) {
  const [openSections, setOpenSections] = useState<Set<string>>(new Set(["rates", "grouping", "assumptions", "scenarios", "run"]));

  // Rates
  const [ratesPreflight, setRatesPreflight] = useState<RatesPreflight | null>(null);
  const [ratesUploading, setRatesUploading] = useState(false);

  // Grouping
  const setGroupKeys = onGroupKeysChange;
  const [newGroupKey, setNewGroupKey] = useState("");
  const [groupPreview, setGroupPreview] = useState<GroupPreview[] | null>(null);
  const [groupLoading, setGroupLoading] = useState(false);

  // Scenarios
  const [scenarios, setScenarios] = useState<ScenarioState[]>([
    { name: "Base Case", assumptions: cloneAssumptions(DEFAULT_ASSUMPTIONS), run_mode: "paired", group_overrides: {} },
  ]);
  const [activeScenario, setActiveScenario] = useState(0);

  // Curve preview
  const [curvePreview, setCurvePreview] = useState<number[] | null>(null);
  const [previewField, setPreviewField] = useState("");

  // Tape readiness
  const [tapePreflight, setTapePreflight] = useState<RunPreflightResult | null>(null);

  // Run state
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [preflightResult, setPreflightResult] = useState<{ok: boolean; issues: string[]} | null>(null);

  const [allColumns, setAllColumns] = useState<string[]>([]);

  useEffect(() => {
    api.getTapePreview(uploadId, 1).then((p) => {
      setAllColumns(p.columns);
    });
    api.getRunPreflight(uploadId, mappingId).then(setTapePreflight);
  }, [uploadId, mappingId]);

  useEffect(() => {
    api.getRatesPreflight(uploadId, mappingId).then(setRatesPreflight);
  }, [uploadId, mappingId]);

  const toggleSection = (id: string) => {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Rates
  const handleRatesUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setRatesUploading(true);
    try {
      await api.uploadRates(uploadId, file);
      const pf = await api.getRatesPreflight(uploadId, mappingId);
      setRatesPreflight(pf);
    } finally {
      setRatesUploading(false);
    }
  };

  // Grouping
  const addGroupKey = (key?: string) => {
    const k = key || newGroupKey;
    if (k && !groupKeys.includes(k)) {
      const next = [...groupKeys, k];
      setGroupKeys(next);
      setNewGroupKey("");
      loadGroupPreview(next);
    }
  };

  const removeGroupKey = (key: string) => {
    const next = groupKeys.filter((k) => k !== key);
    setGroupKeys(next);
    if (next.length) loadGroupPreview(next);
    else setGroupPreview(null);
  };

  useEffect(() => {
    if (groupKeys.length > 0 && !groupPreview) {
      loadGroupPreview(groupKeys);
    }
  }, []);

  const loadGroupPreview = async (keys: string[]) => {
    setGroupLoading(true);
    try {
      const gp = await api.getGroupPreview(uploadId, { keys });
      setGroupPreview(gp);
    } finally {
      setGroupLoading(false);
    }
  };

  // Scenarios
  const sc = scenarios[activeScenario];

  const updateScenario = (patch: Partial<ScenarioState>) => {
    setScenarios((prev) => prev.map((s, i) => (i === activeScenario ? { ...s, ...patch } : s)));
  };

  const updateAssumption = (field: keyof AssumptionSetState, value: any) => {
    updateScenario({ assumptions: { ...sc.assumptions, [field]: value } });
  };

  const addScenario = () => {
    setScenarios((prev) => [
      ...prev,
      { name: `Scenario ${prev.length + 1}`, assumptions: cloneAssumptions(sc.assumptions), run_mode: sc.run_mode, group_overrides: {} },
    ]);
    setActiveScenario(scenarios.length);
  };

  const removeScenario = (idx: number) => {
    if (scenarios.length <= 1) return;
    setScenarios((prev) => prev.filter((_, i) => i !== idx));
    setActiveScenario((prev) => Math.min(prev, scenarios.length - 2));
  };

  // Curve preview
  const handleCurvePreview = async (input: CurveInput, label: string) => {
    setPreviewField(label);
    const spec = buildCurveSpec(input);
    try {
      const res = await api.previewCurve(spec, 361);
      setCurvePreview(res.values);
    } catch {
      setCurvePreview(null);
    }
  };

  // Preflight
  const runPreflight = async () => {
    const issues: string[] = [];

    const tp = await api.getRunPreflight(uploadId, mappingId);
    setTapePreflight(tp);
    issues.push(...tp.blocking);

    if (ratesPreflight && !ratesPreflight.all_fixed && ratesPreflight.missing_indexes.length > 0) {
      issues.push(`Missing rate indexes: ${ratesPreflight.missing_indexes.join(", ")}`);
    }
    for (const s of scenarios) {
      if (s.run_mode !== "scheduled") {
        if (!s.assumptions.smm.value && s.assumptions.smm.type === "constant") {
          issues.push(`${s.name}: SMM value is empty`);
        }
      }
    }
    setPreflightResult({ ok: issues.length === 0, issues });
  };

  const tapeReady = tapePreflight?.ready !== false;

  // Run
  const handleRun = async () => {
    setRunning(true);
    setError("");
    try {
      const mainSc = scenarios[0];
      const assumptions = buildAssumptionsPayload(mainSc);

      const scenarioSpecs = scenarios.map((s) => ({
        name: s.name,
        assumptions: buildAssumptionsPayload(s),
        run_mode: s.run_mode,
      }));

      const res = await api.createRun({
        upload_id: uploadId,
        mapping_id: mappingId,
        grouping: groupKeys.length ? { keys: groupKeys } : null,
        assumptions,
        run_mode: mainSc.run_mode,
        scenarios: scenarioSpecs,
      });

      let poll = res;
      while (poll.status === "queued" || poll.status === "running") {
        await new Promise((r) => setTimeout(r, 1000));
        poll = await api.getRun(poll.run_id);
      }

      if (poll.status === "failed") {
        setError(poll.error || "Run failed");
      } else {
        onRunComplete(poll);
      }
    } catch (e: any) {
      setError(e.message || "Unknown error");
    } finally {
      setRunning(false);
    }
  };

  const ratesOk = !ratesPreflight || ratesPreflight.all_fixed || ratesPreflight.missing_indexes.length === 0;

  return (
    <div className="space-y-3 max-w-4xl">

      {/* Tape readiness banner */}
      {tapePreflight && !tapePreflight.ready && (
        <div className="bg-engine-red/5 border border-engine-red/30 rounded-lg p-3 space-y-1">
          <div className="flex items-center gap-2 text-xs font-medium text-engine-red">
            <AlertTriangle className="w-4 h-4" />
            Tape has data issues that must be fixed before running
          </div>
          {tapePreflight.blocking.map((b, i) => (
            <div key={i} className="text-xs text-engine-red/80 pl-6">{b}</div>
          ))}
          <p className="text-xs text-muted-foreground pl-6">
            Go to Tape View &rarr; Data Quality to fix these issues.
          </p>
        </div>
      )}

      {/* Section 1: Rates */}
      <CollapsiblePanel
        title="Rate Index Curves"
        icon={TrendingUp}
        open={openSections.has("rates")}
        onToggle={() => toggleSection("rates")}
        status={ratesOk ? "ok" : ratesPreflight?.missing_indexes.length ? "error" : "neutral"}
      >
        <div className="px-4 pb-4">
        {ratesPreflight?.all_fixed ? (
          <div className="flex items-center gap-2 text-engine-green text-xs">
            <Check className="w-4 h-4" />
            Tape is 100% fixed-rate — no rate index curves needed.
          </div>
        ) : (
          <div className="space-y-3">
            <label className="flex items-center gap-2 px-3 py-2 rounded border border-dashed border-border hover:border-primary/50 cursor-pointer text-xs text-muted-foreground transition-colors">
              <Upload className="w-4 h-4" />
              {ratesUploading ? "Uploading..." : "Upload rates CSV (date + index columns)"}
              <input type="file" accept=".csv,.xlsx" className="hidden" onChange={handleRatesUpload} />
            </label>

            {ratesPreflight && (
              <div className="space-y-2 text-xs">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-wider text-muted-foreground mb-1">Required Indexes (from tape)</p>
                    {ratesPreflight.required_indexes.map((idx) => (
                      <div key={idx} className="flex items-center gap-2 py-0.5">
                        <span style={MONO} className="text-foreground">{idx}</span>
                        <span className="text-muted-foreground">({ratesPreflight.required_index_loan_counts[idx]} loans)</span>
                        {ratesPreflight.resolved_mapping[idx] ? (
                          <Check className="w-3 h-3 text-engine-green" />
                        ) : (
                          <X className="w-3 h-3 text-engine-red" />
                        )}
                      </div>
                    ))}
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-wider text-muted-foreground mb-1">Provided Columns (from file)</p>
                    {ratesPreflight.provided_columns.length > 0 ? (
                      ratesPreflight.provided_columns.map((col) => (
                        <div key={col} className="py-0.5" style={MONO}>{col}</div>
                      ))
                    ) : (
                      <span className="text-muted-foreground">No rates file uploaded</span>
                    )}
                  </div>
                </div>

                {ratesPreflight.date_min && (
                  <div className="text-muted-foreground">
                    Date range: <span style={MONO}>{ratesPreflight.date_min}</span> to <span style={MONO}>{ratesPreflight.date_max}</span> ({ratesPreflight.date_count} obs)
                  </div>
                )}

                {ratesPreflight.blocking_errors.map((e, i) => (
                  <div key={i} className="flex items-start gap-2 text-engine-red">
                    <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />{e}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        </div>
      </CollapsiblePanel>

      {/* Section 2: Grouping */}
      <CollapsiblePanel
        title="Grouping"
        icon={Layers}
        open={openSections.has("grouping")}
        onToggle={() => toggleSection("grouping")}
        status="ok"
        badge={groupKeys.length ? groupKeys.join(", ") : "Optional"}
      >
        <div className="px-4 pb-4 space-y-3">
          <div className="flex items-center gap-2">
            <FormSelect
              value=""
              onChange={(e) => { if (e.target.value) addGroupKey(e.target.value); }}
              className="flex-1"
            >
              <option value="">Add column to group by...</option>
              {allColumns.filter((col) => !groupKeys.includes(col)).map((col) => (
                <option key={col} value={col}>{col}</option>
              ))}
            </FormSelect>
          </div>
          {groupKeys.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {groupKeys.map((key) => (
                <span key={key} className="px-2 py-0.5 rounded bg-secondary text-xs text-foreground flex items-center gap-1.5">
                  {key}
                  <button onClick={() => removeGroupKey(key)} className="text-muted-foreground hover:text-engine-red text-xs">x</button>
                </span>
              ))}
            </div>
          )}
          {groupPreview && (
            <div className="border border-border rounded overflow-hidden">
              <DataTable
                tableId="group_preview"
                maxHeight="200px"
                columns={[
                  { id: "group_id", header: "Group", accessorKey: "group_id" },
                  { id: "loan_count", header: "Loans", accessorKey: "loan_count", align: "right" },
                  { id: "total_balance", header: "Balance", accessorKey: "total_balance", align: "right", cell: (v) => `$${(Number(v) / 1e6).toFixed(2)}M` },
                ] as DataTableColumn<GroupPreview>[]}
                data={groupPreview}
                getRowId={(r) => r.group_id}
              />
            </div>
          )}
          {groupLoading && <span className="text-muted-foreground text-xs">Loading groups...</span>}
        </div>
      </CollapsiblePanel>

      {/* Section 3: Assumptions + Scenarios */}
      <CollapsiblePanel
        title="Assumptions"
        icon={Settings2}
        open={openSections.has("assumptions")}
        onToggle={() => toggleSection("assumptions")}
        status="ok"
      >
        <div className="px-4 pb-4 space-y-3">
          {/* Scenario tabs */}
          <div className="flex items-center gap-1 border-b border-border">
            {scenarios.map((s, idx) => (
              <button
                key={idx}
                onClick={() => setActiveScenario(idx)}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs border-b-2 transition-colors ${
                  activeScenario === idx
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                {s.name}
                {scenarios.length > 1 && (
                  <button onClick={(e) => { e.stopPropagation(); removeScenario(idx); }}
                    className="text-muted-foreground/50 hover:text-engine-red ml-1">
                    <X className="w-2.5 h-2.5" />
                  </button>
                )}
              </button>
            ))}
            <button onClick={addScenario}
              className="px-2 py-1.5 text-muted-foreground hover:text-foreground text-xs flex items-center gap-1">
              <Plus className="w-3 h-3" /> Add
            </button>
          </div>

          {/* Scenario name + run mode */}
          <div className="flex items-center gap-3">
            <input
              value={sc.name}
              onChange={(e) => updateScenario({ name: e.target.value })}
              className="px-2 py-1 bg-input-background border border-border rounded text-xs w-48"
              style={MONO}
            />
            <div className="flex gap-1">
              {(["scheduled", "actual", "paired"] as RunMode[]).map((mode) => (
                <button
                  key={mode}
                  onClick={() => updateScenario({ run_mode: mode })}
                  className={`px-2 py-1 rounded border text-xs capitalize transition-colors ${
                    sc.run_mode === mode
                      ? "bg-primary/15 text-primary border-primary/30"
                      : "text-muted-foreground border-border hover:text-foreground hover:bg-white/5"
                  }`}
                >
                  {mode}
                </button>
              ))}
            </div>
          </div>

          {/* Assumption tree: Portfolio defaults */}
          <div className="border border-border rounded">
            <div className="bg-grid-header px-3 py-2 text-xs font-medium flex items-center gap-2">
              <GitBranch className="w-3.5 h-3.5 text-primary" />
              Portfolio Defaults
            </div>
            <div className="p-3 space-y-2">
              {sc.run_mode !== "scheduled" && (
                <>
                  <CurveRow label="SMM (Prepay)" input={sc.assumptions.smm}
                    onChange={(v) => updateAssumption("smm", v)}
                    onPreview={(v) => handleCurvePreview(v, "SMM")} />
                  <CurveRow label="MDR (Default)" input={sc.assumptions.mdr}
                    onChange={(v) => updateAssumption("mdr", v)}
                    onPreview={(v) => handleCurvePreview(v, "MDR")} />
                  <CurveRow label="Severity" input={sc.assumptions.severity}
                    onChange={(v) => updateAssumption("severity", v)}
                    onPreview={(v) => handleCurvePreview(v, "Severity")} />
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs text-muted-foreground block mb-1">Severity Lag (months)</label>
                      <input type="number" value={sc.assumptions.severity_lag_months}
                        onChange={(e) => updateAssumption("severity_lag_months", e.target.value)}
                        className="w-full px-2 py-1 bg-input-background border border-border rounded text-xs" style={MONO} />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground block mb-1">Months to Liquidation</label>
                      <input type="number" value={sc.assumptions.months_to_liquidation}
                        onChange={(e) => updateAssumption("months_to_liquidation", e.target.value)}
                        className="w-full px-2 py-1 bg-input-background border border-border rounded text-xs" style={MONO} />
                    </div>
                  </div>
                </>
              )}
              {sc.run_mode === "scheduled" && (
                <p className="text-xs text-muted-foreground">Scheduled-only mode — no prepay/default assumptions needed.</p>
              )}
            </div>
          </div>

          {/* Group overrides (if grouping is active) */}
          {groupPreview && groupPreview.length > 0 && sc.run_mode !== "scheduled" && (() => {
            const overrideCount = Object.keys(sc.group_overrides).filter(
              (k) => sc.group_overrides[k] && Object.keys(sc.group_overrides[k]).length > 0
            ).length;
            return (
            <div className="border border-border rounded">
              <div className="bg-grid-header px-3 py-2 text-xs font-medium flex items-center gap-2">
                <Layers className="w-3.5 h-3.5 text-engine-blue" />
                Group Overrides
                {overrideCount > 0 ? (
                  <span className="text-engine-blue font-normal">— {overrideCount} group(s) overridden</span>
                ) : (
                  <span className="text-muted-foreground font-normal">— all inheriting from portfolio</span>
                )}
                {overrideCount > 0 && (
                  <button
                    onClick={() => updateScenario({ group_overrides: {} })}
                    className="ml-auto text-xs text-muted-foreground hover:text-engine-red flex items-center gap-1 transition-colors"
                  >
                    <Trash2 className="w-3 h-3" /> Clear all overrides
                  </button>
                )}
              </div>
              <div className="max-h-[300px] overflow-auto">
                {groupPreview.map((g) => {
                  const override = sc.group_overrides[g.group_id];
                  const hasOverride = override && Object.keys(override).length > 0;
                  return (
                    <GroupOverrideRow
                      key={g.group_id}
                      groupId={g.group_id}
                      loanCount={g.loan_count}
                      override={override}
                      hasOverride={!!hasOverride}
                      onUpdate={(patch) => {
                        updateScenario({
                          group_overrides: { ...sc.group_overrides, [g.group_id]: patch },
                        });
                      }}
                      onClear={() => {
                        const next = { ...sc.group_overrides };
                        delete next[g.group_id];
                        updateScenario({ group_overrides: next });
                      }}
                    />
                  );
                })}
              </div>
            </div>
            );
          })()}

          {/* Curve preview sparkline */}
          {curvePreview && (
            <div className="border border-border rounded p-3">
              <div className="flex items-center gap-2 mb-2">
                <BarChart3 className="w-3.5 h-3.5 text-primary" />
                <span className="text-xs text-foreground">{previewField} Curve Preview</span>
                <button onClick={() => setCurvePreview(null)} className="ml-auto text-muted-foreground hover:text-foreground">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              <Sparkline values={curvePreview} height={60} />
            </div>
          )}
        </div>
      </CollapsiblePanel>

      {/* Preflight + Run */}
      <div className="bg-card border border-border rounded-lg p-4 space-y-3">
        <div className="flex items-center gap-3">
          <button onClick={runPreflight}
            className="px-3 py-1.5 rounded border border-border text-xs text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors flex items-center gap-1.5">
            <Check className="w-3.5 h-3.5" /> Preflight Check
          </button>

          {preflightResult && (
            <span className={`text-xs ${preflightResult.ok ? "text-engine-green" : "text-engine-red"}`}>
              {preflightResult.ok ? "All checks passed" : `${preflightResult.issues.length} issue(s)`}
            </span>
          )}
        </div>

        {preflightResult && !preflightResult.ok && (
          <div className="space-y-1">
            {preflightResult.issues.map((issue, i) => (
              <div key={i} className="flex items-start gap-2 text-xs text-engine-red">
                <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />{issue}
              </div>
            ))}
          </div>
        )}

        {error && (
          <div className="p-3 rounded border border-engine-red/30 bg-engine-red/5 text-xs text-engine-red flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />{error}
          </div>
        )}

        <button onClick={handleRun} disabled={running || !tapeReady}
          className="w-full py-2.5 rounded bg-primary text-primary-foreground font-medium text-sm hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2">
          {running ? (
            <><Loader2 className="w-4 h-4 animate-spin" /> Running...</>
          ) : !tapeReady ? (
            <><AlertTriangle className="w-4 h-4" /> Fix tape issues first</>
          ) : (
            <><Play className="w-4 h-4" /> Run Cashflows</>
          )}
        </button>
      </div>
    </div>
  );
}

// AccordionSection replaced by shared CollapsiblePanel

// ---------------------------------------------------------------------------
// Curve input row
// ---------------------------------------------------------------------------

function CurveRow({
  label, input, onChange, onPreview,
}: {
  label: string;
  input: CurveInput;
  onChange: (v: CurveInput) => void;
  onPreview?: (v: CurveInput) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <label className="text-xs text-muted-foreground w-28 shrink-0">{label}</label>
      <FormSelect value={input.type} onChange={(e) => onChange({ ...input, type: e.target.value as CurveType })}
        className="w-24">
        <option value="constant">Constant</option>
        <option value="psa">PSA</option>
        <option value="sda">SDA</option>
        <option value="vector">Vector</option>
        <option value="ramp">Ramp</option>
      </FormSelect>
      {input.type === "ramp" ? (
        <textarea value={input.value} onChange={(e) => onChange({ ...input, value: e.target.value })}
          className="flex-1 px-2 py-1 bg-input-background border border-border rounded text-xs resize-none h-8"
          style={MONO} placeholder="e.g. 0.005 for 12; 0.005 ramp 0.02 for 18" />
      ) : (
        <input type="text" value={input.value} onChange={(e) => onChange({ ...input, value: e.target.value })}
          className="flex-1 px-2 py-1 bg-input-background border border-border rounded text-xs"
          style={MONO}
          placeholder={input.type === "constant" ? "decimal (e.g. 0.006)" : input.type === "vector" ? "comma-separated values" : "speed (e.g. 150)"} />
      )}
      {onPreview && (
        <button onClick={() => onPreview(input)}
          className="text-muted-foreground hover:text-primary text-xs shrink-0">
          <BarChart3 className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Group override row
// ---------------------------------------------------------------------------

function GroupOverrideRow({
  groupId, loanCount, override, hasOverride, onUpdate, onClear,
}: {
  groupId: string;
  loanCount: number;
  override?: Partial<AssumptionSetState>;
  hasOverride: boolean;
  onUpdate: (patch: Partial<AssumptionSetState>) => void;
  onClear: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border-b border-border/50 last:border-b-0">
      <div className="flex items-center px-3 py-1.5 text-xs hover:bg-grid-row-hover transition-colors">
        <button onClick={() => setExpanded(!expanded)} className="flex items-center gap-2 flex-1 min-w-0">
          {expanded ? <ChevronDown className="w-3 h-3 shrink-0" /> : <ChevronRight className="w-3 h-3 shrink-0" />}
          <span style={MONO} className="text-foreground truncate">{groupId}</span>
          <span className="text-muted-foreground shrink-0">({loanCount})</span>
        </button>
        {hasOverride ? (
          <div className="flex items-center gap-2 shrink-0 ml-2">
            <span className="text-engine-blue text-xs">overridden</span>
            <button onClick={(e) => { e.stopPropagation(); onClear(); }}
              className="text-muted-foreground hover:text-engine-red" title="Clear this group override">
              <X className="w-3 h-3" />
            </button>
          </div>
        ) : (
          <span className="text-muted-foreground/40 text-xs shrink-0 ml-2">inherits</span>
        )}
      </div>
      {expanded && (
        <div className="px-3 pb-2 pl-8 space-y-2">
          <CurveRow label="SMM" input={override?.smm ?? { type: "constant", value: "" }}
            onChange={(v) => onUpdate({ ...override, smm: v })} />
          <CurveRow label="MDR" input={override?.mdr ?? { type: "constant", value: "" }}
            onChange={(v) => onUpdate({ ...override, mdr: v })} />
          <CurveRow label="Severity" input={override?.severity ?? { type: "constant", value: "" }}
            onChange={(v) => onUpdate({ ...override, severity: v })} />
          {hasOverride && (
            <button onClick={onClear} className="text-xs text-muted-foreground hover:text-engine-red flex items-center gap-1">
              <Trash2 className="w-3 h-3" /> Clear overrides
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sparkline (tiny SVG chart)
// ---------------------------------------------------------------------------

function Sparkline({ values, height = 40 }: { values: number[]; height?: number }) {
  if (!values.length) return null;
  const skip0 = values.slice(1);
  if (!skip0.length) return null;
  const min = Math.min(...skip0);
  const max = Math.max(...skip0);
  const range = max - min || 1;
  const w = 400;
  const points = skip0.map((v, i) => {
    const x = (i / (skip0.length - 1)) * w;
    const y = height - ((v - min) / range) * (height - 4) - 2;
    return `${x},${y}`;
  }).join(" ");

  return (
    <svg viewBox={`0 0 ${w} ${height}`} className="w-full" style={{ height }}>
      <polyline points={points} fill="none" stroke="var(--primary)" strokeWidth="1.5" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildCurveSpec(input: CurveInput): any {
  if (input.type === "constant") return { type: "constant", value: parseFloat(input.value) || 0 };
  if (input.type === "psa") return { type: "psa", speed: parseFloat(input.value) || 100 };
  if (input.type === "sda") return { type: "sda", speed: parseFloat(input.value) || 100 };
  if (input.type === "ramp") return { type: "ramp", expression: input.value || "0" };
  if (input.type === "vector") {
    const vals = input.value.split(",").map((s) => parseFloat(s.trim())).filter((v) => !isNaN(v));
    return { type: "vector", values: vals.length ? vals : [0] };
  }
  return { type: "constant", value: 0 };
}

function buildAssumptionsPayload(sc: ScenarioState): any {
  return {
    portfolio_defaults: {
      smm: buildCurveSpec(sc.assumptions.smm),
      mdr: buildCurveSpec(sc.assumptions.mdr),
      severity: buildCurveSpec(sc.assumptions.severity),
      severity_lag_months: parseInt(sc.assumptions.severity_lag_months) || 12,
      months_to_liquidation: parseInt(sc.assumptions.months_to_liquidation) || 12,
    },
    group_overrides: buildGroupOverrides(sc.group_overrides),
    loan_overrides: {},
  };
}

function buildGroupOverrides(overrides: Record<string, Partial<AssumptionSetState>>): Record<string, any> {
  const result: Record<string, any> = {};
  for (const [groupId, ov] of Object.entries(overrides)) {
    const set: any = {};
    if (ov.smm && ov.smm.value) set.smm = buildCurveSpec(ov.smm);
    if (ov.mdr && ov.mdr.value) set.mdr = buildCurveSpec(ov.mdr);
    if (ov.severity && ov.severity.value) set.severity = buildCurveSpec(ov.severity);
    if (Object.keys(set).length > 0) result[groupId] = set;
  }
  return result;
}
