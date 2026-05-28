"""Shared enums, type aliases, and metadata blocks used across all deal schemas."""
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------

# Bumped to 2.0.0 — contains intentional hard-cut breaking changes relative
# to 1.x payloads.  The migrate_deal_payload() helper in
# bma_standard_formulas.deals.schemas.migrations rewrites 1.x payloads to
# current form before Pydantic validation; every API and studio-load path
# MUST call it before attempting model_validate().
SCHEMA_VERSION = "2.0.0"

# Machine-readable compatibility notes consumed by migrations and API error
# messages.  Each entry describes one class of 1.x → 2.0 breaking change.
SCHEMA_COMPATIBILITY: dict[str, str] = {
    "account_type_removed": (
        "AccountDef.account_type was renamed to account_category in 2.0. "
        "migrate_deal_payload() rewrites the field automatically."
    ),
    "size_dollars_removed": (
        "BondDef.size_dollars was renamed to notional in 2.0. "
        "migrate_deal_payload() rewrites the field automatically."
    ),
    "size_pct_removed": (
        "BondDef.size_pct was renamed to notional_pct_of_collateral in 2.0. "
        "migrate_deal_payload() rewrites the field automatically."
    ),
    "schedule_speed_target_removed": (
        "BondDef.schedule_speed_target was removed in 2.0. TAC is now a "
        "degenerate band where schedule_speed_low == schedule_speed_high."
    ),
    "tranche_type_removed": (
        "BondDef.tranche_type (13 values) and tranche_behavior (4 values) "
        "were collapsed into BondDef.kind (TrancheKind, 8 values) in 2.0. "
        "migrate_deal_payload() rewrites using LEGACY_TRANCHE_KIND_MAP."
    ),
    "relation_fields_removed": (
        "BondDef.support_tranches, supported_by_tranches, tracks_bonds, "
        "parent_tranche, relation_type, notional_ratio were replaced by "
        "BondDef.relations: list[TrancheRelation] in 2.0. "
        "migrate_deal_payload() converts legacy fields automatically."
    ),
    "pay_to_reserve_renamed": (
        "RuleType.PAY_TO_RESERVE was renamed to PAY_TO_ACCOUNT in 2.0. "
        "migrate_deal_payload() rewrites the rule_type automatically."
    ),
    "reserve_recourse_rules_removed": (
        "RuleType values PAY_FROM_RESERVE_INTEREST, PAY_FROM_RESERVE_PRINCIPAL, "
        "PAY_FROM_RESERVE, PAY_RECOURSE_INTEREST, and PAY_RECOURSE_PRINCIPAL "
        "were removed in 2.0.  migrate_deal_payload() rewrites them to "
        "PAY_INTEREST / PAY_PRINCIPAL with the appropriate coverage_mode."
    ),
    "token_rename": (
        "Collateral source tokens INT_CASH and PRIN_CASH were renamed to "
        "ACT_INT and ACT_PRIN in 2.0.  The COLLATERAL token was removed "
        "(use CASH).  migrate_deal_payload() does NOT rewrite token strings "
        "inside IR expressions; update deal IR directly."
    ),
}


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


class TrancheKind(str, Enum):
    CASH_PAY = "CASH_PAY"
    PAC = "PAC"
    TAC = "TAC"
    IO = "IO"
    PO = "PO"
    Z = "Z"
    RESIDUAL = "RESIDUAL"
    PSEUDO = "PSEUDO"


class PayMode(str, Enum):
    CASH_PAY = "CASH_PAY"
    PIK = "PIK"


class AccountCategory(str, Enum):
    """UI / reporting label for an account; the runtime does not branch on this."""

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


class CoverageMode(str, Enum):
    NORMAL = "NORMAL"
    INTEREST_SHORTFALL = "INTEREST_SHORTFALL"
    PRINCIPAL_ACCELERATION = "PRINCIPAL_ACCELERATION"


class CapMode(str, Enum):
    """How a PAY_PRINCIPAL rule interprets the target bond's `schedule_contract`.

    Maps directly to prospectus language:
        - `PLANNED`:    "to its Planned Balance" (PAC bond convention)
        - `SCHEDULED`:  "to its Scheduled Balance" (SCH/Scheduled bond)
        - `TARGETED`:   "to its Targeted Balance" (TAC bond)
        - `NONE`:       "without regard to its [...] Balance" (cleanup rule)

    PLANNED, SCHEDULED, and TARGETED are runtime-equivalent (all enforce the
    bond's `schedule_contract` end-of-period balance target). They differ only
    in naming and structuring intent: PAC vs SCH/Scheduled vs TAC. The
    documentation and UI render them differently to mirror the prospectus
    vocabulary, but the math is identical.

    NONE bypasses the schedule cap entirely so the rule can pay the bond
    beyond its planned balance until the bond's outstanding balance reaches
    zero. This is the standard cleanup-rule pattern at the bottom of every
    PAC priority-of-payments waterfall.
    """
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    TARGETED = "TARGETED"
    NONE = "NONE"


