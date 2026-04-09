"""Output schemas for CMO structuring diagnostics and stress matrices."""
from pydantic import BaseModel, Field

from .common import Dollars, Pct, ScheduleType, StructureRelation


class PacTacDiagnosticsRow(BaseModel):
    """PAC/TAC schedule attainment and range-drift diagnostics per period."""
    scenario_name: str
    tranche_id: str
    schedule_type: ScheduleType
    period: int = Field(ge=0)

    scheduled_principal: Dollars = 0.0
    actual_principal: Dollars = 0.0
    schedule_variance: Dollars = 0.0

    in_protected_range_flag: bool = True
    lower_bound_psa: float = 0.0
    upper_bound_psa: float = 0.0

    range_drift_lower_psa: float = 0.0
    range_drift_upper_psa: float = 0.0

    busted_flag: bool = False
    busted_period: int | None = None  # noqa: UP007 - Pydantic compat


class StructureCompositionRow(BaseModel):
    """Parent-child relationship QA for floater/inverse, IO/PO, Z-accrual."""
    scenario_name: str
    parent_tranche_id: str
    child_tranche_id: str
    relation_type: StructureRelation

    notional_ratio: float = 0.0
    coupon_identity_error: float = 0.0
    principal_conservation_error: Dollars = 0.0
    interest_conservation_error: Dollars = 0.0


class StressMatrixTrancheRow(BaseModel):
    """Stress-test result for a single tranche under a single stress axis."""
    stress_set_name: str
    tranche_id: str

    prepay_vector_id: str = ""
    default_vector_id: str = ""
    severity_vector_id: str = ""
    rate_path_id: str = ""

    pass_fail: bool = True
    principal_loss: Dollars = 0.0
    interest_shortfall_peak: Dollars = 0.0
    final_balance: Dollars = 0.0

    wal: float = 0.0
    maturity_extension_months: int = 0
    trigger_breach_count: int = 0
