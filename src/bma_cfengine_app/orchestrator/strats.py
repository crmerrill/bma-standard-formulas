"""Application-layer stratification — display presets and DQ enrichment.

Wraps the engine-layer strat computation with app-specific concerns:

- **Categorical label presets**: numeric columns like ``dqstatus`` and
  ``zerobal_code`` are mapped to human-readable labels (e.g. 0 → "Current",
  1 → "30 DPD") rather than bucketed as continuous values.

- **DQ distribution columns**: when the tape contains delinquency data
  (status codes, balance buckets, or zero-balance codes), each strat row
  is enriched with balance-weighted DQ percentages.

The engine-layer functions (``compute_strat``, ``available_strat_dimensions``,
``summarize_tape``, etc.) are re-exported here for API compatibility so that
existing routers can continue importing from this module unchanged.

See Also:
    ``bma_standard_formulas.engine.strats``
        Pure analytics engine — bucketing, weighted averages, strat tables.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Engine re-exports — API compatibility for routers and orchestrator callers
# ---------------------------------------------------------------------------
from bma_standard_formulas.engine.strats import (
    BUCKET_PRESETS,
    RATE_STEP_FIELDS,
    add_bucket_column as _engine_add_bucket_column,
    available_strat_dimensions,
    bucketize_column,
    compute_strat as _engine_compute_strat,
    summarize_tape,
    summarize_unique_values,
)

__all__ = [
    "BUCKET_PRESETS",
    "RATE_STEP_FIELDS",
    "CATEGORICAL_LABEL_PRESETS",
    "CATEGORICAL_NUMERIC_FIELDS",
    "LOW_CARDINALITY_THRESHOLD",
    "add_bucket_column",
    "available_strat_dimensions",
    "bucketize_column",
    "compute_strat",
    "summarize_tape",
    "summarize_unique_values",
]


# =============================================================================
# Categorical Label Presets (App-Layer Display Concern)
# =============================================================================
#
# Integer-coded columns that should be displayed as discrete labels rather
# than bucketed as continuous numeric values.  These presets map raw tape
# values to human-readable labels for the UI strat tables.

CATEGORICAL_LABEL_PRESETS: dict[str, dict[int, str]] = {
    "dqstatus": {
        0: "Current",
        1: "30 DPD",
        2: "60 DPD",
        3: "90 DPD",
        4: "120 DPD",
        5: "150 DPD",
        6: "180+ DPD",
    },
    "current_loan_delinquency_status": {
        0: "Current",
        1: "30 DPD",
        2: "60 DPD",
        3: "90 DPD",
        4: "120 DPD",
        5: "150 DPD",
        6: "180+ DPD",
    },
    "zerobal_code": {
        1: "Prepaid/Matured",
        2: "Third Party Sale",
        3: "Short Sale",
        6: "Repurchase",
        9: "REO Disposition",
        15: "Note Sale",
        16: "Reperforming Sale",
    },
    "zero_balance_code": {
        1: "Prepaid/Matured",
        2: "Third Party Sale",
        3: "Short Sale",
        6: "Repurchase",
        9: "REO Disposition",
        15: "Note Sale",
        16: "Reperforming Sale",
    },
}

#: Column names (lowercased) that contain integer codes representing discrete
#: categories rather than continuous measurements.
CATEGORICAL_NUMERIC_FIELDS: set[str] = {
    "dqstatus", "dlq_status", "delinquency_status",
    "current_loan_delinquency_status",
    "zerobal_code", "zero_balance_code", "zero_bal_code",
    "num_borrowers", "num_units", "number_of_units",
    "int", "occupancy_status",
}

#: Numeric columns with this many or fewer unique values are auto-detected as
#: categorical, even without an explicit entry in CATEGORICAL_NUMERIC_FIELDS.
LOW_CARDINALITY_THRESHOLD: int = 15


# =============================================================================
# Categorical Detection + Labeling
# =============================================================================


def _is_categorical_numeric(series: pd.Series, column: str) -> bool:
    """Detect numeric columns that should be treated as discrete categories.

    A column is categorical-numeric if:
    1. Its lowercased name is in ``CATEGORICAL_NUMERIC_FIELDS``, OR
    2. Its lowercased name has a label preset in ``CATEGORICAL_LABEL_PRESETS``, OR
    3. It has few enough unique integer values (≤ ``LOW_CARDINALITY_THRESHOLD``).

    Args:
        series: Numeric pandas Series.
        column: Column name.

    Returns:
        True if the column should be treated as categorical rather than
        continuously bucketed.
    """
    col_lower = column.lower()
    if col_lower in CATEGORICAL_NUMERIC_FIELDS:
        return True
    if col_lower in CATEGORICAL_LABEL_PRESETS:
        return True
    nunique = series.dropna().nunique()
    if nunique <= LOW_CARDINALITY_THRESHOLD and nunique > 0:
        vals = series.dropna()
        if vals.dtype.kind in ("i", "u") or (
            vals.dtype.kind == "f" and (vals == vals.astype(int)).all()
        ):
            return True
    return False


def _label_categorical_numeric(series: pd.Series, column: str) -> pd.Series:
    """Map numeric values to human-readable labels where presets exist.

    Falls back to ``str(value)`` for values not covered by the preset map.
    NaN values become ``"N/A"``.

    Args:
        series: Numeric pandas Series.
        column: Column name (matched case-insensitively against presets).

    Returns:
        String Series of labeled values.
    """
    col_lower = column.lower()
    labels = CATEGORICAL_LABEL_PRESETS.get(col_lower, {})
    if labels:
        def _map(v):
            if pd.isna(v):
                return "N/A"
            iv = int(v) if isinstance(v, (float, np.floating)) and float(v).is_integer() else v
            return labels.get(iv, str(iv))
        return series.map(_map)
    result = series.copy()
    result = result.where(result.notna(), "N/A")
    return result.astype(str)


# =============================================================================
# App-Level Bucket Function
# =============================================================================


def add_bucket_column(
    df: pd.DataFrame,
    column: str,
    max_buckets: int = 10,
) -> pd.Series:
    """Create a bucketed category Series with categorical label presets.

    Extends the engine's ``add_bucket_column`` by first checking whether the
    column is a categorical-numeric field (e.g. ``dqstatus``, ``zerobal_code``)
    that should be displayed with human-readable labels rather than interval
    notation.

    Args:
        df:          Source DataFrame.
        column:      Column name to bucketize.
        max_buckets: Maximum number of bins (for non-categorical numerics).

    Returns:
        String Series of bucket labels, same length as *df*.
    """
    if df[column].dtype in (object, "string", "category"):
        return df[column].astype(str).fillna("N/A")

    if _is_categorical_numeric(df[column], column):
        return _label_categorical_numeric(df[column], column)

    return _engine_add_bucket_column(df, column, max_buckets)


# =============================================================================
# DQ Detection and Enrichment
# =============================================================================
#
# Hard-coded detection of delinquency data in tapes.  This will be replaced
# in a future step by canonical column lookup once the DQ normalizer
# materializes standardized columns onto the working copy.

DQ_BALANCE_ALIASES: dict[str, list[str]] = {
    "dq_30":  ["delinq_31_60", "dq_30", "dq30", "dlq_30_59"],
    "dq_60":  ["delinq_61_90", "dq_60", "dq60", "dlq_60_89"],
    "dq_90":  ["delinq_91_120", "dq_90", "dq90", "dlq_90_119"],
    "dq_120": ["delinq_121_179", "dq_120", "dq120", "dlq_120_179"],
    "dq_180": ["delinq_ge_180", "dq_180", "dq180", "dlq_180_plus"],
}

DQ_STATUS_ALIASES: list[str] = [
    "dqstatus", "dlq_status", "delinquency_status",
    "current_loan_delinquency_status", "dlq",
]

ZB_CODE_ALIASES: list[str] = [
    "zerobal_code", "zero_balance_code", "zero_bal_code", "zb_code",
]

DQ_STATUS_TO_BUCKETS: dict[int, str] = {
    0: "dq_current",
    1: "dq_30",
    2: "dq_60",
    3: "dq_90",
    4: "dq_120",
    5: "dq_150",
    6: "dq_180",
}

FC_ZB_CODES: set[int] = {2, 3, 6}
REO_ZB_CODES: set[int] = {9, 15, 16}

DQ_OUTPUT_COLS: list[str] = [
    "dq_current", "dq_30", "dq_60", "dq_90", "dq_120", "dq_180", "dq_fc", "dq_reo",
]


class _DqInfo:
    """Encapsulates how DQ data is available in the tape."""

    def __init__(
        self,
        mode: str,
        balance_cols: dict[str, str] | None = None,
        status_col: str | None = None,
        zb_col: str | None = None,
    ):
        self.mode = mode
        self.balance_cols = balance_cols or {}
        self.status_col = status_col
        self.zb_col = zb_col

    @property
    def available(self) -> bool:
        return self.mode != "none"

    @property
    def output_cols(self) -> list[str]:
        if self.mode == "balance":
            return sorted(self.balance_cols.keys())
        if self.mode == "status":
            return DQ_OUTPUT_COLS
        return []


def _detect_dq(df: pd.DataFrame) -> _DqInfo:
    """Auto-detect which DQ representation the tape uses.

    Checks for pre-bucketed DQ balance columns first (highest fidelity),
    then integer status codes, falling back to ``"none"`` if no DQ data
    is found.

    Args:
        df: Loan-level DataFrame.

    Returns:
        ``_DqInfo`` describing the detected DQ representation.
    """
    col_lower_map = {c.lower(): c for c in df.columns}

    # --- Pre-bucketed DQ balance columns ---
    found_bal: dict[str, str] = {}
    for canonical, aliases in DQ_BALANCE_ALIASES.items():
        for alias in aliases:
            if alias.lower() in col_lower_map:
                found_bal[canonical] = col_lower_map[alias.lower()]
                break
    if found_bal:
        return _DqInfo("balance", balance_cols=found_bal)

    # --- Zero-balance code (supplementary FC/REO source) ---
    zb_col = None
    for alias in ZB_CODE_ALIASES:
        if alias.lower() in col_lower_map:
            zb_col = col_lower_map[alias.lower()]
            break

    # --- Integer status code ---
    for alias in DQ_STATUS_ALIASES:
        if alias.lower() in col_lower_map:
            return _DqInfo("status", status_col=col_lower_map[alias.lower()], zb_col=zb_col)

    return _DqInfo("none")


def _add_dq_columns(
    row: dict[str, Any],
    sub: pd.DataFrame,
    curr_bal_col: str,
    dq: _DqInfo,
) -> None:
    """Add balance-weighted delinquency percentages to a strat row dict.

    Modifies *row* in place, adding one key per DQ output column.

    Args:
        row:          Mutable strat row dict.
        sub:          Group DataFrame (loans in this bucket).
        curr_bal_col: Current balance column name.
        dq:           DQ detection result from ``_detect_dq``.
    """
    group_bal = float(sub[curr_bal_col].sum()) if curr_bal_col in sub.columns else 0.0
    if group_bal <= 0:
        for col in dq.output_cols:
            row[col] = 0.0
        return

    if dq.mode == "balance":
        for canonical, actual_col in dq.balance_cols.items():
            if actual_col in sub.columns:
                row[canonical] = round(float(sub[actual_col].sum()) / group_bal * 100, 3)
            else:
                row[canonical] = 0.0

    elif dq.mode == "status":
        bal_by_bucket: dict[str, float] = {c: 0.0 for c in DQ_OUTPUT_COLS}
        status_series = sub[dq.status_col]

        for status_val, bucket in DQ_STATUS_TO_BUCKETS.items():
            mask = status_series == status_val
            if mask.any():
                bal_by_bucket[bucket] += float(sub.loc[mask, curr_bal_col].sum())

        gt_6 = status_series > 6
        if gt_6.any():
            bal_by_bucket["dq_180"] += float(sub.loc[gt_6, curr_bal_col].sum())

        if dq.zb_col and dq.zb_col in sub.columns:
            zb = sub[dq.zb_col]
            fc_mask = zb.isin(FC_ZB_CODES)
            reo_mask = zb.isin(REO_ZB_CODES)
            if fc_mask.any():
                bal_by_bucket["dq_fc"] += float(sub.loc[fc_mask, curr_bal_col].sum())
            if reo_mask.any():
                bal_by_bucket["dq_reo"] += float(sub.loc[reo_mask, curr_bal_col].sum())

        for col in dq.output_cols:
            row[col] = round(bal_by_bucket.get(col, 0.0) / group_bal * 100, 3)


# =============================================================================
# App-Level compute_strat (Engine + DQ Enrichment)
# =============================================================================


def compute_strat(
    df: pd.DataFrame,
    group_by: str,
    *,
    orig_bal_col: str = "original_balance",
    curr_bal_col: str = "current_balance",
    rate_col: str = "rate_margin",
    orig_term_col: str = "original_term",
    rem_term_col: str = "remaining_term",
    max_buckets: int = 10,
) -> pd.DataFrame:
    """Compute a stratification table with DQ enrichment.

    Delegates core computation to the engine's ``compute_strat``, passing the
    app-level bucket function (with categorical label presets) and DQ row
    callbacks for delinquency distribution columns.

    Args:
        df:             Loan-level DataFrame.
        group_by:       Column name to stratify by.
        orig_bal_col:   Column containing original UPB.
        curr_bal_col:   Column containing current UPB.
        rate_col:       Column containing coupon/rate (for WAC computation).
        orig_term_col:  Column containing original loan term in months.
        rem_term_col:   Column containing remaining term in months.
        max_buckets:    Maximum bins for numeric columns.

    Returns:
        DataFrame with strat metrics plus DQ distribution columns (if DQ
        data is detected in the tape).

    See Also:
        ``bma_standard_formulas.engine.strats.compute_strat``
            Engine-layer strat computation (no DQ, no categorical labels).
    """
    dq = _detect_dq(df)

    row_cb = None
    totals_cb = None
    if dq.available:
        def row_cb(row: dict, sub: pd.DataFrame, cbc: str) -> None:
            _add_dq_columns(row, sub, cbc, dq)

        def totals_cb(totals: dict, full_df: pd.DataFrame, cbc: str) -> None:
            _add_dq_columns(totals, full_df, cbc, dq)

    return _engine_compute_strat(
        df,
        group_by,
        orig_bal_col=orig_bal_col,
        curr_bal_col=curr_bal_col,
        rate_col=rate_col,
        orig_term_col=orig_term_col,
        rem_term_col=rem_term_col,
        max_buckets=max_buckets,
        bucket_fn=add_bucket_column,
        row_callback=row_cb,
        totals_callback=totals_cb,
    )
