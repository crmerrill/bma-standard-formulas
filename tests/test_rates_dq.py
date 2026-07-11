"""
Tests for rates-file data quality and versioned rate packages.

The detector is calibrated against real SOFR (tests/fixtures/SOFR_historical.csv,
2018-2026), which contains everything that makes this hard:

  - 90 blank rates, all US market holidays (51 fall on a Monday)
  - the March-2020 collapse: 1.10% → 0.01% in weeks, a genuine ~100x move
  - the 2021 ZIRP trough, where real rates sit at 0.01%-0.11%
  - the 2022 hiking cycle back up to 4.3%

So the tests pin the two things that were empirically established:

  1. Outliers must be measured against a SHORT, LOCAL, leave-one-out window.
     A global mean flags the entire ZIRP era (323 false positives on clean data).
     A 21-day window still flags the March-2020 collapse. A 5-day window gives
     zero false positives while catching a planted fat-finger in every regime.

  2. Whole-column scale is NOT always inferable. 2021 SOFR in percent and 5% SOFR
     in decimal are the same numbers. The detector must say "ambiguous" and make
     the user choose, not guess.
"""

import io
import shutil
import unittest
from datetime import date

import numpy as np
import pandas as pd

from bma_cfengine_app.orchestrator.rates_dq import (
    apply_repair,
    available_repairs,
    detect_scale,
    diagnose_rates,
    find_outliers,
    is_ingestible,
    preview_repair,
    windowed_loo_ratio,
)

SOFR = "tests/fixtures/SOFR_historical.csv"


def _sofr() -> pd.Series:
    return pd.read_csv(SOFR)["rate"]


# ---------------------------------------------------------------------------
# The estimator
# ---------------------------------------------------------------------------

class TestWindowedLeaveOneOut(unittest.TestCase):

    def test_no_false_positives_on_real_sofr(self):
        """Clean real data, through ZIRP, the 2020 collapse, and the 2022 hikes."""
        r = windowed_loo_ratio(_sofr())
        flagged = ((r < 0.1) | (r > 10)).sum()
        self.assertEqual(int(flagged), 0)

    def test_global_mean_would_flag_the_entire_zirp_era(self):
        """Why the window is not optional."""
        s = _sofr()
        n = s.notna().sum()
        global_loo = (s.sum() - s.fillna(0)) / (n - s.notna().astype(int))
        r = s / global_loo
        self.assertGreater(int(((r < 0.1) | (r > 10)).sum()), 100)

    def test_holidays_yield_nan_not_outliers(self):
        s = _sofr()
        r = windowed_loo_ratio(s)
        self.assertEqual(int(r.isna().sum()), int(s.isna().sum()))
        self.assertEqual(int(s.isna().sum()), 90)

    def test_cell_is_excluded_from_its_own_baseline(self):
        s = pd.Series([5.0, 5.0, 500.0, 5.0, 5.0])
        r = windowed_loo_ratio(s, window=5)
        self.assertAlmostEqual(float(r.iloc[2]), 100.0, places=6)


# ---------------------------------------------------------------------------
# Outliers, with fixes applied as we go
# ---------------------------------------------------------------------------

class TestFindOutliers(unittest.TestCase):

    def _planted(self, i: int, factor: float):
        s = _sofr().copy()
        s.iloc[i] = s.iloc[i] * factor
        return s

    def test_catches_fat_finger_in_normal_rate_era(self):
        hits = find_outliers(self._planted(1400, 0.01))     # 5.30 -> 0.0530
        self.assertEqual([h["row"] for h in hits], [1400])
        self.assertAlmostEqual(hits[0]["proposed"], 5.30, places=6)

    def test_catches_fat_finger_inside_the_zirp_trough(self):
        hits = find_outliers(self._planted(700, 100))       # 0.07 -> 7.00
        self.assertEqual([h["row"] for h in hits], [700])
        self.assertAlmostEqual(hits[0]["proposed"], 0.07, places=6)

    def test_catches_fat_finger_in_the_2020_collapse_zone(self):
        hits = find_outliers(self._planted(520, 0.01))
        self.assertEqual([h["row"] for h in hits], [520])

    def test_running_fixes_isolate_the_culprit_from_its_neighbours(self):
        """One bad cell contaminates its neighbours' windows.

        A single pass flags 5 cells; re-measuring after each fix converges on the
        one that is actually wrong.
        """
        s = self._planted(700, 100)
        single_pass = windowed_loo_ratio(s)
        naive = np.where((single_pass < 0.1) | (single_pass > 10))[0]
        self.assertGreater(len(naive), 1)              # innocents caught up in it

        hits = find_outliers(s)
        self.assertEqual([h["row"] for h in hits], [700])

    def test_clean_data_yields_no_outliers(self):
        self.assertEqual(find_outliers(_sofr()), [])


