"""Rates file handling: upload storage, preflight validation, alias resolution, RateIndex construction."""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from bma_standard_formulas.engine.rate_index import RateIndex

from ..api.models import RatesPreflightResponse
from ..storage import run_store

CANONICAL_INDEXES = [
    "CMT1Y", "CMT3Y", "CMT5Y",
    "CODI", "COFI", "MTA12M",
    "LIBOR1M", "LIBOR3M", "LIBOR6M", "LIBOR1Y",
    "PRIME",
    "SOFR", "SOFR1M", "SOFR3M",
]

ALIAS_MAP: dict[str, str] = {
    "sofr_1m": "SOFR1M",
    "sofr_3m": "SOFR3M",
    "sofr": "SOFR",
    "1y_cmt": "CMT1Y",
    "1yr_cmt": "CMT1Y",
    "3y_cmt": "CMT3Y",
    "5y_cmt": "CMT5Y",
    "cmt_1y": "CMT1Y",
    "cmt_3y": "CMT3Y",
    "cmt_5y": "CMT5Y",
    "libor_1m": "LIBOR1M",
    "libor_3m": "LIBOR3M",
    "libor_6m": "LIBOR6M",
    "libor_1y": "LIBOR1Y",
    "wsj_prime": "PRIME",
    "prime": "PRIME",
    "mta": "MTA12M",
    "mta_12m": "MTA12M",
    "cofi": "COFI",
    "codi": "CODI",
}


def _canonicalize(name: str) -> str | None:
    """Resolve a column name to a canonical index, or None if not recognized."""
    norm = name.strip().lower().replace(" ", "_").replace("-", "_").replace(".", "_")
    if norm.upper() in CANONICAL_INDEXES:
        return norm.upper()
    return ALIAS_MAP.get(norm)


def save_rates_file(upload_id: str, file_name: str, content: bytes) -> None:
    d = run_store.upload_dir(upload_id) / "rates"
    d.mkdir(exist_ok=True)
    (d / file_name).write_bytes(content)


def load_rates_df(upload_id: str) -> pd.DataFrame | None:
    d = run_store.upload_dir(upload_id) / "rates"
    if not d.exists():
        return None
    files = list(d.glob("*"))
    if not files:
        return None
    f = files[0]
    if f.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(f)
    return pd.read_csv(f)


def rates_preflight(
    upload_id: str,
    mapping_id: str | None = None,
) -> RatesPreflightResponse:
    """Run preflight checks on the rates file vs. the tape's index requirements."""
    from .mapping import apply_mapping, sanitize_field_mappings
    from ..api.models import FieldMapping

    df_tape, _ = run_store.load_upload_df(upload_id)
    if mapping_id:
        try:
            mapping_data = run_store.load_mapping(upload_id, mapping_id)
            mappings = sanitize_field_mappings(
                [FieldMapping(**m) for m in mapping_data["mappings"]]
            )
            df_tape = apply_mapping(df_tape, mappings)
        except FileNotFoundError:
            pass

    if "index_type" not in df_tape.columns:
        return RatesPreflightResponse(all_fixed=True)

    index_counts: dict[str, int] = {}
    for val in df_tape["index_type"].dropna().unique():
        s = str(val).strip()
        if s:
            index_counts[s] = int((df_tape["index_type"] == val).sum())

    if not index_counts:
        return RatesPreflightResponse(all_fixed=True)

    required_canonical: list[str] = []
    required_map: dict[str, int] = {}
    for raw_name, count in index_counts.items():
        canon = _canonicalize(raw_name) or raw_name.upper()
        required_canonical.append(canon)
        required_map[canon] = count

    rates_df = load_rates_df(upload_id)
    if rates_df is None:
        return RatesPreflightResponse(
            required_indexes=required_canonical,
            required_index_loan_counts=required_map,
            missing_indexes=required_canonical,
            blocking_errors=[f"No rates file uploaded. {len(required_canonical)} index(es) needed."],
        )

    date_col = None
    for candidate in ("date", "Date", "DATE", "period", "month"):
        if candidate in rates_df.columns:
            date_col = candidate
            break
    if date_col is None:
        for col in rates_df.columns:
            if "date" in col.lower():
                date_col = col
                break

    blocking: list[str] = []
    warnings: list[str] = []

    if date_col is None:
        blocking.append("No date column found in rates file")
        return RatesPreflightResponse(
            required_indexes=required_canonical,
            required_index_loan_counts=required_map,
            blocking_errors=blocking,
        )

    try:
        dates = pd.to_datetime(rates_df[date_col])
        date_min = str(dates.min().date())
        date_max = str(dates.max().date())
        date_count = len(dates)
    except Exception:
        blocking.append(f"Cannot parse date column '{date_col}'")
        return RatesPreflightResponse(
            required_indexes=required_canonical,
            required_index_loan_counts=required_map,
            blocking_errors=blocking,
        )

    rate_columns = [c for c in rates_df.columns if c != date_col]
    provided = [c for c in rate_columns]

    resolved: dict[str, str] = {}
    for req in required_canonical:
        for col in rate_columns:
            canon = _canonicalize(col)
            if canon == req:
                resolved[req] = col
                break
            if col.upper() == req:
                resolved[req] = col
                break

    missing = [r for r in required_canonical if r not in resolved]
    if missing:
        blocking.append(f"Missing rate index columns: {', '.join(missing)}")

    return RatesPreflightResponse(
        required_indexes=required_canonical,
        required_index_loan_counts=required_map,
        provided_columns=provided,
        resolved_mapping=resolved,
        missing_indexes=missing,
        date_min=date_min,
        date_max=date_max,
        date_count=date_count,
        blocking_errors=blocking,
        warnings=warnings,
        all_fixed=False,
    )


def build_rate_index_from_file(upload_id: str, mapping: dict[str, str]) -> RateIndex | None:
    """Build a merged RateIndex from the rates file using the resolved column mapping."""
    rates_df = load_rates_df(upload_id)
    if rates_df is None:
        return None

    date_col = None
    for candidate in ("date", "Date", "DATE", "period", "month"):
        if candidate in rates_df.columns:
            date_col = candidate
            break
    if date_col is None:
        for col in rates_df.columns:
            if "date" in col.lower():
                date_col = col
                break
    if date_col is None:
        return None

    dates = pd.to_datetime(rates_df[date_col])
    date_list = [d.date() for d in dates]

    indexes: list[RateIndex] = []
    for canonical, file_col in mapping.items():
        if file_col not in rates_df.columns:
            continue
        rates = rates_df[file_col].astype(float).tolist()
        idx = RateIndex(
            dates=tuple(date_list),
            rates=tuple(rates),
            name=canonical,
        )
        indexes.append(idx)

    if not indexes:
        return None

    if len(indexes) == 1:
        return indexes[0]

    return RateIndex.merge(*indexes, name="merged")
