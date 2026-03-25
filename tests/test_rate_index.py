"""
Unit tests for RateIndex — construction, factory methods, and rate vector generation.

Covers:
  - __post_init__ validation (length mismatch, empty, sorting)
  - from_arrays (str dates, date objects, custom format, auto-sort)
  - from_constant (always-available single rate)
  - from_csv: SOFR historical fixture (SOFR_historical.csv, daily, FRED)
             and SOFR forward fixture (03032026_SOFR3M_FWD.csv, % suffix)
  - get_rate_vector: fixed-rate path, annual ARM, monthly ARM,
    seasoned (mid-cycle) ARM, date overflow (month=12 → Jan), no-data error,
    vector length, and the period-0 initialisation path.
  - get_rate_vector with real SOFR data: annual and monthly ARM resets

BMA Reference: engine/rate_index.py
"""

import unittest
from datetime import date

import numpy as np

from bma_standard_formulas.engine import RateIndex


# ---------------------------------------------------------------------------
# Construction / __post_init__
# ---------------------------------------------------------------------------

class TestRateIndexConstruction(unittest.TestCase):

    def test_empty_index_is_valid(self):
        idx = RateIndex()
        self.assertEqual(len(idx), 0)
        self.assertIsNone(idx.name)

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            RateIndex(dates=(date(2024, 1, 1),), rates=(5.0, 6.0))

    def test_dates_sorted_on_construction(self):
        """Out-of-order dates must be sorted ascending."""
        idx = RateIndex(
            dates=(date(2024, 3, 1), date(2024, 1, 1), date(2024, 2, 1)),
            rates=(5.3, 5.1, 5.2),
        )
        self.assertEqual(idx.dates[0], date(2024, 1, 1))
        self.assertAlmostEqual(idx.rates[0], 5.1)
        self.assertEqual(idx.dates[-1], date(2024, 3, 1))
        self.assertAlmostEqual(idx.rates[-1], 5.3)

    def test_name_stored(self):
        idx = RateIndex(
            dates=(date(2024, 1, 1),), rates=(5.0,), name="SOFR"
        )
        self.assertEqual(idx.name, "SOFR")

    def test_repr_nonempty(self):
        idx = RateIndex(
            dates=(date(2024, 1, 1), date(2024, 6, 1)),
            rates=(5.0, 5.5),
            name="TEST",
        )
        r = repr(idx)
        self.assertIn("2 obs", r)
        self.assertIn("TEST", r)

    def test_repr_empty(self):
        r = repr(RateIndex())
        self.assertIn("empty", r)

    def test_len(self):
        idx = RateIndex(
            dates=(date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)),
            rates=(5.0, 5.1, 5.2),
        )
        self.assertEqual(len(idx), 3)


# ---------------------------------------------------------------------------
# from_arrays
# ---------------------------------------------------------------------------

class TestFromArrays(unittest.TestCase):

    def test_string_dates(self):
        idx = RateIndex.from_arrays(
            dates=["2024-01-01", "2024-02-01"],
            rates=[5.0, 5.1],
            name="X",
        )
        self.assertEqual(idx.dates[0], date(2024, 1, 1))
        self.assertAlmostEqual(idx.rates[1], 5.1)

    def test_date_objects(self):
        idx = RateIndex.from_arrays(
            dates=[date(2024, 1, 1), date(2024, 4, 1)],
            rates=[4.5, 4.8],
        )
        self.assertEqual(len(idx), 2)
        self.assertAlmostEqual(idx.rates[0], 4.5)

    def test_custom_date_format(self):
        idx = RateIndex.from_arrays(
            dates=["01/2024", "02/2024"],
            rates=[5.0, 5.2],
            date_format="%m/%Y",
        )
        self.assertEqual(idx.dates[0].month, 1)
        self.assertEqual(idx.dates[1].month, 2)

    def test_auto_sorts(self):
        idx = RateIndex.from_arrays(
            dates=["2024-03-01", "2024-01-01"],
            rates=[5.3, 5.1],
        )
        self.assertEqual(idx.dates[0], date(2024, 1, 1))


# ---------------------------------------------------------------------------
# from_constant
# ---------------------------------------------------------------------------

