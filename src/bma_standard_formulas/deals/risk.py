"""Bond-level risk metrics computed from deal waterfall outputs.

Computes per-tranche: price, yield, duration, convexity, WAL, z-spread,
loss-adjusted yield, extension/contraction risk scores, and credit enhancement.

Two yield conventions are supported:

  - **Annualized monthly rate (APR-style)**: ``monthly_rate * 1200``. This is
    how the legacy `compute_yield_from_cashflows` returns its value.

  - **Corporate-bond-equivalent (CBE) yield**: ``2 * ((1 + r_m) ** 6 - 1) * 100``.
    This is the prospectus convention (Fannie Mae S-19, Bloomberg, BMA SF
    pricing tables) and is used for tie-outs against published yield tables.
    Computed by ``bond_ytm_cbe`` and routed through ``solve_monthly_irr`` /
    ``monthly_to_cbe``.
"""
from collections.abc import Sequence

import numpy as np

from .schemas.output_bond import (
    BondCashflowRow,
    CreditEnhancementRow,
    TrancheRiskSummaryRow,
)
from .schemas.output_bundle import ScenarioOutputBundle


# ---------------------------------------------------------------------------
# Yield primitives -- robust brentq IRR + CBE conversion
# ---------------------------------------------------------------------------


def solve_monthly_irr(
    cashflows: Sequence[float],
    initial_outflow: float,
    *,
    rate_lo: float = -0.05,
    rate_hi: float = 0.50,
) -> float:
    """Solve for the monthly rate ``r_m`` such that
    ``sum(cashflows[i] / (1 + r_m)**i) == initial_outflow``.

    ``cashflows[0]`` is conventionally zero (no payment at settlement);
    period i = 1, 2, ... are positive payments. ``initial_outflow`` is
    the upfront price the buyer pays (for a bond: ``price * face``).

    Uses scipy's brentq on the standard NPV-vs-rate root. If the root is
    not bracketed by ``[rate_lo, rate_hi]`` the bracket is widened
    automatically until it brackets a sign change or fails. Bracket
    failure typically means the cashflow stream is degenerate (all-zero
    or sums to less than ``initial_outflow``).
    """
    from scipy.optimize import brentq

    cf = np.asarray(cashflows, dtype=float)
    periods = np.arange(len(cf), dtype=float)

    def _npv(r_m: float) -> float:
        if r_m <= -1.0 + 1e-9:
            return float("inf")
        df = (1.0 + r_m) ** -periods
        return float((cf * df).sum() - initial_outflow)

    lo, hi = rate_lo, rate_hi
    for _ in range(8):
        try:
            return float(brentq(_npv, lo, hi, maxiter=200, xtol=1e-10))
        except ValueError:
            lo = max(-0.999, lo * 2 - 0.01)
            hi = min(10.0, hi * 2 + 0.01)
            continue
    raise ValueError(
        f"Cashflow IRR not bracketed in [{lo:.6f}, {hi:.6f}]; "
        f"sum_cashflows={float(cf.sum()):.4f} vs initial_outflow={initial_outflow:.4f}"
    )


def monthly_to_cbe(monthly_rate: float) -> float:
    """Convert a monthly rate to corporate-bond-equivalent annualized yield (percent).

    CBE: ``y = 2 * ((1 + r_m) ** 6 - 1)`` -- twice the semi-annual yield
    derived by compounding the monthly rate up by 6 months. This is the
    Fannie Mae yield-table convention.
    """
    return 2.0 * ((1.0 + monthly_rate) ** 6 - 1.0) * 100.0


def monthly_to_apr(monthly_rate: float) -> float:
    """Convert a monthly rate to annualized monthly rate (APR-style, percent)."""
    return monthly_rate * 1200.0


def bond_ytm_cbe(
    cashflows: Sequence[float],
    price: float,
    face: float,
) -> float:
    """Solve for CBE yield-to-maturity given a cashflow stream and price * face.

    ``cashflows[i]`` is the dollar payment at period i (i = 0 is conventionally
    zero). Returns YTM in percent under the corporate-bond-equivalent
    convention used by the prospectus.
    """
    r_m = solve_monthly_irr(cashflows, price * face)
    return monthly_to_cbe(r_m)


def io_cashflows_from_underlying_balance(
    underlying_rows: Sequence[BondCashflowRow],
    coupon_pct: float,
) -> np.ndarray:
    """Build a notional-IO cashflow array from an underlying bond's balance trace.

    Each period's IO coupon = ``begin_balance[period] * coupon_pct / 1200``.
    Used for IO classes (e.g., FNR EI, DI) whose notional balance is
    defined to track a sister bond's outstanding balance and whose only
    cashflows are interest on that notional. The underlying class is
    assumed to be sorted by period; missing periods are zero-filled.
    """
    if not underlying_rows:
        return np.zeros(0)
    sorted_rows = sorted(underlying_rows, key=lambda r: r.period)
    n_periods = sorted_rows[-1].period + 1
    out = np.zeros(n_periods)
    monthly_rate = coupon_pct / 1200.0
    for r in sorted_rows:
        if r.period > 0:
            out[r.period] = float(r.begin_balance) * monthly_rate
    return out


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
