"""Output schemas for bond-level cashflows and risk metrics."""
import datetime as _dt
from typing import Optional

from pydantic import BaseModel, Field

from .common import BasisPoints, Dollars, Pct, Rate, SchemaMetadata


class BondCashflowRow(BaseModel):
    """Single period of a single tranche's cashflow (long-format grain)."""
    scenario_name: str
    deal_id: Optional[str] = None
    deal_version: Optional[int] = None
    tranche_id: str
    period: int = Field(ge=0)
    date: Optional[_dt.date] = None

    begin_balance: Dollars
    sched_principal: Dollars = 0.0
    unsched_principal: Dollars = 0.0
    total_principal: Dollars = 0.0

    interest_due: Dollars = 0.0
    interest_paid: Dollars = 0.0
    interest_shortfall: Dollars = 0.0

    writedown: Dollars = 0.0
    end_balance: Dollars = 0.0
    cashflow_total: Dollars = 0.0

    coupon_rate: Rate = 0.0
    factor: float = 0.0
    wal_running_years: float = 0.0


class TrancheRiskSummaryRow(BaseModel):
    """Risk summary for a single tranche under a single scenario."""
    scenario_name: str
    tranche_id: str

    price: float = 0.0
    yield_pct: Rate = 0.0
    z_spread: BasisPoints = 0.0

    wal_years: float = 0.0
    macaulay_duration: float = 0.0
    modified_duration: float = 0.0
    convexity: float = 0.0

    avg_life_variability: float = 0.0
    extension_risk_score: float = 0.0
    contraction_risk_score: float = 0.0

    loss_adjusted_yield: Rate = 0.0


class CreditEnhancementRow(BaseModel):
    """Credit enhancement breakdown for a single tranche."""
    scenario_name: str
    tranche_id: str

    subordination_pct: Pct = 0.0
    reserve_support_pct: Pct = 0.0
    excess_spread_support_pct: Pct = 0.0
    total_ce_pct: Pct = 0.0
    ce_target_pct: Pct = 0.0
    ce_gap_pct: Pct = 0.0

    break_even_cum_loss_pct: Pct = 0.0
    break_even_default_pct: Pct = 0.0
    break_even_severity_pct: Pct = 0.0