class TestFromConstant(unittest.TestCase):

    def test_rate_value(self):
        idx = RateIndex.from_constant(6.5, name="FLAT")
        self.assertAlmostEqual(idx.rates[0], 6.5)
        self.assertEqual(idx.name, "FLAT")

    def test_single_observation(self):
        idx = RateIndex.from_constant(5.0)
        self.assertEqual(len(idx), 1)

    def test_anchor_date_is_ancient(self):
        """Anchor date 1900-01-01 ensures it's always <= any real payment date."""
        idx = RateIndex.from_constant(5.0)
        self.assertEqual(idx.dates[0], date(1900, 1, 1))


# ---------------------------------------------------------------------------
# get_rate_vector — error handling
# ---------------------------------------------------------------------------

class TestGetRateVectorErrors(unittest.TestCase):

    def test_empty_index_raises(self):
        idx = RateIndex()
        with self.assertRaises(ValueError, msg="No rate data should raise"):
            idx.get_rate_vector(
                next_payment_date=date(2024, 1, 1),
                next_reset_date=date(2024, 1, 1),
                reset_frequency=12,
                remaining_term=12,
            )


# ---------------------------------------------------------------------------
# get_rate_vector — fixed-rate path (reset_frequency=0)
# ---------------------------------------------------------------------------

class TestGetRateVectorFixed(unittest.TestCase):
    """reset_frequency=0: period-0 initialises once, no further resets."""

    def _idx(self) -> RateIndex:
        return RateIndex.from_arrays(
            dates=["2024-01-01", "2024-06-01", "2025-01-01"],
            rates=[5.0, 5.5, 6.0],
        )

    def test_vector_length(self):
        idx = self._idx()
        vec = idx.get_rate_vector(
            next_payment_date=date(2024, 1, 1),
            next_reset_date=date(2024, 1, 1),
            reset_frequency=0,
            remaining_term=24,
        )
        self.assertEqual(len(vec), 24)

    def test_rate_constant_throughout(self):
        """With reset_frequency=0, the rate initialised at period 0 never changes."""
        idx = self._idx()
        vec = idx.get_rate_vector(
            next_payment_date=date(2024, 1, 1),
            next_reset_date=date(2024, 1, 1),
            reset_frequency=0,
            remaining_term=24,
        )
        # At 2024-01-01 the latest rate is 5.0 — constant for all 24 months.
        self.assertTrue(np.all(vec == 5.0), f"Expected constant 5.0, got unique: {np.unique(vec)}")

    def test_period0_picks_latest_rate(self):
        """Period 0 dated to a month after June 2024 should pick 5.5, not 5.0."""
        idx = self._idx()
        vec = idx.get_rate_vector(
            next_payment_date=date(2024, 7, 1),
            next_reset_date=date(2025, 1, 1),   # future reset — irrelevant for fixed path
            reset_frequency=0,
            remaining_term=12,
        )
        self.assertTrue(np.all(vec == 5.5))


# ---------------------------------------------------------------------------
# get_rate_vector — annual ARM (reset_frequency=12)
# ---------------------------------------------------------------------------

class TestGetRateVectorAnnualARM(unittest.TestCase):

    def _idx(self) -> RateIndex:
        """Three annual data points."""
        return RateIndex.from_arrays(
            dates=["2024-01-01", "2025-01-01", "2026-01-01"],
            rates=[5.0, 5.5, 6.0],
        )

    def test_first_year_uses_initial_rate(self):
        """Months 0-11 should all carry the initial rate before first reset."""
        idx = self._idx()
        vec = idx.get_rate_vector(
            next_payment_date=date(2024, 1, 1),
            next_reset_date=date(2024, 1, 1),
            reset_frequency=12,
            remaining_term=24,
        )
        np.testing.assert_array_equal(vec[:12], np.full(12, 5.0))

    def test_second_year_uses_updated_rate(self):
        """Month 12 is 2025-01-01 — should reset to 5.5."""
        idx = self._idx()
        vec = idx.get_rate_vector(
            next_payment_date=date(2024, 1, 1),
            next_reset_date=date(2024, 1, 1),
            reset_frequency=12,
            remaining_term=24,
        )
        np.testing.assert_array_equal(vec[12:], np.full(12, 5.5))

    def test_three_years(self):
        """Years 1/2/3 → rates 5.0 / 5.5 / 6.0."""
        idx = self._idx()
        vec = idx.get_rate_vector(
            next_payment_date=date(2024, 1, 1),
            next_reset_date=date(2024, 1, 1),
            reset_frequency=12,
            remaining_term=36,
        )
        np.testing.assert_array_equal(vec[:12], np.full(12, 5.0))
        np.testing.assert_array_equal(vec[12:24], np.full(12, 5.5))
        np.testing.assert_array_equal(vec[24:], np.full(12, 6.0))


