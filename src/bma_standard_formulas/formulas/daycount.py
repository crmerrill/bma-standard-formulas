# Requires Python 3.12+
"""Direct port of date/daycount utilities from cmutils.

===============================================================================
PURPOSE
===============================================================================
This file is a direct implementation port intended for parity-first review.
Function names and algorithm structure follow the cmutils source so behavior can
be compared one-to-one before any refactoring.

===============================================================================
BMA CONTEXT
===============================================================================
The most relevant references in ``docs/BMA_Calcs2.txt`` are:

- Section E.1 (Calendar Basis): 30/360 day count conventions.
- Section E.2 (Delay Days): cashflow timing shifts for yield analytics.
- Section G (Yield and Yield-Related Measures): duration/convexity calculations
  that depend on consistent day-count assumptions.

This module provides the date/day-count utilities used by those calculations.

===============================================================================
PEDAGOGICAL READING ORDER
===============================================================================
For learners reading this file top-to-bottom, the intended buildup is:

1) Calendar primitives
   ``is_leap_year``, ``days_in_year``, ``days_in_month`` and helpers.
2) Day-count numerators
   ``day_count_30_360`` / ``day_count_30_360_vector``.
3) Day-count fractions
   ``year_fraction_*`` and dispatcher ``year_fraction``.
4) Business-day adjustment
   ``next_business_day``.
5) Date stepping and schedules
   ``increment_days`` ... ``build_date_range_vector`` ... ``iter_date_range``.

This order mirrors how BMA calculations are assembled in practice:
calendar assumptions -> day counts -> year fractions -> timing schedules.
"""

import datetime
import numpy as np
import pandas as pd

# TODO: consider embeding this stuff in classes

# =============================================================================
# 1) Calendar primitives
# =============================================================================
# --BEGIN: Some extended datetime checking utilities similar to datetime.py private functions

# Utility functions, adapted from Python's native datetime.py, which
# also assumes the current Gregorian calendar indefinitely extended in
# both directions.  In general, Python datetime.py references to match
# the definition of the "proleptic Gregorian" calendar in Dershowitz
# and Reingold's "Calendrical Calculations", where it's the base calendar
# for all computations.  See the book for algorithms for converting between
# proleptic Gregorian ordinals and many other calendar systems.  For additional information
# refer to the code in the datetime.py module.

