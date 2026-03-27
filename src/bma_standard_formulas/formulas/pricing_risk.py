# Requires Python 3.12+
"""Pricing and risk metric utilities for BMA cashflow outputs.

===============================================================================
BMA REFERENCES
===============================================================================
Primary formulas in this module align conceptually with:

- BMA_Calcs2 Section E: Day count and delay-day conventions.
- BMA_Calcs2 Section G.1: Yield and yield-related measures.

In particular, Section G defines (BMA SF-48 to SF-49):
    - Bond-Equivalent Yield (Section G.1.a, SF-48) as the root of a discounted
      cashflow equation.
    - Macaulay Duration (Section G.1.d, SF-49) as PV-weighted average receipt
      time.
    - Modified Duration (Section G.1.e, SF-49) as Duration divided by the
      compounding factor.
    - Cash-Flow Convexity (Section G.1.f, SF-49) as a scaled second derivative
      of price with respect to yield.

For floating-rate basis consistency, see Section G.2 (SF-52), especially the
calendar-basis conversion guidance around 30/360 vs ACTUAL/360.

===============================================================================
IMPLEMENTATION CONTRACT (CURRENT)
===============================================================================
This module is intentionally deterministic-path analytics on top of existing
cashflow objects produced by the library:

- ``BMAScheduledCashflow``
- ``BMAActualCashflow``
- ``PortfolioCashflow`` (duck-typed to avoid formula/engine import cycles)

No synthetic schedule object is created.
Timing is taken from the object's existing ``period`` array.

Units:
    - yield inputs/outputs are annual percent (6.50 means 6.50%).
    - prices are quoted per ``face_value`` (default 100).
    - delay-day adjustment is handled via ``years_from_periods``.

Notation used below:
    - CFₖ : cash flow at index k
    - Tₖ  : year-fraction time for CFₖ
    - P   : price (per face-value quote basis)
    - Y   : annual yield in percent
    - y   : annual yield in decimal = Y/100

Compounding note (important):
    BMA text commonly writes the discount denominator on semiannual basis as
    ``(1 + Y/200)^{2Tₖ}``.
    The current implementation uses the algebraically equivalent annual form
    ``(1 + y)^{Tₖ}``, where ``y = Y/100``.
    This is intentionally explicit in code for readability and unit tracing.

===============================================================================
PEDAGOGICAL MODULE ORGANIZATION
===============================================================================
The file is organized in dependency order for readers:

1) Result dataclasses (`PriceYieldScenarioTable`, `RiskMetrics`)
2) Extraction layer (get CFₖ and periodₖ from supported objects)
3) Timing transform (`periodₖ -> Tₖ`)
4) Discount factors and present values
5) Core valuation equation (`price_from_yield_pct`, `yield_pct_from_price`)
6) Scenario grid orchestration (`PriceRiskAnalyzer.price_yield_table`)
7) Section G risk measures (duration/convexity)
8) One-shot analytics object (`PriceRiskAnalyzer`)

This keeps “what is computed” before “how scenario loops are orchestrated”.

===============================================================================
DISCOUNT FACTORS (NOVICE NOTE)
===============================================================================
A discount factor (DF) converts a future dollar into present dollars.

If a cashflow ``CFₖ`` arrives at time ``Tₖ`` and annual yield is ``Y``:

    y    = Y/100
    DFₖ  = 1 / (1 + y)^{Tₖ}
    PVₖ  = CFₖ · DFₖ

Why discount factors are useful:
    1) They separate "time-value math" from "cashflow amounts".
       Once ``DFₖ`` is computed, many quantities are simple dot products:
       ``P = Σ CFₖ·DFₖ``.
    2) They are easy to vectorize with NumPy (elementwise power/multiply).
    3) For fixed ``y > -1`` and increasing ``Tₖ``, discount factors are
       monotone non-increasing: later cashflows get less present-value weight.
    4) They are reusable: price, duration numerators, and convexity terms all
       can be built off the same ``PVₖ`` vector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from bma_standard_formulas.formulas.cashflows import BMAActualCashflow, BMAScheduledCashflow


PriceYieldKind = Literal["price", "yield"]
PortfolioCashflowSource = Literal["scheduled", "pass_through"]


# =============================================================================
# Result containers (public dataclasses)
# =============================================================================

@dataclass(frozen=True, slots=True)
class PriceYieldScenarioTable:
    """Two-way scenario table for price/yield conversion.

    The table represents one fixed cashflow path per row and one input value
    per column:

    - if ``input_kind == "yield"``, each cell is a solved price.
    - if ``input_kind == "price"``, each cell is a solved yield.

    Attributes:
        row_labels: Scenario labels in row order.
        column_inputs: Input axis (prices or yields).
        values: Output matrix with shape (n_scenarios, n_inputs).
        input_kind: Axis interpretation for ``column_inputs``.
        value_kind: Output interpretation for ``values``.
        value_units: Human-readable units for output.
        metadata: Run settings (delay days, period-0 inclusion, quote basis).
    """

    row_labels: tuple[str, ...]
    column_inputs: np.ndarray
    values: np.ndarray
    input_kind: PriceYieldKind
    value_kind: PriceYieldKind
    value_units: str
    metadata: dict[str, str | int | float] = field(default_factory=dict)

    def to_dataframe(self) -> pd.DataFrame:
        """Render scenario table as a DataFrame."""
        columns = [f"{self.input_kind}_{x:g}" for x in self.column_inputs]
        return pd.DataFrame(self.values, index=list(self.row_labels), columns=columns)


@dataclass(frozen=True, slots=True)
class RiskMetrics:
    """Risk metrics for one deterministic price/yield point.

    Attributes:
        price: Price per ``face_value`` at the supplied yield.
        annual_yield_pct: Yield used for metric calculation.
        macaulay_duration_years: PV-weighted average time to cashflow receipt.
        modified_duration_years: Macaulay duration scaled by compounding factor.
        convexity_years2: Cash-flow convexity in year-squared units.
        metadata: Run settings and timing assumptions.
    """

    price: float
    annual_yield_pct: float
    macaulay_duration_years: float
    modified_duration_years: float
    convexity_years2: float
    metadata: dict[str, str | int | float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PriceYieldRiskTable:
    """Expanded price/yield scenario table with risk metrics at every cell.

    Attributes:
        row_labels: Scenario labels in row order.
        column_inputs: Input axis values interpreted by ``input_kind``.
        input_kind: ``"yield"`` or ``"price"`` for the input axis.
        price_values: Cell prices per ``face_value``.
        yield_values: Cell annual yields in percent.
        macaulay_duration_years: Cell Macaulay durations in years.
        modified_duration_years: Cell modified durations in years.
        convexity_years2: Cell convexities in years-squared.
        metadata: Run settings and quote-basis assumptions.
    """

    row_labels: tuple[str, ...]
    column_inputs: np.ndarray
    input_kind: PriceYieldKind
    price_values: np.ndarray
    yield_values: np.ndarray
    macaulay_duration_years: np.ndarray
    modified_duration_years: np.ndarray
    convexity_years2: np.ndarray
    metadata: dict[str, str | int | float] = field(default_factory=dict)


# =============================================================================
# Cashflow/period extraction layer
# Why this exists:
#   Pricing/risk routines should not care which concrete object produced the
#   cashflows (leaf scheduled, leaf actual, or portfolio aggregate).
# =============================================================================

def _is_portfolio_cashflow_like(obj: object) -> bool:
    """Duck-type check for PortfolioCashflow-like objects."""
    cls = type(obj)
    return all(hasattr(cls, attr) for attr in ("mode", "scheduled", "pt_cashflow"))


def _portfolio_mode_name(mode: object) -> str:
    """Return normalized portfolio mode name.

    Args:
        mode: Portfolio mode value, typically an enum or string.

    Returns:
        Uppercase mode name (for example, ``"SCHEDULED_ONLY"``).
    """
    name = getattr(mode, "name", mode)
    return str(name).strip().upper()


def _portfolio_cashflow_source(mode: object) -> PortfolioCashflowSource:
    """Map portfolio mode to pricing cashflow source.

    ``pricing_risk`` uses a two-source extraction policy:
      - ``SCHEDULED_ONLY`` -> scheduled principal+interest path
      - ``ACTUAL_ONLY``/``PAIRED`` -> trust pass-through cashflow path

    Args:
        mode: Portfolio mode value, usually ``PortfolioMode`` or a mode string.

    Returns:
        ``"scheduled"`` or ``"pass_through"``.

    Raises:
        ValueError: If mode is not one of the supported portfolio modes.
    """
    mode_name = _portfolio_mode_name(mode)
    if mode_name == "SCHEDULED_ONLY":
        return "scheduled"
    if mode_name in {"ACTUAL_ONLY", "PAIRED"}:
        return "pass_through"
    raise ValueError(
        "Unsupported portfolio mode for pricing extraction: "
        f"{mode!r}. Expected one of: SCHEDULED_ONLY, ACTUAL_ONLY, PAIRED."
    )


def _cashflows_from_scheduled(cf: BMAScheduledCashflow) -> np.ndarray:
    """Scheduled investor cashflow path: principal + interest."""
    return np.asarray(cf.principal_paid + cf.interest_paid, dtype=np.float64)


def _periods_from_scheduled(cf: BMAScheduledCashflow) -> np.ndarray:
    """Scheduled period axis from source object (no synthetic index)."""
    return np.asarray(cf.period, dtype=np.float64)


def _cashflows_from_actual(cf: BMAActualCashflow) -> np.ndarray:
    # Loan-level proxy: leaf actual cashflows do not contain trust-level
    # pass-through allocation, so we use a transparent sum of principal-like and
    # interest-like components for deterministic-path analytics.
    return np.asarray(cf.act_am + cf.vol_prepay + cf.prin_recov + cf.act_int, dtype=np.float64)


def _periods_from_actual(cf: BMAActualCashflow) -> np.ndarray:
    """Actual period axis from source object (no synthetic index)."""
    return np.asarray(cf.period, dtype=np.float64)


def _cashflows_from_portfolio_like(cf: Any) -> np.ndarray:
    """Portfolio investor cashflow path by mode."""
    source = _portfolio_cashflow_source(getattr(cf, "mode"))
    if source == "scheduled":
        scheduled = cf.scheduled
        return np.asarray(scheduled.principal_paid + scheduled.interest_paid, dtype=np.float64)
    return np.asarray(cf.pt_cashflow, dtype=np.float64)


def _periods_from_portfolio_like(cf: Any) -> np.ndarray:
    """Portfolio period axis by mode."""
    source = _portfolio_cashflow_source(getattr(cf, "mode"))
    if source == "scheduled":
        return np.asarray(cf.scheduled.period, dtype=np.float64)
    return np.asarray(cf.pool.period, dtype=np.float64)


def extract_cashflow_vector(cf: object) -> np.ndarray:
    """Extract investable per-period cashflow vector from supported objects.

    Mapping policy:
        - BMAScheduledCashflow: principal_paid + interest_paid
        - BMAActualCashflow: act_am + vol_prepay + prin_recov + act_int
        - Portfolio scheduled mode: scheduled principal + scheduled interest
        - Portfolio actual/paired mode: trust-level ``pt_cashflow``

    Args:
        cf: One supported cashflow object.

    Returns:
        1D float array indexed by period.

    Raises:
        TypeError: If ``cf`` is unsupported.
    """
    if isinstance(cf, BMAScheduledCashflow):
        return _cashflows_from_scheduled(cf)
    if isinstance(cf, BMAActualCashflow):
        return _cashflows_from_actual(cf)
    if _is_portfolio_cashflow_like(cf):
        return _cashflows_from_portfolio_like(cf)
    raise TypeError(f"Unsupported cashflow type: {type(cf)}")


def extract_period_vector(cf: object) -> np.ndarray:
    """Extract existing period vector from supported cashflow objects.

    This uses each object's native period axis and does NOT create a synthetic
    ``np.arange`` index. That keeps pricing/risk timing aligned with the same
    period semantics used during cashflow generation.
    """
    if isinstance(cf, BMAScheduledCashflow):
        return _periods_from_scheduled(cf)
    if isinstance(cf, BMAActualCashflow):
        return _periods_from_actual(cf)
    if _is_portfolio_cashflow_like(cf):
        return _periods_from_portfolio_like(cf)
    raise TypeError(f"Unsupported cashflow type: {type(cf)}")


def years_from_periods(periods: np.ndarray, *, delay_days: int = 0, month_days: float = 30.0) -> np.ndarray:
    """Convert period indices to year fractions using Section E-style mapping.

    Formula:
        Tₖ = (periodₖ · month_days + delay_days) / 360

    Args:
        periods: Period index vector from the cashflow object.
        delay_days: Investor payment delay offset in days.
        month_days: Assumed day count per month (default 30).

    Returns:
        Year-fraction vector aligned with ``periods``.
    """
    return (np.asarray(periods, dtype=np.float64) * month_days + float(delay_days)) / 360.0


def discount_factors_from_yield_pct(years: np.ndarray, annual_yield_pct: float) -> np.ndarray:
    """Compute discount factors ``DFₖ`` from year fractions ``Tₖ`` and yield ``Y``.

    Formula:
        y    = Y / 100
        DFₖ  = (1 + y)^{-Tₖ}

    Args:
        years: Time vector ``Tₖ`` in years.
        annual_yield_pct: Yield ``Y`` in annual percent units.

    Returns:
        Discount factor vector with same shape as ``years``.

    Raises:
        ValueError: If ``1 + y <= 0`` (invalid discount base).
    """
    years = np.asarray(years, dtype=np.float64)
    y = annual_yield_pct / 100.0
    base = 1.0 + y
    if base <= 0.0:
        raise ValueError(f"annual_yield_pct implies non-positive discount base: {annual_yield_pct}")
    return np.power(base, -years)


def present_values_from_discount_factors(cashflows: np.ndarray, discount_factors: np.ndarray) -> np.ndarray:
    """Compute present values from cashflows and discount factors.

    Formula:
        PVₖ = CFₖ · DFₖ
    """
    cashflows = np.asarray(cashflows, dtype=np.float64)
    discount_factors = np.asarray(discount_factors, dtype=np.float64)
    if cashflows.shape != discount_factors.shape:
        raise ValueError("cashflows and discount_factors must have identical shapes")
    return cashflows * discount_factors


def _notional_from_cashflow_object(cf: object) -> float:
    """Return best-available scenario notional for quote normalization."""
    if isinstance(cf, BMAScheduledCashflow):
        return float(cf.original_balance)
    if isinstance(cf, BMAActualCashflow):
        return float(cf.original_balance)
    if _is_portfolio_cashflow_like(cf):
        source = _portfolio_cashflow_source(getattr(cf, "mode"))
        if source == "scheduled":
            return float(cf.scheduled.original_balance)
        return float(cf.pool.original_balance)
    raise TypeError(f"Unsupported cashflow type: {type(cf)}")


@dataclass(frozen=True, slots=True)
class _PreparedScenario:
    """Normalized scenario inputs on a consistent quote basis."""

    label: str
    cashflows: np.ndarray
    years: np.ndarray


# =============================================================================
# Timing transform layer (Section E linkage)
# =============================================================================

def price_from_yield_pct(
    cashflows: np.ndarray,
    years: np.ndarray,
    annual_yield_pct: float,
    *,
    face_value: float = 100.0,
) -> float:
    """Compute price from annualized yield.

    Pricing equation implemented:

        P = Σₖ [ CFₖ / (1 + y)^{Tₖ} ]

    with:

        y = Y/100
        Y = annual_yield_pct

    BMA Section G.1 equivalent semiannual form:

        P = Σₖ [ CFₖ / (1 + Y/200)^{2Tₖ} ]

    Args:
        cashflows: Cashflow vector on quote basis (e.g., per-100 notional).
        years: Year-fraction vector aligned with ``cashflows``.
        annual_yield_pct: Annual yield in percent.
        face_value: Quote basis denominator (default 100).

    Returns:
        Price quoted per ``face_value``.

    Notes:
        ``cashflows`` are expected to already be normalized to quote basis
        (for example, dollars per 100 current face).
        Implementation computes ``DFₖ`` first, then ``PVₖ = CFₖ·DFₖ``.
    """
    if np.asarray(cashflows).shape != np.asarray(years).shape:
        raise ValueError("cashflows and years must have identical shapes")
    dfs = discount_factors_from_yield_pct(years, annual_yield_pct)
    pv = float(np.sum(present_values_from_discount_factors(cashflows, dfs)))
    return pv / face_value * 100.0


def yield_pct_from_price(
    cashflows: np.ndarray,
    years: np.ndarray,
    target_price: float,
    *,
    face_value: float = 100.0,
    lower_bound_pct: float = -99.0,
    upper_bound_pct: float = 250.0,
) -> float:
    """Solve annualized yield from a target price.

    Uses Brent root finding on:

        f(Y) = Price(Y) - P_target

    where:
        Price(Y) = Σₖ [ CFₖ / (1 + Y/100)^{Tₖ} ]

    Args:
        cashflows: Cashflow vector on quote basis.
        years: Year-fraction vector.
        target_price: Price per ``face_value``.
        face_value: Quote basis denominator.
        lower_bound_pct: Lower root-search bound (percent).
        upper_bound_pct: Upper root-search bound (percent).

    Returns:
        Solved annual yield ``Y`` in percent.

    Raises:
        ValueError: For non-positive price, shape mismatch, or unbracketed root.
    """
    if target_price <= 0:
        raise ValueError(f"target_price must be positive, got {target_price}")
    if np.asarray(cashflows).shape != np.asarray(years).shape:
        raise ValueError("cashflows and years must have identical shapes")

    # Root function: positive when model price > target, negative when below.
    def f(y_pct: float) -> float:
        return price_from_yield_pct(cashflows, years, y_pct, face_value=face_value) - target_price

    f_low = f(lower_bound_pct)
    f_high = f(upper_bound_pct)
    if f_low == 0.0:
        return float(lower_bound_pct)
    if f_high == 0.0:
        return float(upper_bound_pct)
    if f_low * f_high > 0.0:
        raise ValueError(
            "Yield root is not bracketed. Adjust lower_bound_pct/upper_bound_pct "
            f"or inspect cashflow monotonicity. f(low)={f_low}, f(high)={f_high}"
        )
    # Brent is robust for monotone price-yield functions and does not require
    # a derivative (unlike Newton methods).
    return float(brentq(f, lower_bound_pct, upper_bound_pct))


# =============================================================================
# Public analyzer
# =============================================================================


class PriceRiskAnalyzer:
    """Deterministic-path pricing/risk facade for one or many scenarios.

    This class is the primary API for Section G analytics. It pre-normalizes
    each scenario once (cashflow extraction, period filtering, quote-basis
    normalization, and period-to-year mapping), then exposes table and point
    analytics methods over that fixed deterministic path.
    """

    def __init__(
        self,
        scenarios: Mapping[str, object],
        *,
        include_period_zero: bool = False,
        delay_days: int = 0,
        month_days: float = 30.0,
        face_value: float = 100.0,
    ) -> None:
        """Build analyzer context from scenario cashflow objects.

        Args:
            scenarios: Mapping label -> supported cashflow object.
            include_period_zero: Include period-0 state row if True.
            delay_days: Delay-day shift for period-to-year mapping.
            month_days: Day-count month length for period-to-year mapping.
            face_value: Quote basis denominator (default 100).

        Raises:
            ValueError: If scenarios is empty, notional is non-positive, or
                extracted vectors are inconsistent.
            TypeError: If scenario object type is unsupported.
        """
        if len(scenarios) == 0:
            raise ValueError("scenarios must be non-empty")
        self._include_period_zero = bool(include_period_zero)
        self._delay_days = int(delay_days)
        self._month_days = float(month_days)
        self._face_value = float(face_value)
        self._prepared: tuple[_PreparedScenario, ...] = tuple(
            self._prepare_scenario(label, cf) for label, cf in scenarios.items()
        )

    @classmethod
    def from_cashflow(
        cls,
        cashflow: object,
        *,
        label: str = "base",
        include_period_zero: bool = False,
        delay_days: int = 0,
        month_days: float = 30.0,
        face_value: float = 100.0,
    ) -> "PriceRiskAnalyzer":
        """Create analyzer from one cashflow object."""
        return cls(
            {label: cashflow},
            include_period_zero=include_period_zero,
            delay_days=delay_days,
            month_days=month_days,
            face_value=face_value,
        )

    def _prepare_scenario(self, label: str, cf: object) -> _PreparedScenario:
        """Normalize one scenario to quote-basis cashflows and year-fraction times."""
        cashflows = extract_cashflow_vector(cf)
        periods = extract_period_vector(cf)
        notional = _notional_from_cashflow_object(cf)
        if notional <= 0.0:
            raise ValueError(f"Scenario {label!r} has non-positive notional: {notional}")
        if cashflows.shape != periods.shape:
            raise ValueError(f"Scenario {label!r} has mismatched cashflow and period vectors")
        mask = np.ones_like(periods, dtype=bool) if self._include_period_zero else periods > 0
        normalized_cashflows = (cashflows[mask] / notional) * self._face_value
        years = years_from_periods(
            periods[mask],
            delay_days=self._delay_days,
            month_days=self._month_days,
        )
        return _PreparedScenario(label=str(label), cashflows=normalized_cashflows, years=years)

    def _base_metadata(self) -> dict[str, str | int | float]:
        """Return metadata common to all analyzer outputs."""
        return {
            "include_period_zero": int(self._include_period_zero),
            "delay_days": self._delay_days,
            "month_days": self._month_days,
            "face_value": self._face_value,
        }

    def price_yield_table(self, column_inputs: np.ndarray, input_kind: PriceYieldKind) -> PriceYieldScenarioTable:
        """Build two-way price/yield table for all configured scenarios."""
        if input_kind not in ("price", "yield"):
            raise ValueError(f"input_kind must be 'price' or 'yield', got {input_kind!r}")
        inputs = np.asarray(column_inputs, dtype=np.float64)
        if inputs.ndim != 1 or inputs.size == 0:
            raise ValueError("column_inputs must be a non-empty 1D vector")

        row_labels: list[str] = []
        out_rows: list[np.ndarray] = []
        for prepared in self._prepared:
            row = np.empty_like(inputs)
            for i, val in enumerate(inputs):
                if input_kind == "yield":
                    row[i] = price_from_yield_pct(
                        prepared.cashflows,
                        prepared.years,
                        val,
                        face_value=self._face_value,
                    )
                else:
                    row[i] = yield_pct_from_price(
                        prepared.cashflows,
                        prepared.years,
                        val,
                        face_value=self._face_value,
                    )
            row_labels.append(prepared.label)
            out_rows.append(row)

        value_kind: PriceYieldKind = "price" if input_kind == "yield" else "yield"
        value_units = "price per 100 face" if value_kind == "price" else "annual yield percent"
        return PriceYieldScenarioTable(
            row_labels=tuple(row_labels),
            column_inputs=inputs,
            values=np.vstack(out_rows),
            input_kind=input_kind,
            value_kind=value_kind,
            value_units=value_units,
            metadata=self._base_metadata(),
        )

    def risk_metrics(self, annual_yield_pct: float) -> dict[str, RiskMetrics]:
        """Compute point risk metrics for all configured scenarios at one yield."""
        out: dict[str, RiskMetrics] = {}
        for prepared in self._prepared:
            price = price_from_yield_pct(
                prepared.cashflows,
                prepared.years,
                annual_yield_pct,
                face_value=self._face_value,
            )
            out[prepared.label] = RiskMetrics(
                price=price,
                annual_yield_pct=float(annual_yield_pct),
                macaulay_duration_years=macaulay_duration_years(
                    prepared.cashflows,
                    prepared.years,
                    annual_yield_pct,
                ),
                modified_duration_years=modified_duration_years(
                    prepared.cashflows,
                    prepared.years,
                    annual_yield_pct,
                ),
                convexity_years2=convexity_years2(
                    prepared.cashflows,
                    prepared.years,
                    annual_yield_pct,
                ),
                metadata=self._base_metadata(),
            )
        return out

    def expanded_price_yield_table(
        self,
        column_inputs: np.ndarray,
        input_kind: PriceYieldKind,
    ) -> PriceYieldRiskTable:
        """Build cellwise price/yield table expanded with duration and convexity."""
        if input_kind not in ("price", "yield"):
            raise ValueError(f"input_kind must be 'price' or 'yield', got {input_kind!r}")
        inputs = np.asarray(column_inputs, dtype=np.float64)
        if inputs.ndim != 1 or inputs.size == 0:
            raise ValueError("column_inputs must be a non-empty 1D vector")

        n_rows = len(self._prepared)
        n_cols = inputs.size
        prices = np.empty((n_rows, n_cols), dtype=np.float64)
        yields = np.empty((n_rows, n_cols), dtype=np.float64)
        macaulay = np.empty((n_rows, n_cols), dtype=np.float64)
        modified = np.empty((n_rows, n_cols), dtype=np.float64)
        convexity = np.empty((n_rows, n_cols), dtype=np.float64)

        for i, prepared in enumerate(self._prepared):
            for j, input_val in enumerate(inputs):
                if input_kind == "yield":
                    y_val = float(input_val)
                    p_val = price_from_yield_pct(
                        prepared.cashflows,
                        prepared.years,
                        y_val,
                        face_value=self._face_value,
                    )
                else:
                    p_val = float(input_val)
                    y_val = yield_pct_from_price(
                        prepared.cashflows,
                        prepared.years,
                        p_val,
                        face_value=self._face_value,
                    )
                prices[i, j] = p_val
                yields[i, j] = y_val
                macaulay[i, j] = macaulay_duration_years(prepared.cashflows, prepared.years, y_val)
                modified[i, j] = modified_duration_years(prepared.cashflows, prepared.years, y_val)
                convexity[i, j] = convexity_years2(prepared.cashflows, prepared.years, y_val)

        return PriceYieldRiskTable(
            row_labels=tuple(p.label for p in self._prepared),
            column_inputs=inputs,
            input_kind=input_kind,
            price_values=prices,
            yield_values=yields,
            macaulay_duration_years=macaulay,
            modified_duration_years=modified,
            convexity_years2=convexity,
            metadata=self._base_metadata(),
        )

def build_price_yield_table_from_cashflows(
    scenarios: Mapping[str, object],
    column_inputs: np.ndarray,
    input_kind: PriceYieldKind,
    *,
    include_period_zero: bool = False,
    delay_days: int = 0,
    month_days: float = 30.0,
    face_value: float = 100.0,
) -> PriceYieldScenarioTable:
    """Legacy wrapper; prefer ``PriceRiskAnalyzer.price_yield_table``."""
    analyzer = PriceRiskAnalyzer(
        scenarios,
        include_period_zero=include_period_zero,
        delay_days=delay_days,
        month_days=month_days,
        face_value=face_value,
    )
    return analyzer.price_yield_table(column_inputs, input_kind)


# =============================================================================
# Single-scenario risk metrics (Section G linkage)
# =============================================================================

def macaulay_duration_years(cashflows: np.ndarray, years: np.ndarray, annual_yield_pct: float) -> float:
    """Compute Macaulay Duration (PV-weighted average cashflow time).

    Formula:
        PVₖ   = CFₖ / (1 + y)^{Tₖ}
        D_mac = [Σₖ (Tₖ · PVₖ)] / [Σₖ PVₖ]

    Equivalent BMA semiannual denominator uses:
        PVₖ = CFₖ / (1 + Y/200)^{2Tₖ}
    """
    if np.asarray(cashflows).shape != np.asarray(years).shape:
        raise ValueError("cashflows and years must have identical shapes")
    # Discount each cashflow to present value using explicit discount factors.
    dfs = discount_factors_from_yield_pct(years, annual_yield_pct)
    pv = present_values_from_discount_factors(cashflows, dfs)
    # Denominator is price on the same basis as cashflows.
    denom = float(np.sum(pv))
    if denom == 0.0:
        raise ValueError("Present value is zero; duration undefined")
    # Numerator weights each cashflow PV by its receipt time Tₖ.
    return float(np.sum(years * pv) / denom)


def modified_duration_years(cashflows: np.ndarray, years: np.ndarray, annual_yield_pct: float) -> float:
    """Compute Modified Duration from Macaulay Duration.

    Current implementation:
        D_mod = D_mac / (1 + y)
    where:
        y = Y/100

    BMA-style semiannual notation is commonly shown as:
        D_mod = Duration / (1 + Y/200)
    depending on explicit compounding convention.
    """
    mac = macaulay_duration_years(cashflows, years, annual_yield_pct)
    y = annual_yield_pct / 100.0
    return float(mac / (1.0 + y))


def convexity_years2(cashflows: np.ndarray, years: np.ndarray, annual_yield_pct: float) -> float:
    """Compute cash-flow convexity (second-order price sensitivity).

    This implementation uses:
        PVₖ   = CFₖ / (1 + y)^{Tₖ}
        Conv  = [Σₖ Tₖ(Tₖ + 1)·PVₖ] / [P·(1 + y)²]

    where:
        y = Y/100
        P = Σₖ PVₖ

    This is the cash-flow convexity analogue under the same annual-yield
    discounting convention used throughout this module.
    """
    if np.asarray(cashflows).shape != np.asarray(years).shape:
        raise ValueError("cashflows and years must have identical shapes")
    y = annual_yield_pct / 100.0
    dfs = discount_factors_from_yield_pct(years, annual_yield_pct)
    pv = present_values_from_discount_factors(cashflows, dfs)
    price = float(np.sum(pv))
    if price == 0.0:
        raise ValueError("Present value is zero; convexity undefined")
    # The Tₖ(Tₖ+1) term captures second-order curvature sensitivity.
    return float(np.sum(years * (years + 1.0) * pv) / (price * (1.0 + y) ** 2))


def compute_risk_metrics_from_cashflow(
    cf: object,
    annual_yield_pct: float,
    *,
    include_period_zero: bool = False,
    delay_days: int = 0,
    month_days: float = 30.0,
    face_value: float = 100.0,
) -> RiskMetrics:
    """Legacy wrapper; prefer ``PriceRiskAnalyzer.risk_metrics``."""
    analyzer = PriceRiskAnalyzer.from_cashflow(
        cf,
        include_period_zero=include_period_zero,
        delay_days=delay_days,
        month_days=month_days,
        face_value=face_value,
    )
    return analyzer.risk_metrics(annual_yield_pct)["base"]
