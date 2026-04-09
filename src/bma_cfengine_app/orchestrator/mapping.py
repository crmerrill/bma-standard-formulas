from __future__ import annotations

import pandas as pd

from bma_standard_formulas.engine.tape import TapeSchema, _normalize_col

from ..api.models import (
    ALL_CANONICAL_FIELDS,
    REQUIRED_FIELDS,
    ColumnProfile,
    FieldMapping,
    MappingValidation,
    TapeProfile,
)

# Not part of CFEngine tape mapping — pool/group is defined via Run Setup grouping keys.
_SKIP_TAPE_CANONICAL = frozenset({"group_id"})


def _norm_cf(name: str | None) -> str:
    """Normalize canonical field for comparisons (whitespace / case)."""
    return (name or "").strip().lower()


def sanitize_field_mappings(mappings: list[FieldMapping]) -> list[FieldMapping]:
    """Remove mappings the UI must not send (defense in depth for API clients)."""
    return [m for m in mappings if _norm_cf(m.canonical_field) not in _SKIP_TAPE_CANONICAL]


def profile_dataframe(df: pd.DataFrame, upload_id: str, file_name: str, file_size: int) -> TapeProfile:
    columns: list[ColumnProfile] = []
    for col in df.columns:
        series = df[col]
        samples = series.dropna().head(5).tolist()
        columns.append(
            ColumnProfile(
                name=str(col),
                dtype=str(series.dtype),
                sample_values=[str(v) for v in samples],
                null_count=int(series.isna().sum()),
                unique_count=int(series.nunique()),
            )
        )
    return TapeProfile(
        upload_id=upload_id,
        file_name=file_name,
        file_size_bytes=file_size,
        row_count=len(df),
        column_count=len(df.columns),
        columns=columns,
    )


def auto_infer_mappings(df_columns: list[str]) -> list[FieldMapping]:
    """Use TapeSchema's alias map to auto-infer column->canonical mappings."""
    schema = TapeSchema()
    inferred: list[FieldMapping] = []
    seen_canonical: set[str] = set()

    for col in df_columns:
        norm = _normalize_col(col)
        canonical = schema.column_map.get(norm)
        if canonical is None and norm in {s for s in ALL_CANONICAL_FIELDS}:
            canonical = norm
        if canonical and _norm_cf(canonical) in _SKIP_TAPE_CANONICAL:
            continue
        if canonical and canonical not in seen_canonical:
            inferred.append(FieldMapping(source_column=col, canonical_field=canonical))
            seen_canonical.add(canonical)

    return inferred


def validate_mapping(
    df: pd.DataFrame,
    explicit_mappings: list[FieldMapping],
    asof_date: str | None = None,
) -> MappingValidation:
    dropped_skip = [m for m in explicit_mappings if _norm_cf(m.canonical_field) in _SKIP_TAPE_CANONICAL]
    explicit_mappings = [
        m for m in explicit_mappings if _norm_cf(m.canonical_field) not in _SKIP_TAPE_CANONICAL
    ]

    all_mappings = list(explicit_mappings)
    explicit_canonicals = {m.canonical_field for m in explicit_mappings}
    inferred = auto_infer_mappings(list(df.columns))
    inferred_new = [
        m
        for m in inferred
        if m.canonical_field not in explicit_canonicals
        and _norm_cf(m.canonical_field) not in _SKIP_TAPE_CANONICAL
    ]
    all_mappings.extend(inferred_new)

    leaked = [m for m in all_mappings if _norm_cf(m.canonical_field) in _SKIP_TAPE_CANONICAL]
    all_mappings = [m for m in all_mappings if _norm_cf(m.canonical_field) not in _SKIP_TAPE_CANONICAL]

    allowed_norm = {_norm_cf(f) for f in ALL_CANONICAL_FIELDS}
    mapped_canonicals = {m.canonical_field for m in all_mappings}
    errors: list[str] = []
    warnings: list[str] = []

    if dropped_skip or leaked:
        warnings.append(
            "Mappings to group_id were ignored — define groups in Run Setup (grouping keys), "
            "not from the tape."
        )

    for m in all_mappings:
        cf = _norm_cf(m.canonical_field)
        if cf in _SKIP_TAPE_CANONICAL:
            continue
        if m.source_column not in df.columns:
            errors.append(f"Source column '{m.source_column}' not found in uploaded file")
        if cf not in allowed_norm:
            errors.append(f"'{m.canonical_field}' is not a recognized canonical field")

    unmapped_required: list[str] = []
    for req in REQUIRED_FIELDS:
        if req not in mapped_canonicals:
            if req == "asof_date" and asof_date:
                warnings.append("asof_date will be supplied from run-level parameter")
            else:
                unmapped_required.append(req)

    if unmapped_required:
        errors.append(f"Required fields not mapped: {', '.join(unmapped_required)}")

    return MappingValidation(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        mapped_fields=sorted(mapped_canonicals),
        unmapped_required=unmapped_required,
        inferred_mappings=inferred_new,
    )


def apply_mapping(df: pd.DataFrame, mappings: list[FieldMapping]) -> pd.DataFrame:
    """Rename source columns to canonical names per the mapping list."""
    rename_map = {m.source_column: m.canonical_field for m in mappings}
    return df.rename(columns=rename_map)
