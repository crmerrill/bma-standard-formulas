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


# ---------------------------------------------------------------------------
# Carry tie-out artifact
# ---------------------------------------------------------------------------


class CarryTieoutTrancheRow(BaseModel):
    """Per-tranche realized YTM and duration at par pricing for one scenario."""
    scenario_name: str
    tranche_id: str

    # Notional outstanding at issuance (face). For the IO/PO pair the IO
    # carries its notional balance (= principal of the underlying PO).
    notional: Dollars = 0.0

    # Stated coupon rate (percent). For zero-coupon classes (PO, residual) = 0.
    coupon_pct: Rate = 0.0

    # Realized YTM at par pricing, corporate-bond-equivalent (CBE)
    # convention: ``2 * ((1 + r_m)**6 - 1)``. Solved from the realized
    # cashflow stream against the tranche's notional * 1.0 par price.
    ytm_cbe_pct: Rate = 0.0

    # Realized duration (modified, years) under the solved YTM. For the
    # carry tie-out's weighted residual computation we need durations
    # under the realized rate, not the stated coupon.
    modified_duration_years: float = 0.0

    # Weighted-average life in years (industry convention: principal-flow
    # weighted period count / 12). For IOs we copy the underlying
    # bond's WAL since IOs have no principal of their own.
    wal_years: float = 0.0


class CarryTieoutSummary(BaseModel):
    """Engine-truth carry tie-out for a single scenario.

    Computed after a base-case run by the orchestrator's carry-tieout
    service. Each per-tranche row is populated from the realized
    cashflow stream; pool-level YTM is solved from the net pool
    interest+principal stream; the residual yield is back-solved so
    the duration-weighted carry equation balances:

        Σ(notional_i × ytm_i × dur_i) + resid_balance × resid_ytm × resid_dur
            = pool_balance × pool_ytm × pool_duration

    Status follows the project's tight default thresholds:

      - OK    : implied residual yield in [5%, 35%]
      - WARN  : implied residual yield in [0%, 5%) or (35%, 50%]
      - BLOCK : implied residual yield < 0% or > 50%

    Block triggers a runtime/solve guard in the Studio UI; warn surfaces
    a banner; OK is silent. Thresholds are user-overridable per deal via
    `deal_knobs["tieout_thresholds"]`.
    """
    scenario_name: str

    # Pool-level realized economics.
    pool_balance: Dollars = 0.0
    pool_ytm_cbe_pct: Rate = 0.0
    pool_modified_duration_years: float = 0.0
    pool_wal_years: float = 0.0

    # Per-tranche detail (excluding the residual class).
    tranches: list[CarryTieoutTrancheRow] = Field(default_factory=list)

    # Residual class balance + back-solved implied yield.
    residual_balance: Dollars = 0.0
    residual_modified_duration_years: float = 0.0
    implied_residual_ytm_cbe_pct: Rate = 0.0

    # Stack-level weighted yield (Σ notional×ytm×dur / Σ notional×dur).
    stack_weighted_ytm_cbe_pct: Rate = 0.0

    # Carry tie-out status driven by the implied residual yield.
    # `status` is one of {"OK", "WARN", "BLOCK"}. `reason` is a short
    # human-readable explanation that surfaces in the Studio banner.
    status: str = "OK"
    reason: str = ""

    # Tolerance bands actually used (echoed for observability).
    warn_low_pct: Rate = 0.0
    warn_high_pct: Rate = 50.0
    block_low_pct: Rate = -100.0
    block_high_pct: Rate = 100.0