# -1 is a placeholder for indexing purposes.
_DAYS_IN_MONTH_LIST = [-1, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

_DAYS_BEFORE_MONTH_LIST = [-1]  # -1 is a placeholder for indexing purposes.
_dbm = 0
for _dim in _DAYS_IN_MONTH_LIST[1:]:
    _DAYS_BEFORE_MONTH_LIST.append(_dbm)
    _dbm += _dim
del _dbm, _dim

_DAYCOUNT_METHODS_30360 = {"NASD", "ISDA"}


def _is_scalar_date_input(value):
    """Return whether input should be treated as a scalar date.

    Args:
        value: Candidate date-like value.

    Returns:
        bool: True when ``value`` is not list-like/pandas-index-like and should
        follow scalar execution paths.
    """
    return not isinstance(value, (list, tuple, np.ndarray, pd.Series, pd.Index, pd.DatetimeIndex))


def _normalize_30360_method(method):
    """Normalize and validate 30/360 convention names.

    Args:
        method: Raw convention label. Accepted values are ``"NASD"`` and
            ``"ISDA"`` (case-insensitive). ``None`` defaults to ``"NASD"``.

    Returns:
        str: Upper-case normalized convention label.

    Raises:
        ValueError: If the provided convention is unsupported.
    """
    if method is None:
        return "NASD"
    method_ = str(method).upper()
    if method_ not in _DAYCOUNT_METHODS_30360:
        raise ValueError(f"Unsupported 30/360 method '{method}'. Expected one of {sorted(_DAYCOUNT_METHODS_30360)}.")
    return method_


def _is_feb_last_day_scalar(ts: pd.Timestamp) -> bool:
    """Return whether a scalar timestamp is February month-end.

    Args:
        ts: Timestamp to classify.

    Returns:
        bool: True when ``ts`` is the last day of February for its year.
    """
    return ts.month == 2 and ts.day == days_in_month(ts.year, ts.month)


def _days_in_month_from_datetime64(array):
    """Compute month lengths from numpy datetime arrays.

    Args:
        array: Array-like dates coercible to ``numpy.datetime64[D]``.

    Returns:
        numpy.ndarray: Integer day counts for each date's calendar month.
    """
    arr = np.array(array, dtype="datetime64[D]")
    month_start = arr.astype("datetime64[M]").astype("datetime64[D]")
    month_end = (arr.astype("datetime64[M]") + np.timedelta64(1, "M")).astype("datetime64[D]") - np.timedelta64(1, "D")
    return (month_end - month_start).astype("timedelta64[D]").astype(np.int64) + 1


def is_leap_year(year):
    """Return leap-year flags using Gregorian calendar rules.

    Args:
        year: Scalar year or numpy-compatible year array.

    Returns:
        bool | numpy.ndarray: Leap-year indicator(s), True for leap years and
        False otherwise.
    """
    # written in numpy to support vectorized array calculations
    return np.logical_and(year % 4 == 0, np.logical_or(year % 100 != 0, year % 400 == 0))


def days_in_year(year):
    """Return day count for a scalar calendar year.

    Args:
        year: Calendar year.

    Returns:
        int: 366 for leap years, otherwise 365.

    Notes:
        For array inputs, use :func:`days_in_year_vector`.
    """
    if is_leap_year(year):
        return 366
    else:
        return 365


def days_in_year_vector(array):
    """Return day counts for vectorized year inputs.

    Args:
        array: Array-like years.

    Returns:
        numpy.ndarray: Integer day counts (366 for leap year, else 365).
    """
    return np.where(is_leap_year(array), 366, 365)


def days_before_year(year):
    """Return days elapsed before January 1 of ``year``.

    Args:
        year: Calendar year.

    Returns:
        int: Number of Gregorian days before ``year-01-01`` in proleptic
        Gregorian convention.
    """
    y = year - 1
    return y * 365 + y // 4 - y // 100 + y // 400


def days_in_month(year, month):
    """Return day count for a specific year/month pair.

    Args:
        year: Calendar year.
        month: Calendar month in ``[1, 12]``.

    Returns:
        int: Number of days in the given month and year.

    Raises:
        AssertionError: If ``month`` is outside ``[1, 12]``.

    Notes:
        For vectorized inputs, use :func:`days_in_month_vector`.
    """
    assert 1 <= month <= 12, month
    if month == 2 and is_leap_year(year):
        return 29
    return _DAYS_IN_MONTH_LIST[month]


def days_in_month_vector(array):
    """Return month lengths for vectorized date inputs.

    Args:
        array: Array-like dates coercible to ``numpy.datetime64``.

    Returns:
        numpy.ndarray: Integer month lengths corresponding to each input date.
    """
    return _days_in_month_from_datetime64(array).astype("intc")


def days_before_month(year, month):
    """Return day count in ``year`` before month start.

    Args:
        year: Calendar year.
        month: Calendar month in ``[1, 12]``.

    Returns:
        int: Days elapsed in the year before the first day of ``month``.

    Raises:
        AssertionError: If ``month`` is outside ``[1, 12]``.
    """
    assert 1 <= month <= 12, "month must be in 1..12"
    return _DAYS_BEFORE_MONTH_LIST[month] + (month > 2 and is_leap_year(year))


def days_before_date_vector(array):
    """Return day-of-year offsets for vectorized dates.

    Args:
        array: Array-like dates coercible to ``numpy.datetime64[D]``.

    Returns:
        numpy.ndarray: Integer offsets measured from January 1 of each date's
        calendar year.
    """
    array = np.array(array, dtype="datetime64[D]")
    return (array - array.astype("datetime64[Y]").astype("datetime64[D]")).astype("intc")


# --END extended datetime.py date checking utilities


# =============================================================================
# 2) Day-count numerators (Section E.1)
# =============================================================================
# --BEGIN: Day Count Calculators
#
# BMA Section E.1 (Calendar Basis, SF-44) implementation note:
#   "The number of days from M1/D1/Y1 to M2/D2/Y2 on a 30/360 calendar basis
#    is computed ... N = 360*(Y2-Y1) + 30*(M2-M1) + (D2-D1)"
#
# This block implements those algebraic adjustments (NASD/BMA and ISDA variants)
# so downstream accrued-interest and yield routines share one consistent numerator.

def day_count_30_360(start_date, end_date, convention="NASD"):
    """Compute 30/360 day-count numerator for one date pair.

    BMA Reference:
        Section E.1 (Calendar Basis, SF-44), with optional ISDA adjustment mode.

    Args:
        start_date: Scalar date-like object (python datetime/date, numpy datetime,
            pandas timestamp, or parseable date string).
        end_date: Scalar date-like object.
        convention: 30/360 convention label. Supported values:
            ``"NASD"`` (BMA-style default) and ``"ISDA"``.

    Returns:
        int: 30/360 numerator ``N`` for the input interval.

    Raises:
        ValueError: If ``convention`` is unsupported.

    Notes:
        - This scalar API preserves signed behavior when ``end_date < start_date``
          (result is negative).
        - NASD branch applies BMA Section E.1 start-date adjustments
          (Feb month-end/31st handling).
        - For vectorized workloads, use :func:`day_count_30_360_vector`.
    """
    convention_ = _normalize_30360_method(convention)

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)

    # Preserve signed behavior used by common analytics libraries:
    # swap endpoints for adjustment logic, then apply sign at return.
    sign = 1
    if start_ts > end_ts:
        sign = -1
        start_ts, end_ts = end_ts, start_ts

    sd, sm, sy = start_ts.day, start_ts.month, start_ts.year
    ed, em, ey = end_ts.day, end_ts.month, end_ts.year

    if convention_ == "ISDA":
        if sd == 31:
            sd = 30
        if ed == 31 and sd == 30:
            ed = 30
    else:  # NASD / BMA-style 30/360
        # Section E.1 (BMA): if start date is end-of-February, change D1 to 30.
        if _is_feb_last_day_scalar(start_ts):
            sd = 30
        if sd == 31:
            sd = 30
        if sd == 30 and ed == 31:
            ed = 30

    datediff = (ey - sy) * 360 + (em - sm) * 30 + (ed - sd)
    return sign * datediff


