"""Unit tests for Section E calendar-basis day-count conventions.

BMA context:
    Section E.1 defines calendar-basis conventions (30/360 variants and actual
    day-count denominators). Section E.2 introduces delay-day timing shifts.
"""

from __future__ import annotations

import datetime as dt
import unittest

import numpy as np

from bma_standard_formulas.formulas.daycount import (
    day_count_30_360,
    day_count_30_360_vector,
    year_fraction,
    year_fraction_actual_360,
    year_fraction_actual_365,
    year_fraction_actual_actual,
)
from bma_standard_formulas.formulas.pricing_risk import years_from_periods


class TestECalendarBasis(unittest.TestCase):
    """Validate Section E day-count rules and dispatcher behavior."""

    def test_nasd_vs_isda_february_month_end(self) -> None:
        """NASD and ISDA should diverge on February end-of-month treatment."""
        start = dt.date(2024, 2, 29)
        end = dt.date(2024, 3, 31)
        self.assertEqual(day_count_30_360(start, end, convention="NASD"), 30)
        self.assertEqual(day_count_30_360(start, end, convention="ISDA"), 32)

    def test_year_fraction_dispatcher_matches_direct_functions(self) -> None:
        """Dispatcher should map to direct implementation outputs."""
        start = dt.date(2024, 1, 1)
        end = dt.date(2024, 7, 1)
        self.assertAlmostEqual(
            year_fraction(start, end, "30/360 NASD"),
            day_count_30_360(start, end, "NASD") / 360.0,
            places=12,
        )
        self.assertAlmostEqual(
            year_fraction(start, end, "act/365"),
            year_fraction_actual_365(start, end),
            places=12,
        )

    def test_actual_daycount_scalar_contract(self) -> None:
        """ACT/360 and ACT/365 scalar paths should return float values."""
        start = dt.date(2024, 1, 1)
        end = dt.date(2024, 7, 1)
        frac360 = year_fraction_actual_360(start, end)
        frac365 = year_fraction_actual_365(start, end)
        self.assertIsInstance(frac360, float)
        self.assertIsInstance(frac365, float)
        self.assertAlmostEqual(frac360, 182.0 / 360.0, places=12)
        self.assertAlmostEqual(frac365, 182.0 / 365.0, places=12)

    def test_actact_full_year_identity(self) -> None:
        """Act/Act ISDA should return exactly 1.0 for Jan1-to-Jan1 one-year spans."""
        self.assertEqual(year_fraction_actual_actual(dt.date(2023, 1, 1), dt.date(2024, 1, 1)), 1.0)
        self.assertEqual(year_fraction_actual_actual(dt.date(2024, 1, 1), dt.date(2025, 1, 1)), 1.0)

    def test_vectorized_30_360_shape_and_sign(self) -> None:
        """Vectorized 30/360 output should preserve input shape and sign conventions."""
        starts = np.array(["2024-01-31", "2024-03-31"], dtype="datetime64[D]")
        ends = np.array(["2024-02-29", "2024-02-29"], dtype="datetime64[D]")
        out = day_count_30_360_vector(starts, ends, convention="NASD")
        self.assertEqual(out.shape, starts.shape)
        np.testing.assert_array_equal(out, np.array([29, -30]))

    def test_invalid_convention_raises_value_error(self) -> None:
        """Unsupported day-count names should fail loudly."""
        with self.assertRaises(ValueError):
            day_count_30_360(dt.date(2024, 1, 1), dt.date(2024, 2, 1), convention="BAD")

    def test_e_sf44_delay_days_table(self) -> None:
        """SF-44 delay-day table maps directly to delay/360 timing shifts.

        BMA SF-44 lists actual delays (days) for pass-through types issued on
        March 1, assuming 30-day months:
            GNMA I: 14, GNMA II: 19, FNMA: 24, FHLMC NONGOLD: 44, FHLMC GOLD: 14.
        """
        delay_by_type = {
            "GNMA_I": 14,
            "GNMA_II": 19,
            "FNMA": 24,
            "FHLMC_NONGOLD": 44,
            "FHLMC_GOLD": 14,
        }
        periods = np.array([1.0], dtype=np.float64)  # first monthly period
        base = years_from_periods(periods, delay_days=0, month_days=30.0)[0]
        self.assertAlmostEqual(base, 30.0 / 360.0, places=12)
        for deal_type, delay_days in delay_by_type.items():
            with self.subTest(pass_through_type=deal_type, delay_days=delay_days):
                shifted = years_from_periods(periods, delay_days=delay_days, month_days=30.0)[0]
                self.assertAlmostEqual(shifted, (30.0 + delay_days) / 360.0, places=12)


if __name__ == "__main__":
    unittest.main()

