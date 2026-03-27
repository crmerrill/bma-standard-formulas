"""Unit tests for Section G yield, pricing, duration, and convexity analytics."""

from __future__ import annotations

import unittest

import numpy as np

from bma_standard_formulas.engine import build_expanded_price_yield_table, build_price_yield_table
from bma_standard_formulas.formulas.cashflows import run_bma_scheduled_cashflow
from bma_standard_formulas.formulas.examples import BMA_EXAMPLES
from bma_standard_formulas.formulas.pricing_risk import (
    PriceRiskAnalyzer,
    clean_price_from_dirty,
    dirty_price_from_clean,
)


def _build_scheduled_cf(coupon_pct: float):
    """Build a deterministic fixed-rate cashflow for Section G tests."""
    return run_bma_scheduled_cashflow(
        original_balance=100_000.0,
        current_balance=100_000.0,
        coupon_vector=coupon_pct,
        original_term=360,
        remaining_term=360,
    )


class TestGPriceYieldTable(unittest.TestCase):
    """Validate monotonic and contract behavior for Section G price/yield grids."""

    def test_price_input_table_yields_are_monotone_decreasing(self) -> None:
        scenarios = {"base": _build_scheduled_cf(6.0), "high_coupon": _build_scheduled_cf(8.0)}
        prices = np.array([90.0, 95.0, 100.0, 105.0], dtype=float)
        table = PriceRiskAnalyzer(scenarios).price_yield_table(prices, "price")
        self.assertEqual(table.value_kind, "yield")
        self.assertEqual(table.values.shape, (2, 4))
        for row in table.values:
            self.assertTrue(np.all(np.diff(row) < 0.0))

    def test_yield_input_table_prices_are_monotone_decreasing(self) -> None:
        scenarios = {"base": _build_scheduled_cf(6.0), "high_coupon": _build_scheduled_cf(8.0)}
        yields = np.array([3.0, 5.0, 7.0, 9.0], dtype=float)
        table = PriceRiskAnalyzer(scenarios).price_yield_table(yields, "yield")
        self.assertEqual(table.value_kind, "price")
        self.assertEqual(table.values.shape, (2, 4))
        for row in table.values:
            self.assertTrue(np.all(np.diff(row) < 0.0))

    def test_engine_wrapper_matches_analyzer(self) -> None:
        scenarios = {"base": _build_scheduled_cf(6.0)}
        prices = np.array([95.0, 100.0], dtype=float)
        direct = PriceRiskAnalyzer(scenarios).price_yield_table(prices, "price")
        wrapped = build_price_yield_table(scenarios=scenarios, column_inputs=prices, input_kind="price")
        np.testing.assert_allclose(direct.values, wrapped.values)


class TestGRiskMeasures(unittest.TestCase):
    """Validate point and expanded Section G risk outputs."""

    def test_risk_metrics_positive_for_standard_cashflow(self) -> None:
        metrics = PriceRiskAnalyzer.from_cashflow(_build_scheduled_cf(6.0)).risk_metrics(6.0)["base"]
        self.assertGreater(metrics.price, 0.0)
        self.assertGreater(metrics.macaulay_duration_years, 0.0)
        self.assertGreater(metrics.modified_duration_years, 0.0)
        self.assertGreater(metrics.convexity_years2, 0.0)

    def test_expanded_table_shapes(self) -> None:
        scenarios = {"base": _build_scheduled_cf(6.0)}
        yields = np.array([4.0, 6.0, 8.0], dtype=float)
        table = PriceRiskAnalyzer(scenarios).expanded_price_yield_table(yields, "yield")
        self.assertEqual(table.price_values.shape, (1, 3))
        self.assertEqual(table.yield_values.shape, (1, 3))
        self.assertEqual(table.macaulay_duration_years.shape, (1, 3))
        self.assertEqual(table.modified_duration_years.shape, (1, 3))
        self.assertEqual(table.convexity_years2.shape, (1, 3))

    def test_engine_expanded_wrapper_matches_analyzer(self) -> None:
        scenarios = {"base": _build_scheduled_cf(6.0)}
        yields = np.array([5.0, 6.0], dtype=float)
        direct = PriceRiskAnalyzer(scenarios).expanded_price_yield_table(yields, "yield")
        wrapped = build_expanded_price_yield_table(
            scenarios=scenarios,
            column_inputs=yields,
            input_kind="yield",
        )
        np.testing.assert_allclose(direct.price_values, wrapped.price_values)
        np.testing.assert_allclose(direct.yield_values, wrapped.yield_values)

    def test_g_sf49_sf50_yield_duration_convexity(self) -> None:
        """SF-49/50 reference values satisfy core Section G identities."""
        ex = BMA_EXAMPLES["SF49_50"]
        cf = ex.cashflows[(0, 1)]
        y = cf.yield_pct

        # Modified duration identity from Section G.1.e:
        #   Modified Duration = Duration / (1 + Y/200)
        implied_mod = cf.duration / (1.0 + y / 200.0)
        self.assertAlmostEqual(cf.mod_duration, implied_mod, places=4)

        # Convexity for fixed cash flows should be positive (G.1.f discussion).
        self.assertGreater(cf.convexity, 0.0)

        # Mortgage yield and BEY differ by compounding basis; both should be positive.
        self.assertGreater(cf.yield_pct, 0.0)
        self.assertGreater(cf.mortgage_yield, 0.0)

    def test_g_sf51_settlement_shift(self) -> None:
        """SF-51 (7-day settlement shift) should move price/yield in expected direction."""
        sf49 = BMA_EXAMPLES["SF49_50"].cashflows[(0, 1)]
        sf51 = BMA_EXAMPLES["SF51"].cashflows[(0, 1)]

        # Same underlying projected cash flows in examples, so static risk terms match.
        self.assertAlmostEqual(sf51.duration, sf49.duration, places=5)
        self.assertAlmostEqual(sf51.mod_duration, sf49.mod_duration, places=5)
        self.assertAlmostEqual(sf51.convexity, sf49.convexity, places=4)

        # SF-49/50 is quoted at clean price 100.0.
        self.assertAlmostEqual(sf49.price, 100.0, places=6)

        # SF-51 includes 7 days of accrued net coupon at 9.0%:
        # dirty = clean + accrued = 100 + (7/30)*(9.0/12) = 100.175
        expected_dirty = dirty_price_from_clean(
            sf49.price,
            annual_coupon_pct=9.0,
            accrued_days=7.0,
            face_value=100.0,
            day_count_basis=360.0,
        )
        self.assertAlmostEqual(sf51.price, 100.1750, places=6)
        self.assertAlmostEqual(expected_dirty, 100.1750, places=6)
        self.assertAlmostEqual(sf51.price, expected_dirty, places=6)

        # Clean < dirty must hold when accrued interest is positive.
        self.assertLess(sf49.price, sf51.price)
        self.assertAlmostEqual(
            clean_price_from_dirty(
                sf51.price,
                annual_coupon_pct=9.0,
                accrued_days=7.0,
                face_value=100.0,
                day_count_basis=360.0,
            ),
            sf49.price,
            places=6,
        )

        # Higher dirty price from accrued interest implies slightly lower solved yield.
        self.assertLess(sf51.yield_pct, sf49.yield_pct)


if __name__ == "__main__":
    unittest.main()

