# Requires Python 3.12+
"""
Stratification engine — balance-weighted summary statistics by grouping column.

===============================================================================
PURPOSE
===============================================================================
Computes loan-level stratification ("strat") tables from a DataFrame of loan
data.  Given a grouping column (e.g. FICO score, state, LTV), the engine
bucketizes the column, groups loans into those buckets, and produces a table
of counts, balances, and balance-weighted averages per bucket.

This is the foundational analytics layer.  It deliberately excludes display
concerns (categorical label presets, DQ detection heuristics) — those belong
in the application layer which can pass custom ``bucket_fn`` and
``row_callback`` callables to extend the engine's behavior.

===============================================================================
KEY CONCEPTS
===============================================================================
**Bucket presets**
    Well-known bin edges for common mortgage attributes (FICO, LTV, DTI, term).
    When a column name matches a preset key, those edges are used instead of
    auto-computed quantile-based bins.

**Rate step fields**
    Columns representing interest rates or spreads, bucketed in 0.25% increments
    rather than equal-width bins.

**Balance-weighted averages**
    The standard in MBS analytics: a loan contributing more balance has
    proportionally more influence on the average.  WAC (weighted-average coupon),
    WAM (weighted-average maturity), WALA (weighted-average loan age) are all
    balance-weighted.

===============================================================================
USAGE
===============================================================================
::

    from bma_standard_formulas.engine.strats import (
        compute_strat,
        bucketize_column,
        available_strat_dimensions,
        summarize_tape,
    )

    strat_df = compute_strat(df, "borrower_fico", max_buckets=12)
    dims = available_strat_dimensions(df)

See Also:
    ``bma_cfengine_app.orchestrator.strats``
        Application-layer wrapper that adds categorical label presets,
        DQ distribution columns, and display-specific formatting.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd


# =============================================================================
# Bucket Presets
# =============================================================================
#
# Standard bin edges for common MBS collateral attributes, sourced from
# industry convention (Mosaic/stratutils).  When the grouping column name
# contains a preset key (case-insensitive), these edges are used verbatim
# to produce consistent, comparable strat tables across deals and vintages.

BUCKET_PRESETS: dict[str, list[float]] = {
    "fico": [300, 540, 580, 620, 640, 660, 680, 700, 720, 740, 760, 780, 800, 850],
    "ltv":  [30, 40, 50, 60, 65, 70, 75, 80, 85, 90, 95, 100, 105, 120],
    "dti":  [10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60],
    "term": [3, 6, 12, 24, 36, 48, 60, 84, 120, 180, 240, 360, 420],
}

#: Columns representing rates or spreads — bucketed in 0.25% steps rather
#: than equal-width bins so that rate strats align to market quoting convention.
RATE_STEP_FIELDS: set[str] = {"rate", "margin", "coupon", "wac"}


# =============================================================================
# Bucketing Helpers
# =============================================================================


def _round_to_nearest(x: float, base: float, method: str = "down") -> float:
    """Round *x* to the nearest multiple of *base*.

    Args:
        x:      Value to round.
        base:   Step size (e.g. 0.25 for quarter-point rate steps).
        method: ``"down"`` (floor), ``"up"`` (ceiling), or ``"nearest"`` (round).

    Returns:
        Rounded value.
    """
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
    """Compute bin edges for a numeric column.

    Uses preset edges when the column name matches a well-known attribute
    (FICO, LTV, DTI, term).  Rate-like columns get 0.25% steps.  All other
    numeric columns get equal-width bins capped at *max_buckets*.

    The returned edges always cover the full data range: the first edge is
    at or below the series minimum, and the last edge is at or above the
    maximum.

    Args:
        series:      Numeric pandas Series to bucketize.
        column_name: Column label — matched case-insensitively against preset
                     keys and rate-step field patterns.
        max_buckets: Maximum number of bins for columns without a preset.

    Returns:
        Sorted list of bin edges (floats) suitable for ``pd.cut()``.

    Examples::

        edges = bucketize_column(df["borrower_fico"], "borrower_fico")
        # → [300, 540, 580, 620, 640, 660, 680, 700, 720, 740, 760, 780, 800, 850]

        edges = bucketize_column(df["note_rate"], "note_rate", max_buckets=8)
        # → [3.0, 3.25, 3.5, ..., 5.0]  (0.25% steps)
    """
    valid = series.dropna()
    if valid.empty:
        return [0, 1]

    data_min = float(valid.min())
    data_max = float(valid.max())
    col_lower = column_name.lower()

    # --- Preset edges (FICO, LTV, DTI, term) ---
    for preset_key, preset_edges in BUCKET_PRESETS.items():
        if preset_key in col_lower:
            edges = [e for e in preset_edges if e <= data_max + 1e-9]
            if not edges or edges[-1] < data_max:
                edges.append(data_max)
            if edges[0] > data_min:
                edges.insert(0, data_min)
            return edges

    # --- Rate-step fields (0.25% increments) ---
    for rate_key in RATE_STEP_FIELDS:
        if rate_key in col_lower:
            if data_max <= data_min:
                return [data_min, data_min + 0.25]
            step = _round_to_nearest(
                (data_max - data_min) / max_buckets, base=0.25, method="down",
            )
            if step <= 0:
                step = 0.25
            edges = [data_min + step * i for i in range(max_buckets + 1)]
            if edges[-1] < data_max:
                edges[-1] = data_max
            return edges

    # --- Fallback: equal-width bins ---
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
    """Create a bucketed category Series for a DataFrame column.

    String and categorical columns pass through unchanged (converted to str).
    Numeric columns are bucketed via ``bucketize_column`` and ``pd.cut``.
    NaN values are labeled ``"N/A"`` so they are never silently dropped from
    groupby operations.

    This is the engine's default bucketing function.  The application layer
    can supply a custom ``bucket_fn`` to ``compute_strat`` that adds
    categorical-label presets or other display logic before falling through
    to this function.

    Args:
        df:          Source DataFrame.
        column:      Column name to bucketize.
        max_buckets: Maximum number of bins (passed to ``bucketize_column``).

    Returns:
        String Series of bucket labels, same length as *df*.

    See Also:
        ``bucketize_column``: Returns raw bin edges without applying ``pd.cut``.
    """
    if df[column].dtype in (object, "string", "category"):
        # Fill nulls before casting to str so None does not become literal "None".
        return df[column].astype("object").fillna("N/A").astype(str)

    edges = bucketize_column(df[column], column, max_buckets)
    result = pd.cut(df[column], bins=edges, include_lowest=True, duplicates="drop")
    result = result.astype(str).where(df[column].notna(), "N/A")
    return result


# =============================================================================
# Weighted Average
# =============================================================================


def _weighted_avg(values: pd.Series, weights: pd.Series) -> float:
    """Balance-weighted average, ignoring NaN and zero-weight rows.

    Args:
        values:  Numeric Series of values to average.
        weights: Numeric Series of weights (typically current or original
                 balance).

    Returns:
        Weighted average as a float, or 0.0 if no valid observations.
    """
    mask = values.notna() & weights.notna() & (weights > 0)
    if mask.sum() == 0:
        return 0.0
    return float(np.average(values[mask], weights=weights[mask]))


# =============================================================================
# Strat Table Generation
# =============================================================================


def compute_strat(
    df: pd.DataFrame,
    group_by: str | list[str],
    *,
    orig_bal_col: str = "original_balance",
    curr_bal_col: str = "current_balance",
    rate_col: str = "rate_margin",
    orig_term_col: str = "original_term",
    rem_term_col: str = "remaining_term",
    max_buckets: int = 10,
    bucket_fn: Callable[[pd.DataFrame, str, int], pd.Series] | None = None,
    row_callback: Callable[[dict[str, Any], pd.DataFrame, str], None] | None = None,
    totals_callback: Callable[[dict[str, Any], pd.DataFrame, str], None] | None = None,
    filter_: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Compute a stratification table grouped by one or more columns.

    Produces a DataFrame with one row per bucket (or bucket combination for
    multi-column cross-tabulation), showing loan counts, balance totals and
    percentages, pool factor, and balance-weighted averages.  A ``TOTAL`` row
    is always appended as the last row.

    **Single-column mode** (``group_by`` is a string):
        One row per bucket of the named column.

    **Cross-tabulation mode** (``group_by`` is a list of strings):
        Each column is bucketed independently.  The strat table has one row
        per unique combination of buckets, with the ``bucket`` column showing
        a pipe-delimited composite label (e.g. ``"(620, 640] | CA"``).

    Args:
        df:             Loan-level DataFrame.
        group_by:       Column name or list of column names to stratify by.
        orig_bal_col:   Column containing original UPB.
        curr_bal_col:   Column containing current UPB.
        rate_col:       Column containing coupon/rate (for WAC computation).
        orig_term_col:  Column containing original loan term in months.
        rem_term_col:   Column containing remaining term in months.
        max_buckets:    Maximum bins per numeric column (ignored for
                        categorical columns).
        bucket_fn:      Custom bucketing function with signature
                        ``(df, column, max_buckets) -> pd.Series``.  Defaults
                        to ``add_bucket_column``.  Pass an app-layer function
                        to add categorical-label presets or other display logic.
        row_callback:   Optional callable invoked for each group row after the
                        base metrics are computed.  Signature:
                        ``(row_dict, group_df, curr_bal_col) -> None``.
                        Mutate *row_dict* in place to add custom columns
                        (e.g. DQ distribution).
        totals_callback: Same as *row_callback* but invoked for the TOTAL row
                        with the full DataFrame.
        filter_:        Optional filter dict mapping bucket column names to
                        bucket values.  Only loans matching all filters are
                        included.  Useful for drill-down strats (e.g. strat
                        by state within a specific FICO bucket).

    Returns:
        DataFrame with columns: ``bucket``, ``count``, ``count_pct``,
        ``orig_bal``, ``orig_bal_pct``, ``curr_bal``, ``curr_bal_pct``,
        ``factor``, ``wa_rate``, ``wa_orig_term``, ``wa_rem_term``, ``wala``,
        plus any columns added by *row_callback*.

    Examples::

        # Single-column strat
        strat = compute_strat(df, "borrower_fico")

        # Cross-tabulation: FICO × State
        strat = compute_strat(df, ["borrower_fico", "prop_state"])

        # Drill-down: State strat within a specific FICO bucket
        strat = compute_strat(
            df, "prop_state",
            filter_={"borrower_fico_bucket": "(720, 740]"},
        )
    """
    if bucket_fn is None:
        bucket_fn = add_bucket_column

    work = df.copy()

    # --- Apply pre-filter (drill-down) ---
    if filter_:
        for col, val in filter_.items():
            if col in work.columns:
                work = work[work[col].astype(str) == str(val)]
        if work.empty:
            return _empty_strat_result()

    # --- Normalize group_by to list ---
    group_cols = [group_by] if isinstance(group_by, str) else list(group_by)

    # --- Bucket each grouping column independently ---
    grp_keys: list[str] = []
    for col in group_cols:
        if pd.api.types.is_numeric_dtype(work[col]):
            bucket_col = f"{col}_bucket"
            work[bucket_col] = bucket_fn(work, col, max_buckets)
            grp_keys.append(bucket_col)
        else:
            grp_keys.append(col)

    # --- Determine single-key vs composite groupby ---
    grp = grp_keys[0] if len(grp_keys) == 1 else grp_keys

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

        wa_rate = (
            _weighted_avg(sub[rate_col], w_curr)
            if rate_col in sub.columns and has_curr
            else 0.0
        )
        wa_orig_term = (
            _weighted_avg(sub[orig_term_col], w_orig)
            if orig_term_col in sub.columns and has_orig
            else 0.0
        )
        wa_rem_term = (
            _weighted_avg(sub[rem_term_col], w_curr)
            if rem_term_col in sub.columns and has_curr
            else 0.0
        )
        wala = wa_orig_term - wa_rem_term if (wa_orig_term > 0 and wa_rem_term > 0) else 0.0

        # Multi-column: composite label.  Single-column: plain string.
        if isinstance(key, tuple):
            bucket_label = " | ".join(str(k) for k in key)
        else:
            bucket_label = str(key)

        row: dict[str, Any] = {
            "bucket": bucket_label,
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

        if row_callback is not None:
            row_callback(row, sub, curr_bal_col)

        rows.append(row)

    result = pd.DataFrame(rows)

    # --- TOTAL row ---
    totals: dict[str, Any] = {
        "bucket": "TOTAL",
        "count": total_count,
        "count_pct": 100.0,
        "orig_bal": round(total_orig, 2),
        "orig_bal_pct": 100.0,
        "curr_bal": round(total_curr, 2),
        "curr_bal_pct": 100.0,
        "factor": round(total_curr / total_orig * 100, 2) if total_orig else 0.0,
        "wa_rate": (
            round(_weighted_avg(work[rate_col], work[curr_bal_col]), 4)
            if rate_col in work.columns and has_curr
            else 0.0
        ),
        "wa_orig_term": (
            round(_weighted_avg(work[orig_term_col], work[orig_bal_col]), 1)
            if orig_term_col in work.columns and has_orig
            else 0.0
        ),
        "wa_rem_term": (
            round(_weighted_avg(work[rem_term_col], work[curr_bal_col]), 1)
            if rem_term_col in work.columns and has_curr
            else 0.0
        ),
        "wala": 0.0,
    }
    totals["wala"] = round(totals["wa_orig_term"] - totals["wa_rem_term"], 1)

    if totals_callback is not None:
        totals_callback(totals, work, curr_bal_col)

    result = pd.concat([result, pd.DataFrame([totals])], ignore_index=True)
    return result


def _empty_strat_result() -> pd.DataFrame:
    """Return a minimal strat DataFrame for empty filter results."""
    return pd.DataFrame([{
        "bucket": "TOTAL", "count": 0, "count_pct": 100.0,
        "orig_bal": 0.0, "orig_bal_pct": 100.0,
        "curr_bal": 0.0, "curr_bal_pct": 100.0,
        "factor": 0.0, "wa_rate": 0.0,
        "wa_orig_term": 0.0, "wa_rem_term": 0.0, "wala": 0.0,
    }])


# =============================================================================
# Available Dimensions
# =============================================================================


def available_strat_dimensions(df: pd.DataFrame) -> list[dict[str, str]]:
    """Return columns suitable for stratification, with type metadata.

    Filters out private columns (prefixed with ``_``), single-valued columns,
    and high-cardinality categorical columns (>200 unique values).

    Args:
        df: Loan-level DataFrame.

    Returns:
        List of dicts with keys ``column``, ``type`` (``"numeric"`` or
        ``"categorical"``), and ``unique`` (count of distinct values).

    Examples::

        dims = available_strat_dimensions(df)
        # [{"column": "borrower_fico", "type": "numeric", "unique": 142}, ...]
    """
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


# =============================================================================
# Tape Summary Utilities
# =============================================================================
#
# Per-column descriptive statistics and unique-value profiles.  These are
# general-purpose tape profiling functions used by the Tape View UI.


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
    """Get top unique values for a column, sorted by frequency.

    Args:
        series:             Pandas Series to profile.
        max_display:        Maximum number of unique values to return.
        absolute_threshold: If the column has more unique values than this,
                            return an empty string (too many to display).

    Returns:
        List of unique values (most frequent first), or ``""`` if the column
        exceeds *absolute_threshold* unique values or is entirely null.
    """
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
    """Per-column summary: dtype, count, missing, missing%, unique count, top values.

    Args:
        df:                 Loan-level DataFrame.
        max_display:        Max unique values per column in the output.
        absolute_threshold: Columns with more uniques than this show empty
                            ``top_values``.

    Returns:
        DataFrame with one row per column and summary statistics.
    """
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
    """Per-column descriptive statistics: mean, median, quartiles, deciles, extremes.

    Numeric columns get full statistical profiles (mean, median, percentiles,
    min/max, std).  Non-numeric columns get ``None`` for all numeric stats.
    All columns get count, missing count/pct, unique count, and top values.

    Args:
        df: Loan-level DataFrame.

    Returns:
        DataFrame with one row per column and comprehensive descriptive
        statistics.
    """
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
