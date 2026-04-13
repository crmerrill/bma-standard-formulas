"""Shared enums, type aliases, and metadata blocks used across all deal schemas."""
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0.0"


class SchemaMetadata(BaseModel):
    """Metadata block attached to every top-level IR / output document."""
    schema_version: str = SCHEMA_VERSION
    run_id: str | None = None
    deal_id: str | None = None
    deal_version: int | None = None
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Scalar type aliases (documentation + validation in one place)
# ---------------------------------------------------------------------------

Dollars = Annotated[float, Field(description="Dollar amount")]
Rate = Annotated[float, Field(description="Annualized rate in percent (e.g. 5.0 = 5%)")]
Factor = Annotated[float, Field(ge=0.0, le=1.0, description="Factor between 0 and 1")]
Months = Annotated[int, Field(ge=0, description="Non-negative month count")]
BasisPoints = Annotated[float, Field(description="Basis points (e.g. 25.0 = 25bp)")]
Pct = Annotated[float, Field(description="Percentage (e.g. 10.0 = 10%)")]


# ---------------------------------------------------------------------------
# Core enums
# ---------------------------------------------------------------------------


class CouponType(str, Enum):
    FIXED = "FIXED"
    FLOATING = "FLOATING"
    INVERSE_FLOATING = "INVERSE_FLOATING"
    ZERO = "ZERO"


class DayCount(str, Enum):
    THIRTY_360 = "30/360"
    ACTUAL_360 = "ACT/360"
    ACTUAL_365 = "ACT/365"
    ACTUAL_ACTUAL = "ACT/ACT"


class AccrualPeriod(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    SEMI_ANNUAL = "SEMI_ANNUAL"
    ANNUAL = "ANNUAL"


class TrancheType(str, Enum):
    SEQUENTIAL = "SEQUENTIAL"
    PAC = "PAC"
    PAC_II = "PAC_II"
    TAC = "TAC"
    SUPPORT = "SUPPORT"
    Z_BOND = "Z_BOND"
    ACCRETION_DIRECTED = "ACCRETION_DIRECTED"
    FLOATER = "FLOATER"
    INVERSE_FLOATER = "INVERSE_FLOATER"
    IO = "IO"
    PO = "PO"
    PSEUDO = "PSEUDO"
    RESIDUAL = "RESIDUAL"


class TrancheBehavior(str, Enum):
    SEQUENTIAL = "SEQUENTIAL"
    PAC = "PAC"
    TAC = "TAC"
    Z = "Z"


class PayMode(str, Enum):
    CASH_PAY = "CASH_PAY"
    PIK = "PIK"


class AccountType(str, Enum):
    RESERVE = "RESERVE"
    PREFUNDING = "PREFUNDING"
    REVOLVING = "REVOLVING"
    PAYMENT = "PAYMENT"
    SPREAD_ACCOUNT = "SPREAD_ACCOUNT"


class MinimumBasis(str, Enum):
    FIXED_DOLLAR = "FIXED_DOLLAR"
    COLLATERAL_BALANCE = "COLLATERAL_BALANCE"
    NOTE_BALANCE = "NOTE_BALANCE"
    ORIGINAL_COLLATERAL = "ORIGINAL_COLLATERAL"


class FeeBasisType(str, Enum):
    FIXED_DOLLAR = "FIXED_DOLLAR"
    COLLATERAL_BALANCE = "COLLATERAL_BALANCE"
    PER_LOAN = "PER_LOAN"


class FeeFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


class PaymentStyle(str, Enum):
    SEQUENTIAL = "SEQUENTIAL"
    PRO_RATA = "PRO_RATA"


class RuleType(str, Enum):
    PAY_INTEREST = "PAY_INTEREST"
    PAY_INTEREST_SHORTFALL = "PAY_INTEREST_SHORTFALL"
    PAY_PRINCIPAL = "PAY_PRINCIPAL"
    PAY_WRITEDOWN = "PAY_WRITEDOWN"
    PAY_FEE = "PAY_FEE"
    PAY_TO_RESERVE = "PAY_TO_RESERVE"
    PAY_FROM_RESERVE_INTEREST = "PAY_FROM_RESERVE_INTEREST"
    PAY_FROM_RESERVE_PRINCIPAL = "PAY_FROM_RESERVE_PRINCIPAL"
    PAY_FROM_RESERVE = "PAY_FROM_RESERVE"
    PAY_RECOURSE_INTEREST = "PAY_RECOURSE_INTEREST"
    PAY_RECOURSE_PRINCIPAL = "PAY_RECOURSE_PRINCIPAL"
    PAY_RESIDUAL = "PAY_RESIDUAL"


class TriggerMetricType(str, Enum):
    CUMULATIVE_LOSS = "CUMULATIVE_LOSS"
    CUMULATIVE_DEFAULT = "CUMULATIVE_DEFAULT"
    DELINQUENCY_RATE = "DELINQUENCY_RATE"
    OC_TEST = "OC_TEST"
    IC_TEST = "IC_TEST"
    CUSTOM = "CUSTOM"


class TriggerState(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    CURED = "cured"
    INACTIVE = "inactive"


class ScheduleType(str, Enum):
    PAC = "PAC"
    TAC = "TAC"
    SUPPORT = "SUPPORT"


class StructureRelation(str, Enum):
    FLOATER_INVERSE = "floater_inverse"
    IO_PO = "io_po"
    Z_ACCRUAL = "z_accrual"


class CollateralInputMode(str, Enum):
    POOLED = "POOLED"
    GROUPED = "GROUPED"
    STRIP_PI = "STRIP_PI"


class SolverStatus(str, Enum):
    RUNNING = "RUNNING"
    CONVERGED = "CONVERGED"
    FAILED = "FAILED"
    INFEASIBLE = "INFEASIBLE"


# ---------------------------------------------------------------------------
# Precision / rounding policy
# ---------------------------------------------------------------------------


class PrecisionPolicy(BaseModel):
    """Controls decimal precision for outputs and comparisons."""
    currency_decimals: int = 2
    rate_decimals: int = 6
    factor_decimals: int = 8
    comparison_tolerance: float = 1e-6
    currency_rounding_mode: str = "HALF_EVEN"
