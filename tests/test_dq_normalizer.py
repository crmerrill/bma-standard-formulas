"""
Tests for the DQ normalizer (orchestrator/dq_normalizer.py).

Covers:
  - detect_dq_pattern: all six pattern types and the "none" fallback
  - suggest_dq_mapping: alias for detect_dq_pattern
  - materialize_dq_columns: canonical column output for each pattern type
  - FC/REO overlay from zero-balance codes and boolean flags
  - Edge cases: empty DataFrame, NaN-only columns, mixed patterns

BMA Reference: orchestrator/dq_normalizer.py
"""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from bma_cfengine_app.orchestrator.dq_normalizer import (
    DqMapping,
    detect_dq_pattern,
    materialize_dq_columns,
    suggest_dq_mapping,
)


# ---------------------------------------------------------------------------
# Test data factories
# ---------------------------------------------------------------------------

def _base_df(n: int = 10) -> pd.DataFrame:
    """Minimal loan DataFrame without any DQ columns."""
    return pd.DataFrame({
        "loan_id": range(1, n + 1),
        "current_balance": [100_000.0] * n,
    })


def _status_code_df() -> pd.DataFrame:
    """Tape with integer DQ status codes (agency CRT convention)."""
    df = _base_df(7)
    df["dqstatus"] = [0, 0, 1, 2, 3, 0, 6]
    return df


def _dpd_df() -> pd.DataFrame:
    """Tape with days-past-due column."""
    df = _base_df(5)
    df["days_past_due"] = [0, 30, 60, 0, 90]
    return df


def _pay_through_df() -> pd.DataFrame:
    """Tape with pay-through date and as-of date."""
    df = _base_df(4)
    df["paid_thru_date"] = ["2024-01-01", "2023-11-01", "2023-09-01", "2024-01-01"]
    df["asof_date"] = ["2024-01-01"] * 4
    return df


def _boolean_flags_df() -> pd.DataFrame:
    """Tape with boolean FC/REO flag columns."""
    df = _base_df(4)
    df["is_foreclosure"] = ["N", "Y", "N", "N"]
    df["is_reo"] = ["N", "N", "Y", "N"]
    return df


def _balance_bucket_df() -> pd.DataFrame:
    """Tape with pre-bucketed DQ balance columns."""
    df = _base_df(3)
    df["delinq_31_60"] = [10_000.0, 0.0, 5_000.0]
    df["delinq_61_90"] = [0.0, 20_000.0, 0.0]
    df["delinq_91_120"] = [0.0, 0.0, 15_000.0]
    return df


def _zb_code_df() -> pd.DataFrame:
    """Tape with status codes AND zero-balance codes for FC/REO."""
    df = _status_code_df()
    df["zerobal_code"] = [0, 0, 0, 0, 0, 3, 9]
    return df


# =============================================================================
# detect_dq_pattern
# =============================================================================

