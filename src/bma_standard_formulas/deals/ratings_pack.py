"""Ratings-style output pack generation.

Produces structured scenario-stress tables, CE stacks, trigger breach
timelines, WAL/legal-final diagnostics, and break-even analytics from
waterfall outputs.
"""
from typing import Any

import numpy as np

from .risk import (
    compute_credit_enhancement,
    compute_tranche_risk,
    compute_wal,
    _group_by_tranche,
)
from .runtime import run_deal
from .schemas.common import TriggerState
from .schemas.input import DealRunInput
from .schemas.ir import DealDefinition
from .schemas.output_bond import BondCashflowRow, CreditEnhancementRow, TrancheRiskSummaryRow
from .schemas.output_bundle import DealRunOutput, ScenarioOutputBundle
from .schemas.output_structuring import StressMatrixTrancheRow
from .schemas.output_waterfall import TriggerStateRow


# ---------------------------------------------------------------------------
# Scenario stress matrix
# ---------------------------------------------------------------------------


def run_stress_matrix(
    deal: DealDefinition,
    base_input: DealRunInput,
    prepay_multipliers: list[float] | None = None,
    default_multipliers: list[float] | None = None,
    severity_multipliers: list[float] | None = None,
) -> list[StressMatrixTrancheRow]:
    """Run the deal under a grid of stress scenarios and produce tranche-level results.

    Multipliers scale the base collateral vectors (e.g., 1.5x defaults).
    """
    if prepay_multipliers is None:
        prepay_multipliers = [1.0]
    if default_multipliers is None:
        default_multipliers = [0.5, 1.0, 1.5, 2.0, 3.0]
    if severity_multipliers is None:
        severity_multipliers = [1.0]

    results: list[StressMatrixTrancheRow] = []

    for pm in prepay_multipliers:
        for dm in default_multipliers:
            for sm in severity_multipliers:
                stress_name = f"PP{pm:.1f}x_DEF{dm:.1f}x_SEV{sm:.1f}x"
                stressed_input = _scale_collateral(base_input, pm, dm, sm)

                scenario = run_deal(deal, stressed_input, scenario_name=stress_name)
                grouped = _group_by_tranche(scenario.bond_cashflows)

                for tranche_id, rows in grouped.items():
                    initial_bal = rows[0].begin_balance if rows else 0.0
                    if initial_bal <= 0:
                        continue

                    final_bal = rows[-1].end_balance if rows else 0.0
                    total_loss = sum(r.writedown for r in rows if r.period > 0)
                    peak_shortfall = max(
                        (r.interest_shortfall for r in rows if r.period > 0),
                        default=0.0,
                    )
                    wal = compute_wal(rows)

                    results.append(StressMatrixTrancheRow(
                        stress_set_name=stress_name,
                        tranche_id=tranche_id,
                        prepay_vector_id=f"base*{pm:.1f}",
                        default_vector_id=f"base*{dm:.1f}",
                        severity_vector_id=f"base*{sm:.1f}",
                        pass_fail=(total_loss < 1e-2 and peak_shortfall < 1e-2),
                        principal_loss=total_loss,
                        interest_shortfall_peak=peak_shortfall,
                        final_balance=final_bal,
                        wal=wal,
                    ))

    return results


