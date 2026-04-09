"""Parity-check, tolerance, and QA report schemas."""
from pydantic import BaseModel, Field

from .common import PrecisionPolicy


class FieldComparisonResult(BaseModel):
    """Result of comparing one field across two outputs."""
    field_name: str
    period: int | None = None
    tranche_id: str | None = None

    expected: float = 0.0
    actual: float = 0.0
    absolute_error: float = 0.0
    relative_error: float = 0.0
    within_tolerance: bool = True


class ParityCheckReport(BaseModel):
    """Result of comparing deal outputs against a golden baseline."""
    test_name: str
    deal_name: str
    scenario_name: str = "Base Case"

    total_comparisons: int = 0
    pass_count: int = 0
    fail_count: int = 0
    max_absolute_error: float = 0.0
    max_relative_error: float = 0.0

    precision: PrecisionPolicy = Field(default_factory=PrecisionPolicy)
    failures: list[FieldComparisonResult] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.fail_count == 0


class SchemaCompatibility(BaseModel):
    """Compatibility matrix entry — IR version vs runtime vs artifact version."""
    ir_schema_version: str
    runtime_version: str
    artifact_schema_version: str
    compatible: bool = True
    notes: str = ""
