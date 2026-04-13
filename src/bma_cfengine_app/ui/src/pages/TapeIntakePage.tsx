import React, { useCallback, useEffect, useState } from "react";
import { useDropzone } from "react-dropzone";
import {
  Upload,
  FileSpreadsheet,
  Check,
  AlertTriangle,
  ArrowRight,
  Link2,
  Unlink2,
  Activity,
} from "lucide-react";
import type {
  UploadResponse,
  TapeProfile,
  FieldMapping,
  MappingValidation,
  DqMapping,
} from "../services/api";
import * as api from "../services/api";
import { MONO } from "../lib/format";
import FormSelect from "../components/FormSelect";

const REQUIRED_FIELDS = [
  "loan_id", "origination_date", "asof_date", "original_balance",
  "current_balance", "rate_margin", "original_term", "remaining_term",
];

const OPTIONAL_GENERAL_FIELDS = [
  "servicing_fee", "accrued_interest",
  "maturity_date", "first_payment_date", "next_payment_date", "last_payment_date",
];

const OPTIONAL_SERVICER_FIELDS = [
  "pi_advanced", "advance_months",
  "svc_rate_default", "svc_rate_foreclosure",
];

const OPTIONAL_FLOATING_FIELDS = [
  "index_type", "reset_frequency", "next_reset_date",
  "periodic_cap", "periodic_floor", "rate_cap", "rate_floor",
];

interface FieldSection {
  label: string;
  fields: string[];
  required: boolean;
}

const FIELD_SECTIONS: FieldSection[] = [
  { label: "Required", fields: REQUIRED_FIELDS, required: true },
  { label: "Optional — General", fields: OPTIONAL_GENERAL_FIELDS, required: false },
  { label: "Optional — Servicer / Advancing", fields: OPTIONAL_SERVICER_FIELDS, required: false },
  { label: "Optional — Floating Rate / ARM", fields: OPTIONAL_FLOATING_FIELDS, required: false },
];

/** Pool/group comes from Run Setup keys, not tape mapping (never send to /mappings/*). */
function stripGroupId(maps: FieldMapping[]): FieldMapping[] {
  return maps.filter((m) => m.canonical_field.trim().toLowerCase() !== "group_id");
}

interface Props {
  onComplete: (uploadId: string, mappingId: string, mappings: FieldMapping[]) => void;
  asofDate: string;
}

