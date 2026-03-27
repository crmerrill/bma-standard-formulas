# Requires Python 3.12+
"""Engine-level wrappers for pricing/risk table utilities.

BMA context:
    These wrappers expose Section G-oriented analytics in the engine namespace,
    while formula math lives in ``formulas.pricing_risk``.

Why this layer exists:
    1. Keep user-facing imports consistent with existing ``engine`` patterns.
    2. Preserve a stable API boundary if formula internals change.
    3. Provide application-level docstrings where users typically discover APIs.
"""

from __future__ import annotations

import numpy as np

from bma_standard_formulas.engine.portfolio import PortfolioCashflow
from bma_standard_formulas.formulas.cashflows import BMAActualCashflow, BMAScheduledCashflow
from bma_standard_formulas.formulas.pricing_risk import (
    PriceRiskAnalyzer,
    PriceYieldKind,
    RiskMetrics,
    PriceYieldRiskTable,
    PriceYieldScenarioTable,
)


def build_price_yield_table(
    scenarios: dict[str, BMAScheduledCashflow | BMAActualCashflow | PortfolioCashflow],
    column_inputs: np.ndarray,
    input_kind: PriceYieldKind,
    *,
    include_period_zero: bool = False,
    delay_days: int = 0,
    month_days: float = 30.0,
    face_value: float = 100.0,
) -> PriceYieldScenarioTable:
    """Build two-way price/yield table from existing cashflow objects.

    Args:
        scenarios: Mapping from scenario label to cashflow dataclass or portfolio.
        column_inputs: Input axis values interpreted according to ``input_kind``.
        input_kind: ``"price"`` or ``"yield"``.
        include_period_zero: Include period-0 state row if True.
        delay_days: Settlement delay in days added to each period's discount time.
        month_days: Day-count month length used for period-to-year mapping.
        face_value: Quotation basis for price output/input (default ``100``).

    Returns:
        ``PriceYieldScenarioTable`` with one row per scenario and one column per
        input-axis value.

    Raises:
        ValueError: Forwarded from formula implementation for invalid inputs.
        TypeError: Forwarded when unsupported scenario object types are supplied.
    """
    analyzer = PriceRiskAnalyzer(
        scenarios,
        include_period_zero=include_period_zero,
        delay_days=delay_days,
        month_days=month_days,
        face_value=face_value,
    )
    return analyzer.price_yield_table(column_inputs=column_inputs, input_kind=input_kind)


def compute_risk_metrics(
    cashflow: BMAScheduledCashflow | BMAActualCashflow | PortfolioCashflow,
    annual_yield_pct: float,
    *,
    include_period_zero: bool = False,
    delay_days: int = 0,
    month_days: float = 30.0,
    face_value: float = 100.0,
) -> RiskMetrics:
    """Compute deterministic-path risk metrics for one cashflow object.

    Metrics include:
        - price at the provided yield,
        - Macaulay duration,
        - modified duration,
        - cash-flow convexity.
    """
    analyzer = PriceRiskAnalyzer.from_cashflow(
        cashflow,
        include_period_zero=include_period_zero,
        delay_days=delay_days,
        month_days=month_days,
        face_value=face_value,
    )
    return analyzer.risk_metrics(annual_yield_pct)["base"]


def build_expanded_price_yield_table(
    scenarios: dict[str, BMAScheduledCashflow | BMAActualCashflow | PortfolioCashflow],
    column_inputs: np.ndarray,
    input_kind: PriceYieldKind,
    *,
    include_period_zero: bool = False,
    delay_days: int = 0,
    month_days: float = 30.0,
    face_value: float = 100.0,
) -> PriceYieldRiskTable:
    """Build expanded table with price, yield, duration, and convexity per cell."""
    analyzer = PriceRiskAnalyzer(
        scenarios,
        include_period_zero=include_period_zero,
        delay_days=delay_days,
        month_days=month_days,
        face_value=face_value,
    )
    return analyzer.expanded_price_yield_table(column_inputs=column_inputs, input_kind=input_kind)
