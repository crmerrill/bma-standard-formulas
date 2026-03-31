from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Canonical field contract — derived from TapeSchema.FIELD_SPECS
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: list[str] = [
    "loan_id",
    "origination_date",
    "asof_date",
    "original_balance",
    "current_balance",
    "rate_margin",
    "original_term",
    "remaining_term",
]

OPTIONAL_FIELDS: list[str] = [
    "servicing_fee",
    "accrued_interest",
    "pi_advanced",
    "advance_months",
    "reset_frequency",
    "maturity_date",
    "first_payment_date",
    "next_payment_date",
    "last_payment_date",
    "svc_rate_default",
    "svc_rate_foreclosure",
    "index_type",
    "next_reset_date",
    "periodic_cap",
    "periodic_floor",
    "rate_cap",
    "rate_floor",
    "days_past_due",
    "loan_status",
]

ALL_CANONICAL_FIELDS: list[str] = REQUIRED_FIELDS + OPTIONAL_FIELDS

# ---------------------------------------------------------------------------
# Upload / profiling
# ---------------------------------------------------------------------------


class ColumnProfile(BaseModel):
    name: str
    dtype: str
    sample_values: list[Any] = []
    null_count: int = 0
    unique_count: int = 0


class TapeProfile(BaseModel):
    upload_id: str
    file_name: str
    file_size_bytes: int
    row_count: int
    column_count: int
    columns: list[ColumnProfile]


class UploadResponse(BaseModel):
    upload_id: str
    file_name: str
    row_count: int
    column_count: int


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------


class FieldMapping(BaseModel):
    source_column: str
    canonical_field: str


class MappingRequest(BaseModel):
    upload_id: str
    mappings: list[FieldMapping]
    asof_date: str | None = None


class MappingValidation(BaseModel):
    valid: bool
    errors: list[str] = []
    warnings: list[str] = []
    mapped_fields: list[str] = []
    unmapped_required: list[str] = []
    inferred_mappings: list[FieldMapping] = []


# ---------------------------------------------------------------------------
# Tape statistics
# ---------------------------------------------------------------------------


class TapeStats(BaseModel):
    record_count: int
    total_balance: float
    wac: float
    wala: float
    wam: float
    coupon_min: float
    coupon_max: float
    balance_min: float
    balance_max: float
    rate_type_distribution: dict[str, int] = {}
    top_states: dict[str, int] | None = None


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


class GroupingConfig(BaseModel):
    keys: list[str] = Field(min_length=1)
    group_id_format: str = "{key}={value}"
    missing_value_policy: Literal["literal_unknown", "exclude"] = "literal_unknown"


class GroupPreview(BaseModel):
    group_id: str
    loan_count: int
    total_balance: float


# ---------------------------------------------------------------------------
# Assumption curves (discriminated union)
# ---------------------------------------------------------------------------


class ConstantCurve(BaseModel):
    type: Literal["constant"] = "constant"
    value: Annotated[float, Field(ge=0.0, le=1.0)]


class VectorCurve(BaseModel):
    type: Literal["vector"] = "vector"
    values: list[float] = Field(min_length=1)


class PsaCurve(BaseModel):
    type: Literal["psa"] = "psa"
    speed: float = Field(default=100.0, gt=0.0)


class SdaCurve(BaseModel):
    type: Literal["sda"] = "sda"
    speed: float = Field(default=100.0, gt=0.0)


class RampCurve(BaseModel):
    type: Literal["ramp"] = "ramp"
    expression: str = Field(min_length=1)


CurveSpec = Annotated[
    Union[ConstantCurve, VectorCurve, PsaCurve, SdaCurve, RampCurve],
    Field(discriminator="type"),
]


class AssumptionSet(BaseModel):
    smm: CurveSpec | None = None
    mdr: CurveSpec | None = None
    severity: CurveSpec | None = None
    severity_lag_months: int = Field(default=12, ge=0)
    months_to_liquidation: int = Field(default=12, ge=0)


class AssumptionsPayload(BaseModel):
    portfolio_defaults: AssumptionSet
    group_overrides: dict[str, AssumptionSet] = {}
    loan_overrides: dict[str, AssumptionSet] = {}


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class RunStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class ScenarioSpec(BaseModel):
    name: str = "Base Case"
    assumptions: AssumptionsPayload
    run_mode: Literal["scheduled", "actual", "paired"] = "actual"
    notes: str = ""


class RunRequest(BaseModel):
    upload_id: str
    mapping_id: str
    grouping: GroupingConfig | None = None
    assumptions: AssumptionsPayload
    run_mode: Literal["scheduled", "actual", "paired"] = "actual"
    include_period_zero: bool = False
    scenarios: list[ScenarioSpec] | None = None


class RunSummary(BaseModel):
    loan_count: int = 0
    group_count: int = 0
    total_balance: float = 0.0
    wac: float = 0.0
    wam: float = 0.0
    warnings: list[str] = []
    elapsed_seconds: float | None = None


class RunResponse(BaseModel):
    run_id: str
    status: RunStatus
    created_at: str
    summary: RunSummary | None = None
    sections: list[str] = []
    error: str | None = None


# ---------------------------------------------------------------------------
# Cashflow preview
# ---------------------------------------------------------------------------


class CashflowPreview(BaseModel):
    section: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool = False


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------


class RiskRequest(BaseModel):
    analytics: list[Literal["price_yield_table", "risk_metrics"]]
    input_kind: Literal["price", "yield"] = "yield"
    base_value: float = 6.0
    column_inputs: list[float] = Field(default=[4.0, 5.0, 6.0, 7.0, 8.0])


class RiskMetricsResult(BaseModel):
    price: float
    macaulay_duration_years: float
    modified_duration_years: float
    convexity_years2: float
    yield_pct: float


class PriceYieldTableResult(BaseModel):
    input_kind: str
    value_kind: str
    scenarios: list[str]
    column_inputs: list[float]
    values: list[list[float]]


class RiskResponse(BaseModel):
    run_id: str
    risk_metrics: dict[str, RiskMetricsResult] | None = None
    price_yield_table: PriceYieldTableResult | None = None


# ---------------------------------------------------------------------------
# Curve preview
# ---------------------------------------------------------------------------


class CurvePreviewRequest(BaseModel):
    spec: CurveSpec
    horizon: int = Field(default=361, ge=2, le=600)


class CurvePreviewResponse(BaseModel):
    values: list[float]
    length: int


# ---------------------------------------------------------------------------
# Rates preflight
# ---------------------------------------------------------------------------


class RatesPreflightResponse(BaseModel):
    required_indexes: list[str] = []
    required_index_loan_counts: dict[str, int] = {}
    provided_columns: list[str] = []
    resolved_mapping: dict[str, str] = {}
    missing_indexes: list[str] = []
    date_min: str | None = None
    date_max: str | None = None
    date_count: int = 0
    blocking_errors: list[str] = []
    warnings: list[str] = []
    all_fixed: bool = False
