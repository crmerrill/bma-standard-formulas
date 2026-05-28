"""Output schemas for account state, waterfall trace, and trigger history."""
import datetime as _dt
from typing import Optional

from pydantic import BaseModel, Field

from .common import Dollars, DealStateType, SchemaMetadata, TriggerState


class DealAccountRow(BaseModel):
    """Single period of a single account (long-format grain)."""
    scenario_name: str
    account_id: str
    account_category: str
    period: int = Field(ge=0)
    date: Optional[_dt.date] = None

    begin_balance: Dollars = 0.0
    deposit: Dollars = 0.0
    withdrawal: Dollars = 0.0
    interest_earned: Dollars = 0.0
    end_balance: Dollars = 0.0

    required_minimum: Dollars = 0.0
    minimum_basis: str = ""
    breach_flag: bool = False


class WaterfallTraceRow(BaseModel):
    """Audit record for a single rule execution in a single period."""
    scenario_name: str
    period: int = Field(ge=0)
    rule_id: str
    rule_order: int = Field(ge=0)
    rule_type: str

    from_source: str
    to_target: str
    amount_requested: Dollars = 0.0
    amount_paid: Dollars = 0.0

    remaining_source: Dollars = 0.0
    remaining_obligation: Dollars = 0.0

    condition_id: Optional[str] = None
    condition_result: Optional[bool] = None
    constraint_binding_flag: bool = False


class TriggerStateRow(BaseModel):
    """Trigger state for a single trigger in a single period."""
    scenario_name: str
    trigger_id: str
    period: int = Field(ge=0)
    date: Optional[_dt.date] = None

    metric_value: float = 0.0
    threshold_value: float = 0.0
    state: TriggerState = TriggerState.INACTIVE

    first_breach_period: Optional[int] = None
    cure_period: Optional[int] = None
    days_in_breach: int = 0


class DealStateRow(BaseModel):
    """Phase 9: per-period deal state record for auditing state transitions.

    Emitted once per period so callers can observe when and why the deal
    transitioned (e.g. REVOLVING → EARLY_AMORTIZATION on trigger FAIL).
    """
    scenario_name: str
    period: int = Field(ge=0)
    begin_state: str  # deal state at start of period (before triggers)
    end_state: str    # deal state at end of period (after trigger evaluation)
    transition_trigger: Optional[str] = None  # trigger that caused the transition, if any
