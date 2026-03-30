const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

export interface UploadResponse {
  upload_id: string;
  file_name: string;
  row_count: number;
  column_count: number;
}

export interface ColumnProfile {
  name: string;
  dtype: string;
  sample_values: string[];
  null_count: number;
  unique_count: number;
}

export interface TapeProfile {
  upload_id: string;
  file_name: string;
  file_size_bytes: number;
  row_count: number;
  column_count: number;
  columns: ColumnProfile[];
}

export interface FieldMapping {
  source_column: string;
  canonical_field: string;
}

export interface MappingValidation {
  valid: boolean;
  errors: string[];
  warnings: string[];
  mapped_fields: string[];
  unmapped_required: string[];
  inferred_mappings: FieldMapping[];
}

export interface TapeStats {
  record_count: number;
  total_balance: number;
  wac: number;
  wala: number;
  wam: number;
  coupon_min: number;
  coupon_max: number;
  balance_min: number;
  balance_max: number;
  rate_type_distribution: Record<string, number>;
  top_states: Record<string, number> | null;
}

export interface GroupPreview {
  group_id: string;
  loan_count: number;
  total_balance: number;
}

export interface RunResponse {
  run_id: string;
  status: "queued" | "running" | "completed" | "failed";
  created_at: string;
  summary?: {
    loan_count: number;
    group_count: number;
    total_balance: number;
    wac: number;
    wam: number;
    warnings: string[];
    elapsed_seconds: number | null;
  };
  sections: string[];
  error?: string;
}

export interface CashflowPreview {
  section: string;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
}

export interface RiskMetricsResult {
  price: number;
  macaulay_duration_years: number;
  modified_duration_years: number;
  convexity_years2: number;
  yield_pct: number;
}

export interface PriceYieldTableResult {
  input_kind: string;
  value_kind: string;
  scenarios: string[];
  column_inputs: number[];
  values: number[][];
}

export interface RiskResponse {
  run_id: string;
  risk_metrics: Record<string, RiskMetricsResult> | null;
  price_yield_table: PriceYieldTableResult | null;
}

export interface TapePreview {
  columns: string[];
  rows: Record<string, unknown>[];
  total_rows: number;
  showing: number;
}

// ---------- Upload ----------

export function uploadTape(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  return request("/uploads", { method: "POST", body: form });
}

export function getProfile(uploadId: string): Promise<TapeProfile> {
  return request(`/uploads/${uploadId}/profile`);
}

export function getAutoMap(uploadId: string): Promise<FieldMapping[]> {
  return request(`/uploads/${uploadId}/auto-map`);
}

export function getTapeStats(
  uploadId: string,
  mappingId?: string
): Promise<TapeStats> {
  const q = mappingId ? `?mapping_id=${mappingId}` : "";
  return request(`/uploads/${uploadId}/stats${q}`);
}

export function getTapePreview(
  uploadId: string,
  limit = 100,
  mappingId?: string
): Promise<TapePreview> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (mappingId) params.set("mapping_id", mappingId);
  return request(`/uploads/${uploadId}/preview?${params}`);
}

// ---------- Tape Summary ----------

export interface TapeSummaryRow {
  column: string;
  dtype: string;
  count: number;
  missing: number;
  missing_pct: number;
  unique: number;
  mean: number | null;
  median: number | null;
  min: number | null;
  q25: number | null;
  q50: number | null;
  q75: number | null;
  p90: number | null;
  p95: number | null;
  p99: number | null;
  p995: number | null;
  p999: number | null;
  max: number | null;
  std: number | null;
  top_values: unknown[];
}

export interface TapeSummaryResult {
  columns: string[];
  rows: TapeSummaryRow[];
  row_count: number;
}

export function getTapeSummary(
  uploadId: string,
  mappingId?: string
): Promise<TapeSummaryResult> {
  const q = mappingId ? `?mapping_id=${mappingId}` : "";
  return request(`/uploads/${uploadId}/tape-summary${q}`);
}

export interface UniqueValuesRow {
  column: string;
  dtype: string;
  count: number;
  missing: number;
  missing_pct: number;
  unique: number;
  top_values: unknown[];
}

export interface UniqueValuesResult {
  columns: string[];
  rows: UniqueValuesRow[];
  row_count: number;
}

export function getUniqueValues(
  uploadId: string,
  mappingId?: string
): Promise<UniqueValuesResult> {
  const q = mappingId ? `?mapping_id=${mappingId}` : "";
  return request(`/uploads/${uploadId}/unique-values${q}`);
}

// ---------- Strats ----------

export interface StratDimension {
  column: string;
  type: "numeric" | "categorical";
  unique: number;
}

export interface StratResult {
  group_by: string;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
}