# ---------------------------------------------------------------------------
# Scale
# ---------------------------------------------------------------------------

class TestDetectScale(unittest.TestCase):

    def test_ordinary_percent_column_is_confident(self):
        v = detect_scale(pd.Series([5.33, 5.31, 5.35]))
        self.assertEqual(v["scale"], "percent")
        self.assertTrue(v["confident"])

    def test_full_sofr_history_is_confident_percent(self):
        """A multi-year package spans 500x internally, which disambiguates it."""
        v = detect_scale(_sofr())
        self.assertEqual(v["scale"], "percent")

    def test_zirp_only_slice_is_ambiguous_not_guessed(self):
        """2021 SOFR in percent looks exactly like 5% SOFR in decimal."""
        df = pd.read_csv(SOFR, parse_dates=["date"])
        zirp = df[df.date.dt.year == 2021]["rate"]
        v = detect_scale(zirp)
        self.assertEqual(v["scale"], "ambiguous")
        self.assertFalse(v["confident"])
        # Both readings are surfaced with their implied ranges.
        self.assertIn("if_percent", v)
        self.assertIn("if_decimal", v)

    def test_decimal_scaled_column_is_ambiguous_not_silently_accepted(self):
        df = pd.read_csv(SOFR, parse_dates=["date"])
        decimal = df[df.date.dt.year == 2023]["rate"] / 100.0
        v = detect_scale(decimal)
        self.assertEqual(v["scale"], "ambiguous")
        self.assertTrue(v["if_decimal"]["plausible"])


# ---------------------------------------------------------------------------
# diagnose / repair loop
# ---------------------------------------------------------------------------

class TestDiagnoseAndRepair(unittest.TestCase):

    def test_clean_file_has_no_blocking_problems(self):
        df = pd.read_csv(SOFR)
        ok, blockers = is_ingestible(df)
        self.assertTrue(ok, f"unexpected blockers: {blockers}")

    def test_holidays_are_reported_as_info_not_errors(self):
        diag = diagnose_rates(pd.read_csv(SOFR))
        gaps = [p for p in diag["problems"] if p["kind"] == "calendar_gaps"]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["severity"], "info")
        self.assertEqual(gaps[0]["count"], 90)

    def test_corrupt_cells_block(self):
        df = pd.read_csv(io.StringIO(
            "date,SOFR\n2024-01-01,5.33\n2024-01-02,5.2x\n2024-01-03,5.35\n"
        ))
        diag = diagnose_rates(df)
        bad = [p for p in diag["problems"] if p["kind"] == "unparseable_cells"]
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["severity"], "blocking")
        ok, _ = is_ingestible(df)
        self.assertFalse(ok)

    def test_ambiguous_scale_blocks_and_offers_both_readings(self):
        df = pd.read_csv(io.StringIO(
            "date,SOFR\n2024-01-01,0.0533\n2024-02-01,0.0531\n2024-03-01,0.0535\n"
        ))
        ok, blockers = is_ingestible(df)
        self.assertFalse(ok)

        repairs = {r["id"] for r in available_repairs(df)}
        self.assertIn("scale_to_percent:SOFR", repairs)
        self.assertIn("scale_keep_percent:SOFR", repairs)

    def test_declaring_decimal_scale_repairs_the_file(self):
        df = pd.read_csv(io.StringIO(
            "date,SOFR\n2024-01-01,0.0533\n2024-02-01,0.0531\n2024-03-01,0.0535\n"
        ))
        prev = preview_repair(df, "scale_to_percent:SOFR")
        self.assertEqual(prev["changed_count"], 3)
        self.assertAlmostEqual(prev["sample"][0]["before"], 0.0533)
        self.assertAlmostEqual(prev["sample"][0]["after"], 5.33)

        fixed, n = apply_repair(df, "scale_to_percent:SOFR")
        self.assertEqual(n, 3)
        self.assertAlmostEqual(float(fixed["SOFR"].iloc[0]), 5.33)

        ok, blockers = is_ingestible(fixed)
        self.assertTrue(ok, f"still blocked: {blockers}")

    def test_outlier_repair_round_trips_to_the_true_value(self):
        df = pd.read_csv(SOFR)
        true = float(df.loc[1400, "rate"])
        df.loc[1400, "rate"] = true / 100

        repairs = [r for r in available_repairs(df) if r["kind"] == "rescale_cell"]
        self.assertEqual(len(repairs), 1)

        fixed, n = apply_repair(df, repairs[0]["id"])
        self.assertEqual(n, 1)
        self.assertAlmostEqual(float(fixed.loc[1400, "rate"]), true, places=6)
        self.assertEqual(find_outliers(fixed["rate"]), [])

    def test_outliers_warn_but_do_not_block(self):
        """A surprising value may still be legitimate — the user decides."""
        df = pd.read_csv(SOFR)
        df.loc[1400, "rate"] = float(df.loc[1400, "rate"]) / 100
        diag = diagnose_rates(df)
        outliers = [p for p in diag["problems"] if p["kind"] == "outlier_cell"]
        self.assertEqual(len(outliers), 1)
        self.assertEqual(outliers[0]["severity"], "warning")
        ok, _ = is_ingestible(df)
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# Versioned packages
# ---------------------------------------------------------------------------