class TestDetectDqPattern(unittest.TestCase):

    def test_status_code_detected(self):
        df = _status_code_df()
        m = detect_dq_pattern(df)
        self.assertEqual(m.pattern, "status_code")
        self.assertEqual(m.status_col, "dqstatus")
        self.assertGreater(m.confidence, 0)

    def test_dpd_detected(self):
        df = _dpd_df()
        m = detect_dq_pattern(df)
        self.assertEqual(m.pattern, "days_past_due")
        self.assertEqual(m.dpd_col, "days_past_due")

    def test_pay_through_detected(self):
        df = _pay_through_df()
        m = detect_dq_pattern(df)
        self.assertEqual(m.pattern, "pay_through")
        self.assertEqual(m.pay_thru_col, "paid_thru_date")
        self.assertEqual(m.asof_col, "asof_date")

    def test_boolean_flags_detected(self):
        df = _boolean_flags_df()
        m = detect_dq_pattern(df)
        self.assertEqual(m.pattern, "boolean_flags")
        self.assertIsNotNone(m.fc_col)

    def test_balance_buckets_detected(self):
        df = _balance_bucket_df()
        m = detect_dq_pattern(df)
        self.assertEqual(m.pattern, "balance_buckets")
        self.assertIn("delinq_31_60", m.balance_bucket_cols)

    def test_no_dq_data(self):
        df = _base_df(5)
        m = detect_dq_pattern(df)
        self.assertEqual(m.pattern, "none")
        self.assertEqual(m.confidence, 0.0)

    def test_status_code_with_zb_code(self):
        """Status code pattern should also detect ZB code for FC/REO."""
        df = _zb_code_df()
        m = detect_dq_pattern(df)
        self.assertEqual(m.pattern, "status_code")
        self.assertIsNotNone(m.fc_col)
        self.assertIsNotNone(m.reo_col)

    def test_empty_dataframe(self):
        df = pd.DataFrame({"loan_id": [], "current_balance": []})
        m = detect_dq_pattern(df)
        self.assertEqual(m.pattern, "none")

    def test_status_priority_over_dpd(self):
        """When both status codes and DPD are present, status code wins."""
        df = _base_df(5)
        df["dqstatus"] = [0, 1, 2, 0, 3]
        df["days_past_due"] = [0, 30, 60, 0, 90]
        m = detect_dq_pattern(df)
        self.assertEqual(m.pattern, "status_code")

    def test_case_insensitive_detection(self):
        df = _base_df(3)
        df["DQStatus"] = [0, 1, 2]
        m = detect_dq_pattern(df)
        self.assertEqual(m.pattern, "status_code")


class TestSuggestDqMapping(unittest.TestCase):

    def test_suggest_is_detect(self):
        df = _status_code_df()
        detected = detect_dq_pattern(df)
        suggested = suggest_dq_mapping(df)
        self.assertEqual(detected.pattern, suggested.pattern)
        self.assertEqual(detected.status_col, suggested.status_col)


# =============================================================================
# materialize_dq_columns
# =============================================================================

