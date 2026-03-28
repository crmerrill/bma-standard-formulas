"""Unit tests for Section D calendar/date primitives.

BMA context:
    Section D establishes calendar arithmetic assumptions used by later
    day-count and pricing sections. These tests validate foundational helpers
    (leap years, month lengths, and ordinal day positioning).
"""

from __future__ import annotations

import unittest

import numpy as np

from bma_standard_formulas.formulas.daycount import (
    days_before_date_vector,
    days_in_month,
    days_in_month_vector,
    days_in_year,
    days_in_year_vector,
    is_leap_year,
)


class TestDCalendarPrimitives(unittest.TestCase):
    """Verify calendar primitives used by downstream Section E/F/G logic."""

    def test_is_leap_year_matches_gregorian_rules(self) -> None:
        """Leap-year helper should follow Gregorian 4/100/400 rules."""
        self.assertTrue(is_leap_year(2024))
        self.assertFalse(is_leap_year(1900))
        self.assertTrue(is_leap_year(2000))
        self.assertFalse(is_leap_year(2023))

    def test_days_in_year_scalar_and_vector(self) -> None:
        """Scalar and vector year-length helpers should agree."""
        self.assertEqual(days_in_year(2024), 366)
        self.assertEqual(days_in_year(2023), 365)
        years = np.array([2023, 2024, 2100, 2400], dtype=np.int64)
        expected = np.array([365, 366, 365, 366], dtype=np.int64)
        np.testing.assert_array_equal(days_in_year_vector(years), expected)

    def test_days_in_month_scalar_and_vector(self) -> None:
        """Month-length helpers should handle leap February and month ends."""
        self.assertEqual(days_in_month(2024, 2), 29)
        self.assertEqual(days_in_month(2023, 2), 28)
        self.assertEqual(days_in_month(2023, 4), 30)
        self.assertEqual(days_in_month(2023, 5), 31)

        dates = np.array(["2024-02-10", "2023-02-10", "2023-04-10"], dtype="datetime64[D]")
        expected = np.array([29, 28, 30], dtype=np.int64)
        np.testing.assert_array_equal(days_in_month_vector(dates), expected)

    def test_days_before_date_vector_is_monotone_within_year(self) -> None:
        """Days-before-date helper should be 0-based and monotone within year."""
        dates = np.array(["2024-01-01", "2024-01-31", "2024-02-01", "2024-12-31"], dtype="datetime64[D]")
        out = days_before_date_vector(dates)
        self.assertEqual(int(out[0]), 0)
        self.assertGreater(int(out[1]), int(out[0]))
        self.assertGreater(int(out[2]), int(out[1]))
        self.assertEqual(int(out[3]), 365)


if __name__ == "__main__":
    unittest.main()