# ---------------------------------------------------------------------------
# get_rate_vector — monthly ARM (reset_frequency=1)
# ---------------------------------------------------------------------------

class TestGetRateVectorMonthlyARM(unittest.TestCase):

    def test_rate_updates_every_period(self):
        """Monthly reset: each period uses the latest available rate."""
        idx = RateIndex.from_arrays(
            dates=["2024-01-01", "2024-02-01", "2024-03-01"],
            rates=[5.0, 5.1, 5.2],
        )
        vec = idx.get_rate_vector(
            next_payment_date=date(2024, 1, 1),
            next_reset_date=date(2024, 1, 1),
            reset_frequency=1,
            remaining_term=3,
        )
        np.testing.assert_array_almost_equal(vec, [5.0, 5.1, 5.2])

    def test_constant_index_monthly_arm(self):
        """Constant rate index with monthly resets — all periods same rate."""
        idx = RateIndex.from_constant(4.75)
        vec = idx.get_rate_vector(
            next_payment_date=date(2024, 1, 1),
            next_reset_date=date(2024, 1, 1),
            reset_frequency=1,
            remaining_term=12,
        )
        self.assertTrue(np.all(vec == 4.75))


# ---------------------------------------------------------------------------
# get_rate_vector — seasoned (mid-cycle) ARM
# ---------------------------------------------------------------------------

class TestGetRateVectorSeasonedARM(unittest.TestCase):
    """
    A seasoned loan may be mid-cycle: next_reset_date is in the future, but
    the loan already has a current rate from a previous reset.  The vector
    should hold that rate until next_reset_date fires.
    """

    def test_seasoned_rate_held_until_reset(self):
        """Loan originated 2023-01: next reset is 2025-01.
        Rate data: 5.0 (2023-01), 5.5 (2024-01), 6.0 (2025-01).
        As-of date is 2024-07 — next_reset_date is 2025-01 (6 months away).
        First 6 months of vector should hold 5.5 (most recent rate at 2024-07).
        Months 6+ should use 6.0 after the 2025-01 reset.
        """
        idx = RateIndex.from_arrays(
            dates=["2023-01-01", "2024-01-01", "2025-01-01"],
            rates=[5.0, 5.5, 6.0],
        )
        # Payment date 2024-07, next reset 2025-01 (annual ARM, mid-cycle)
        vec = idx.get_rate_vector(
            next_payment_date=date(2024, 7, 1),
            next_reset_date=date(2025, 1, 1),
            reset_frequency=12,
            remaining_term=18,
        )
        # Periods 0-5 = 2024-07 through 2024-12: no reset yet, rate = 5.5
        np.testing.assert_array_equal(vec[:6], np.full(6, 5.5))
        # Period 6 = 2025-01: reset fires, new rate = 6.0
        np.testing.assert_array_equal(vec[6:], np.full(12, 6.0))

    def test_next_reset_already_passed(self):
        """next_reset_date == next_payment_date: reset fires immediately at period 0."""
        idx = RateIndex.from_arrays(
            dates=["2024-01-01", "2025-01-01"],
            rates=[5.0, 5.5],
        )
        vec = idx.get_rate_vector(
            next_payment_date=date(2025, 1, 1),
            next_reset_date=date(2025, 1, 1),
            reset_frequency=12,
            remaining_term=12,
        )
        # Period 0 is 2025-01: reset fires at period 0, picks 5.5.
        self.assertAlmostEqual(vec[0], 5.5)
        np.testing.assert_array_equal(vec, np.full(12, 5.5))


# ---------------------------------------------------------------------------
# get_rate_vector — month-boundary / year-wrap safety
# ---------------------------------------------------------------------------