export function getStratDimensions(
  uploadId: string,
  mappingId?: string
): Promise<StratDimension[]> {
  const q = mappingId ? `?mapping_id=${mappingId}` : "";
  return request(`/uploads/${uploadId}/strat-dimensions${q}`);
}

export function computeStrat(
  uploadId: string,
  groupBy: string,
  mappingId?: string,
  maxBuckets = 10
): Promise<StratResult> {
  return request(`/uploads/${uploadId}/strats`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      group_by: groupBy,
      mapping_id: mappingId || null,
      max_buckets: maxBuckets,
    }),
  });
}

export function exportStrats(
  uploadId: string,
  dimensions: string[],
  mappingId?: string,
  format: "xlsx" | "csv" = "xlsx"
): void {
  const body = JSON.stringify({
    dimensions,
    mapping_id: mappingId || null,
    format,
  });
  fetch(`${BASE}/uploads/${uploadId}/strats-export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  })
    .then((res) => res.blob())
    .then((blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `strats.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    });
}

// ---------- Data Quality / Repair ----------

export interface ColumnIssue {
  column: string;
  missing_count: number;
  total_count: number;
  missing_pct: number;
}

export interface RepairRule {
  id: string;
  target: string;
  sources: string[];
  formula: string;
  description: string;
  missing_count: number;
  fixable_count: number;
}

export interface DiagnoseResult {
  total_rows: number;
  issues: ColumnIssue[];
  available_repairs: RepairRule[];
}

export interface RepairPreview {
  rule_id: string;
  rule: RepairRule;
  total_fixable: number;
  showing: number;
  columns: string[];
  rows: Record<string, unknown>[];
}

export function diagnoseTape(
  uploadId: string,
  mappingId?: string
): Promise<DiagnoseResult> {
  const q = mappingId ? `?mapping_id=${mappingId}` : "";
  return request(`/uploads/${uploadId}/diagnose${q}`);
}

export function getRepairPreview(
  uploadId: string,
  ruleId: string,
  mappingId?: string,
  limit = 20
): Promise<RepairPreview> {
  const params = new URLSearchParams({ rule_id: ruleId, limit: String(limit) });
  if (mappingId) params.set("mapping_id", mappingId);
  return request(`/uploads/${uploadId}/repair-preview?${params}`);
}

export function applyRepair(
  uploadId: string,
  ruleId: string,
  mappingId?: string
): Promise<{
  rule_id: string;
  rows_fixed: number;
  has_working_copy: boolean;
  message: string;
}> {
  return request(`/uploads/${uploadId}/apply-repair`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      rule_id: ruleId,
      mapping_id: mappingId || null,
    }),
  });
}

export function revertToRaw(
  uploadId: string
): Promise<{ message: string; has_working_copy: boolean }> {
  return request(`/uploads/${uploadId}/revert`, { method: "POST" });
}

export function getUploadStatus(
  uploadId: string
): Promise<{ upload_id: string; has_working_copy: boolean }> {
  return request(`/uploads/${uploadId}/status`);
}

// ---------- DQ Normalization ----------

export interface DqMapping {
  pattern: "status_code" | "days_past_due" | "pay_through" | "boolean_flags" | "balance_buckets" | "none";
  status_col?: string | null;
  dpd_col?: string | null;
  pay_thru_col?: string | null;
  asof_col?: string | null;
  fc_col?: string | null;
  fc_values?: unknown[] | null;
  reo_col?: string | null;
  reo_values?: unknown[] | null;
  status_code_map?: Record<string, string> | null;
  balance_bucket_cols?: Record<string, string> | null;
  confidence: number;
  notes: string;
}

export interface DqApplyResult {
  upload_id: string;
  pattern: string;
  columns_added: string[];
  row_count: number;
  has_working_copy: boolean;
  message: string;
}

export function detectDq(
  uploadId: string,
  mappingId?: string
): Promise<DqMapping> {
  const q = mappingId ? `?mapping_id=${mappingId}` : "";
  return request(`/uploads/${uploadId}/dq-detect${q}`);
}

