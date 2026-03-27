"""Tests for direct cmutils-port daycount/date functions."""

from __future__ import annotations

import datetime as dt

import numpy as np

from bma_standard_formulas.formulas.daycount import (
    build_date_range_vector,
    day_count_30_360,
    day_count_30_360_vector,
    increment_date,
    increment_months,
    next_business_day,
    year_fraction,
    year_fraction_actual_360,
    year_fraction_actual_365,
    year_fraction_actual_actual,
)


def test_days360diff_nasd_and_isda_month_end_behavior() -> None:
    """Month-end handling follows each convention's adjustment rules."""
    start = dt.date(2024, 2, 29)  # leap-year February EOM
    end = dt.date(2024, 3, 31)
    # BMA/NASD adjusts start EOM-Feb to 30, then 30->31 end-day to 30.
    assert day_count_30_360(start, end, convention="NASD") == 30
    # ISDA does not apply Feb-EOM rule here, so this period is longer.
    assert day_count_30_360(start, end, convention="ISDA") == 32


def test_dayfrac_dispatcher_matches_direct_conventions() -> None:
    """Dispatcher outputs expected fractions for supported methods."""
    start = dt.date(2024, 1, 1)
    end = dt.date(2024, 7, 1)

    assert year_fraction(start, end, "30/360 NASD") == day_count_30_360(start, end, "NASD") / 360.0
    assert year_fraction(start, end, "30/360 ISDA") == day_count_30_360(start, end, "ISDA") / 360.0
    assert year_fraction(start, end, "act/365") == year_fraction_actual_365(start, end)


def test_vectorized_act365() -> None:
    """Vectorized year fractions return elementwise results."""
    starts = np.array(["2024-01-01", "2024-01-15"], dtype="datetime64[D]")
    ends = np.array(["2024-07-01", "2024-02-14"], dtype="datetime64[D]")
    frac = year_fraction_actual_365(starts, ends)
    assert np.allclose(frac, np.array([182.0 / 365.0, 30.0 / 365.0]))


def test_scalar_act_dayfracs_return_floats() -> None:
    """Scalar ACT day-fraction APIs return float, not Timedelta."""
    start = dt.date(2024, 1, 1)
    end = dt.date(2024, 7, 1)
    frac360 = year_fraction_actual_360(start, end)
    frac365 = year_fraction_actual_365(start, end)
    assert isinstance(frac360, float)
    assert isinstance(frac365, float)
    assert frac360 == 182.0 / 360.0
    assert frac365 == 182.0 / 365.0


def test_actact_isda_full_year_identity() -> None:
    """Under Act/Act ISDA, a full year from Jan 1 to Jan 1 is 1.0."""
    assert year_fraction_actual_actual(dt.date(2024, 1, 1), dt.date(2025, 1, 1), convention="ISDA") == 1.0
    assert year_fraction_actual_actual(dt.date(2023, 1, 1), dt.date(2024, 1, 1), convention="ISDA") == 1.0


def test_days360diff_array_shape_and_sign_contract() -> None:
    """Vectorized 30/360 result length matches inputs and preserves sign."""
    starts = np.array(["2024-01-31", "2024-03-31"], dtype="datetime64[D]")
    ends = np.array(["2024-02-29", "2024-02-29"], dtype="datetime64[D]")
    out = day_count_30_360_vector(starts, ends, convention="NASD")
    assert out.shape == starts.shape
    # First is forward (positive), second is reversed (negative).
    assert np.array_equal(out, np.array([29, -30]))


def test_invalid_daycount_method_raises_value_error() -> None:
    """Unsupported method names should fail with ValueError."""
    start = dt.date(2024, 1, 1)
    end = dt.date(2024, 2, 1)
    try:
        day_count_30_360(start, end, convention="BAD")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError for invalid 30/360 method")


def test_nextbusday_rolls_weekend() -> None:
    """Weekend dates roll forward to Monday."""
    sat = dt.date(2024, 3, 2)  # Saturday
    sun = dt.date(2024, 3, 3)  # Sunday
    assert next_business_day(sat) == dt.date(2024, 3, 4)
    assert next_business_day(sun) == dt.date(2024, 3, 4)


def test_date_increment_monthend_and_monthly() -> None:
    """Date increment keeps month-end semantics where requested."""
    start = dt.date(2024, 1, 31)
    assert increment_months(start, 1) == dt.date(2024, 2, 29)
    assert increment_date(start, 1, "monthend") == dt.date(2024, 2, 29)
    assert increment_date(start, 2, "monthly") == dt.date(2024, 3, 31)
