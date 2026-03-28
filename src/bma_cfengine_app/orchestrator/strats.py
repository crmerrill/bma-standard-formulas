"""Stratification engine — ported from Mosaic/Tape cmutils.stratutils.

Provides bucket presets, auto-bucketing for numeric columns, and
balance-weighted summary statistics per strat group.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Bucket presets (from Mosaic stratutils.py)
# ---------------------------------------------------------------------------

BUCKET_PRESETS: dict[str, list[float]] = {
    "fico": [300, 540, 580, 620, 640, 660, 680, 700, 720, 740, 760, 780, 800, 850],
    "ltv": [30, 40, 50, 60, 65, 70, 75, 80, 85, 90, 95, 100, 105, 120],
    "dti": [10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60],
    "term": [3, 6, 12, 24, 36, 48, 60, 84, 120, 180, 240, 360, 420],
}

RATE_STEP_FIELDS = {"rate", "margin", "coupon", "wac"}


def _round_to_nearest(x: float, base: float, method: str = "down") -> float:
    if method == "down":
        return base * math.floor(x / base)
    elif method == "up":
        return base * math.ceil(x / base)
    return base * round(x / base)


def bucketize_column(
    series: pd.Series,
    column_name: str,
    max_buckets: int = 10,
) -> list[float]:
    """Return bin edges for a numeric column, using presets where applicable.

    The returned edges always cover the full data range: the first edge is
    at or below the series min, and the last edge is at or above the max.
    """
    valid = series.dropna()
    if valid.empty:
        return [0, 1]

    data_min = float(valid.min())
    data_max = float(valid.max())
    col_lower = column_name.lower()

    for preset_key, preset_edges in BUCKET_PRESETS.items():
        if preset_key in col_lower:
            edges = [e for e in preset_edges if e <= data_max + 1e-9]
            if not edges or edges[-1] < data_max:
                edges.append(data_max)
            if edges[0] > data_min:
                edges.insert(0, data_min)
            return edges

    for rate_key in RATE_STEP_FIELDS:
        if rate_key in col_lower:
            if data_max <= data_min:
                return [data_min, data_min + 0.25]
            step = _round_to_nearest((data_max - data_min) / max_buckets, base=0.25, method="down")
            if step <= 0:
                step = 0.25
            edges = [data_min + step * i for i in range(max_buckets + 1)]
            if edges[-1] < data_max:
                edges[-1] = data_max
            return edges

    if data_max <= data_min:
        return [data_min, data_min + 1]
    step = (data_max - data_min) / max_buckets
    edges = [data_min + step * i for i in range(max_buckets + 1)]
    if edges[-1] < data_max:
        edges[-1] = data_max
    return edges


def add_bucket_column(
    df: pd.DataFrame,
    column: str,
    max_buckets: int = 10,
) -> pd.Series:
    """Create a bucketed category series for a column.

    NaN values in the source column are labeled "N/A" so they are never
    silently dropped from groupby operations.
    """
    if df[column].dtype in (object, "string", "category"):
        return df[column].astype(str).fillna("N/A")

    edges = bucketize_column(df[column], column, max_buckets)
    result = pd.cut(df[column], bins=edges, include_lowest=True, duplicates="drop")
    result = result.astype(str).where(df[column].notna(), "N/A")
    return result


# ---------------------------------------------------------------------------
# Weighted average helper
# ---------------------------------------------------------------------------

def _weighted_avg(values: pd.Series, weights: pd.Series) -> float:
    mask = values.notna() & weights.notna() & (weights > 0)
    if mask.sum() == 0:
        return 0.0
    return float(np.average(values[mask], weights=weights[mask]))


# ---------------------------------------------------------------------------
# Strat table generation
# ---------------------------------------------------------------------------

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
    """Compute a stratification table grouped by one column.

    Returns a DataFrame with one row per bucket/category with columns:
    count, count_pct, orig_bal, orig_bal_pct, curr_bal, curr_bal_pct,
    factor, wa_rate, wa_orig_term, wa_rem_term, wala.
    """
    work = df.copy()

    is_numeric = pd.api.types.is_numeric_dtype(work[group_by])
    if is_numeric:
        bucket_col = f"{group_by}_bucket"
        work[bucket_col] = add_bucket_column(work, group_by, max_buckets)
        grp = bucket_col
    else:
        grp = group_by

    total_count = len(work)
    has_orig = orig_bal_col in work.columns
    has_curr = curr_bal_col in work.columns
    total_orig = float(work[orig_bal_col].sum()) if has_orig else 0.0
    total_curr = float(work[curr_bal_col].sum()) if has_curr else 0.0

    rows: list[dict[str, Any]] = []

    for key, sub in work.groupby(grp, observed=True, sort=True):
        n = len(sub)
        orig = float(sub[orig_bal_col].sum()) if has_orig else 0.0
        curr = float(sub[curr_bal_col].sum()) if has_curr else 0.0

        w_orig = sub[orig_bal_col] if has_orig else pd.Series(dtype=float)
        w_curr = sub[curr_bal_col] if has_curr else pd.Series(dtype=float)

        wa_rate = _weighted_avg(sub[rate_col], w_curr) if rate_col in sub.columns and has_curr else 0.0
        wa_orig_term = _weighted_avg(sub[orig_term_col], w_orig) if orig_term_col in sub.columns and has_orig else 0.0
        wa_rem_term = _weighted_avg(sub[rem_term_col], w_curr) if rem_term_col in sub.columns and has_curr else 0.0

        wala = wa_orig_term - wa_rem_term if (wa_orig_term > 0 and wa_rem_term > 0) else 0.0

        rows.append({
            "bucket": str(key),
            "count": n,
            "count_pct": round(n / total_count * 100, 2) if total_count else 0.0,
            "orig_bal": round(orig, 2),
            "orig_bal_pct": round(orig / total_orig * 100, 2) if total_orig else 0.0,
            "curr_bal": round(curr, 2),
            "curr_bal_pct": round(curr / total_curr * 100, 2) if total_curr else 0.0,
            "factor": round(curr / orig * 100, 2) if orig else 0.0,
            "wa_rate": round(wa_rate, 4),
            "wa_orig_term": round(wa_orig_term, 1),
            "wa_rem_term": round(wa_rem_term, 1),
            "wala": round(wala, 1),
        })

    result = pd.DataFrame(rows)

    totals = {
        "bucket": "TOTAL",
        "count": total_count,
        "count_pct": 100.0,
        "orig_bal": round(total_orig, 2),
        "orig_bal_pct": 100.0,
        "curr_bal": round(total_curr, 2),
        "curr_bal_pct": 100.0,
        "factor": round(total_curr / total_orig * 100, 2) if total_orig else 0.0,
        "wa_rate": round(_weighted_avg(work[rate_col], work[curr_bal_col]), 4) if rate_col in work.columns and has_curr else 0.0,
        "wa_orig_term": round(_weighted_avg(work[orig_term_col], work[orig_bal_col]), 1) if orig_term_col in work.columns and has_orig else 0.0,
        "wa_rem_term": round(_weighted_avg(work[rem_term_col], work[curr_bal_col]), 1) if rem_term_col in work.columns and has_curr else 0.0,
        "wala": 0.0,
    }
    totals["wala"] = round(totals["wa_orig_term"] - totals["wa_rem_term"], 1)
    result = pd.concat([result, pd.DataFrame([totals])], ignore_index=True)

    return result


def available_strat_dimensions(df: pd.DataFrame) -> list[dict[str, str]]:
    """Return a list of columns suitable for stratification with their types."""
    dims: list[dict[str, str]] = []
    for col in df.columns:
        if col.startswith("_"):
            continue
        dtype = str(df[col].dtype)
        nunique = df[col].nunique()
        if nunique <= 1:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            dims.append({"column": col, "type": "numeric", "unique": nunique})
        elif nunique <= 200:
            dims.append({"column": col, "type": "categorical", "unique": nunique})
    return dims