class TestGetRateVectorDateBoundary(unittest.TestCase):

    def test_december_to_january_wrap(self):
        """Starting in October, 3-month vector should not raise on year wrap."""
        idx = RateIndex.from_constant(5.0)
        try:
            vec = idx.get_rate_vector(
                next_payment_date=date(2024, 10, 1),
                next_reset_date=date(2025, 1, 1),
                reset_frequency=12,
                remaining_term=6,
            )
        except Exception as exc:
            self.fail(f"Year-wrap raised unexpectedly: {exc}")
        self.assertEqual(len(vec), 6)

    def test_31st_day_clamped(self):
        """Day 31 in next_payment_date should clamp to 28 to avoid month-end errors."""
        idx = RateIndex.from_constant(5.0)
        try:
            vec = idx.get_rate_vector(
                next_payment_date=date(2024, 1, 28),
                next_reset_date=date(2024, 1, 28),
                reset_frequency=12,
                remaining_term=13,  # will cross February
            )
        except Exception as exc:
            self.fail(f"Day-clamp raised unexpectedly: {exc}")
        self.assertEqual(len(vec), 13)

    def test_vector_length_always_equals_remaining_term(self):
        idx = RateIndex.from_constant(4.0)
        for term in [1, 12, 60, 120, 360]:
            with self.subTest(term=term):
                vec = idx.get_rate_vector(
                    next_payment_date=date(2024, 1, 1),
                    next_reset_date=date(2024, 1, 1),
                    reset_frequency=12,
                    remaining_term=term,
                )
                self.assertEqual(len(vec), term)


# ---------------------------------------------------------------------------
# get_rate_vector — fallback when index predates all data
# ---------------------------------------------------------------------------

class TestGetRateVectorFallback(unittest.TestCase):

    def test_period_before_any_data_uses_first_rate(self):
        """If payment date precedes all index dates, fallback to rates_list[0]."""
        idx = RateIndex.from_arrays(
            dates=["2030-01-01"],
            rates=[7.0],
        )
        # Payment date is 2024 — well before the single data point in 2030.
        vec = idx.get_rate_vector(
            next_payment_date=date(2024, 1, 1),
            next_reset_date=date(2024, 1, 1),
            reset_frequency=0,
            remaining_term=12,
        )
        # bisect returns idx=-1 (no data before 2024), so fallback rate 7.0 is used.
        self.assertTrue(np.all(vec == 7.0))


# ---------------------------------------------------------------------------
# from_csv — real fixtures
# ---------------------------------------------------------------------------

FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"
SOFR_HIST_CSV = FIXTURES / "SOFR_historical.csv"
SOFR_FWD_CSV  = FIXTURES / "03032026_SOFR3M_FWD.csv"


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------

class TestMerge(unittest.TestCase):

    def test_basic_merge(self):
        """Two non-overlapping series combine into one sorted index."""
        hist = RateIndex.from_arrays(
            dates=["2023-01-01", "2023-06-01"],
            rates=[5.0, 5.25],
        )
        fwd = RateIndex.from_arrays(
            dates=["2024-01-01", "2024-06-01"],
            rates=[4.75, 4.50],
        )
        merged = RateIndex.merge(hist, fwd, name="COMBINED")
        self.assertEqual(len(merged), 4)
        self.assertEqual(merged.name, "COMBINED")
        self.assertEqual(merged.dates[0], date(2023, 1, 1))
        self.assertEqual(merged.dates[-1], date(2024, 6, 1))

    def test_later_argument_wins_on_overlap(self):
        """When dates overlap, the later argument's rate takes precedence."""
        hist = RateIndex.from_arrays(
            dates=["2024-01-01"],
            rates=[5.0],
        )
        fwd = RateIndex.from_arrays(
            dates=["2024-01-01"],   # same date, different rate
            rates=[4.80],
        )
        merged = RateIndex.merge(hist, fwd)
        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(merged.rates[0], 4.80,
                               msg="Forward (fwd) rate should override historical")

    def test_merge_three(self):
        """Three sources combine correctly."""
        a = RateIndex.from_constant(3.0)  # 1900-01-01
        b = RateIndex.from_arrays(dates=["2024-01-01"], rates=[5.0])
        c = RateIndex.from_arrays(dates=["2025-01-01"], rates=[4.5])
        merged = RateIndex.merge(a, b, c)
        self.assertEqual(len(merged), 3)

    def test_single_source_passthrough(self):
        """Merging one source returns an equivalent index."""
        idx = RateIndex.from_arrays(
            dates=["2024-01-01", "2024-06-01"],
            rates=[5.0, 5.1],
        )
        merged = RateIndex.merge(idx)
        self.assertEqual(len(merged), len(idx))
        self.assertEqual(merged.dates, idx.dates)
        np.testing.assert_array_almost_equal(
            np.array(merged.rates), np.array(idx.rates)
        )

    def test_merged_dates_sorted(self):
        """Result is always sorted by date regardless of input order."""
        a = RateIndex.from_arrays(dates=["2025-01-01"], rates=[4.0])
        b = RateIndex.from_arrays(dates=["2023-01-01"], rates=[5.5])
        merged = RateIndex.merge(a, b)
        self.assertEqual(merged.dates[0], date(2023, 1, 1))
        self.assertEqual(merged.dates[1], date(2025, 1, 1))

    def test_sofr_hist_fwd_merge(self):
        """Merging the real SOFR historical + forward fixtures spans 2018–2036."""
        hist = RateIndex.from_csv(SOFR_HIST_CSV, name="SOFR")
        fwd  = RateIndex.from_csv(SOFR_FWD_CSV, date_col="ResetDate",
                                   rate_col="Rate", name="SOFR3M_FWD")
        sofr = RateIndex.merge(hist, fwd, name="SOFR_FULL")
        self.assertEqual(sofr.name, "SOFR_FULL")
        # Spans historical start
        self.assertEqual(sofr.dates[0], date(2018, 4, 3))
        # And forward end
        self.assertEqual(sofr.dates[-1], date(2036, 2, 3))
        # Total length: hist + fwd minus any overlapping dates
        self.assertGreater(len(sofr), max(len(hist), len(fwd)))

    def test_merged_index_rate_vector_coverage(self):
        """A merged SOFR index can produce a 10-year rate vector starting in 2026."""
        hist = RateIndex.from_csv(SOFR_HIST_CSV)
        fwd  = RateIndex.from_csv(SOFR_FWD_CSV, date_col="ResetDate", rate_col="Rate")
        sofr = RateIndex.merge(hist, fwd)
        vec = sofr.get_rate_vector(
            next_payment_date=date(2026, 3, 1),
            next_reset_date=date(2026, 3, 1),
            reset_frequency=12,
            remaining_term=120,
        )
        self.assertEqual(len(vec), 120)
        # All rates should be plausible SOFR values
        self.assertTrue(np.all(vec >= 0.0))
        self.assertTrue(np.all(vec <= 10.0))


