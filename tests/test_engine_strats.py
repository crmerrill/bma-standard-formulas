"""
Tests for the engine-layer stratification module (engine/strats.py).

Covers:
  - Bucket presets: FICO, LTV, DTI, term matching
  - Rate-step bucketing (0.25% increments)
  - Equal-width fallback bucketing
  - Edge cases: empty series, single-value series, all-NaN
  - add_bucket_column: string passthrough, numeric bucketing, NaN handling
  - compute_strat: correct counts, balances, weighted averages, TOTAL row
  - compute_strat: bucket_fn, row_callback, totals_callback extension points
  - available_strat_dimensions: numeric/categorical detection, single-value exclusion
  - summarize_tape, summarize_unique_values: per-column profiling

BMA Reference: engine/strats.py
"""
from __future__ import annotations

import unittest
from typing import Any

import numpy as np
import pandas as pd

from bma_standard_formulas.engine.strats import (
    BUCKET_PRESETS,
    RATE_STEP_FIELDS,
    _round_to_nearest,
    _weighted_avg,
    add_bucket_column,
    available_strat_dimensions,
    bucketize_column,
    compute_strat,
    summarize_tape,
    summarize_unique_values,
)


# ---------------------------------------------------------------------------
# Test data factory
# ---------------------------------------------------------------------------

