from __future__ import annotations

import pandas as pd

from ..api.models import GroupingConfig, GroupPreview
from .strats import add_bucket_column


def compute_group_ids(
    df: pd.DataFrame,
    config: GroupingConfig,
) -> pd.Series:
    """Compute a deterministic group_id for each row from grouping keys.

    For numeric columns, applies strat-style bucketing so that continuous
    values (rates, balances, terms, etc.) are grouped into ranges.
    """
    parts: list[pd.Series] = []
    for key in config.keys:
        if key not in df.columns:
            raise ValueError(f"Grouping key '{key}' not found in tape columns")
        col = df[key]
        if pd.api.types.is_numeric_dtype(col):
            bucketed = add_bucket_column(df, key, max_buckets=10)
            parts.append(bucketed.astype(str).fillna("UNKNOWN"))
        else:
            col = col.copy()
            if config.missing_value_policy == "literal_unknown":
                col = col.fillna("UNKNOWN").replace("", "UNKNOWN")
            parts.append(col.astype(str))

    if len(config.keys) == 1:
        return parts[0]

    return parts[0].str.cat(parts[1:], sep="|")


_BALANCE_CANDIDATES = [
    "current_balance", "current_upb", "curr_upb", "curr_bal",
    "current_bal", "upb", "balance", "original_balance", "original_upb",
]


def preview_groups(
    df: pd.DataFrame,
    config: GroupingConfig,
    balance_col: str | None = None,
) -> list[GroupPreview]:
    group_ids = compute_group_ids(df, config)
    df_work = df.copy()
    df_work["__group_id__"] = group_ids

    if config.missing_value_policy == "exclude":
        for key in config.keys:
            df_work = df_work[df_work[key].notna() & (df_work[key] != "")]

    if balance_col and balance_col in df_work.columns:
        balance = balance_col
    else:
        balance = None
        for candidate in _BALANCE_CANDIDATES:
            if candidate in df_work.columns:
                balance = candidate
                break
    previews: list[GroupPreview] = []
    for gid, sub in df_work.groupby("__group_id__", sort=True):
        total_bal = float(sub[balance].sum()) if balance else 0.0
        previews.append(
            GroupPreview(group_id=str(gid), loan_count=len(sub), total_balance=total_bal)
        )
    return previews
