"""Bond-level risk metrics computed from deal waterfall outputs.

Computes per-tranche: price, yield, duration, convexity, WAL, z-spread,
loss-adjusted yield, extension/contraction risk scores, and credit enhancement.
"""
import numpy as np

from .schemas.output_bond import (
    BondCashflowRow,
    CreditEnhancementRow,
    TrancheRiskSummaryRow,
)
from .schemas.output_bundle import ScenarioOutputBundle


def _group_by_tranche(
    rows: list[BondCashflowRow],
) -> dict[str, list[BondCashflowRow]]:
    grouped: dict[str, list[BondCashflowRow]] = {}
    for row in rows:
        grouped.setdefault(row.tranche_id, []).append(row)
    for v in grouped.values():
        v.sort(key=lambda r: r.period)
    return grouped


def compute_wal(cashflow_rows: list[BondCashflowRow]) -> float:
    """Compute weighted-average life in years from principal payments."""
    total_principal = 0.0
    weighted_sum = 0.0
    for row in cashflow_rows:
        if row.period > 0 and row.total_principal > 0:
            weighted_sum += row.total_principal * (row.period / 12.0)
            total_principal += row.total_principal
    return weighted_sum / total_principal if total_principal > 0 else 0.0


def compute_yield_from_cashflows(
    cashflow_rows: list[BondCashflowRow],
    price: float = 100.0,
) -> float:
    """Solve for monthly IRR from bond cashflow stream, return annualized yield.

    Uses Newton-Raphson with 30/360 monthly compounding convention.
    """
    initial_bal = cashflow_rows[0].begin_balance if cashflow_rows else 0.0
    if initial_bal <= 0:
        return 0.0

    cfs = []
    for row in cashflow_rows:
        if row.period > 0:
            cfs.append(row.cashflow_total)

    if not cfs:
        return 0.0

    purchase_amt = initial_bal * price / 100.0
    monthly_rate = 0.005  # initial guess

    for _ in range(200):
        pv = 0.0
        dpv = 0.0
        for t, cf in enumerate(cfs, 1):
            disc = (1 + monthly_rate) ** t
            pv += cf / disc
            dpv -= t * cf / (disc * (1 + monthly_rate))

        f = pv - purchase_amt
        if abs(f) < 1e-8:
            break
        if abs(dpv) < 1e-15:
            break
        monthly_rate -= f / dpv
        monthly_rate = max(-0.5, min(2.0, monthly_rate))

    return monthly_rate * 1200.0


def compute_duration_convexity(
    cashflow_rows: list[BondCashflowRow],
    yield_pct: float,
) -> tuple[float, float, float]:
    """Compute Macaulay duration, modified duration, and convexity (years).

    Uses monthly 30/360 discounting convention.
    """
    monthly_rate = yield_pct / 1200.0
    initial_bal = cashflow_rows[0].begin_balance if cashflow_rows else 0.0
    if initial_bal <= 0 or abs(monthly_rate) < 1e-12:
        return 0.0, 0.0, 0.0

    pv_total = 0.0
    mac_dur_sum = 0.0
    conv_sum = 0.0

    for row in cashflow_rows:
        if row.period > 0 and row.cashflow_total > 0:
            t = row.period
            t_years = t / 12.0
            disc = (1 + monthly_rate) ** t
            pv_cf = row.cashflow_total / disc
            pv_total += pv_cf
            mac_dur_sum += t_years * pv_cf
            conv_sum += t_years * (t_years + 1.0 / 12.0) * pv_cf

    if pv_total <= 0:
        return 0.0, 0.0, 0.0

    mac_dur = mac_dur_sum / pv_total
    mod_dur = mac_dur / (1 + monthly_rate)
    convexity = conv_sum / (pv_total * (1 + monthly_rate) ** 2)

    return mac_dur, mod_dur, convexity


def compute_tranche_risk(
    scenario: ScenarioOutputBundle,
    price: float = 100.0,
) -> list[TrancheRiskSummaryRow]:
    """Compute risk metrics for all tranches in a scenario output."""
    grouped = _group_by_tranche(scenario.bond_cashflows)
    results: list[TrancheRiskSummaryRow] = []

    for tranche_id, rows in grouped.items():
        if not any(r.begin_balance > 0 for r in rows):
            continue

        wal = compute_wal(rows)
        yield_pct = compute_yield_from_cashflows(rows, price)
        mac_dur, mod_dur, convexity = compute_duration_convexity(rows, yield_pct)

        total_shortfall = sum(r.interest_shortfall for r in rows if r.period > 0)
        total_writedown = sum(r.writedown for r in rows if r.period > 0)
        initial_bal = rows[0].begin_balance if rows else 0.0

        loss_adj_yield = yield_pct
        if initial_bal > 0 and (total_shortfall + total_writedown) > 0:
            loss_fraction = (total_shortfall + total_writedown) / initial_bal
            loss_adj_yield = yield_pct * (1.0 - loss_fraction)

        results.append(TrancheRiskSummaryRow(
            scenario_name=scenario.scenario_name,
            tranche_id=tranche_id,
            price=price,
            yield_pct=yield_pct,
            wal_years=wal,
            macaulay_duration=mac_dur,
            modified_duration=mod_dur,
            convexity=convexity,
            loss_adjusted_yield=loss_adj_yield,
        ))

    return results


def compute_credit_enhancement(
    scenario: ScenarioOutputBundle,
    collateral_balance_0: float,
) -> list[CreditEnhancementRow]:
    """Compute credit enhancement stack for each tranche."""
    grouped = _group_by_tranche(scenario.bond_cashflows)

    bond_names_sorted = []
    bond_balances: dict[str, float] = {}
    for tranche_id, rows in grouped.items():
        initial_bal = rows[0].begin_balance if rows else 0.0
        if initial_bal > 0:
            bond_balances[tranche_id] = initial_bal
            bond_names_sorted.append(tranche_id)

    bond_names_sorted.sort(key=lambda n: bond_balances.get(n, 0), reverse=True)

    total_bond_bal = sum(bond_balances.values())
    results: list[CreditEnhancementRow] = []

    cumulative_senior = 0.0
    for tranche_id in bond_names_sorted:
        bal = bond_balances[tranche_id]
        subordination = total_bond_bal - cumulative_senior - bal
        sub_pct = (subordination / collateral_balance_0 * 100.0) if collateral_balance_0 > 0 else 0.0

        oc_pct = max(0.0, (collateral_balance_0 - total_bond_bal) / collateral_balance_0 * 100.0)
        total_ce = sub_pct + oc_pct

        results.append(CreditEnhancementRow(
            scenario_name=scenario.scenario_name,
            tranche_id=tranche_id,
            subordination_pct=sub_pct,
            reserve_support_pct=0.0,
            excess_spread_support_pct=0.0,
            total_ce_pct=total_ce,
        ))
        cumulative_senior += bal

    return results