def _make_loan_df(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """Produce a synthetic loan DataFrame for strat tests."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "loan_id": range(1, n + 1),
        "borrower_fico": rng.integers(620, 800, size=n),
        "original_ltv": rng.uniform(50, 100, size=n).round(1),
        "note_rate": rng.uniform(3.0, 7.0, size=n).round(3),
        "original_balance": rng.uniform(100_000, 500_000, size=n).round(2),
        "current_balance": rng.uniform(80_000, 450_000, size=n).round(2),
        "rate_margin": rng.uniform(3.0, 7.0, size=n).round(4),
        "original_term": rng.choice([180, 360], size=n),
        "remaining_term": rng.integers(100, 360, size=n),
        "prop_state": rng.choice(["CA", "TX", "NY", "FL", "IL"], size=n),
    })


# =============================================================================
# _round_to_nearest
# =============================================================================

class TestRoundToNearest(unittest.TestCase):

    def test_round_down(self):
        self.assertAlmostEqual(_round_to_nearest(7.3, 0.25, "down"), 7.25)

    def test_round_up(self):
        self.assertAlmostEqual(_round_to_nearest(7.3, 0.25, "up"), 7.5)

    def test_round_nearest(self):
        self.assertAlmostEqual(_round_to_nearest(7.3, 0.25, "nearest"), 7.25)
        self.assertAlmostEqual(_round_to_nearest(7.4, 0.25, "nearest"), 7.5)


# =============================================================================
# bucketize_column
# =============================================================================

class TestBucketizeColumn(unittest.TestCase):

    def test_fico_preset(self):
        s = pd.Series([650, 700, 750, 800])
        edges = bucketize_column(s, "borrower_fico")
        self.assertIn(620, edges)
        self.assertIn(700, edges)
        self.assertIn(780, edges)

    def test_ltv_preset(self):
        s = pd.Series([60, 80, 95])
        edges = bucketize_column(s, "original_ltv")
        self.assertIn(60, edges)
        self.assertIn(80, edges)
        self.assertIn(95, edges)

    def test_rate_step(self):
        """Rate columns should use 0.25% step sizes."""
        s = pd.Series([3.0, 5.0, 7.0])
        edges = bucketize_column(s, "note_rate", max_buckets=8)
        steps = [edges[i + 1] - edges[i] for i in range(len(edges) - 2)]
        for step in steps:
            self.assertAlmostEqual(step % 0.25, 0.0, places=6)

    def test_empty_series(self):
        s = pd.Series(dtype=float)
        edges = bucketize_column(s, "anything")
        self.assertEqual(edges, [0, 1])

    def test_single_value(self):
        s = pd.Series([100.0, 100.0, 100.0])
        edges = bucketize_column(s, "unknown_col")
        self.assertEqual(len(edges), 2)
        self.assertLessEqual(edges[0], 100.0)
        self.assertGreaterEqual(edges[1], 100.0)

    def test_covers_full_range(self):
        s = pd.Series([10, 50, 90])
        edges = bucketize_column(s, "generic_numeric")
        self.assertLessEqual(edges[0], 10)
        self.assertGreaterEqual(edges[-1], 90)


# =============================================================================
# add_bucket_column
# =============================================================================

class TestAddBucketColumn(unittest.TestCase):

    def test_string_passthrough(self):
        df = pd.DataFrame({"state": ["CA", "TX", None, "NY"]})
        result = add_bucket_column(df, "state")
        self.assertEqual(list(result), ["CA", "TX", "N/A", "NY"])

    def test_numeric_bucketing(self):
        df = _make_loan_df(50)
        result = add_bucket_column(df, "borrower_fico")
        self.assertEqual(len(result), 50)
        self.assertTrue(all(isinstance(v, str) for v in result))

    def test_nan_labeled_na(self):
        df = pd.DataFrame({"val": [1.0, 2.0, np.nan, 4.0]})
        result = add_bucket_column(df, "val")
        self.assertEqual(result.iloc[2], "N/A")

    def test_category_dtype(self):
        df = pd.DataFrame({"cat": pd.Categorical(["A", "B", "A", "C"])})
        result = add_bucket_column(df, "cat")
        self.assertTrue(all(isinstance(v, str) for v in result))


# =============================================================================
# _weighted_avg
# =============================================================================

class TestWeightedAvg(unittest.TestCase):

    def test_basic(self):
        vals = pd.Series([5.0, 10.0])
        wts = pd.Series([100.0, 300.0])
        wa = _weighted_avg(vals, wts)
        self.assertAlmostEqual(wa, 8.75)

    def test_with_nan(self):
        vals = pd.Series([5.0, np.nan, 10.0])
        wts = pd.Series([100.0, 200.0, 300.0])
        wa = _weighted_avg(vals, wts)
        self.assertAlmostEqual(wa, 8.75)

    def test_all_zero_weights(self):
        vals = pd.Series([5.0, 10.0])
        wts = pd.Series([0.0, 0.0])
        self.assertEqual(_weighted_avg(vals, wts), 0.0)

    def test_empty(self):
        vals = pd.Series(dtype=float)
        wts = pd.Series(dtype=float)
        self.assertEqual(_weighted_avg(vals, wts), 0.0)


# =============================================================================
# compute_strat
# =============================================================================

class TestComputeStrat(unittest.TestCase):

    def setUp(self):
        self.df = _make_loan_df(100)

    def test_basic_numeric_strat(self):
        result = compute_strat(self.df, "borrower_fico")
        self.assertIn("bucket", result.columns)
        self.assertIn("count", result.columns)
        self.assertIn("wa_rate", result.columns)
        self.assertEqual(result.iloc[-1]["bucket"], "TOTAL")

    def test_total_row_counts(self):
        result = compute_strat(self.df, "borrower_fico")
        total = result[result["bucket"] == "TOTAL"].iloc[0]
        non_total = result[result["bucket"] != "TOTAL"]
        self.assertEqual(int(total["count"]), 100)
        self.assertEqual(int(non_total["count"].sum()), 100)

    def test_balance_pct_sums_to_100(self):
        result = compute_strat(self.df, "borrower_fico")
        non_total = result[result["bucket"] != "TOTAL"]
        self.assertAlmostEqual(non_total["curr_bal_pct"].sum(), 100.0, places=0)

    def test_categorical_strat(self):
        result = compute_strat(self.df, "prop_state")
        non_total = result[result["bucket"] != "TOTAL"]
        self.assertLessEqual(len(non_total), 5)
        total = result.iloc[-1]
        self.assertEqual(int(total["count"]), 100)

    def test_max_buckets_respected(self):
        """max_buckets limits bins for non-preset columns."""
        result = compute_strat(self.df, "original_ltv", max_buckets=5)
        non_total = result[result["bucket"] != "TOTAL"]
        # LTV uses a preset so may exceed max_buckets; test a generic column
        df2 = self.df.copy()
        df2["generic_score"] = np.random.default_rng(1).uniform(0, 100, len(df2))
        result2 = compute_strat(df2, "generic_score", max_buckets=5)
        non_total2 = result2[result2["bucket"] != "TOTAL"]
        self.assertLessEqual(len(non_total2), 6)

    def test_custom_bucket_fn(self):
        """Verify the bucket_fn callback is invoked."""
        called = {"count": 0}

        def custom_bucket(df, column, max_buckets):
            called["count"] += 1
            return add_bucket_column(df, column, max_buckets)

        compute_strat(self.df, "borrower_fico", bucket_fn=custom_bucket)
        self.assertEqual(called["count"], 1)

    def test_row_callback(self):
        """Verify row_callback is invoked for each group."""
        enriched_keys: list[str] = []

        def row_cb(row: dict, sub: pd.DataFrame, cbc: str) -> None:
            row["custom_col"] = len(sub)
            enriched_keys.append(row["bucket"])

        result = compute_strat(self.df, "prop_state", row_callback=row_cb)
        self.assertIn("custom_col", result.columns)
        non_total = result[result["bucket"] != "TOTAL"]
        for _, r in non_total.iterrows():
            self.assertEqual(int(r["custom_col"]), int(r["count"]))

    def test_totals_callback(self):
        """Verify totals_callback is invoked for the TOTAL row."""
        called = {"invoked": False}

        def totals_cb(totals: dict, full_df: pd.DataFrame, cbc: str) -> None:
            totals["extra_total"] = 999
            called["invoked"] = True

        result = compute_strat(self.df, "prop_state", totals_callback=totals_cb)
        self.assertTrue(called["invoked"])
        total_row = result[result["bucket"] == "TOTAL"].iloc[0]
        self.assertEqual(total_row["extra_total"], 999)

    def test_missing_balance_cols(self):
        """Strat should work even without balance columns."""
        df = self.df.drop(columns=["original_balance", "current_balance"])
        result = compute_strat(df, "prop_state")
        self.assertEqual(result.iloc[-1]["bucket"], "TOTAL")

    def test_wala_computed(self):
        result = compute_strat(self.df, "prop_state")
        total = result.iloc[-1]
        expected_wala = total["wa_orig_term"] - total["wa_rem_term"]
        self.assertAlmostEqual(total["wala"], expected_wala, places=1)

    # --- Multi-column cross-tabulation ---

    def test_cross_tab_two_columns(self):
        """group_by as list produces composite bucket labels."""
        result = compute_strat(self.df, ["prop_state", "original_term"])
        non_total = result[result["bucket"] != "TOTAL"]
        for label in non_total["bucket"]:
            self.assertIn(" | ", label)

    def test_cross_tab_count_consistency(self):
        """Total count in cross-tab matches DataFrame row count."""
        result = compute_strat(self.df, ["prop_state", "original_term"])
        total = result[result["bucket"] == "TOTAL"].iloc[0]
        non_total = result[result["bucket"] != "TOTAL"]
        self.assertEqual(int(total["count"]), 100)
        self.assertEqual(int(non_total["count"].sum()), 100)

    def test_cross_tab_with_callbacks(self):
        """row_callback fires for each composite group."""
        keys: list[str] = []

        def row_cb(row: dict, sub: pd.DataFrame, cbc: str) -> None:
            keys.append(row["bucket"])

        result = compute_strat(
            self.df, ["prop_state", "original_term"], row_callback=row_cb,
        )
        non_total = result[result["bucket"] != "TOTAL"]
        self.assertEqual(len(keys), len(non_total))

    # --- Drill-down filter ---

    def test_filter_reduces_rows(self):
        """filter_ restricts the strat to matching rows only."""
        work = self.df.copy()
        work["prop_state_bucket"] = work["prop_state"]
        result = compute_strat(
            work, "original_term",
            filter_={"prop_state_bucket": "CA"},
        )
        total = result[result["bucket"] == "TOTAL"].iloc[0]
        expected = len(work[work["prop_state_bucket"] == "CA"])
        self.assertEqual(int(total["count"]), expected)

    def test_filter_no_match_returns_empty_total(self):
        """filter_ with no matching rows returns a TOTAL-only result."""
        result = compute_strat(
            self.df, "borrower_fico",
            filter_={"prop_state": "ZZ"},
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["bucket"], "TOTAL")
        self.assertEqual(int(result.iloc[0]["count"]), 0)


# =============================================================================
# available_strat_dimensions
# =============================================================================

class TestAvailableStratDimensions(unittest.TestCase):

    def test_returns_numeric_and_categorical(self):
        df = _make_loan_df(50)
        dims = available_strat_dimensions(df)
        names = [d["column"] for d in dims]
        self.assertIn("borrower_fico", names)
        self.assertIn("prop_state", names)

    def test_excludes_single_valued(self):
        df = pd.DataFrame({"a": [1, 1, 1], "b": [1, 2, 3]})
        dims = available_strat_dimensions(df)
        names = [d["column"] for d in dims]
        self.assertNotIn("a", names)
        self.assertIn("b", names)

    def test_excludes_private_columns(self):
        df = pd.DataFrame({"_internal": [1, 2, 3], "public": [4, 5, 6]})
        dims = available_strat_dimensions(df)
        names = [d["column"] for d in dims]
        self.assertNotIn("_internal", names)

    def test_excludes_high_cardinality_categorical(self):
        df = pd.DataFrame({"unique_str": [f"val_{i}" for i in range(250)]})
        dims = available_strat_dimensions(df)
        self.assertEqual(len(dims), 0)


# =============================================================================
# summarize_tape / summarize_unique_values
# =============================================================================

class TestSummarizeTape(unittest.TestCase):

    def test_numeric_column_stats(self):
        df = _make_loan_df(50)
        summary = summarize_tape(df)
        fico_row = summary[summary["column"] == "borrower_fico"].iloc[0]
        self.assertIsNotNone(fico_row["mean"])
        self.assertIsNotNone(fico_row["median"])
        self.assertGreater(fico_row["max"], fico_row["min"])

    def test_string_column_stats(self):
        """Non-numeric columns should have null/NaN stats, not numeric values."""
        df = _make_loan_df(50)
        summary = summarize_tape(df)
        state_row = summary[summary["column"] == "prop_state"].iloc[0]
        self.assertTrue(state_row["mean"] is None or pd.isna(state_row["mean"]))

    def test_missing_values_reported(self):
        df = pd.DataFrame({"a": [1.0, np.nan, 3.0], "b": ["x", "y", None]})
        summary = summarize_tape(df)
        a_row = summary[summary["column"] == "a"].iloc[0]
        self.assertEqual(a_row["missing"], 1)

    def test_boolean_column_skips_numeric_stats(self):
        """Bool is numeric in pandas but quantile/std must not run (numpy error)."""
        df = pd.DataFrame({"flag": [True, False, True, False]})
        summary = summarize_tape(df)
        row = summary[summary["column"] == "flag"].iloc[0]
        self.assertTrue(row["mean"] is None or pd.isna(row["mean"]))
        self.assertIsInstance(row["top_values"], list)


class TestSummarizeUniqueValues(unittest.TestCase):

    def test_unique_count(self):
        df = pd.DataFrame({"x": [1, 2, 2, 3]})
        uv = summarize_unique_values(df)
        self.assertEqual(uv.iloc[0]["unique"], 3)

    def test_top_values_populated(self):
        df = pd.DataFrame({"x": [1, 2, 3, 4, 5]})
        uv = summarize_unique_values(df)
        self.assertIsInstance(uv.iloc[0]["top_values"], list)
        self.assertEqual(len(uv.iloc[0]["top_values"]), 5)

    def test_high_cardinality_empty_top_values(self):
        df = pd.DataFrame({"x": list(range(600))})
        uv = summarize_unique_values(df, absolute_threshold=500)
        self.assertEqual(uv.iloc[0]["top_values"], [])


# =============================================================================
# Orchestrator strats: canonical DQ column enrichment
# =============================================================================

class TestCanonicalDqEnrichment(unittest.TestCase):
    """Verify that compute_strat picks up canonical DQ columns from the normalizer."""

    def test_canonical_dq_columns_in_strat(self):
        from bma_cfengine_app.orchestrator.strats import compute_strat as app_compute_strat

        df = _make_loan_df(20)
        statuses = ["Current"] * 10 + ["30 DPD"] * 5 + ["FC"] * 3 + ["REO"] * 2
        df["dlq_status"] = statuses
        df["days_past_due"] = [0] * 10 + [30] * 5 + [0] * 3 + [0] * 2
        df["is_fc"] = [False] * 15 + [True] * 3 + [False] * 2
        df["is_reo"] = [False] * 18 + [True] * 2

        result = app_compute_strat(df, "prop_state")
        self.assertIn("dq_current", result.columns)
        self.assertIn("dq_fc", result.columns)
        self.assertIn("dq_reo", result.columns)

        total = result[result["bucket"] == "TOTAL"].iloc[0]
        self.assertGreater(total["dq_current"], 0)

    def test_legacy_fallback_when_no_canonical(self):
        from bma_cfengine_app.orchestrator.strats import compute_strat as app_compute_strat

        df = _make_loan_df(10)
        df["dqstatus"] = [0, 0, 1, 2, 3, 0, 0, 1, 0, 0]

        result = app_compute_strat(df, "prop_state")
        self.assertIn("dq_current", result.columns)
        self.assertIn("dq_30", result.columns)


if __name__ == "__main__":
    unittest.main()
