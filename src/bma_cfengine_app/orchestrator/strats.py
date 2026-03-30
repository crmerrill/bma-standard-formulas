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

CATEGORICAL_NUMERIC_FIELDS = {
    "dqstatus", "dlq_status", "delinquency_status",
    "current_loan_delinquency_status",
    "zerobal_code", "zero_balance_code", "zero_bal_code",
    "num_borrowers", "num_units", "number_of_units",
    "int", "occupancy_status",
}

LOW_CARDINALITY_THRESHOLD = 15


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


def _is_categorical_numeric(series: pd.Series, column: str) -> bool:
    """Detect numeric columns that should be treated as discrete categories."""
    col_lower = column.lower()
    if col_lower in CATEGORICAL_NUMERIC_FIELDS:
        return True
    if col_lower in CATEGORICAL_LABEL_PRESETS:
        return True
    nunique = series.dropna().nunique()
    if nunique <= LOW_CARDINALITY_THRESHOLD and nunique > 0:
        vals = series.dropna()
        if vals.dtype.kind in ("i", "u") or (vals.dtype.kind == "f" and (vals == vals.astype(int)).all()):
            return True
    return False


def _label_categorical_numeric(series: pd.Series, column: str) -> pd.Series:
    """Map numeric values to human-readable labels where presets exist."""
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

    if _is_categorical_numeric(df[column], column):
        return _label_categorical_numeric(df[column], column)

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

    dq = _detect_dq(work)

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

        row = {
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
        }
        if dq.available:
            _add_dq_columns(row, sub, curr_bal_col, dq)
        rows.append(row)

    result = pd.DataFrame(rows)

    totals: dict[str, Any] = {
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
    if dq.available:
        _add_dq_columns(totals, work, curr_bal_col, dq)
    result = pd.concat([result, pd.DataFrame([totals])], ignore_index=True)

    return result


DQ_BALANCE_ALIASES: dict[str, list[str]] = {
    "dq_30": ["delinq_31_60", "dq_30", "dq30", "dlq_30_59"],
    "dq_60": ["delinq_61_90", "dq_60", "dq60", "dlq_60_89"],
    "dq_90": ["delinq_91_120", "dq_90", "dq90", "dlq_90_119"],
    "dq_120": ["delinq_121_179", "dq_120", "dq120", "dlq_120_179"],
    "dq_180": ["delinq_ge_180", "dq_180", "dq180", "dlq_180_plus"],
}

DQ_STATUS_ALIASES = [
    "dqstatus", "dlq_status", "delinquency_status",
    "current_loan_delinquency_status", "dlq",
]

ZB_CODE_ALIASES = [
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

FC_ZB_CODES = {2, 3, 6}
REO_ZB_CODES = {9, 15, 16}

DQ_OUTPUT_COLS = ["dq_current", "dq_30", "dq_60", "dq_90", "dq_120", "dq_180", "dq_fc", "dq_reo"]


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
    col_lower_map = {c.lower(): c for c in df.columns}

    found_bal: dict[str, str] = {}
    for canonical, aliases in DQ_BALANCE_ALIASES.items():
        for alias in aliases:
            if alias.lower() in col_lower_map:
                found_bal[canonical] = col_lower_map[alias.lower()]
                break
    if found_bal:
        return _DqInfo("balance", balance_cols=found_bal)

    zb_col = None
    for alias in ZB_CODE_ALIASES:
        if alias.lower() in col_lower_map:
            zb_col = col_lower_map[alias.lower()]
            break

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
    """Add balance-weighted delinquency percentages to a strat row."""
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


# ---------------------------------------------------------------------------
# Tape summary functions (from Mosaic cmutils.stratutils)
# ---------------------------------------------------------------------------


def _json_safe(v: Any) -> Any:
    """Convert numpy scalars and other non-JSON-safe types to Python builtins."""
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        if not np.isfinite(f):
            return None
        return f
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (np.datetime64, pd.Timestamp)):
        return str(v)
    return v


def _get_unique_values(
    series: pd.Series,
    max_display: int = 25,
    absolute_threshold: int = 500,
) -> list[Any] | str:
    """Get top unique values for a column, sorted by frequency."""
    nunique = series.nunique()
    if nunique > absolute_threshold:
        return ""
    non_null = series.dropna()
    if len(non_null) == 0:
        return ""
    if nunique > max_display:
        vc = non_null.value_counts()
        return [_json_safe(v) for v in vc.index[:max_display]]
    return [_json_safe(v) for v in non_null.unique()]


def summarize_unique_values(
    df: pd.DataFrame,
    max_display: int = 25,
    absolute_threshold: int = 500,
) -> pd.DataFrame:
    """Per-column summary: type, count, missing, missing%, unique count, top values."""
    rows: list[dict[str, Any]] = []
    for col in df.columns:
        s = df[col]
        missing = int(s.isna().sum())
        total = len(s)
        uv = _get_unique_values(s, max_display, absolute_threshold)
        rows.append({
            "column": col,
            "dtype": str(s.dtype),
            "count": int(s.count()),
            "missing": missing,
            "missing_pct": round(missing / total * 100, 2) if total else 0.0,
            "unique": int(s.nunique()),
            "top_values": uv if isinstance(uv, list) else [],
        })
    return pd.DataFrame(rows)


def summarize_tape(df: pd.DataFrame) -> pd.DataFrame:
    """Per-column descriptive statistics: mean, median, quartiles, deciles, extremes."""
    rows: list[dict[str, Any]] = []
    for col in df.columns:
        s = df[col]
        is_num = pd.api.types.is_numeric_dtype(s)
        valid = s.dropna()
        missing = int(s.isna().sum())
        total = len(s)

        row: dict[str, Any] = {
            "column": col,
            "dtype": str(s.dtype),
            "count": int(s.count()),
            "missing": missing,
            "missing_pct": round(missing / total * 100, 2) if total else 0.0,
            "unique": int(s.nunique()),
        }

        if is_num and len(valid) > 0:
            row.update({
                "mean": round(float(valid.mean()), 6),
                "median": round(float(valid.median()), 6),
                "min": float(valid.min()),
                "q25": float(valid.quantile(0.25)),
                "q50": float(valid.quantile(0.50)),
                "q75": float(valid.quantile(0.75)),
                "p90": float(valid.quantile(0.90)),
                "p95": float(valid.quantile(0.95)),
                "p99": float(valid.quantile(0.99)),
                "p995": float(valid.quantile(0.995)),
                "p999": float(valid.quantile(0.999)),
                "max": float(valid.max()),
                "std": round(float(valid.std()), 6) if len(valid) > 1 else 0.0,
            })
        else:
            for k in ("mean", "median", "min", "q25", "q50", "q75",
                       "p90", "p95", "p99", "p995", "p999", "max", "std"):
                row[k] = None

        uv = _get_unique_values(s, max_display=10, absolute_threshold=200)
        row["top_values"] = uv if isinstance(uv, list) else []
        rows.append(row)

    return pd.DataFrame(rows)