export default function TapeIntakePage({ onComplete, asofDate }: Props) {
  const [upload, setUpload] = useState<UploadResponse | null>(null);
  const [profile, setProfile] = useState<TapeProfile | null>(null);
  const [mappings, setMappings] = useState<FieldMapping[]>([]);
  const [validation, setValidation] = useState<MappingValidation | null>(null);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [mappingId, setMappingId] = useState<string | null>(null);
  const [dqMapping, setDqMapping] = useState<DqMapping | null>(null);
  const [dqLoading, setDqLoading] = useState(false);
  const [dqApplied, setDqApplied] = useState(false);
  const [flowError, setFlowError] = useState<string | null>(null);

  const onDrop = useCallback(async (files: File[]) => {
    if (!files.length) return;
    setUploading(true);
    setFlowError(null);
    try {
      const file = files[0];
      const fallbackName = file.name.replace(/\.[^/.]+$/, "").trim() || file.name;
      const res = await api.uploadTape(file, fallbackName);
      const [prof, autoMap] = await Promise.all([
        api.getProfile(res.upload_id),
        api.getAutoMap(res.upload_id),
      ]);
      setUpload(res);
      setProfile(prof);
      setMappings(stripGroupId(autoMap));
      setValidation(null);
      setMappingId(null);
      setDqMapping(null);
      setDqApplied(false);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setFlowError(msg);
      setUpload(null);
      setProfile(null);
      setMappings([]);
    } finally {
      setUploading(false);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "text/csv": [".csv"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
    },
    maxFiles: 1,
  });

  const handleValidate = async () => {
    if (!upload) return;
    setFlowError(null);
    try {
      const mapsForApi = stripGroupId(mappings);
      const res = await api.validateMapping({
        upload_id: upload.upload_id,
        mappings: mapsForApi,
        asof_date: asofDate || null,
      });
      setValidation(res);

      const inferred = stripGroupId(res.inferred_mappings);
      let nextMaps = mapsForApi;
      if (inferred.length) {
        const byCanon = new Map(mapsForApi.map((m) => [m.canonical_field, m]));
        for (const m of inferred) {
          if (!byCanon.has(m.canonical_field)) byCanon.set(m.canonical_field, m);
        }
        nextMaps = Array.from(byCanon.values());
      }
      setMappings(nextMaps);

      if (res.valid) {
        const { mapping_id: mid } = await api.saveMapping({
          upload_id: upload.upload_id,
          mappings: nextMaps,
          asof_date: asofDate || null,
        });
        setMappingId(mid);

        setDqLoading(true);
        try {
          const dq = await api.detectDq(upload.upload_id, mid);
          setDqMapping(dq);
        } finally {
          setDqLoading(false);
        }
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setFlowError(msg);
    }
  };

  const handleApplyDq = async (mappingToApply?: DqMapping) => {
    const payload = mappingToApply ?? dqMapping;
    if (!upload || !mappingId || !payload) return;
    setSaving(true);
    setFlowError(null);
    try {
      await api.applyDq(upload.upload_id, payload, mappingId);
      setDqMapping(payload);
      setDqApplied(true);
    } catch (e: unknown) {
      setFlowError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleContinue = async () => {
    if (!upload || !mappingId || !validation?.valid) return;
    setSaving(true);
    setFlowError(null);
    try {
      if (dqMapping && dqMapping.pattern !== "none" && !dqApplied) {
        await api.applyDq(upload.upload_id, dqMapping, mappingId);
      }
      onComplete(upload.upload_id, mappingId, stripGroupId(mappings));
    } catch (e: unknown) {
      setFlowError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const setMapping = (canonical: string, source: string) => {
    setMappings((prev) => {
      const filtered = prev.filter((m) => m.canonical_field !== canonical);
      if (source) filtered.push({ source_column: source, canonical_field: canonical });
      return filtered;
    });
    setValidation(null);
  };

  const sourceColumns = profile?.columns.map((c) => c.name) ?? [];
  const mappedSources = new Set(mappings.map((m) => m.source_column));

  return (
    <div className="space-y-6 max-w-5xl">
      {flowError && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive flex gap-3 items-start">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <div className="min-w-0 flex-1">
            <p className="font-medium text-foreground">Something went wrong</p>
            <p className="text-xs mt-1 break-words opacity-90">{flowError}</p>
            <p className="text-xs text-muted-foreground mt-2">
              From repo root with deps installed:{" "}
              <code className="text-foreground/80 break-all" style={MONO}>
                PYTHONPATH=src uvicorn bma_cfengine_app.api.main:app --reload --port 8000
              </code>
            </p>
          </div>
          <button
            type="button"
            onClick={() => setFlowError(null)}
            className="text-xs text-muted-foreground hover:text-foreground shrink-0"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Upload zone */}
      {!upload && (
        <div
          {...getRootProps()}
          className={`border-2 border-dashed rounded-lg p-12 text-center cursor-pointer transition-colors ${
            isDragActive
              ? "border-primary bg-primary/5"
              : "border-border hover:border-primary/50"
          }`}
        >
          <input {...getInputProps()} />
          <Upload className="w-10 h-10 mx-auto text-muted-foreground mb-3" />
          <p className="text-sm text-foreground">
            {uploading ? "Uploading..." : "Drop a CSV or XLSX tape file here"}
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            or click to browse
          </p>
        </div>
      )}

      {/* Upload summary */}
      {upload && profile && (
        <div className="bg-card border border-border rounded-lg p-4">
          <div className="flex items-center gap-3 mb-3">
            <FileSpreadsheet className="w-5 h-5 text-primary" />
            <div>
              <p className="text-sm font-medium" style={MONO}>{upload.display_name || upload.file_name}</p>
              <p className="text-xs text-muted-foreground">
                {upload.row_count.toLocaleString()} rows &middot;{" "}
                {upload.column_count} columns &middot;{" "}
                {(profile.file_size_bytes / 1024).toFixed(0)} KB
              </p>
            </div>
          </div>

          {/* Mapping editor */}
          <div className="border border-border rounded overflow-hidden">
            <div className="bg-grid-header px-3 py-2 flex items-center gap-2">
              <Link2 className="w-3.5 h-3.5 text-primary" />
              <span className="text-xs font-medium">Field Mapping</span>
              <span className="text-xs text-muted-foreground ml-auto">
                {mappings.length} mapped
              </span>
            </div>

            <div className="max-h-[400px] overflow-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-grid-header">
                  <tr className="text-muted-foreground border-b border-border">
                    <th className="text-left px-3 py-1.5 w-1/3">Engine Field</th>
                    <th className="text-left px-3 py-1.5">Source Column</th>
                    <th className="text-center px-3 py-1.5 w-16">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {FIELD_SECTIONS.map((section) => (
                    <React.Fragment key={section.label}>
                      <tr className="bg-secondary/50">
                        <td colSpan={3} className="px-3 py-1.5 text-xs uppercase tracking-wider text-muted-foreground font-medium">
                          {section.label}
                        </td>
                      </tr>
                      {section.fields.map((field) => (
                        <MappingRow
                          key={field}
                          field={field}
                          required={section.required}
                          sourceColumns={sourceColumns}
                          currentMapping={mappings.find((m) => m.canonical_field === field)?.source_column ?? ""}
                          onChange={(src) => setMapping(field, src)}
                        />
                      ))}
                    </React.Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Validation */}
          {validation && (
            <div className={`mt-3 p-3 rounded border text-xs ${
              validation.valid
                ? "border-engine-green/30 bg-engine-green/5"
                : "border-engine-red/30 bg-engine-red/5"
            }`}>
              {validation.valid ? (
                <div className="flex items-center gap-2 text-engine-green">
                  <Check className="w-4 h-4" />
                  <span>Mapping valid — {validation.mapped_fields.length} fields mapped</span>
                </div>
              ) : (
                <div className="space-y-1">
                  {validation.errors.map((e, i) => (
                    <div key={i} className="flex items-start gap-2 text-engine-red">
                      <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                      <span>{e}</span>
                    </div>
                  ))}
                </div>
              )}
              {validation.warnings.map((w, i) => (
                <div key={i} className="flex items-start gap-2 text-engine-amber mt-1">
                  <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                  <span>{w}</span>
                </div>
              ))}
            </div>
          )}

          {/* DQ Mapping Panel */}
          {validation?.valid && dqMapping && (
            <DqMappingPanel
              mapping={dqMapping}
              onChange={setDqMapping}
              onApply={handleApplyDq}
              applied={dqApplied}
              loading={dqLoading}
              tapeColumns={profile?.columns.map((c) => c.name) ?? []}
            />
          )}
          {validation?.valid && dqLoading && (
            <div className="mt-3 p-3 rounded border border-border text-xs text-muted-foreground animate-pulse">
              Detecting delinquency patterns...
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 mt-4">
            <button
              onClick={handleValidate}
              className="px-3 py-1.5 rounded border border-border text-xs text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors"
            >
              Validate Mapping
            </button>
            <button
              onClick={handleContinue}
              disabled={!validation?.valid || saving || !mappingId}
              className="px-3 py-1.5 rounded bg-primary/10 border border-primary/20 text-primary text-xs hover:bg-primary/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
            >
              {saving ? "Saving..." : "Continue"}
              <ArrowRight className="w-3 h-3" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function MappingRow({
  field,
  required,
  sourceColumns,
  currentMapping,
  onChange,
}: {
  field: string;
  required: boolean;
  sourceColumns: string[];
  currentMapping: string;
  onChange: (source: string) => void;
}) {
  const mapped = !!currentMapping;
  return (
    <tr className="border-b border-border/50 hover:bg-grid-row-hover transition-colors">
      <td className="px-3 py-1.5">
        <span style={MONO} className={required ? "text-foreground" : "text-muted-foreground"}>
          {field}
        </span>
        {required && (
          <span className="ml-1.5 text-xs px-1 py-0.5 rounded bg-engine-amber/10 text-engine-amber border border-engine-amber/20">
            required
          </span>
        )}
      </td>
      <td className="px-3 py-1.5">
        <FormSelect
          value={currentMapping}
          onChange={(e) => onChange(e.target.value)}
          className="text-xs"
          style={MONO}
        >
          <option value="">— select —</option>
          {sourceColumns.map((col) => (
            <option key={col} value={col}>{col}</option>
          ))}
        </FormSelect>
      </td>
      <td className="px-3 py-1.5 text-center">
        {mapped ? (
          <Link2 className="w-3.5 h-3.5 text-engine-green inline-block" />
        ) : required ? (
          <Unlink2 className="w-3.5 h-3.5 text-engine-red inline-block" />
        ) : (
          <Unlink2 className="w-3.5 h-3.5 text-muted-foreground/30 inline-block" />
        )}
      </td>
    </tr>
  );
}

const PATTERN_LABELS: Record<string, string> = {
  status_code: "Integer Status Codes",
  days_past_due: "Days Past Due",
  pay_through: "Pay-Through Date",
  boolean_flags: "Boolean FC/REO Flags",
  balance_buckets: "Pre-Bucketed Balances",
  none: "None Detected",
};

/** Parse comma/semicolon-separated disposition codes (numbers, strings, true/false). */
function parseDispositionCodes(raw: string): unknown[] {
  return raw
    .split(/[,;]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
    .map((p) => {
      const lower = p.toLowerCase();
      if (lower === "true") return true;
      if (lower === "false") return false;
      const n = Number(p);
      if (p !== "" && !Number.isNaN(n) && /^-?\d+(\.\d+)?$/.test(p)) return n;
      return p;
    });
}

function DqMappingPanel({
  mapping,
  onChange,
  onApply,
  applied,
  loading,
  tapeColumns,
}: {
  mapping: DqMapping;
  onChange: (m: DqMapping) => void;
  /** Pass final mapping (after parsing FC/REO code fields). */
  onApply: (mapping: DqMapping) => void;
  applied: boolean;
  loading: boolean;
  tapeColumns: string[];
}) {
  const [fcCodesText, setFcCodesText] = useState("");
  const [reoCodesText, setReoCodesText] = useState("");

  useEffect(() => {
    setFcCodesText(mapping.fc_values?.map((v) => String(v)).join(", ") ?? "");
    setReoCodesText(mapping.reo_values?.map((v) => String(v)).join(", ") ?? "");
  }, [mapping.fc_values, mapping.reo_values]);

  if (loading) return null;

  const patternLabel = PATTERN_LABELS[mapping.pattern] ?? mapping.pattern;
  const isNone = mapping.pattern === "none";
  const hasManualFcReo =
    (!!mapping.fc_col && (mapping.fc_values?.length ?? 0) > 0) ||
    (!!mapping.reo_col && (mapping.reo_values?.length ?? 0) > 0);
  const canApplyDq = !isNone || hasManualFcReo;

  const commitFcReoCodes = () => {
    onChange({
      ...mapping,
      fc_values: parseDispositionCodes(fcCodesText),
      reo_values: parseDispositionCodes(reoCodesText),
    });
  };

  return (
    <div className="mt-3 border border-border rounded-lg overflow-clip">
      <div className="bg-grid-header px-3 py-2 flex items-center gap-2">
        <Activity className="w-3.5 h-3.5 text-primary" />
        <span className="text-xs font-medium">Delinquency Mapping</span>
        {applied && (
          <span className="ml-auto text-xs text-engine-green flex items-center gap-1">
            <Check className="w-3 h-3" /> Applied
          </span>
        )}
        {!applied && !isNone && (
          <span className="ml-auto text-xs text-muted-foreground">
            {Math.round(mapping.confidence * 100)}% confidence
          </span>
        )}
      </div>
      <div className="p-3 space-y-2 text-xs">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">Pattern:</span>
          <span className={`font-medium ${isNone ? "text-muted-foreground" : "text-foreground"}`}>
            {patternLabel}
          </span>
        </div>

        {mapping.notes && (
          <p className="text-muted-foreground">{mapping.notes}</p>
        )}

        {mapping.status_col && (
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">Status column:</span>
            <span className="font-mono text-foreground">{mapping.status_col}</span>
          </div>
        )}

        {mapping.dpd_col && (
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">DPD column:</span>
            <span className="font-mono text-foreground">{mapping.dpd_col}</span>
          </div>
        )}

        {mapping.pay_thru_col && (
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">Pay-through column:</span>
            <span className="font-mono text-foreground">{mapping.pay_thru_col}</span>
          </div>
        )}

        {mapping.fc_col && (
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">FC source:</span>
            <span className="font-mono text-foreground">
              {mapping.fc_col}
              {mapping.fc_values ? ` [${mapping.fc_values.join(", ")}]` : ""}
            </span>
          </div>
        )}

        {mapping.reo_col && (
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">REO source:</span>
            <span className="font-mono text-foreground">
              {mapping.reo_col}
              {mapping.reo_values ? ` [${mapping.reo_values.join(", ")}]` : ""}
            </span>
          </div>
        )}

        {isNone && !hasManualFcReo && (
          <p className="text-muted-foreground italic">
            No delinquency data detected in this tape. You can still map FC/REO from a code column
            below (e.g. zero-balance or loan-status codes).
          </p>
        )}

        {tapeColumns.length > 0 && (
          <div className="mt-3 pt-3 border-t border-border space-y-2">
            <p className="text-xs font-medium text-foreground">FC / REO code mapping</p>
            <p className="text-muted-foreground text-xs leading-snug">
              When FC/REO are not simple Y/N flags, choose the source column(s) and enter which
              raw values mean foreclosure vs REO (comma-separated). Often the same column for both
              (e.g. <span className="font-mono">zerobal_code</span>).
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="flex flex-col gap-1">
                <span className="text-muted-foreground">FC column</span>
                <FormSelect
                  className="bg-background font-mono"
                  value={mapping.fc_col ?? ""}
                  onChange={(e) => {
                    const v = e.target.value || null;
                    onChange({ ...mapping, fc_col: v, fc_values: mapping.fc_values ?? [] });
                  }}
                >
                  <option value="">—</option>
                  {tapeColumns.map((c) => (
                    <option key={`fc-${c}`} value={c}>
                      {c}
                    </option>
                  ))}
                </FormSelect>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-muted-foreground">REO column</span>
                <FormSelect
                  className="bg-background font-mono"
                  value={mapping.reo_col ?? ""}
                  onChange={(e) => {
                    const v = e.target.value || null;
                    onChange({ ...mapping, reo_col: v, reo_values: mapping.reo_values ?? [] });
                  }}
                >
                  <option value="">—</option>
                  {tapeColumns.map((c) => (
                    <option key={`reo-${c}`} value={c}>
                      {c}
                    </option>
                  ))}
                </FormSelect>
              </label>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="flex flex-col gap-1">
                <span className="text-muted-foreground">Values = FC</span>
                <input
                  type="text"
                  className="rounded border border-border bg-background px-2 py-1 font-mono text-xs"
                  placeholder="e.g. 2, 3, 6"
                  value={fcCodesText}
                  onChange={(e) => setFcCodesText(e.target.value)}
                  onBlur={commitFcReoCodes}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-muted-foreground">Values = REO</span>
                <input
                  type="text"
                  className="rounded border border-border bg-background px-2 py-1 font-mono text-xs"
                  placeholder="e.g. 9, 15, 16"
                  value={reoCodesText}
                  onChange={(e) => setReoCodesText(e.target.value)}
                  onBlur={commitFcReoCodes}
                />
              </label>
            </div>
          </div>
        )}

        {canApplyDq && !applied && (
          <button
            type="button"
            onClick={() => {
              const next: DqMapping = {
                ...mapping,
                fc_values: parseDispositionCodes(fcCodesText),
                reo_values: parseDispositionCodes(reoCodesText),
              };
              onChange(next);
              onApply(next);
            }}
            className="mt-1 px-3 py-1.5 rounded border border-primary/20 bg-primary/10 text-primary text-xs hover:bg-primary/20 transition-colors"
          >
            Apply DQ Mapping
          </button>
        )}
      </div>
    </div>
  );
}