class TestRatePackages(unittest.TestCase):

    def setUp(self):
        from bma_cfengine_app.storage import rate_store
        self.store = rate_store
        rate_store.init_rate_store()
        self.pid = rate_store.create_package("test-sofr", package_id="pkg-test-dq")

    def tearDown(self):
        d = self.store.package_dir(self.pid)
        if d.exists():
            shutil.rmtree(d)

    def _clean_df(self):
        return pd.read_csv(io.StringIO(
            "date,SOFR,PRIME\n"
            "2024-01-01,5.33,8.50\n2024-02-01,5.31,8.50\n2024-03-01,5.35,8.75\n"
        ))

    def test_version_is_unapproved_until_approved(self):
        v = self.store.add_version(self.pid, self._clean_df(), asof_date=date(2024, 3, 1))
        self.assertEqual(v, 1)
        self.assertFalse(self.store.load_version(self.pid, v)["approved"])

        with self.assertRaises(self.store.RatePackageError):
            self.store.build_deck(self.pid, v)

        self.store.approve(self.pid, v, approved_by="tester")
        deck = self.store.build_deck(self.pid, v)
        self.assertEqual(sorted(deck.keys()), ["PRIME", "SOFR"])

    def test_blocking_problems_cannot_be_approved(self):
        bad = pd.read_csv(io.StringIO(
            "date,SOFR\n2024-01-01,0.0533\n2024-02-01,0.0531\n"   # ambiguous scale
        ))
        v = self.store.add_version(self.pid, bad, asof_date=date(2024, 2, 1))
        with self.assertRaises(self.store.RatePackageError) as cm:
            self.store.approve(self.pid, v)
        self.assertIn("blocking", str(cm.exception))

    def test_versions_are_immutable_and_asof_dated(self):
        v1 = self.store.add_version(self.pid, self._clean_df(), asof_date=date(2024, 3, 1))
        self.store.approve(self.pid, v1)

        newer = self._clean_df()
        newer.loc[0, "SOFR"] = 9.99
        v2 = self.store.add_version(self.pid, newer, asof_date=date(2024, 6, 1))
        self.store.approve(self.pid, v2)

        self.assertEqual(self.store.load_version(self.pid, v1)["asof_date"], "2024-03-01")
        self.assertEqual(self.store.load_version(self.pid, v2)["asof_date"], "2024-06-01")

        # v1 still prices exactly as the run that used it saw it.
        self.assertAlmostEqual(self.store.build_deck(self.pid, v1)["SOFR"].rates[0], 5.33)
        self.assertAlmostEqual(self.store.build_deck(self.pid, v2)["SOFR"].rates[0], 9.99)
        self.assertEqual(self.store.latest_approved_version(self.pid), v2)

    def test_repairs_are_recorded_on_the_version(self):
        df = pd.read_csv(io.StringIO(
            "date,SOFR\n2024-01-01,0.0533\n2024-02-01,0.0531\n2024-03-01,0.0535\n"
        ))
        fixed, _ = apply_repair(df, "scale_to_percent:SOFR")
        v = self.store.add_version(
            self.pid, fixed, asof_date=date(2024, 3, 1),
            source_file="sofr.csv", repairs_applied=["scale_to_percent:SOFR"],
        )
        meta = self.store.approve(self.pid, v)
        self.assertEqual(meta["repairs_applied"], ["scale_to_percent:SOFR"])
        self.assertEqual(meta["source_file"], "sofr.csv")


if __name__ == "__main__":
    unittest.main()
