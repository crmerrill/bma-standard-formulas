"""Rates file handling: upload storage, preflight validation, RateDeck construction.

App-layer counterpart to bma_standard_formulas.engine.rates.  The split:

    engine.rates   → RateIndex/RateDeck, canonical index names, aliases, and the
                     readers that turn a DataFrame into curves.
    this module    → where the file lives, whether it's usable, and what to tell
                     the user if it isn't.

Canonical names and alias resolution deliberately live in the engine, so that a
rate file's column header and a loan tape's index_type cell resolve identically
whether the caller arrived over HTTP or from a notebook.
"""
from __future__ import annotations

import pandas as pd

from bma_standard_formulas.engine.rates import (
    RateDeck,
    RateDeckError,
    canonicalize_index_name,
    is_date_column,
)

from ..api.models import RatesPreflightResponse
from ..storage import run_store


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
        canon = canonicalize_index_name(raw_name) or raw_name.upper()
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

    blocking: list[str] = []
    warnings: list[str] = []

    # Classify the layout before parsing anything. A file we can't classify is a
    # blocking error the user can fix, not something to guess at.
    try:
        RateDeck.infer_layout(rates_df)
    except RateDeckError as e:
        return RatesPreflightResponse(
            required_indexes=required_canonical,
            required_index_loan_counts=required_map,
            blocking_errors=[str(e)],
        )

    date_cols = [c for c in rates_df.columns if is_date_column(c)]
    rate_columns = [c for c in rates_df.columns if not is_date_column(c)]

    # Span every date column — the paired layout carries one per curve.
    parsed = pd.concat(
        [pd.to_datetime(rates_df[c], errors="coerce") for c in date_cols]
    ).dropna()

    if parsed.empty:
        return RatesPreflightResponse(
            required_indexes=required_canonical,
            required_index_loan_counts=required_map,
            blocking_errors=[f"No parseable dates in column(s): {date_cols}"],
        )

    date_min = str(parsed.min().date())
    date_max = str(parsed.max().date())
    date_count = int(len(parsed))

    resolved: dict[str, str] = {}
    for req in required_canonical:
        for col in rate_columns:
            if canonicalize_index_name(str(col)) == req or str(col).upper() == req:
                resolved[req] = str(col)
                break

    missing = [r for r in required_canonical if r not in resolved]
    if missing:
        blocking.append(f"Missing rate index columns: {', '.join(missing)}")

    return RatesPreflightResponse(
        required_indexes=required_canonical,
        required_index_loan_counts=required_map,
        provided_columns=[str(c) for c in rate_columns],
        resolved_mapping=resolved,
        missing_indexes=missing,
        date_min=date_min,
        date_max=date_max,
        date_count=date_count,
        blocking_errors=blocking,
        warnings=warnings,
        all_fixed=False,
    )


def build_rate_deck_from_file(
    upload_id: str, mapping: dict[str, str] | None = None
) -> RateDeck | None:
    """Build a RateDeck from the uploaded rates file.

    One curve per index, each carrying its own date vector.  The portfolio
    runners route each loan to the curve named by its ``index_type``.

    Args:
        upload_id: Upload whose rates file to read.
        mapping:   Optional canonical index name → file column, as produced by
                   ``rates_preflight().resolved_mapping``.  When omitted, the
                   reader infers indexes from the column headers.

    Returns:
        RateDeck, or None if no rates file was uploaded.
    """
    rates_df = load_rates_df(upload_id)
    if rates_df is None:
        return None
    return RateDeck.from_frame(rates_df, columns=mapping or None, name=upload_id)
