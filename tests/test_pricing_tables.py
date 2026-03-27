"""Tests for price/yield scenario table utilities (Section G scaffolding)."""

from __future__ import annotations

import numpy as np

from bma_standard_formulas.engine import build_expanded_price_yield_table, build_price_yield_table
from bma_standard_formulas.formulas.cashflows import run_bma_scheduled_cashflow
from bma_standard_formulas.formulas.pricing_risk import (
    PriceRiskAnalyzer,
    discount_factors_from_yield_pct,
    extract_cashflow_vector,
    extract_period_vector,
    present_values_from_discount_factors,
    years_from_periods,
)


def _build_scheduled_cf(coupon_pct: float):
    """Build a small fixed-rate scheduled cashflow for test usage."""
    return run_bma_scheduled_cashflow(
        original_balance=100_000.0,
        current_balance=100_000.0,
        coupon_vector=coupon_pct,
        original_term=360,
        remaining_term=360,
    )


def test_extract_cashflow_vector_supports_portfolio_and_leaf() -> None:
    """Extractor should accept existing cashflow dataclasses and portfolio object."""
    cf_a = _build_scheduled_cf(6.0)
    cf_b = _build_scheduled_cf(7.0)
    portfolio = cf_a + cf_b

    leaf_vec = extract_cashflow_vector(cf_a)
    port_vec = extract_cashflow_vector(portfolio)

    assert leaf_vec.shape[0] == 361
    assert port_vec.shape[0] == 361
    assert np.all(leaf_vec >= 0.0)
    assert np.all(port_vec >= 0.0)


def test_extract_period_vector_uses_existing_cashflow_periods() -> None:
    """Period extraction should use object-provided period arrays directly."""
    cf = _build_scheduled_cf(6.0)
    periods = extract_period_vector(cf)
    assert np.array_equal(periods, cf.period)


def test_price_input_table_returns_monotonic_yields() -> None:
    """Higher input price implies lower solved yield for each scenario."""
    scenarios = {
        "base": _build_scheduled_cf(6.0),
        "high_coupon": _build_scheduled_cf(8.0),
    }
    prices = np.array([90.0, 95.0, 100.0, 105.0], dtype=float)

    analyzer = PriceRiskAnalyzer(scenarios)
    table = analyzer.price_yield_table(column_inputs=prices, input_kind="price")

    assert table.value_kind == "yield"
    assert table.values.shape == (2, 4)
    for row in table.values:
        assert np.all(np.diff(row) < 0.0)


def test_yield_input_table_returns_monotonic_prices() -> None:
    """Higher input yield implies lower price for each scenario."""
    scenarios = {
        "base": _build_scheduled_cf(6.0),
        "higher_coupon": _build_scheduled_cf(7.0),
    }
    yields = np.array([3.0, 5.0, 7.0, 9.0], dtype=float)

    analyzer = PriceRiskAnalyzer(scenarios)
    table = analyzer.price_yield_table(column_inputs=yields, input_kind="yield")

    assert table.value_kind == "price"
    assert table.values.shape == (2, 4)
    for row in table.values:
        assert np.all(np.diff(row) < 0.0)


def test_engine_wrapper_matches_formula_builder() -> None:
    """Engine wrapper should forward to formula implementation unchanged."""
    scenarios = {"base": _build_scheduled_cf(6.0)}
    prices = np.array([95.0, 100.0], dtype=float)

    direct = PriceRiskAnalyzer(scenarios).price_yield_table(
        column_inputs=prices,
        input_kind="price",
    )
    wrapped = build_price_yield_table(
        scenarios=scenarios,
        column_inputs=prices,
        input_kind="price",
    )
    assert np.allclose(direct.values, wrapped.values)
    assert direct.row_labels == wrapped.row_labels


def test_risk_metrics_computation_produces_positive_price_and_duration() -> None:
    """Risk metric helper returns sensible positive values for standard CFs."""
    cf = _build_scheduled_cf(6.0)
    metrics = PriceRiskAnalyzer.from_cashflow(cf).risk_metrics(annual_yield_pct=6.0)["base"]
    assert metrics.price > 0.0
    assert metrics.macaulay_duration_years > 0.0
    assert metrics.modified_duration_years > 0.0


def test_expanded_price_yield_table_has_cellwise_risk_metrics() -> None:
    """Expanded table should expose risk outputs with same shape as prices/yields."""
    scenarios = {"base": _build_scheduled_cf(6.0)}
    yields = np.array([4.0, 6.0, 8.0], dtype=float)
    expanded = PriceRiskAnalyzer(scenarios).expanded_price_yield_table(
        column_inputs=yields,
        input_kind="yield",
    )
    assert expanded.price_values.shape == (1, 3)
    assert expanded.yield_values.shape == (1, 3)
    assert expanded.macaulay_duration_years.shape == (1, 3)
    assert expanded.modified_duration_years.shape == (1, 3)
    assert expanded.convexity_years2.shape == (1, 3)


def test_engine_expanded_table_wrapper_matches_analyzer_output() -> None:
    """Engine expanded-table wrapper should match analyzer outputs."""
    scenarios = {"base": _build_scheduled_cf(6.0)}
    yields = np.array([5.0, 6.0], dtype=float)
    direct = PriceRiskAnalyzer(scenarios).expanded_price_yield_table(
        column_inputs=yields,
        input_kind="yield",
    )
    wrapped = build_expanded_price_yield_table(
        scenarios=scenarios,
        column_inputs=yields,
        input_kind="yield",
    )
    assert np.allclose(direct.price_values, wrapped.price_values)
    assert np.allclose(direct.yield_values, wrapped.yield_values)


def test_discount_factors_are_non_increasing_over_time_for_positive_yield() -> None:
    """For positive yield, later discount factors should be smaller."""
    years = years_from_periods(np.array([1.0, 2.0, 3.0, 12.0]))
    dfs = discount_factors_from_yield_pct(years, annual_yield_pct=6.0)
    assert np.all(np.diff(dfs) <= 0.0)
    assert np.all((dfs > 0.0) & (dfs <= 1.0))


def test_present_values_from_discount_factors_matches_elementwise_product() -> None:
    """PV helper should equal CF * DF elementwise."""
    cf = np.array([1.2, 3.4, 5.6], dtype=float)
    df = np.array([0.99, 0.95, 0.80], dtype=float)
    pv = present_values_from_discount_factors(cf, df)
    assert np.allclose(pv, cf * df)


def test_extract_cashflow_vector_rejects_unknown_portfolio_mode() -> None:
    """Portfolio-like objects with unknown mode should fail loudly."""

    class _FakePool:
        period = np.array([0.0, 1.0], dtype=float)

    class _FakePortfolio:
        mode = "BROKEN_MODE"
        scheduled = None
        pt_cashflow = np.array([0.0, 1.0], dtype=float)
        pool = _FakePool()

    try:
        extract_cashflow_vector(_FakePortfolio())
    except ValueError as exc:
        assert "Unsupported portfolio mode" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unknown portfolio mode")
