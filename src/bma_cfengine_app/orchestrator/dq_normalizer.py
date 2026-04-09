"""Delinquency / FC / REO normalization layer.

===============================================================================
PURPOSE
===============================================================================
Mortgage loan tapes represent delinquency in wildly different ways depending
on the data source: integer status codes (agency CRT), days-past-due columns,
pay-through-date arithmetic, boolean FC/REO flags, pre-bucketed balance
columns, or zero-balance disposition codes.  This module auto-detects which
representation a tape uses and materializes a canonical set of columns so
that downstream analytics (strats, assumption resolution, DQ-conditional
curves) can consume a uniform interface.

===============================================================================
CANONICAL OUTPUT COLUMNS
===============================================================================
After normalization, the working copy DataFrame gains these computed columns::

    dlq_status    : str  — "Current", "30 DPD", "60 DPD", ..., "180+ DPD", "FC", "REO"
    days_past_due : int  — 0, 30, 60, 90, 120, 150, 180  (numeric, for sorting/bucketing)
    is_fc         : bool — True if loan is in foreclosure
    is_reo        : bool — True if loan is REO / liquidated

These columns are tape-level enrichment — they live alongside the original
columns in the working copy and are available for strats, filtering, and
summary.  They also feed the ``Loan.days_past_due`` and ``Loan.loan_status``
fields when TapeSchema reads the working copy into Loan objects.

===============================================================================
DETECTION + SUGGESTION FLOW
===============================================================================
1. ``detect_dq_pattern(df)``  → examines column names, dtypes, sample values
2. ``suggest_dq_mapping(df)`` → builds a structured ``DqMapping`` suggestion
3. ``materialize_dq_columns(df, mapping)`` → computes and adds canonical columns

The UI shows the suggestion, lets the user override, and then calls
``materialize_dq_columns`` to produce the working copy enrichment.

===============================================================================
PATTERN PRIORITY
===============================================================================
1. **Status code** — ``dqstatus``, ``dlq_status``, ``delinquency_status``
2. **Days past due** — ``dpd``, ``days_past_due``, ``days_delinquent``
3. **Pay-through date** — ``paid_thru_date`` + ``asof_date`` → month diff
4. **Boolean flags** — ``is_fc``, ``in_foreclosure``, ``is_reo``, ``reo_flag``
5. **Balance buckets** — ``delinq_31_60``, ``delinq_61_90``, etc.
6. **Zero balance code** — always checked as supplementary FC/REO source

Multiple patterns can coexist (e.g. ``dqstatus`` + ``zerobal_code``).

See Also:
    ``bma_cfengine_app.orchestrator.strats``
        Consumes the canonical columns for DQ distribution in strat tables.
    ``bma_standard_formulas.engine.loan.Loan``
        ``days_past_due`` and ``loan_status`` fields populated from canonical
        columns during tape-to-Loan conversion.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel


# =============================================================================
# Data Model
# =============================================================================


DqPatternType = Literal[
    "status_code",
    "days_past_due",
    "pay_through",
    "boolean_flags",
    "balance_buckets",
    "none",
]

#: Maps integer DQ status codes (agency convention) to canonical labels.
STATUS_CODE_TO_LABEL: dict[int, str] = {
    0: "Current",
    1: "30 DPD",
    2: "60 DPD",
    3: "90 DPD",
    4: "120 DPD",
    5: "150 DPD",
    6: "180+ DPD",
}

#: Maps canonical DQ labels to numeric days-past-due for sorting/bucketing.
LABEL_TO_DPD: dict[str, int] = {
    "Current": 0,
    "30 DPD": 30,
    "60 DPD": 60,
    "90 DPD": 90,
    "120 DPD": 120,
    "150 DPD": 150,
    "180+ DPD": 180,
    "FC": 0,
    "REO": 0,
}

#: Maps days-past-due numeric values to canonical status labels.
DPD_TO_LABEL: dict[int, str] = {
    0: "Current",
    30: "30 DPD",
    60: "60 DPD",
    90: "90 DPD",
    120: "120 DPD",
    150: "150 DPD",
    180: "180+ DPD",
}

#: Maps canonical labels to loan_status values for the Loan dataclass.
LABEL_TO_LOAN_STATUS: dict[str, str] = {
    "Current": "current",
    "30 DPD": "30_dpd",
    "60 DPD": "60_dpd",
    "90 DPD": "90_dpd",
    "120 DPD": "120_dpd",
    "150 DPD": "150_dpd",
    "180+ DPD": "180_dpd",
    "FC": "fc",
    "REO": "reo",
}


class DqMapping(BaseModel):
    """Structured mapping describing how to derive canonical DQ columns.

    Populated by ``suggest_dq_mapping`` (auto-detected) or by the user via
    the UI.  Consumed by ``materialize_dq_columns`` to produce the canonical
    columns on the working copy DataFrame.

    Attributes:
        pattern:         Which DQ representation the tape uses.
        status_col:      Column containing integer DQ status codes.
        dpd_col:         Column containing days-past-due values.
        pay_thru_col:    Column containing pay-through date.
        asof_col:        Column containing as-of / reporting date.
        fc_col:          Column containing FC indicator (boolean, or codes).
        fc_values:       Values in *fc_col* that mean "in foreclosure" (auto or user-edited).
        reo_col:         Column containing REO indicator (boolean, or codes).
        reo_values:      Values in *reo_col* that mean "REO" (auto or user-edited).
        status_code_map: Override map from status code → canonical label.
        balance_bucket_cols: Map of canonical bucket → actual column name
                          (for ``balance_buckets`` pattern).
        confidence:      Detection confidence (0.0–1.0).
        notes:           Human-readable detection notes.
    """
    pattern: DqPatternType = "none"

    status_col: str | None = None
    dpd_col: str | None = None
    pay_thru_col: str | None = None
    asof_col: str | None = None

    fc_col: str | None = None
    fc_values: list[Any] | None = None

    reo_col: str | None = None
    reo_values: list[Any] | None = None

    status_code_map: dict[str, str] | None = None
    balance_bucket_cols: dict[str, str] | None = None

    confidence: float = 0.0
    notes: str = ""


# =============================================================================
# Pattern Detection Heuristics
# =============================================================================


# --- Column name patterns for each DQ representation ---

_STATUS_CODE_PATTERNS: list[str] = [
    "dqstatus", "dlq_status", "delinquency_status",
    "current_loan_delinquency_status", "dlq",
]

_DPD_PATTERNS: list[str] = [
    "dpd", "days_past_due", "days_delinquent", "months_delinquent",
]

_PAY_THRU_PATTERNS: list[str] = [
    "paid_thru_date", "last_paid_installment_date", "pay_through_date",
]

_ASOF_PATTERNS: list[str] = [
    "asof_date", "as_of_date", "report_date", "reporting_date",
    "cutoff_date", "monthly_reporting_period", "month",
]

_FC_PATTERNS: list[str] = [
    "is_fc", "is_foreclosure", "in_foreclosure", "fc_flag",
    "in_fc", "foreclosure_flag",
]

_REO_PATTERNS: list[str] = [
    "is_reo", "reo_flag", "in_reo", "reo_status",
]

_ZB_CODE_PATTERNS: list[str] = [
    "zerobal_code", "zero_balance_code", "zero_bal_code", "zb_code",
]

_BALANCE_BUCKET_MAP: dict[str, list[str]] = {
    "delinq_31_60":  ["delinq_31_60", "dq_30", "dq30", "dlq_30_59"],
    "delinq_61_90":  ["delinq_61_90", "dq_60", "dq60", "dlq_60_89"],
    "delinq_91_120": ["delinq_91_120", "dq_90", "dq90", "dlq_90_119"],
    "delinq_121_179": ["delinq_121_179", "dq_120", "dq120", "dlq_120_179"],
    "delinq_ge_180": ["delinq_ge_180", "dq_180", "dq180", "dlq_180_plus"],
}

#: Zero-balance codes indicating foreclosure (agency CRT convention).
FC_ZB_CODES: set[int] = {2, 3, 6}

#: Zero-balance codes indicating REO disposition (agency CRT convention).
REO_ZB_CODES: set[int] = {9, 15, 16}


def _find_col(df: pd.DataFrame, patterns: list[str]) -> str | None:
    """Find the first DataFrame column whose lowercased name matches a pattern."""
    col_lower = {c.lower(): c for c in df.columns}
    for pattern in patterns:
        if pattern.lower() in col_lower:
            return col_lower[pattern.lower()]
    return None


def _find_balance_buckets(df: pd.DataFrame) -> dict[str, str]:
    """Find pre-bucketed DQ balance columns present in the DataFrame."""
    col_lower = {c.lower(): c for c in df.columns}
    found: dict[str, str] = {}
    for canonical, aliases in _BALANCE_BUCKET_MAP.items():
        for alias in aliases:
            if alias.lower() in col_lower:
                found[canonical] = col_lower[alias.lower()]
                break
    return found


def _is_small_int_status(series: pd.Series) -> bool:
    """Check if a numeric series looks like integer DQ status codes (0-10)."""
    valid = series.dropna()
    if valid.empty:
        return False
    if not pd.api.types.is_numeric_dtype(valid):
        return False
    vmin, vmax = float(valid.min()), float(valid.max())
    return vmin >= 0 and vmax <= 10 and (valid == valid.astype(int)).all()


def _is_dpd_like(series: pd.Series) -> bool:
    """Check if a numeric series looks like days-past-due (multiples of 30)."""
    valid = series.dropna()
    if valid.empty:
        return False
    if not pd.api.types.is_numeric_dtype(valid):
        return False
    uniques = set(valid.unique())
    dpd_values = {0, 30, 60, 90, 120, 150, 180}
    return len(uniques & dpd_values) >= 2 or all(v % 30 == 0 for v in uniques if v >= 0)


def detect_dq_pattern(df: pd.DataFrame) -> DqMapping:
    """Examine a tape DataFrame to identify which DQ representation it uses.

    Checks column names, dtypes, and sample values against known patterns
    in priority order.  Returns a ``DqMapping`` with the detected pattern
    and the source columns identified.

    Zero-balance codes are always checked as a supplementary FC/REO source
    regardless of the primary DQ pattern.

    Args:
        df: Loan-level DataFrame (raw or mapped).

    Returns:
        ``DqMapping`` describing the detected pattern.  ``pattern="none"``
        if no DQ data is found.

    Examples::

        mapping = detect_dq_pattern(df)
        if mapping.pattern != "none":
            print(f"Detected: {mapping.pattern} via {mapping.status_col or mapping.dpd_col}")
    """
    # --- Supplementary FC/REO sources (checked for all patterns) ---
    zb_col = _find_col(df, _ZB_CODE_PATTERNS)
    fc_col_bool = _find_col(df, _FC_PATTERNS)
    reo_col_bool = _find_col(df, _REO_PATTERNS)

    # Build supplementary FC/REO info
    fc_col = None
    fc_values: list[Any] | None = None
    reo_col = None
    reo_values: list[Any] | None = None

    if zb_col is not None:
        fc_col = zb_col
        fc_values = sorted(FC_ZB_CODES)
        reo_col = zb_col
        reo_values = sorted(REO_ZB_CODES)

    if fc_col_bool is not None:
        fc_col = fc_col_bool
        fc_values = _detect_boolean_true_values(df[fc_col_bool])

    if reo_col_bool is not None:
        reo_col = reo_col_bool
        reo_values = _detect_boolean_true_values(df[reo_col_bool])

    # --- 1. Status code ---
    status_col = _find_col(df, _STATUS_CODE_PATTERNS)
    if status_col is not None and _is_small_int_status(df[status_col]):
        code_map = dict(STATUS_CODE_TO_LABEL)
        return DqMapping(
            pattern="status_code",
            status_col=status_col,
            status_code_map={str(k): v for k, v in code_map.items()},
            fc_col=fc_col,
            fc_values=fc_values,
            reo_col=reo_col,
            reo_values=reo_values,
            confidence=0.9,
            notes=f"Integer status codes detected in '{status_col}'.",
        )

    # --- 2. Days past due ---
    dpd_col = _find_col(df, _DPD_PATTERNS)
    if dpd_col is not None and pd.api.types.is_numeric_dtype(df[dpd_col]):
        conf = 0.85 if _is_dpd_like(df[dpd_col]) else 0.5
        return DqMapping(
            pattern="days_past_due",
            dpd_col=dpd_col,
            fc_col=fc_col,
            fc_values=fc_values,
            reo_col=reo_col,
            reo_values=reo_values,
            confidence=conf,
            notes=f"Numeric days-past-due detected in '{dpd_col}'.",
        )

    # --- 3. Pay-through date ---
    pay_thru_col = _find_col(df, _PAY_THRU_PATTERNS)
    asof_col = _find_col(df, _ASOF_PATTERNS)
    if pay_thru_col is not None and asof_col is not None:
        return DqMapping(
            pattern="pay_through",
            pay_thru_col=pay_thru_col,
            asof_col=asof_col,
            fc_col=fc_col,
            fc_values=fc_values,
            reo_col=reo_col,
            reo_values=reo_values,
            confidence=0.7,
            notes=(
                f"Pay-through date '{pay_thru_col}' with as-of date "
                f"'{asof_col}' — DPD computed as month difference."
            ),
        )

    # --- 4. Boolean flags ---
    if fc_col_bool is not None or reo_col_bool is not None:
        return DqMapping(
            pattern="boolean_flags",
            fc_col=fc_col,
            fc_values=fc_values,
            reo_col=reo_col,
            reo_values=reo_values,
            confidence=0.6,
            notes="Boolean FC/REO flag columns detected.",
        )

    # --- 5. Balance buckets ---
    bucket_cols = _find_balance_buckets(df)
    if bucket_cols:
        return DqMapping(
            pattern="balance_buckets",
            balance_bucket_cols=bucket_cols,
            fc_col=fc_col,
            fc_values=fc_values,
            reo_col=reo_col,
            reo_values=reo_values,
            confidence=0.65,
            notes=f"Pre-bucketed DQ balance columns found: {list(bucket_cols.values())}.",
        )

    # --- 6. No DQ data ---
    return DqMapping(
        pattern="none",
        fc_col=fc_col if fc_col else None,
        fc_values=fc_values if fc_col else None,
        reo_col=reo_col if reo_col else None,
        reo_values=reo_values if reo_col else None,
        confidence=0.0,
        notes="No delinquency data detected.",
    )


def suggest_dq_mapping(df: pd.DataFrame) -> DqMapping:
    """Auto-detect DQ pattern and return a mapping suggestion.

    Convenience wrapper around ``detect_dq_pattern`` — identical behavior,
    provided as a separate function for semantic clarity in the API layer
    (detect = inspection, suggest = actionable recommendation).

    Args:
        df: Loan-level DataFrame.

    Returns:
        ``DqMapping`` suggestion ready for user review and override.
    """
    return detect_dq_pattern(df)


# =============================================================================
# Materialization
# =============================================================================


def _mask_disposition_codes(series: pd.Series, codes: list[Any] | None) -> pd.Series:
    """Row mask: *series* matches any value in *codes*.

    Tolerates CSV type drift (``"2"`` vs ``2``) and mixed string/numeric codes.
    """
    if not codes:
        return pd.Series(False, index=series.index)
    mask = pd.Series(False, index=series.index)
    sn = pd.to_numeric(series, errors="coerce")
    for code in codes:
        mask |= series == code
        if isinstance(code, bool):
            continue
        if isinstance(code, (int, float)) and not isinstance(code, bool):
            mask |= sn == float(code)
            continue
        cs = str(code).strip()
        mask |= series.astype(str).str.strip().str.upper() == cs.upper()
        try:
            mask |= sn == float(cs)
        except (ValueError, TypeError):
            pass
    return mask


def materialize_dq_columns(
    df: pd.DataFrame,
    mapping: DqMapping,
) -> pd.DataFrame:
    """Apply a DQ mapping to produce canonical columns on a DataFrame.

    Adds four columns to the DataFrame: ``dlq_status`` (str), ``days_past_due``
    (int), ``is_fc`` (bool), ``is_reo`` (bool).  The input DataFrame is
    copied; the original is never modified.

    Args:
        df:      Loan-level DataFrame (working copy).
        mapping: ``DqMapping`` describing how to derive canonical columns.

    Returns:
        New DataFrame with canonical DQ columns appended.

    Raises:
        ValueError: If the mapping references columns not present in *df*.

    Examples::

        mapping = suggest_dq_mapping(df)
        enriched = materialize_dq_columns(df, mapping)
        print(enriched[["dlq_status", "days_past_due", "is_fc", "is_reo"]].head())
    """
    result = df.copy()
    n = len(result)

    # Initialize canonical columns with safe defaults
    dlq_status = pd.Series(["Current"] * n, index=result.index)
    days_past_due = pd.Series(np.zeros(n, dtype=int), index=result.index)
    is_fc = pd.Series(np.zeros(n, dtype=bool), index=result.index)
    is_reo = pd.Series(np.zeros(n, dtype=bool), index=result.index)

    if mapping.pattern == "status_code":
        dlq_status, days_past_due = _materialize_status_code(result, mapping)

    elif mapping.pattern == "days_past_due":
        dlq_status, days_past_due = _materialize_dpd(result, mapping)

    elif mapping.pattern == "pay_through":
        dlq_status, days_past_due = _materialize_pay_through(result, mapping)

    elif mapping.pattern == "balance_buckets":
        pass  # Balance bucket tapes don't have per-loan DQ — columns stay at defaults

    # --- FC/REO overlay (applies regardless of primary pattern) ---
    if mapping.fc_col and mapping.fc_col in result.columns and mapping.fc_values:
        fc_mask = _mask_disposition_codes(result[mapping.fc_col], mapping.fc_values)
        is_fc = is_fc | fc_mask
        dlq_status = dlq_status.where(~fc_mask, "FC")

    if mapping.reo_col and mapping.reo_col in result.columns and mapping.reo_values:
        reo_mask = _mask_disposition_codes(result[mapping.reo_col], mapping.reo_values)
        is_reo = is_reo | reo_mask
        dlq_status = dlq_status.where(~reo_mask, "REO")

    # --- Boolean flags pattern ---
    if mapping.pattern == "boolean_flags":
        pass  # FC/REO already handled above

    result["dlq_status"] = dlq_status
    result["days_past_due"] = days_past_due
    result["is_fc"] = is_fc
    result["is_reo"] = is_reo

    return result


# =============================================================================
# Pattern-Specific Materialization
# =============================================================================


def _materialize_status_code(
    df: pd.DataFrame,
    mapping: DqMapping,
) -> tuple[pd.Series, pd.Series]:
    """Derive canonical DQ from integer status codes (agency convention).

    Status codes: 0=Current, 1=30DPD, 2=60DPD, ..., 6+=180+DPD.
    Uses the mapping's ``status_code_map`` for label lookup, falling back
    to ``STATUS_CODE_TO_LABEL`` for unmapped codes.
    """
    col = mapping.status_col
    if col is None or col not in df.columns:
        raise ValueError(f"Status column '{col}' not found in DataFrame.")

    code_map = {}
    if mapping.status_code_map:
        code_map = {int(k): v for k, v in mapping.status_code_map.items()}
    else:
        code_map = dict(STATUS_CODE_TO_LABEL)

    raw = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    def _code_to_label(code: int) -> str:
        if code in code_map:
            return code_map[code]
        if code > 6:
            return "180+ DPD"
        return "Current"

    labels = raw.map(_code_to_label)
    dpd = labels.map(lambda lbl: LABEL_TO_DPD.get(lbl, 0))

    return labels, dpd


def _materialize_dpd(
    df: pd.DataFrame,
    mapping: DqMapping,
) -> tuple[pd.Series, pd.Series]:
    """Derive canonical DQ from a numeric days-past-due column.

    Snaps raw DPD values to the nearest standard bucket boundary (0, 30, 60,
    90, 120, 150, 180) so that non-standard values (e.g. 45, 91) are
    normalized consistently.
    """
    col = mapping.dpd_col
    if col is None or col not in df.columns:
        raise ValueError(f"DPD column '{col}' not found in DataFrame.")

    raw = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # Snap to nearest standard DPD bucket
    boundaries = [0, 30, 60, 90, 120, 150, 180]

    def _snap_dpd(val: int) -> int:
        if val <= 0:
            return 0
        if val >= 180:
            return 180
        for i in range(len(boundaries) - 1):
            if val <= boundaries[i + 1]:
                return boundaries[i + 1] if (val - boundaries[i]) >= 15 else boundaries[i]
        return 180

    dpd = raw.map(_snap_dpd)
    labels = dpd.map(lambda d: DPD_TO_LABEL.get(d, "180+ DPD"))

    return labels, dpd


def _materialize_pay_through(
    df: pd.DataFrame,
    mapping: DqMapping,
) -> tuple[pd.Series, pd.Series]:
    """Derive canonical DQ from pay-through date minus as-of date.

    Computes the month difference between the as-of date and the last paid
    installment date.  A positive difference means the loan is delinquent
    by that many months (× 30 days).
    """
    pay_col = mapping.pay_thru_col
    asof_col = mapping.asof_col
    if not pay_col or pay_col not in df.columns:
        raise ValueError(f"Pay-through column '{pay_col}' not found in DataFrame.")
    if not asof_col or asof_col not in df.columns:
        raise ValueError(f"As-of column '{asof_col}' not found in DataFrame.")

    pay_dates = pd.to_datetime(df[pay_col], errors="coerce")
    asof_dates = pd.to_datetime(df[asof_col], errors="coerce")

    # Months delinquent = (asof_year*12 + asof_month) - (pay_year*12 + pay_month)
    months_dlq = (
        (asof_dates.dt.year * 12 + asof_dates.dt.month)
        - (pay_dates.dt.year * 12 + pay_dates.dt.month)
    ).fillna(0).astype(int)

    # Clamp negative values (paid ahead) to 0
    months_dlq = months_dlq.clip(lower=0)

    dpd = (months_dlq * 30).clip(upper=180)
    labels = dpd.map(lambda d: DPD_TO_LABEL.get(d, "180+ DPD"))

    return labels, dpd


# =============================================================================
# Helpers
# =============================================================================


def _detect_boolean_true_values(series: pd.Series) -> list[Any]:
    """Identify which values in a boolean-like column represent True.

    Handles actual booleans, Y/N strings, and 0/1 integers.
    """
    valid = series.dropna()
    if valid.empty:
        return [True]

    if valid.dtype == bool or valid.dtype == "bool":
        return [True]

    uniques = set(valid.unique())

    # Y/N strings
    str_uniques = {str(v).strip().upper() for v in uniques}
    if str_uniques <= {"Y", "N", "YES", "NO"}:
        return [v for v in uniques if str(v).strip().upper() in ("Y", "YES")]

    # 0/1 integers
    if uniques <= {0, 1, 0.0, 1.0}:
        return [1]

    # True/False strings
    if str_uniques <= {"TRUE", "FALSE"}:
        return [v for v in uniques if str(v).strip().upper() == "TRUE"]

    return [True]