def _scale_collateral(
    base_input: DealRunInput,
    prepay_mult: float,
    default_mult: float,
    severity_mult: float,
) -> DealRunInput:
    """Create a stressed copy of the input with scaled vectors."""
    from .schemas.input import PooledCollateralInput, CollateralCashflows

    base_coll = base_input.collateral
    if not isinstance(base_coll, PooledCollateralInput):
        return base_input

    cf = base_coll.collateral
    n = len(cf.balance)

    bal = np.array(cf.balance)
    loss = np.array(cf.loss) * default_mult * severity_mult
    principal = np.array(cf.principal) * prepay_mult

    new_bal = np.zeros(n)
    new_bal[0] = bal[0]
    for i in range(1, n):
        new_bal[i] = max(0.0, new_bal[i - 1] - principal[i] - loss[i])

    new_cf = CollateralCashflows(
        cfdate=cf.cfdate,
        balance=new_bal.tolist(),
        principal=principal.tolist(),
        interest=cf.interest,
        cashflow=(principal + np.array(cf.interest)).tolist(),
        loss=loss.tolist(),
        prepbal=cf.prepbal,
        defbal=cf.defbal,
        recovery=cf.recovery,
        principal_sched=cf.principal_sched,
        principal_unsched=cf.principal_unsched,
        cpr=cf.cpr,
        cdr=cf.cdr,
        sev=cf.sev,
        dq=cf.dq,
        surv_fac=cf.surv_fac,
        sched_coupon=cf.sched_coupon,
        sched_netcoupon=cf.sched_netcoupon,
        coupon=cf.coupon,
        effcoupon=cf.effcoupon,
        sched_balance=cf.sched_balance,
        discount_factor=cf.discount_factor,
    )

    return DealRunInput(
        collateral=PooledCollateralInput(collateral=new_cf),
        loan_count=base_input.loan_count,
        original_collateral_balance=base_input.original_collateral_balance,
        market_date=base_input.market_date,
    )


# ---------------------------------------------------------------------------
# Break-even analysis
# ---------------------------------------------------------------------------


def compute_break_even_loss(
    deal: DealDefinition,
    base_input: DealRunInput,
    tranche_id: str,
    *,
    max_multiplier: float = 10.0,
    tolerance: float = 0.01,
    max_iterations: int = 50,
) -> float:
    """Binary-search for the default multiplier at which a tranche first takes loss.

    Returns the break-even default multiplier (e.g., 2.5 means 2.5x base defaults).
    """
    low, high = 0.0, max_multiplier

    for _ in range(max_iterations):
        mid = (low + high) / 2.0
        stressed = _scale_collateral(base_input, 1.0, mid, 1.0)
        scenario = run_deal(deal, stressed, scenario_name="BE_search")
        grouped = _group_by_tranche(scenario.bond_cashflows)
        rows = grouped.get(tranche_id, [])
        total_loss = sum(r.writedown for r in rows if r.period > 0)

        if total_loss > tolerance:
            high = mid
        else:
            low = mid

        if high - low < tolerance:
            break

    return (low + high) / 2.0


# ---------------------------------------------------------------------------
# Trigger breach timeline
# ---------------------------------------------------------------------------


def compute_trigger_breach_timeline(
    scenario: ScenarioOutputBundle,
) -> list[dict[str, Any]]:
    """Extract trigger breach/cure events from scenario output."""
    events: list[dict[str, Any]] = []
    for trig_row in scenario.trigger_state_history:
        if trig_row.state in (TriggerState.FAIL, TriggerState.CURED):
            events.append({
                "trigger_id": trig_row.trigger_id,
                "period": trig_row.period,
                "state": trig_row.state.value,
                "metric_value": trig_row.metric_value,
                "threshold_value": trig_row.threshold_value,
            })
    return events


# ---------------------------------------------------------------------------
# Full ratings pack
# ---------------------------------------------------------------------------


def generate_ratings_pack(
    deal: DealDefinition,
    run_input: DealRunInput,
    collateral_balance_0: float,
    *,
    default_multipliers: list[float] | None = None,
) -> dict[str, Any]:
    """Generate the complete ratings output pack for a deal.

    Returns a dict with all ratings-ready artifacts.
    """
    base_scenario = run_deal(deal, run_input, scenario_name="Base Case")

    risk = compute_tranche_risk(base_scenario)
    ce = compute_credit_enhancement(base_scenario, collateral_balance_0)

    stress = run_stress_matrix(
        deal, run_input,
        default_multipliers=default_multipliers or [0.5, 1.0, 1.5, 2.0, 3.0],
    )

    bond_names = [b.name for b in deal.bonds if b.is_bond and not b.is_pseudo]
    break_evens: dict[str, float] = {}
    for bname in bond_names:
        be = compute_break_even_loss(deal, run_input, bname)
        break_evens[bname] = be

    trigger_timeline = compute_trigger_breach_timeline(base_scenario)

    return {
        "base_scenario": base_scenario,
        "tranche_risk": risk,
        "credit_enhancement": ce,
        "stress_matrix": stress,
        "break_even_loss_multipliers": break_evens,
        "trigger_breach_timeline": trigger_timeline,
    }
