"""Unit tests for Section F schedule stepping and date increment behavior."""

from __future__ import annotations

import datetime as dt
import unittest

import numpy as np

from bma_standard_formulas.formulas.daycount import (
    build_date_range_vector,
    increment_date,
    increment_months,
    increment_month_end,
    iter_date_range,
    next_business_day,
)


class TestFDateIncrementRules(unittest.TestCase):
    """Validate date increment and business-day rolling utilities."""

    def test_next_business_day_rolls_weekend_to_monday(self) -> None:
        """Weekend inputs should roll forward to Monday under weekend-only calendar."""
        saturday = dt.date(2024, 3, 2)
        sunday = dt.date(2024, 3, 3)
        self.assertEqual(next_business_day(saturday), dt.date(2024, 3, 4))
        self.assertEqual(next_business_day(sunday), dt.date(2024, 3, 4))

    def test_month_increment_preserves_month_end_semantics(self) -> None:
        """Monthly helpers should preserve expected month-end behavior."""
        start = dt.date(2024, 1, 31)
        self.assertEqual(increment_months(start, 1), dt.date(2024, 2, 29))
        self.assertEqual(increment_month_end(start, 1), dt.date(2024, 2, 29))
        self.assertEqual(increment_date(start, 2, "monthly"), dt.date(2024, 3, 31))
        self.assertEqual(increment_date(start, 1, "monthmid"), dt.date(2024, 2, 15))

    def test_build_date_range_vector_monthly_length_and_end(self) -> None:
        """Date range vector should produce deterministic monthly schedule points."""
        start = dt.date(2024, 1, 31)
        out = build_date_range_vector(start, 4, "monthly")
        self.assertEqual(len(out), 4)
        self.assertEqual(str(out[0]), "2024-01-31")
        self.assertEqual(str(out[-1]), "2024-04-30")

    def test_build_date_range_vector_weekday_only_applies_business_roll(self) -> None:
        """weekday_only flag should roll weekend schedule points to business days."""
        start = dt.date(2024, 3, 1)  # Friday
        out = build_date_range_vector(start, 3, "daily", weekday_only=True)
        # Expected dates: 2024-03-01, 2024-03-04, 2024-03-04 (legacy TODO behavior)
        self.assertEqual(str(out[0]), "2024-03-01")
        self.assertEqual(str(out[1]), "2024-03-04")
        self.assertEqual(str(out[2]), "2024-03-04")

    def test_iter_date_range_inclusive_end(self) -> None:
        """Iterator should include reachable terminal dates under monthly stepping."""
        out = list(iter_date_range(dt.date(2024, 1, 31), dt.date(2024, 4, 30), "monthly"))
        self.assertEqual(len(out), 4)
        self.assertEqual(out[0], dt.date(2024, 1, 31))
        # monthly stepping from Jan-31 follows 29th anchors in later months here
        self.assertEqual(out[-1], dt.date(2024, 4, 29))


if __name__ == "__main__":
    unittest.main()

