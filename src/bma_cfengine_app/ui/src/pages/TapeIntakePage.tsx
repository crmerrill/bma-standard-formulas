import React, { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import {
  Upload,
  FileSpreadsheet,
  Check,
  AlertTriangle,
  ArrowRight,
  Link2,
  Unlink2,
} from "lucide-react";
import type {
  UploadResponse,
  TapeProfile,
  FieldMapping,
  MappingValidation,
} from "../services/api";
import * as api from "../services/api";
import { MONO } from "../lib/format";

const REQUIRED_FIELDS = [
  "loan_id", "origination_date", "asof_date", "original_balance",
  "current_balance", "rate_margin", "original_term", "remaining_term",
];

const OPTIONAL_GENERAL_FIELDS = [
  "servicing_fee", "accrued_interest", "group_id",
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

  const onDrop = useCallback(async (files: File[]) => {
    if (!files.length) return;
    setUploading(true);
    try {
      const res = await api.uploadTape(files[0]);
      setUpload(res);
      const [prof, autoMap] = await Promise.all([
        api.getProfile(res.upload_id),
        api.getAutoMap(res.upload_id),
      ]);
      setProfile(prof);
      setMappings(autoMap);
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
    const res = await api.validateMapping({
      upload_id: upload.upload_id,
      mappings,
      asof_date: asofDate || null,
    });
    setValidation(res);
    if (res.inferred_mappings.length) {
      setMappings((prev) => {
        const existing = new Set(prev.map((m) => m.canonical_field));
        const novel = res.inferred_mappings.filter((m) => !existing.has(m.canonical_field));
        return [...prev, ...novel];
      });
    }
  };

  const handleSaveAndContinue = async () => {
    if (!upload || !validation?.valid) return;
    setSaving(true);
    try {
      const { mapping_id } = await api.saveMapping({
        upload_id: upload.upload_id,
        mappings,
        asof_date: asofDate || null,
      });
      onComplete(upload.upload_id, mapping_id, mappings);
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
              <p className="text-sm font-medium" style={MONO}>{upload.file_name}</p>
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
              <span className="text-[10px] text-muted-foreground ml-auto">
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
                        <td colSpan={3} className="px-3 py-1.5 text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
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

          {/* Actions */}
          <div className="flex items-center gap-2 mt-4">
            <button
              onClick={handleValidate}
              className="px-3 py-1.5 rounded border border-border text-xs text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors"
            >
              Validate Mapping
            </button>
            <button
              onClick={handleSaveAndContinue}
              disabled={!validation?.valid || saving}
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
          <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-engine-amber/10 text-engine-amber border border-engine-amber/20">
            required
          </span>
        )}
      </td>
      <td className="px-3 py-1.5">
        <select
          value={currentMapping}
          onChange={(e) => onChange(e.target.value)}
          className="w-full px-2 py-1 bg-input-background border border-border rounded text-xs text-foreground"
          style={MONO}
        >
          <option value="">— select —</option>
          {sourceColumns.map((col) => (
            <option key={col} value={col}>{col}</option>
          ))}
        </select>
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