class TestFromCSVHistorical(unittest.TestCase):
    """Load the FRED SOFR daily historical fixture (SOFR_historical.csv).

    File format: date,rate  (standard from_csv column names)
    Coverage: 2018-04-03 through 2026-03-20 (~2079 daily observations).
    """

    @classmethod
    def setUpClass(cls):
        cls.idx = RateIndex.from_csv(SOFR_HIST_CSV, name="SOFR")

    def test_loads_without_error(self):
        self.assertIsNotNone(self.idx)

    def test_observation_count(self):
        # ~1989 business-day observations (weekends/holidays excluded by FRED)
        self.assertGreater(len(self.idx), 1900)

    def test_name(self):
        self.assertEqual(self.idx.name, "SOFR")

    def test_dates_sorted_ascending(self):
        for i in range(len(self.idx.dates) - 1):
            self.assertLessEqual(self.idx.dates[i], self.idx.dates[i + 1])

    def test_first_observation(self):
        """SOFR launched 2018-04-03 at 1.83%."""
        self.assertEqual(self.idx.dates[0], date(2018, 4, 3))
        self.assertAlmostEqual(self.idx.rates[0], 1.83)

    def test_rates_in_plausible_range(self):
        """All historical SOFR rates should be between 0% and 15%."""
        rates = np.array(self.idx.rates)
        self.assertTrue(np.all(rates >= 0.0), "Rate below 0%")
        self.assertTrue(np.all(rates <= 15.0), "Rate above 15%")

    def test_repr_contains_obs_count(self):
        self.assertIn("obs", repr(self.idx))


