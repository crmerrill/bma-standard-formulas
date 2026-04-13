import React, { useEffect, useMemo, useState } from "react";
import * as api from "../../../services/api";
import type {
  RunListItem,
  UploadLibraryItem,
  UploadMappingSummary,
} from "../../../services/api";
import { fmtDate, fmtNamedId, MONO } from "../../../lib/format";
import FormSelect from "../../../components/FormSelect";
import { applyProductFamilyPreset, type CollateralRiskSettings } from "./riskSettings";

interface Props {
  value: CollateralRiskSettings;
  onChange: (next: CollateralRiskSettings) => void;
  availableRuns: RunListItem[];
  availableTapes?: UploadLibraryItem[];
  poolSnapshots?: unknown[];
  onOpenTape?: (uploadId: string, mappingId: string) => Promise<void> | void;
  onRunCashflow?: () => Promise<void> | void;
  canRunCashflow?: boolean;
  runCashflowBusy?: boolean;
  title?: string;
  className?: string;
}

function ConfigNum({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (next: number) => void;
}) {
  return (
    <label className="space-y-1">
      <span className="text-muted-foreground">{label}</span>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
        className="w-full px-2 py-1 bg-input-background border border-border rounded text-foreground"
      />
    </label>
  );
}

export default function CollateralRiskSettingsEditor({
  value,
  onChange,
  availableRuns,
  availableTapes = [],
  poolSnapshots: _poolSnapshots = [],
  onOpenTape,
  onRunCashflow,
  canRunCashflow = false,
  runCashflowBusy = false,
  title = "Collateral Pool Assignment",
  className,
}: Props) {
  const existingRiskRuns = availableRuns.filter(
    (run) => run.status === "completed" && (run.run_type ?? "portfolio") === "portfolio",
  );

  const set = <K extends keyof CollateralRiskSettings>(key: K, next: CollateralRiskSettings[K]) =>
    onChange({ ...value, [key]: next });
  const [tapeMappings, setTapeMappings] = useState<UploadMappingSummary[]>([]);
  const [mappingsLoading, setMappingsLoading] = useState(false);
  const [openingTape, setOpeningTape] = useState(false);
  const [tapeSearch, setTapeSearch] = useState("");
  const selectedTape = availableTapes.find((tape) => tape.upload_id === value.tapeId) ?? null;
  const selectedTapeInLibrary = !!selectedTape;
  const filteredTapes = useMemo(() => {
    const needle = tapeSearch.trim().toLowerCase();
    if (!needle) return availableTapes;
    return availableTapes.filter((tape) =>
      `${tape.display_name} ${tape.file_name} ${tape.upload_id}`.toLowerCase().includes(needle),
    );
  }, [availableTapes, tapeSearch]);
  const selectedMappingSummary = tapeMappings.find((item) => item.mapping_id === value.tapeMappingId) ?? null;

  useEffect(() => {
    let cancelled = false;
    if (!value.tapeId) {
      setTapeMappings([]);
      if (value.tapeMappingId) {
        onChange({ ...value, tapeMappingId: "" });
      }
      return () => {
        cancelled = true;
      };
    }
    setMappingsLoading(true);
    api.listUploadMappings(value.tapeId)
      .then((res) => {
        if (cancelled) return;
        setTapeMappings(res.items);
        const exists = !!value.tapeMappingId && res.items.some((item) => item.mapping_id === value.tapeMappingId);
        const latest = [...res.items].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))[0] ?? null;
        const nextMappingId = exists ? value.tapeMappingId : (latest?.mapping_id ?? "");
        const nextPoolId = value.tapeId;
        const nextPoolName = selectedTape?.display_name || selectedTape?.file_name || value.tapeId;
        if (
          nextMappingId !== value.tapeMappingId
          || nextPoolId !== value.poolId
          || nextPoolName !== value.poolName
          || value.poolVersion !== null
        ) {
          onChange({
            ...value,
            tapeMappingId: nextMappingId,
            poolId: nextPoolId,
            poolName: nextPoolName,
            poolVersion: null,
          });
        }
      })
      .catch(() => {
        if (!cancelled) setTapeMappings([]);
      })
      .finally(() => {
        if (!cancelled) setMappingsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [value.tapeId]);

  const handleOpenTape = async () => {
    if (!onOpenTape || !value.tapeId || !value.tapeMappingId) return;
    setOpeningTape(true);
    try {
      await onOpenTape(value.tapeId, value.tapeMappingId);
    } finally {
      setOpeningTape(false);
    }
  };

  return (
    <div className={className ?? "space-y-2"}>
      <div className="text-xs uppercase tracking-wider text-muted-foreground">{title}</div>
      <div className="rounded border border-border p-2 space-y-2">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-2 items-end">
          <label className="block space-y-1">
            <span className="text-muted-foreground">Product Family</span>
            <FormSelect
              value={value.productFamily}
              onChange={(e) =>
                set("productFamily", e.target.value as CollateralRiskSettings["productFamily"])
              }
              className="px-2"
            >
              <option value="AGENCY">Agency</option>
              <option value="PRIME_JUMBO">Prime Jumbo</option>
              <option value="NON_QM_QRM">Non-QM / QRM</option>
              <option value="CUSTOM">Custom</option>
            </FormSelect>
          </label>
          <button
            type="button"
            onClick={() => onChange(applyProductFamilyPreset(value, value.productFamily))}
            className="px-2.5 py-1 rounded border border-border text-xs text-muted-foreground hover:text-foreground"
          >
            Apply Profile Preset
          </button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <label className="block space-y-1">
            <span className="text-muted-foreground">Tape ID</span>
            {availableTapes.length > 0 && (
              <input
                value={tapeSearch}
                onChange={(e) => setTapeSearch(e.target.value)}
                className="w-full px-2 py-1 bg-input-background border border-border rounded text-foreground"
                placeholder="Search tapes..."
              />
            )}
            {availableTapes.length > 0 ? (
              <FormSelect
                value={value.tapeId}
                onChange={(e) =>
                  onChange({
                    ...value,
                    tapeId: e.target.value,
                    tapeMappingId: "",
                    poolId: "",
                    poolName: "",
                    poolVersion: null,
                  })
                }
                className="px-2"
              >
                <option value="">Select tape...</option>
                {value.tapeId && !selectedTapeInLibrary && (
                  <option value={value.tapeId}>{value.tapeId}</option>
                )}
                {value.tapeId
                  && selectedTapeInLibrary
                  && !filteredTapes.some((tape) => tape.upload_id === value.tapeId) && (
                    <option value={value.tapeId}>
                      {fmtNamedId(selectedTape?.display_name || selectedTape?.file_name || value.tapeId, value.tapeId)}
                    </option>
                  )}
                {filteredTapes.map((tape) => (
                  <option key={tape.upload_id} value={tape.upload_id}>
                    {fmtNamedId(tape.display_name || tape.file_name, tape.upload_id)}
                  </option>
                ))}
              </FormSelect>
            ) : (
              <input
                value={value.tapeId}
                onChange={(e) =>
                  onChange({
                    ...value,
                    tapeId: e.target.value,
                    tapeMappingId: "",
                    poolId: "",
                    poolName: "",
                    poolVersion: null,
                  })
                }
                className="w-full px-2 py-1 bg-input-background border border-border rounded text-foreground"
                style={MONO}
                placeholder="upload_xxx"
              />
            )}
          </label>
          <div className="text-xs text-muted-foreground md:col-span-2">
            Tape mapping is auto-bound and locked:{" "}
            {mappingsLoading
              ? "resolving..."
              : value.tapeMappingId || (!value.tapeId ? "select tape first" : "no saved mapping found")}
            {selectedMappingSummary
              ? ` (${selectedMappingSummary.mapped_fields} fields, ${fmtDate(selectedMappingSummary.updated_at)})`
              : ""}
          </div>
        </div>
        {onOpenTape && (
          <div className="flex items-center justify-end gap-2">
            {onRunCashflow && (
              <button
                type="button"
                onClick={() => void onRunCashflow()}
                disabled={!canRunCashflow || !value.validation.isValid || runCashflowBusy}
                className="px-2.5 py-1 rounded border border-primary/40 bg-primary/10 text-xs text-primary hover:bg-primary/20 disabled:opacity-40"
                title={!canRunCashflow ? "Save the deal first to enable run." : undefined}
              >
                {runCashflowBusy ? "Running CF..." : "Run Cashflow"}
              </button>
            )}
            <button
              type="button"
              onClick={handleOpenTape}
              disabled={!value.tapeId || !value.tapeMappingId || openingTape}
              className="px-2.5 py-1 rounded border border-border text-xs text-muted-foreground hover:text-foreground disabled:opacity-40"
            >
              {openingTape ? "Opening tape..." : "Open tape in Tape View"}
            </button>
          </div>
        )}
        {onRunCashflow && !canRunCashflow && (
          <div className="text-xs text-muted-foreground">Save deal to enable Run Cashflow from Properties.</div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <label className="block space-y-1">
            <span className="text-muted-foreground">Risk Source</span>
            <FormSelect
              value={value.riskSourceMode}
              onChange={(e) =>
                set("riskSourceMode", e.target.value as CollateralRiskSettings["riskSourceMode"])
              }
              className="px-2"
            >
              <option value="new_risk">Run New Risk</option>
              <option value="existing_run">Use Existing Risk Run</option>
            </FormSelect>
          </label>
          {value.riskSourceMode === "existing_run" ? (
            <label className="block space-y-1">
              <span className="text-muted-foreground">Existing risk run</span>
              <FormSelect
                value={value.existingRiskRunId ?? ""}
                onChange={(e) => set("existingRiskRunId", e.target.value || null)}
                className="px-2"
              >
                <option value="">Select run</option>
                {existingRiskRuns.map((run) => (
                  <option key={run.run_id} value={run.run_id}>
                    {`${run.run_id} (${fmtDate(run.created_at)})`}
                  </option>
                ))}
              </FormSelect>
            </label>
          ) : (
            <div className="text-xs text-muted-foreground self-end pb-1">
              Configure scenario assumptions below.
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <ConfigNum
            label="CPR %"
            value={value.newRiskParams.cpr}
            onChange={(v) => set("newRiskParams", { ...value.newRiskParams, cpr: v })}
          />
          <ConfigNum
            label="CDR %"
            value={value.newRiskParams.cdr}
            onChange={(v) => set("newRiskParams", { ...value.newRiskParams, cdr: v })}
          />
          <ConfigNum
            label="Severity %"
            value={value.newRiskParams.severity}
            onChange={(v) => set("newRiskParams", { ...value.newRiskParams, severity: v })}
          />
          <ConfigNum
            label="Horizon (months)"
            value={value.newRiskParams.horizonMonths}
            onChange={(v) => set("newRiskParams", { ...value.newRiskParams, horizonMonths: v })}
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          <label className="block space-y-1">
            <span className="text-muted-foreground">Rate scenario</span>
            <input
              value={value.rateScenario.scenarioName}
              onChange={(e) =>
                set("rateScenario", { ...value.rateScenario, scenarioName: e.target.value })
              }
              className="w-full px-2 py-1 bg-input-background border border-border rounded text-foreground"
            />
          </label>
          <ConfigNum
            label="Spread shock (bps)"
            value={value.rateScenario.spreadShockBps}
            onChange={(v) => set("rateScenario", { ...value.rateScenario, spreadShockBps: v })}
          />
          <ConfigNum
            label="Yield shock (bps)"
            value={value.rateScenario.yieldShockBps}
            onChange={(v) => set("rateScenario", { ...value.rateScenario, yieldShockBps: v })}
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          <label className="block space-y-1">
            <span className="text-muted-foreground">Execution mode</span>
            <FormSelect
              value={value.execution.runMode}
              onChange={(e) =>
                set("execution", {
                  ...value.execution,
                  runMode: e.target.value as CollateralRiskSettings["execution"]["runMode"],
                })
              }
              className="px-2"
            >
              <option value="cashflow">Cashflow</option>
              <option value="solver">Solver</option>
            </FormSelect>
          </label>
          <label className="block space-y-1">
            <span className="text-muted-foreground">Artifact scope</span>
            <FormSelect
              value={value.execution.artifactScope}
              onChange={(e) =>
                set("execution", {
                  ...value.execution,
                  artifactScope: e.target.value as CollateralRiskSettings["execution"]["artifactScope"],
                })
              }
              className="px-2"
            >
              <option value="standard">Standard</option>
              <option value="full">Full diagnostics</option>
            </FormSelect>
          </label>
          <label className="block space-y-1">
            <span className="text-muted-foreground">Compare baseline run</span>
            <FormSelect
              value={value.execution.compareBaselineRunId ?? ""}
              onChange={(e) =>
                set("execution", {
                  ...value.execution,
                  compareBaselineRunId: e.target.value || null,
                })
              }
              className="px-2"
            >
              <option value="">None</option>
              {availableRuns.map((run) => (
                <option key={run.run_id} value={run.run_id}>
                  {run.run_id}
                </option>
              ))}
            </FormSelect>
          </label>
        </div>

        <div
          className={
            value.validation.isValid
              ? "rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-xs text-emerald-300"
              : "rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs text-amber-200"
          }
        >
          {value.validation.isValid ? (
            <span>Validation: ready</span>
          ) : (
            <span>Validation: {value.validation.messages.join(" | ")}</span>
          )}
        </div>
      </div>
    </div>
  );
}