class RuleType(str, Enum):
    PAY_INTEREST = "PAY_INTEREST"
    PAY_INTEREST_SHORTFALL = "PAY_INTEREST_SHORTFALL"
    PAY_PRINCIPAL = "PAY_PRINCIPAL"
    PAY_WRITEDOWN = "PAY_WRITEDOWN"
    PAY_FEE = "PAY_FEE"
    PAY_TO_ACCOUNT = "PAY_TO_ACCOUNT"
    PAY_RESIDUAL = "PAY_RESIDUAL"
    # Cash-flow plumbing: split one stream into N target streams (or merge N
    # streams into one) using explicit per-target weights. The targets are
    # named virtual streams that subsequent rules draw from via `from_sources`.
    # This is the IR primitive for face-weighted cash splits (e.g., FNR
    # 2006-018 supports 95.65 / 4.35) and stream-of-streams plumbing
    # (interest-vs-principal sub-cascades, sweep-back paths, etc.).
    SPLIT_CASH = "SPLIT_CASH"
    # Credit-card master-trust mechanics (Phase 6):
    # Reimbursement of previously-depleted Nominal Liquidation Amount (NLA)
    # from available cash (typically excess spread). Debits from_sources and
    # credits the NLA balance of each target bond up to the bond's starting
    # NLA (i.e., does not inflate NLA above the original face amount).
    # Does NOT change the bond's economic balance — only the NLA tracker.
    REIMBURSE_NLA = "REIMBURSE_NLA"


class TriggerMetricType(str, Enum):
    CUMULATIVE_LOSS = "CUMULATIVE_LOSS"
    CUMULATIVE_DEFAULT = "CUMULATIVE_DEFAULT"
    DELINQUENCY_RATE = "DELINQUENCY_RATE"
    OC_TEST = "OC_TEST"
    IC_TEST = "IC_TEST"
    CUSTOM = "CUSTOM"
    # Phase 9: rolling-window averages are expressed as CUSTOM triggers with
    # a calculation_ref pointing to the relevant metric AND window_periods set
    # on the TriggerNode. This is more flexible than named metric types because
    # excess spread, portfolio yield, and base rate are all deal-specific
    # calculations that vary by prospectus definition.
    #
    # Example:
    #   CalculationNode(name="excess_spread_rate", expression="collateral_net_rate - ..."),
    #   TriggerNode(name="ExcessSpreadTrigger", metric_type=CUSTOM,
    #               calculation_ref="excess_spread_rate",
    #               threshold_value=3.5, comparison="<",  # fires when BELOW threshold
    #               window_periods=3)
    #
    # No dedicated enum values for individual rolling metrics — they would be
    # misleadingly similar to CUSTOM without adding expressiveness.


class DealStateType(str, Enum):
    """Phase 9: deal-level state machine for credit-card revolving / amortization modes.

    The runtime computes the current deal state each period based on the
    `deal_state_trigger` field on `DealDefinition`. The state is exposed in
    the expression context as `deal_state` (string) and can gate rules via
    `condition_expr`.

    REVOLVING:          Default. Principal returned to seller / reinvested.
    ACCUMULATION:       PFA/IFA accumulation period. Principal deposited to
                        funding accounts; bonds not yet paid principal.
    AMORTIZATION:       Scheduled amortization. Principal paid to bonds.
    EARLY_AMORTIZATION: Pay-out / early amortization event. Principal paid
                        to bonds in priority order immediately.
    """
    REVOLVING = "REVOLVING"
    ACCUMULATION = "ACCUMULATION"
    AMORTIZATION = "AMORTIZATION"
    EARLY_AMORTIZATION = "EARLY_AMORTIZATION"


class TriggerState(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    CURED = "cured"
    INACTIVE = "inactive"


class ScheduleType(str, Enum):
    PAC = "PAC"
    TAC = "TAC"
    SUPPORT = "SUPPORT"


class PrepayModelType(str, Enum):
    PSA = "PSA"
    CPR = "CPR"
    ABS = "ABS"
    CUSTOM_VECTOR = "CUSTOM_VECTOR"


class TrancheRelationType(str, Enum):
    SUPPORTED_BY = "SUPPORTED_BY"
    ACCRETES_TO = "ACCRETES_TO"
    NOTIONAL_TRACKS = "NOTIONAL_TRACKS"
    BALANCE_TRACKS = "BALANCE_TRACKS"
    COUPON_INVERSE_OF = "COUPON_INVERSE_OF"
    COUPON_LEVERAGE_OF = "COUPON_LEVERAGE_OF"
    MACR_EXCHANGE = "MACR_EXCHANGE"


class CollateralInputMode(str, Enum):
    """Discriminator for the collateral payload variants in DealRunInput.

    POOLED:   Single LDCMA-format CollateralCashflows feed (legacy parity path).
    GROUPED:  ``dict[group_id, CollateralCashflows]`` for multi-group deals
              (legacy parity path).
    STRIP_PI: Separate principal and interest LDCMA streams (rare; mostly
              legacy strip products).
    PAIRED:   BMA PortfolioCashflow in PAIRED mode, consumed natively by the
              runtime with full per-loan visibility (proposal R, Phase 1).
              Multi-group deals tag each loan with ``group_id`` and the
              runtime calls ``portfolio.aggregate_actual_by_group()`` to
              route ``GROUP_<id>_*`` source tokens.
    """
    POOLED = "POOLED"
    GROUPED = "GROUPED"
    STRIP_PI = "STRIP_PI"
    PAIRED = "PAIRED"


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