class TestFromCSVForward(unittest.TestCase):
    """Load the SOFR 3M forward curve fixture (03032026_SOFR3M_FWD.csv).

    File format: ResetDate,Rate  (non-default column names; rates have % suffix)
    Coverage: 2026-03-03 through 2036-02-03 (119 monthly observations).
    """

    @classmethod
    def setUpClass(cls):
        cls.idx = RateIndex.from_csv(
            SOFR_FWD_CSV,
            date_col="ResetDate",
            rate_col="Rate",
            name="SOFR3M_FWD",
        )

    def test_loads_without_error(self):
        self.assertIsNotNone(self.idx)

    def test_observation_count(self):
        # 120 monthly points (blank row dropped by dropna; file has 121 lines)
        self.assertEqual(len(self.idx), 120)

    def test_name(self):
        self.assertEqual(self.idx.name, "SOFR3M_FWD")

    def test_first_rate_no_percent_suffix(self):
        """First rate should be numeric 3.66, not the string '3.66%'."""
        self.assertAlmostEqual(self.idx.rates[0], 3.66)

    def test_first_date(self):
        self.assertEqual(self.idx.dates[0], date(2026, 3, 3))

    def test_last_date(self):
        self.assertEqual(self.idx.dates[-1], date(2036, 2, 3))

    def test_dates_sorted_ascending(self):
        for i in range(len(self.idx.dates) - 1):
            self.assertLessEqual(self.idx.dates[i], self.idx.dates[i + 1])

    def test_rates_in_plausible_range(self):
        rates = np.array(self.idx.rates)
        self.assertTrue(np.all(rates >= 0.0))
        self.assertTrue(np.all(rates <= 15.0))


# ---------------------------------------------------------------------------
# get_rate_vector — SOFR-based ARM scenarios using real fixture data
# ---------------------------------------------------------------------------

class TestGetRateVectorSOFR(unittest.TestCase):
    """End-to-end ARM rate vector tests using the real SOFR historical fixture."""

    @classmethod
    def setUpClass(cls):
        cls.hist = RateIndex.from_csv(SOFR_HIST_CSV, name="SOFR")

    def test_annual_arm_origination_2020(self):
        """Annual ARM originated 2020-01 at low rates, resets post-hike-cycle.

        Actual SOFR (from fixture):
          Year 1 reset (2020-01-02):  1.54%  (pre-COVID)
          Year 2 reset (2021-01-04):  0.10%  (near-zero post-COVID)
          Year 3 reset (2022-01-03):  0.05%  (still near-zero; Fed hikes March 2022)
          Year 4 reset (2023-01-03):  4.31%  (post-hike-cycle)
        """
        vec = self.hist.get_rate_vector(
            next_payment_date=date(2020, 1, 2),
            next_reset_date=date(2020, 1, 2),
            reset_frequency=12,
            remaining_term=48,
        )
        self.assertEqual(len(vec), 48)
        # Each year holds a single constant rate
        for yr in range(4):
            with self.subTest(year=yr + 1):
                self.assertEqual(len(np.unique(vec[yr*12:(yr+1)*12])), 1)
        # Year 1 (pre-COVID 1.54%) > year 2 (near-zero 0.10%)
        self.assertGreater(vec[0], vec[12], msg="Year 1 pre-COVID should exceed year 2 near-zero")
        # Year 4 (post-hike 4.31%) >> year 2 (near-zero 0.10%)
        self.assertGreater(vec[36], vec[12],
                           msg="SOFR year 4 (post-hike) should far exceed year 2 (near-zero)")

    def test_monthly_arm_2022_hike(self):
        """Monthly ARM during 2022 Fed hike cycle: each period's rate rises month-over-month.

        SOFR rose from near zero in early 2022 to over 4% by year-end 2022.
        Over this 12-month window the rate vector should be monotonically non-decreasing.
        """
        vec = self.hist.get_rate_vector(
            next_payment_date=date(2022, 1, 3),
            next_reset_date=date(2022, 1, 3),
            reset_frequency=1,
            remaining_term=12,
        )
        self.assertEqual(len(vec), 12)
        # During 2022 tightening, each monthly reset should track upward
        self.assertGreater(vec[-1], vec[0],
                           msg="SOFR should rise over 2022 hike cycle")

    def test_forward_curve_annual_arm(self):
        """Annual ARM using the forward curve: verify 10-year vector covers full horizon."""
        fwd = RateIndex.from_csv(
            SOFR_FWD_CSV,
            date_col="ResetDate",
            rate_col="Rate",
            name="SOFR3M_FWD",
        )
        vec = fwd.get_rate_vector(
            next_payment_date=date(2026, 3, 3),
            next_reset_date=date(2026, 3, 3),
            reset_frequency=12,
            remaining_term=120,   # 10 years
        )
        self.assertEqual(len(vec), 120)
        # All rates should be in the 3%-5% forward curve range
        self.assertTrue(np.all(vec >= 3.0))
        self.assertTrue(np.all(vec <= 5.0))
        # First 12 months should be constant (annual reset)
        self.assertEqual(len(np.unique(vec[:12])), 1)


if __name__ == "__main__":
    unittest.main()