def day_count_30_360_vector(start_array, end_array, convention="NASD"):
    """Compute 30/360 numerators for aligned date arrays.

    BMA Reference:
        Section E.1 (Calendar Basis, SF-44), vectorized over date pairs.

    Args:
        start_array: Array-like start dates.
        end_array: Array-like end dates (same length as ``start_array``).
        convention: 30/360 convention label (``"NASD"`` or ``"ISDA"``).

    Returns:
        numpy.ndarray: Signed integer 30/360 numerators for each input pair.

    Raises:
        ValueError: If ``start_array`` and ``end_array`` lengths differ.
        ValueError: If ``convention`` is unsupported.

    Notes:
        Signed behavior matches :func:`day_count_30_360`: intervals with
        ``end < start`` are returned as negative values.
    """
    convention_ = _normalize_30360_method(convention)
    start_arr = np.array(start_array, dtype="datetime64[D]")
    end_arr = np.array(end_array, dtype="datetime64[D]")

    if len(start_arr) != len(end_arr):
        raise ValueError("start_array and end_array must have the same length")

    sign = np.where(start_arr <= end_arr, 1, -1)
    start_ordered = np.where(sign == 1, start_arr, end_arr).astype("datetime64[D]")
    end_ordered = np.where(sign == 1, end_arr, start_arr).astype("datetime64[D]")

    start_month = start_ordered.astype("datetime64[M]")
    end_month = end_ordered.astype("datetime64[M]")

    sy = start_ordered.astype("datetime64[Y]").astype(np.int64) + 1970
    ey = end_ordered.astype("datetime64[Y]").astype(np.int64) + 1970
    sm = start_month.astype(np.int64) % 12 + 1
    em = end_month.astype(np.int64) % 12 + 1
    sd = (start_ordered - start_month.astype("datetime64[D]")).astype("timedelta64[D]").astype(np.int64) + 1
    ed = (end_ordered - end_month.astype("datetime64[D]")).astype("timedelta64[D]").astype(np.int64) + 1

    if convention_ == "ISDA":
        sd_adj = np.where(sd == 31, 30, sd)
        ed_adj = np.where((ed == 31) & (sd_adj == 30), 30, ed)
    else:  # NASD / BMA-style 30/360
        start_month_days = _days_in_month_from_datetime64(start_ordered)
        start_is_feb_eom = (sm == 2) & (sd == start_month_days)
        sd_adj = np.where(start_is_feb_eom, 30, sd)
        sd_adj = np.where(sd_adj == 31, 30, sd_adj)
        ed_adj = np.where((sd_adj == 30) & (ed == 31), 30, ed)

    datediff = (ey - sy) * 360 + (em - sm) * 30 + (ed_adj - sd_adj)
    return sign * np.asarray(datediff, dtype=np.int64)