export function applyDq(
  uploadId: string,
  dqMapping: DqMapping,
  mappingId?: string
): Promise<DqApplyResult> {
  return request(`/uploads/${uploadId}/dq-apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mapping_id: mappingId || null,
      dq_mapping: dqMapping,
    }),
  });
}

// ---------- Run Preflight (tape readiness) ----------

export interface RunPreflightResult {
  ready: boolean;
  blocking: string[];
  warnings: string[];
}

export function getRunPreflight(
  uploadId: string,
  mappingId?: string
): Promise<RunPreflightResult> {
  const q = mappingId ? `?mapping_id=${mappingId}` : "";
  return request(`/uploads/${uploadId}/run-preflight${q}`);
}

// ---------- Rates ----------

export interface RatesPreflight {
  required_indexes: string[];
  required_index_loan_counts: Record<string, number>;
  provided_columns: string[];
  resolved_mapping: Record<string, string>;
  missing_indexes: string[];
  date_min: string | null;
  date_max: string | null;
  date_count: number;
  blocking_errors: string[];
  warnings: string[];
  all_fixed: boolean;
}

export function uploadRates(
  uploadId: string,
  file: File
): Promise<{ upload_id: string; file_name: string }> {
  const form = new FormData();
  form.append("file", file);
  return request(`/uploads/${uploadId}/rates`, { method: "POST", body: form });
}

export function getRatesPreflight(
  uploadId: string,
  mappingId?: string
): Promise<RatesPreflight> {
  const q = mappingId ? `?mapping_id=${mappingId}` : "";
  return request(`/uploads/${uploadId}/rates-preflight${q}`);
}

// ---------- Curve Preview ----------

export interface CurvePreviewResult {
  values: number[];
  length: number;
}

export function previewCurve(
  spec: unknown,
  horizon = 361
): Promise<CurvePreviewResult> {
  return request("/curve-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ spec, horizon }),
  });
}

// ---------- Mapping ----------

export function validateMapping(body: {
  upload_id: string;
  mappings: FieldMapping[];
  asof_date?: string | null;
}): Promise<MappingValidation> {
  return request("/mappings/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function saveMapping(body: {
  upload_id: string;
  mappings: FieldMapping[];
  asof_date?: string | null;
}): Promise<{ mapping_id: string }> {
  return request("/mappings/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getGroupPreview(
  uploadId: string,
  grouping: { keys: string[] }
): Promise<GroupPreview[]> {
  return request(`/mappings/group-preview?upload_id=${uploadId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(grouping),
  });
}

// ---------- Runs ----------

export function createRun(body: {
  upload_id: string;
  mapping_id: string;
  grouping?: { keys: string[] } | null;
  assumptions: unknown;
  run_mode: string;
  scenarios?: unknown[];
}): Promise<RunResponse> {
  return request("/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getRun(runId: string): Promise<RunResponse> {
  return request(`/runs/${runId}`);
}

export function getPreview(
  runId: string,
  section: string
): Promise<CashflowPreview> {
  return request(`/runs/${runId}/preview/${section}`);
}

export function getArtifacts(
  runId: string
): Promise<{ run_id: string; artifacts: string[] }> {
  return request(`/runs/${runId}/artifacts`);
}

export function getRunGroups(
  runId: string
): Promise<{
  run_id: string;
  groups: string[];
  group_artifacts: Record<string, string>;
}> {
  return request(`/runs/${runId}/groups`);
}

export function getRunScenarios(
  runId: string
): Promise<{ run_id: string; scenarios: string[] }> {
  return request(`/runs/${runId}/scenarios`);
}

// ---------- Run History ----------

export interface RunListItem {
  run_id: string;
  status: string;
  created_at: string;
  loan_count: number;
  group_count: number;
  scenario_names: string[];
  elapsed_seconds: number | null;
  total_balance: number;
  wac: number;
  error?: string;
  has_inputs?: boolean;
}

export function listRuns(): Promise<RunListItem[]> {
  return request("/runs-list");
}

export interface RunConfig {
  run_config: {
    upload_id: string;
    mapping_id: string | null;
    mappings: FieldMapping[];
    asof_date: string | null;
    grouping: { keys: string[] } | null;
    run_mode: string;
    include_period_zero: boolean;
  };
  scenarios: Array<{
    name: string;
    run_mode: string;
    assumptions: unknown;
  }>;
  group_names: string[];
  summary: Record<string, unknown>;
}

export function getRunConfig(runId: string): Promise<RunConfig> {
  return request(`/runs/${runId}/config`);
}

// ---------- Run Inputs ----------

export function getRunInputTape(
  runId: string,
  maxRows = 500
): Promise<CashflowPreview> {
  return request(`/runs/${runId}/inputs/tape?max_rows=${maxRows}`);
}

export interface RunInputAssumptions {
  run_mode: string;
  grouping: { keys: string[] } | null;
  base_assumptions: Record<string, unknown>;
  scenarios: Array<{
    name: string;
    run_mode: string;
    assumptions: Record<string, unknown>;
  }> | null;
}

export function getRunInputAssumptions(
  runId: string
): Promise<RunInputAssumptions> {
  return request(`/runs/${runId}/inputs/assumptions`);
}

export interface RunInputMappings {
  asof_date: string | null;
  mappings: FieldMapping[];
}

export function getRunInputMappings(
  runId: string
): Promise<RunInputMappings> {
  return request(`/runs/${runId}/inputs/mappings`);
}

// ---------- Risk ----------

export function computeRisk(
  runId: string,
  body: {
    analytics: string[];
    input_kind?: string;
    base_value?: number;
    column_inputs?: number[];
  }
): Promise<RiskResponse> {
  return request(`/runs/${runId}/risk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
