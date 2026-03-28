"""Tape data quality diagnosis and user-approved repair suggestions.

Never modifies data without explicit apply. Flow:
1. diagnose_tape() -> TapeQualityReport (read-only scan)
2. preview_repair() -> shows what a specific rule would compute
3. apply_repair() -> user approved, apply one rule to the DataFrame
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def diagnose_tape(df: pd.DataFrame) -> dict[str, Any]:
    """Scan every column for missing/NaN values. Returns a summary dict."""
    total = len(df)
    issues: list[dict[str, Any]] = []
    for col in df.columns:
        missing = int(df[col].isna().sum())
        if missing > 0:
            issues.append({
                "column": col,
                "missing_count": missing,
                "total_count": total,
                "missing_pct": round(missing / total * 100, 2) if total else 0,
            })
    return {"total_rows": total, "issues": issues}


REPAIR_RULES: list[dict[str, Any]] = [
    {
        "id": "remaining_term_from_age",
        "target": "remaining_term",
        "sources": ["original_term", "loan_age"],
        "formula": "original_term - loan_age",
        "description": "Derive remaining_term as original_term minus loan_age",
    },
    {
        "id": "remaining_term_from_dates",
        "target": "remaining_term",
        "sources": ["original_term", "origination_date", "asof_date"],
        "formula": "original_term - months_between(origination_date, asof_date)",
        "description": "Derive remaining_term from original_term minus months elapsed since origination",
    },
    {
        "id": "original_term_from_age",
        "target": "original_term",
        "sources": ["remaining_term", "loan_age"],
        "formula": "remaining_term + loan_age",
        "description": "Derive original_term as remaining_term plus loan_age",
    },
    {
        "id": "current_balance_from_original",
        "target": "current_balance",
        "sources": ["original_balance"],
        "formula": "original_balance (copy as starting estimate)",
        "description": "Fill missing current_balance with original_balance as a conservative estimate",
    },
]


def available_repairs(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Return repair rules that are applicable given the columns present and missing."""
    results: list[dict[str, Any]] = []
    for rule in REPAIR_RULES:
        target = rule["target"]
        if target not in df.columns:
            continue
        missing = int(df[target].isna().sum())
        if missing == 0:
            continue
        if not all(s in df.columns for s in rule["sources"]):
            continue
        fixable = _count_fixable(df, rule)
        if fixable == 0:
            continue
        results.append({
            **rule,
            "missing_count": missing,
            "fixable_count": fixable,
        })
    return results


def preview_repair(df: pd.DataFrame, rule_id: str, limit: int = 20) -> dict[str, Any]:
    """Preview what a repair rule would produce without applying it.

    Returns rows where the target is currently missing, showing the source
    values and the computed result as a pseudo-column.
    """
    rule = _find_rule(rule_id)
    target = rule["target"]
    mask = df[target].isna()
    source_mask = pd.DataFrame({s: df[s].notna() for s in rule["sources"]}).all(axis=1)
    fixable_mask = mask & source_mask

    preview_df = df.loc[fixable_mask].head(limit).copy()
    computed = _compute_values(preview_df, rule)

    display_cols = ["loan_id"] if "loan_id" in preview_df.columns else []
    display_cols += rule["sources"]

    rows: list[dict[str, Any]] = []
    for i, (idx, row) in enumerate(preview_df.iterrows()):
        r: dict[str, Any] = {}
        for c in display_cols:
            r[c] = _safe_val(row.get(c))
        r[f"{target} (current)"] = _safe_val(row.get(target))
        r[f"{target} (computed)"] = _safe_val(computed.iloc[i]) if i < len(computed) else None
        rows.append(r)

    columns = display_cols + [f"{target} (current)", f"{target} (computed)"]

    return {
        "rule_id": rule_id,
        "rule": rule,
        "total_fixable": int(fixable_mask.sum()),
        "showing": len(rows),
        "columns": columns,
        "rows": rows,
    }


def apply_repair(df: pd.DataFrame, rule_id: str) -> tuple[pd.DataFrame, int]:
    """Apply a repair rule to the DataFrame. Returns (new_df, count_fixed)."""
    rule = _find_rule(rule_id)
    df = df.copy()
    target = rule["target"]

    mask = df[target].isna()
    source_mask = pd.DataFrame({s: df[s].notna() for s in rule["sources"]}).all(axis=1)
    fixable_mask = mask & source_mask

    if fixable_mask.sum() == 0:
        return df, 0

    computed = _compute_values(df.loc[fixable_mask], rule)
    df.loc[fixable_mask, target] = computed.values
    return df, int(fixable_mask.sum())


def _find_rule(rule_id: str) -> dict[str, Any]:
    for r in REPAIR_RULES:
        if r["id"] == rule_id:
            return r
    raise ValueError(f"Unknown repair rule: {rule_id}")


def _count_fixable(df: pd.DataFrame, rule: dict[str, Any]) -> int:
    target = rule["target"]
    mask = df[target].isna()
    source_mask = pd.DataFrame({s: df[s].notna() for s in rule["sources"]}).all(axis=1)
    return int((mask & source_mask).sum())


def _compute_values(subset: pd.DataFrame, rule: dict[str, Any]) -> pd.Series:
    """Execute the derivation logic for a rule on a DataFrame subset."""
    rid = rule["id"]

    if rid == "remaining_term_from_age":
        return subset["original_term"] - subset["loan_age"]

    if rid == "remaining_term_from_dates":
        orig = pd.to_datetime(subset["origination_date"])
        asof = pd.to_datetime(subset["asof_date"])
        months_elapsed = (asof.dt.year - orig.dt.year) * 12 + (asof.dt.month - orig.dt.month)
        return subset["original_term"] - months_elapsed

    if rid == "original_term_from_age":
        return subset["remaining_term"] + subset["loan_age"]

    if rid == "current_balance_from_original":
        return subset["original_balance"].copy()

    raise ValueError(f"No computation defined for rule: {rid}")


def _safe_val(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return v