# --END: Day Count Calculators


# =============================================================================
# 3) Day-count fractions
# =============================================================================
# --BEGIN: Day Count Fraction Calculators
#
# BMA Section E.1 + Section G linkage:
#   - E.1 defines calendar-basis numerators (30/360 and actual-day counting).
#   - G.1/G.2 define yield quoting/discounting bases (Bond-Equivalent 30/360 and
#     Money-Market ACTUAL/360).
#
# These functions convert day-count numerators into year fractions consumed by
# pricing/yield analytics.

def year_fraction_30_360(start_date, end_date, convention="NASD"):
    """Compute year fraction under 30/360 convention.

    Args:
        start_date: Scalar or array-like start date(s).
        end_date: Scalar or array-like end date(s).
        convention: 30/360 convention label (``"NASD"`` or ``"ISDA"``).

    Returns:
        float | numpy.ndarray: Year fraction(s) computed as
        ``day_count_30_360(...) / 360``.
    """
    if _is_scalar_date_input(start_date) and _is_scalar_date_input(end_date):
        num = day_count_30_360(start_date, end_date, convention=convention)
    else:
        num = day_count_30_360_vector(start_date, end_date, convention=convention)
    return num / 360


def year_fraction_30_360_fnma(start_date, end_date, convention="NASD"):
    """Compute FNMA split year fraction from 30/360 numerator.

    Args:
        start_date: Scalar or array-like start date(s).
        end_date: Scalar or array-like end date(s).
        convention: 30/360 convention used for numerator ``N``.

    Returns:
        float | numpy.ndarray: FNMA split fraction
        ``(N // 30)/360 + (N % 30)/365`` where ``N`` is the 30/360 day count.
    """
    if _is_scalar_date_input(start_date) and _is_scalar_date_input(end_date):
        num = day_count_30_360(start_date, end_date, convention=convention)
    else:
        num = day_count_30_360_vector(start_date, end_date, convention=convention)
    return (num // 30) / 360 + (num % 30) / 365


def year_fraction_actual_360(start_date, end_date, convention=None):
    """Compute Actual/360 year fraction.

    BMA context:
        Section E.1 states Money-Market accounting uses actual day counts over a
        360-day denominator. Section G.2 applies this basis for instruments quoted
        on ACTUAL/360.

    Formula:
        year_fraction = actual_days(start_date, end_date) / 360

    Args:
        start_date: Scalar or array-like start date(s).
        end_date: Scalar or array-like end date(s).
        convention: Unused (kept for dispatcher signature consistency).

    Returns:
        float | numpy.ndarray: Actual-day numerator divided by 360.

    Notes:
        - Scalar inputs return ``float``.
        - Array-like inputs return ``numpy.ndarray`` of floats.
        - Signed behavior is preserved (``end < start`` gives negative fraction).
    """
    if _is_scalar_date_input(start_date) and _is_scalar_date_input(end_date):
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        num_days = float((end_ts - start_ts) / pd.Timedelta(days=1))
    else:
        start_arr = np.array(start_date, dtype="datetime64[ns]")
        end_arr = np.array(end_date, dtype="datetime64[ns]")
        num_days = (end_arr - start_arr) / np.timedelta64(1, "D")
    return num_days / 360.0


def year_fraction_actual_365(start_date, end_date, convention=None):
    """Compute Actual/365 (fixed denominator) year fraction.

    Formula:
        year_fraction = actual_days(start_date, end_date) / 365

    Args:
        start_date: Scalar or array-like start date(s).
        end_date: Scalar or array-like end date(s).
        convention: Unused (kept for dispatcher signature consistency).

    Returns:
        float | numpy.ndarray: Actual-day numerator divided by 365.

    Notes:
        - Scalar inputs return ``float``.
        - Array-like inputs return ``numpy.ndarray`` of floats.
        - Signed behavior is preserved (``end < start`` gives negative fraction).
    """
    if _is_scalar_date_input(start_date) and _is_scalar_date_input(end_date):
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        num_days = float((end_ts - start_ts) / pd.Timedelta(days=1))
    else:
        start_arr = np.array(start_date, dtype="datetime64[ns]")
        end_arr = np.array(end_date, dtype="datetime64[ns]")
        num_days = (end_arr - start_arr) / np.timedelta64(1, "D")
    return num_days / 365.0


def year_fraction_actual_actual(start_date, end_date, convention="ISDA"):
    """Compute Actual/Actual year fraction.

    Args:
        start_date: Scalar or array-like start date(s).
        end_date: Scalar or array-like end date(s).
        convention: Day-count convention label. Currently only ``"ISDA"``
            is supported.

    Returns:
        float | numpy.ndarray: Actual/Actual year fraction(s) computed as
        sum(days in leap years / 366 + days in normal years / 365) using
        ``[start, end)`` interval convention.

    Raises:
        ValueError: If ``convention`` is not ``"ISDA"``.
        ValueError: If vector inputs have mismatched lengths.

    Notes:
        BMA Section G requires calendar-basis consistency when computing/comparing
        floating-rate yield measures. This implementation makes the ACT/ACT basis
        explicit so callers can avoid accidental basis mixing.
    """
    method_ = str(convention).upper()
    if method_ != "ISDA":
        raise ValueError("Only convention='ISDA' is currently supported for year_fraction_actual_actual")

    def _actact_isda_scalar(start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> float:
        """Compute one scalar Act/Act ISDA fraction on [start, end)."""
        if start_ts == end_ts:
            return 0.0
        if end_ts < start_ts:
            return -_actact_isda_scalar(end_ts, start_ts)
        if start_ts.year == end_ts.year:
            return (end_ts - start_ts).days / days_in_year(start_ts.year)

        start_of_next_year = pd.Timestamp(year=start_ts.year + 1, month=1, day=1)
        start_of_end_year = pd.Timestamp(year=end_ts.year, month=1, day=1)
        frac_first = (start_of_next_year - start_ts).days / days_in_year(start_ts.year)
        frac_middle = max(end_ts.year - start_ts.year - 1, 0)
        frac_last = (end_ts - start_of_end_year).days / days_in_year(end_ts.year)
        return frac_first + frac_middle + frac_last

    if _is_scalar_date_input(start_date) and _is_scalar_date_input(end_date):
        return _actact_isda_scalar(pd.Timestamp(start_date), pd.Timestamp(end_date))

    start_idx = pd.DatetimeIndex(start_date)
    end_idx = pd.DatetimeIndex(end_date)
    if len(start_idx) != len(end_idx):
        raise ValueError("start_date and end_date arrays must have the same length for act/act")
    return np.array(
        [_actact_isda_scalar(pd.Timestamp(s), pd.Timestamp(e)) for s, e in zip(start_idx, end_idx)],
        dtype=float,
    )


def year_fraction(start_date, end_date, convention):
    """Dispatch to a named year-fraction convention.

    Args:
        start_date: Scalar or array-like start date(s).
        end_date: Scalar or array-like end date(s).
        convention: Convention key. Supported values:
            ``"30/360 NASD"``, ``"30/360 ISDA"``, ``"30/360 FNMA"``,
            ``"act/360"``, ``"act/365"``, ``"act/act"``.

    Returns:
        float | numpy.ndarray: Year fraction(s) from the selected convention.

    Raises:
        ValueError: If ``convention`` is unsupported.
    """
    __DAYFRAC_FUNC_DICT = {
        "30/360 NASD": (year_fraction_30_360, "NASD"),
        "30/360 ISDA": (year_fraction_30_360, "ISDA"),
        "30/360 FNMA": (year_fraction_30_360_fnma, "NASD"),
        "act/360": (year_fraction_actual_360, None),
        "act/365": (year_fraction_actual_365, None),
        "act/act": (year_fraction_actual_actual, "ISDA"),
    }
    if convention not in __DAYFRAC_FUNC_DICT:
        raise ValueError(
            f"Unsupported day-fraction convention '{convention}'. Expected one of {sorted(__DAYFRAC_FUNC_DICT)}."
        )
    func, func_method = __DAYFRAC_FUNC_DICT[convention]
    return func(start_date, end_date, func_method)


# --END: Day Count Fraction Calculators


# =============================================================================
# 4) Business-day adjustment
# =============================================================================
# --BEGIN: Next Business Day Logic
#
# BMA Section E.2 (Delay Days, SF-44) context:
#   Delay is the time from accrual-period end to investor payment date, and BMA
#   emphasizes "actual delay" disclosure/use. This module does not compute delay
#   days directly, but business-day roll and date stepping utilities below are
#   the calendar primitives used to assemble payment-date timing assumptions.

# in general array based datetime calcs for arrays should be done in numpy and single datetimes in native python.
# Other features such as pandas are here to ensure compatability with pandas indicies.
def next_business_day(date):
    """Roll date(s) forward to the next business day (weekend-only calendar).

    Args:
        date: Scalar date-like object or array-like dates (numpy/pandas).

    Returns:
        Same type family as input with weekend dates moved to Monday.

    Notes:
        - Business-day logic is weekend-only (no holiday calendar).
        - Numpy array path uses ``numpy.busday_offset`` for speed.
    """

    # NUMPY IMPLEMENTATION
    if type(date) == np.datetime64 or type(date) == np.ndarray:
        return np.busday_offset(date, 0, roll="forward")
    # PANDAS DATE INDEX IMPLEMENTATION.  THERE IS NO DATAFRAME IMPLEMENTATION!
    # this implementation is here for pandas for compatability.  It should be avoided because it is extremely slow
    # for example the elif below will take 10x as long as the above statement for numpy
    elif type(date) == pd.core.indexes.datetimes.DatetimeIndex or type(date) == pd.core.series.Series:
        _type = type(date)
        return _type((np.busday_offset((np.array(date).astype("datetime64[D]")), 0, roll="forward")))
    # ORDINARY DATETIME IMPLEMENTATION
    else:
        if date.weekday() == 5:
            return date + pd.Timedelta(2, unit="d")
        elif date.weekday() == 6:
            return date + pd.Timedelta(1, unit="d")
        else:
            return date


# --END: Next Business Day Logic


# =============================================================================
# 5) Date increment functions
# =============================================================================
# --BEGIN: Time Increment Functions
#
# Timing-construction helpers:
#   These functions build accrual/payment schedules used by settlement/yield
#   workflows (Sections F/G), where time exponents T_k depend on date spacing
#   plus delay assumptions.

def increment_days(start_date: datetime.date, inc_amt: int, busday=False) -> datetime.date:
    """Increment a date by day count, optionally rolling to business day.

    Args:
        start_date: Starting date.
        inc_amt: Number of calendar days to add (can be negative).
        busday: If True, roll result through :func:`next_business_day`.

    Returns:
        datetime.date | pandas.Timestamp: Incremented date.
    """
    end_date = start_date + datetime.timedelta(days=inc_amt)
    if busday:
        return next_business_day(end_date)
    else:
        return end_date


def increment_weeks(start_date: datetime.date, inc_amt: int, busday=False) -> datetime.date:
    """Increment a date by week count, optionally rolling to business day.

    Args:
        start_date: Starting date.
        inc_amt: Number of calendar weeks to add (can be negative).
        busday: If True, roll result through :func:`next_business_day`.

    Returns:
        datetime.date | pandas.Timestamp: Incremented date.
    """
    end_date = start_date + datetime.timedelta(weeks=inc_amt)
    if busday:
        return next_business_day(end_date)
    else:
        return end_date


def increment_months(start_date, inc_amt, busday=False):
    """Increment date by whole months with end-of-month clipping.

    Args:
        start_date: Starting date.
        inc_amt: Number of months to add (can be negative).
        busday: If True, roll result through :func:`next_business_day`.

    Returns:
        datetime.date | pandas.Timestamp: Incremented date where day-of-month is
        clipped to target month length.
    """
    end_year = (start_date.year + ((start_date.month + inc_amt - 1) // 12))
    end_month = ((start_date.month + inc_amt - 1) % 12 + 1)
    end_day = min(start_date.day, days_in_month(end_year, end_month))
    end_date = datetime.date(end_year, end_month, end_day)
    del (end_year, end_month, end_day)
    if busday:
        return next_business_day(end_date)
    else:
        return end_date


def increment_month_end(start_date: datetime.date, inc_amt=0, busday=False) -> datetime.date:
    """Increment to target month, then set to month-end.

    Args:
        start_date: Starting date.
        inc_amt: Number of months to shift before month-end snap.
        busday: If True, roll month-end date through :func:`next_business_day`.

    Returns:
        datetime.date | pandas.Timestamp: Month-end date after shift.
    """
    _advDate = increment_months(start_date, inc_amt, busday)
    _endDate = datetime.date(_advDate.year, _advDate.month, days_in_month(_advDate.year, _advDate.month))
    if busday:
        return next_business_day(_endDate)
    else:
        return _endDate


def increment_month_mid(start_date: datetime.date, inc_amt=0, busday=False) -> datetime.date:
    """Increment to target month, then set to the 15th.

    Args:
        start_date: Starting date.
        inc_amt: Number of months to shift before mid-month snap.
        busday: If True, roll resulting date through :func:`next_business_day`.

    Returns:
        datetime.date | pandas.Timestamp: Mid-month date after shift.
    """
    _advDate = increment_months(start_date, inc_amt, busday)
    _endDate = datetime.date(_advDate.year, _advDate.month, 15)
    if busday:
        return next_business_day(_endDate)
    else:
        return _endDate


def increment_quarters(start_date, inc_amt, busday=False):
    """Increment date by whole quarters.

    Args:
        start_date: Starting date.
        inc_amt: Number of quarters to add.
        busday: If True, roll result through :func:`next_business_day`.

    Returns:
        datetime.date | pandas.Timestamp: Incremented date.
    """
    return increment_months(start_date, inc_amt * 3, busday)


def increment_semiannual(start_date, inc_amt, busday=False):
    """Increment date by semiannual periods.

    Args:
        start_date: Starting date.
        inc_amt: Number of half-year periods to add.
        busday: If True, roll result through :func:`next_business_day`.

    Returns:
        datetime.date | pandas.Timestamp: Incremented date.
    """
    return increment_months(start_date, inc_amt * 6, busday)


def increment_years(start_date, inc_amt, busday=False):
    """Increment date by whole years with month-length clipping.

    Args:
        start_date: Starting date.
        inc_amt: Number of years to add (can be negative).
        busday: If True, roll result through :func:`next_business_day`.

    Returns:
        datetime.date | pandas.Timestamp: Incremented date.
    """
    end_year = start_date.year + inc_amt
    end_month = start_date.month
    end_day = min(start_date.day, days_in_month(end_year, end_month))
    end_date = datetime.date(end_year, end_month, end_day)
    # del (end_year, end_month, end_day)
    if busday:
        return next_business_day(end_date)
    else:
        return end_date


# --END: Time Increment Functions


# =============================================================================
# 6) Date range builders
# =============================================================================
# --BEGIN: Date Range Creator
#
# Section G connection:
#   G.1 defines yield equations using cash-flow times T_k (years from settlement)
#   on a chosen calendar basis. The range builders here generate the discrete
#   schedule backbone from which those time points are derived elsewhere.

# Dictionary of increment functions that can be used.
__INCREMENT_FUNC_DICT = {"daily": (increment_days, "datetime64[D]"),
                         "weekly": (increment_weeks, "datetime64[W]"),
                         "monthly": (increment_months, "datetime64[M]"),
                         "monthend": (increment_month_end, "datetime64[M]"),
                         "monthmid": (increment_month_mid, "datetime64[M]"),
                         "quarterly": (increment_quarters, "datetime64[M]"),
                         "semiannual": (increment_semiannual, "datetime64[M]"),
                         "annual": (increment_years, "datetime64[M]")}


def increment_date(start_date, periods, increment_type, weekday_only=False):
    """Apply one named increment operation to a starting date.

    Args:
        start_date: Starting date.
        periods: Number of increment units.
        increment_type: Increment key in
            ``{"daily","weekly","monthly","monthend","monthmid","quarterly","semiannual","annual"}``.
        weekday_only: If True, roll output through :func:`next_business_day`.

    Returns:
        datetime.date | pandas.Timestamp: Incremented date.

    Raises:
        KeyError: If ``increment_type`` is unsupported.
    """
    return __INCREMENT_FUNC_DICT[increment_type][0](start_date, periods, weekday_only)


def build_date_range_vector(start_date, periods, increment_type, weekday_only=False):
    """Construct schedule dates using cmutils-compatible vector semantics.

    Args:
        start_date: Starting date.
        periods: Number of increment units to span.
        increment_type: Increment key accepted by :func:`increment_date`.
        weekday_only: If True, apply :func:`next_business_day` to final vector.

    Returns:
        numpy.ndarray: Date vector in numpy datetime64 dtype family.

    Notes:
        Preserves legacy branch logic for month-end, month-mid, and 29/30/31
        day-of-month behavior to maintain schedule parity.
    """
    # TODO: Fix the daily date range generator w/ business days so that it doesn't repeat days.
    _dateRange = np.arange(start_date, __INCREMENT_FUNC_DICT[increment_type][0](start_date, periods, weekday_only), dtype=__INCREMENT_FUNC_DICT[increment_type][1])
    # Logic for dealing with dates where increments are greater than monthly.  Three cases:
    if not (increment_type == "daily" or increment_type == "weekly"):
        #   (1) Days are not 29, 30, 31 so no need to worry about leap year or how many dates a month has
        #   (2) Using mid month convention, so always use the 15th after the first date
        #   (3) Using month end steps, so always need to grab the last day
        #   (4) using 29, 30, 31 so need to grab the lesser of the actual date or the maximum dates in a month
        # CASE 1
        if start_date.day < 29 and increment_type != "monthend" and increment_type != "monthmid":
            _dateRange = _dateRange + np.timedelta64(start_date.day - 1, "D")
        # CASE 2
        elif increment_type == "monthmid":
            _dateRange = _dateRange + (lambda x: 1 if x > 15 else 0)(start_date.day) * np.timedelta64(1, "M") + np.timedelta64(14, "D")
        # CASES 3, 4
        else:
            _yearVector = [dt.year for dt in _dateRange.astype(object)]
            _monthVector = [dt.month for dt in _dateRange.astype(object)]
            _dateAdder = np.empty(len(_dateRange), dtype="<m8[D]")
            # CASE 3
            if increment_type == "monthend":
                for i in range(0, len(_dateRange)):
                    _dateAdder[i] = np.timedelta64(days_in_month(_yearVector[i], _monthVector[i]) - 1, "D")
            # CASE 4
            else:
                for i in range(0, len(_dateRange)):
                    _dateAdder[i] = np.timedelta64(min(start_date.day, days_in_month(_yearVector[i], _monthVector[i])) - 1, "D")
            _dateRange = _dateRange + _dateAdder
    # Do the business day logics
    if weekday_only is True:
        _dateRange = next_business_day(_dateRange)
    # Give the final answer
    return _dateRange


def iter_date_range(start_date, end_date, increment_type, weekday_only=False):
    """Yield dates from ``start_date`` to ``end_date`` by named increments.

    Args:
        start_date: First yielded date.
        end_date: Upper bound (inclusive).
        increment_type: Increment key accepted by :func:`increment_date`.
        weekday_only: If True, apply :func:`next_business_day` each step.

    Yields:
        datetime.date | pandas.Timestamp: Sequential schedule dates.

    Notes:
        This generator preserves cmutils stepping semantics.
    """
    try:
        date_iter = start_date
        while date_iter <= end_date:
            yield date_iter
            date_iter = increment_date(date_iter, 1, increment_type, weekday_only)
        return
    except Exception:
        print("iter_date_range inputs not correctly specified")


# END: Date Range Creator