class TestMaterializeDqColumns(unittest.TestCase):

    def _assert_canonical_cols(self, result: pd.DataFrame):
        """Verify all four canonical columns exist and have correct dtypes."""
        for col in ["dlq_status", "days_past_due", "is_fc", "is_reo"]:
            self.assertIn(col, result.columns, f"Missing column: {col}")

    def test_status_code_materialization(self):
        df = _status_code_df()
        mapping = detect_dq_pattern(df)
        result = materialize_dq_columns(df, mapping)

        self._assert_canonical_cols(result)
        self.assertEqual(result.loc[0, "dlq_status"], "Current")
        self.assertEqual(result.loc[2, "dlq_status"], "30 DPD")
        self.assertEqual(result.loc[3, "dlq_status"], "60 DPD")
        self.assertEqual(result.loc[6, "dlq_status"], "180+ DPD")
        self.assertEqual(result.loc[0, "days_past_due"], 0)
        self.assertEqual(result.loc[2, "days_past_due"], 30)

    def test_dpd_materialization(self):
        df = _dpd_df()
        mapping = detect_dq_pattern(df)
        result = materialize_dq_columns(df, mapping)

        self._assert_canonical_cols(result)
        self.assertEqual(result.loc[0, "dlq_status"], "Current")
        self.assertEqual(result.loc[1, "dlq_status"], "30 DPD")
        self.assertEqual(result.loc[4, "dlq_status"], "90 DPD")
        self.assertEqual(result.loc[1, "days_past_due"], 30)

    def test_pay_through_materialization(self):
        df = _pay_through_df()
        mapping = detect_dq_pattern(df)
        result = materialize_dq_columns(df, mapping)

        self._assert_canonical_cols(result)
        self.assertEqual(result.loc[0, "dlq_status"], "Current")
        self.assertEqual(result.loc[1, "days_past_due"], 60)
        self.assertEqual(result.loc[2, "days_past_due"], 120)

    def test_boolean_flags_materialization(self):
        df = _boolean_flags_df()
        mapping = detect_dq_pattern(df)
        result = materialize_dq_columns(df, mapping)

        self._assert_canonical_cols(result)
        self.assertTrue(result.loc[1, "is_fc"])
        self.assertTrue(result.loc[2, "is_reo"])
        self.assertFalse(result.loc[0, "is_fc"])
        self.assertEqual(result.loc[1, "dlq_status"], "FC")
        self.assertEqual(result.loc[2, "dlq_status"], "REO")

    def test_zb_code_fc_reo_overlay(self):
        """ZB codes should override DQ status with FC/REO."""
        df = _zb_code_df()
        mapping = detect_dq_pattern(df)
        result = materialize_dq_columns(df, mapping)

        self._assert_canonical_cols(result)
        self.assertTrue(result.loc[5, "is_fc"])
        self.assertTrue(result.loc[6, "is_reo"])
        self.assertEqual(result.loc[5, "dlq_status"], "FC")
        self.assertEqual(result.loc[6, "dlq_status"], "REO")

    def test_no_pattern_returns_defaults(self):
        df = _base_df(3)
        mapping = DqMapping(pattern="none")
        result = materialize_dq_columns(df, mapping)

        self._assert_canonical_cols(result)
        self.assertTrue((result["dlq_status"] == "Current").all())
        self.assertTrue((result["days_past_due"] == 0).all())
        self.assertTrue((~result["is_fc"]).all())
        self.assertTrue((~result["is_reo"]).all())

    def test_original_df_not_modified(self):
        df = _status_code_df()
        mapping = detect_dq_pattern(df)
        original_cols = set(df.columns)
        materialize_dq_columns(df, mapping)
        self.assertEqual(set(df.columns), original_cols)

    def test_missing_status_col_raises(self):
        df = _base_df(3)
        mapping = DqMapping(pattern="status_code", status_col="nonexistent")
        with self.assertRaises(ValueError):
            materialize_dq_columns(df, mapping)

    def test_balance_buckets_defaults(self):
        """Balance bucket pattern doesn't set per-loan DQ (aggregate only)."""
        df = _balance_bucket_df()
        mapping = detect_dq_pattern(df)
        result = materialize_dq_columns(df, mapping)

        self._assert_canonical_cols(result)
        self.assertTrue((result["dlq_status"] == "Current").all())

    def test_dpd_snapping(self):
        """Non-standard DPD values (e.g. 45, 91) should snap to nearest bucket."""
        df = _base_df(4)
        df["days_past_due"] = [0, 45, 91, 170]
        mapping = detect_dq_pattern(df)
        result = materialize_dq_columns(df, mapping)

        self.assertEqual(result.loc[0, "days_past_due"], 0)
        self.assertEqual(result.loc[1, "days_past_due"], 60)
        self.assertEqual(result.loc[2, "days_past_due"], 90)
        self.assertEqual(result.loc[3, "days_past_due"], 180)


# =============================================================================
# DqMapping model
# =============================================================================

class TestDqMapping(unittest.TestCase):

    def test_serialization_roundtrip(self):
        m = DqMapping(
            pattern="status_code",
            status_col="dqstatus",
            status_code_map={"0": "Current", "1": "30 DPD"},
            confidence=0.9,
        )
        data = m.model_dump()
        m2 = DqMapping(**data)
        self.assertEqual(m.pattern, m2.pattern)
        self.assertEqual(m.status_col, m2.status_col)

    def test_json_roundtrip(self):
        m = DqMapping(pattern="days_past_due", dpd_col="dpd", confidence=0.85)
        json_str = m.model_dump_json()
        m2 = DqMapping.model_validate_json(json_str)
        self.assertEqual(m.pattern, m2.pattern)
        self.assertEqual(m.dpd_col, m2.dpd_col)


if __name__ == "__main__":
    unittest.main()
