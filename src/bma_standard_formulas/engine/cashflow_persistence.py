# Requires Python 3.12+
from __future__ import annotations

"""
Parquet persistence for BMA cashflow objects.

Provides schema-validated read/write of BMAScheduledCashflow and BMAActualCashflow
to Parquet files using direct numpy <-> PyArrow conversion (no pandas in the I/O path).

Key design decisions:
  - Explicit Arrow schemas generated from FieldKind metadata at import time.
  - cf_type discriminator column ("scheduled" / "actual") for mixed files.
  - Scalar META fields stored as JSON in Parquet file-level metadata.
  - Schema validation on both read and write.
  - Direct numpy -> pa.array -> pa.Table (write) and pa.Table -> numpy (read).

Public API:
  write_cashflow(cf, path, mode)     — write any cashflow type
  read_scheduled(path, cf_id, ...)   — read scheduled CFs with type validation
  read_actual(path, cf_id, ...)      — read actual CFs with type validation
  read_cashflows(path, cf_id, ...)   — read any type, auto-detect per row group

Architecture layering:
  cashflow_persistence.py  → cashflows.py  (imports dataclass types)
  cashflows.py             → (lazy import of this module in thin wrapper methods)
"""

import json
from types import UnionType
from dataclasses import fields as dc_fields
from pathlib import Path
from typing import Union, get_args, get_origin, get_type_hints

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from bma_standard_formulas.formulas.cashflows import (
    BMAActualCashflow,
    BMAScheduledCashflow,
    FieldKind,
)


# =============================================================================
# Schema Definitions (metadata-driven)
# =============================================================================
#
# Schemas are built from the FieldKind tags on each dataclass.  Adding a new
# FLOW/STOCK/RATIO field to the dataclass automatically updates the schema.
# =============================================================================


class SchemaValidationError(ValueError):
    """Raised when a Parquet file's schema doesn't match the expected cashflow schema."""


def _build_schema(cls: type) -> pa.Schema:
    """Build a PyArrow schema from a cashflow dataclass's FieldKind-tagged fields.

    Includes cf_id (string) and cf_type (string) as the first two columns,
    then all primitive array fields (FLOW, STOCK, RATIO) as float64 and
    period as int64. Derived fields (those tagged with metadata
    ``"derived": True``) are EXCLUDED from the on-disk schema — they are
    fully recomputed by the dataclass __post_init__ on read from the
    primitive fields, so persisting them would be redundant storage and
    would also break round-trip (init=False fields can't be passed to
    __init__).

    Args:
        cls:  BMAScheduledCashflow or BMAActualCashflow.

    Returns:
        pa.Schema with one column per primitive array field plus cf_id
        and cf_type.
    """
    columns = [("cf_id", pa.string()), ("cf_type", pa.string())]
    for f in dc_fields(cls):
        kind = f.metadata.get("kind")
        if f.metadata.get("derived"):
            # Derived fields are recomputed on read; never written to disk.
            continue
        if f.name == "period":
            columns.append((f.name, pa.int64()))
        elif kind in (FieldKind.FLOW, FieldKind.STOCK, FieldKind.RATIO):
            columns.append((f.name, pa.float64()))
    return pa.schema(columns)


SCHEDULED_SCHEMA: pa.Schema = _build_schema(BMAScheduledCashflow)
ACTUAL_SCHEMA: pa.Schema = _build_schema(BMAActualCashflow)

# Map class -> (schema, cf_type string)
_TYPE_INFO: dict[type, tuple[pa.Schema, str]] = {
    BMAScheduledCashflow: (SCHEDULED_SCHEMA, "scheduled"),
    BMAActualCashflow: (ACTUAL_SCHEMA, "actual"),
}


# =============================================================================
# Metadata Encoding / Decoding
# =============================================================================


def _encode_meta(cf) -> dict[str, str]:
    """Extract scalar META fields from a cashflow as a string dict.

    Skips array META fields (period).  None values are encoded as "null".
    Dates are encoded as ISO strings.  Used for Parquet file-level metadata.

    Args:
        cf:  A BMAScheduledCashflow or BMAActualCashflow.

    Returns:
        dict[str, str]: All scalar META fields as string key-value pairs.
    """
    meta = {}
    for f in dc_fields(type(cf)):
        if f.metadata.get("kind") != FieldKind.META:
            continue
        val = getattr(cf, f.name)
        if isinstance(val, np.ndarray):
            continue
        meta[f.name] = "null" if val is None else str(val)
    return meta


def _decode_meta(raw: dict[str, str], cls: type) -> dict[str, object]:
    """Convert string metadata values back to typed Python values.

    Type inference is derived directly from dataclass META field annotations.
    "null"/"None"/"NaT" decode to None for optional metadata values.

    Args:
        raw:  String key-value pairs (from Parquet metadata or JSON).
        cls:  The target dataclass type.

    Returns:
        dict[str, object]: Typed values ready to pass as kwargs.
    """
    type_hints = get_type_hints(cls)
    meta_types = {
        f.name: type_hints.get(f.name, f.type)
        for f in dc_fields(cls)
        if f.metadata.get("kind") == FieldKind.META
    }
    typed = {}
    for key, val in raw.items():
        if key not in meta_types:
            continue
        if val in ("null", "None", "NaT"):
            typed[key] = None
            continue

        target_type = meta_types[key]
        origin = get_origin(target_type)
        union_arms: list[type] = []
        if origin in (Union, UnionType):
            union_arms = [a for a in get_args(target_type) if a is not type(None)]
            target_type = union_arms[0] if union_arms else object

        def _coerce(t: type, v: str) -> object:
            if t in (int, np.int64):
                return int(v)
            if t in (float, np.float64):
                return float(v)
            if t in (bool, np.bool_):
                return v.lower() in ("true", "1")
            if t is str:
                return v
            if t is np.datetime64:
                return np.datetime64(v)
            return v

        # For Union types with multiple concrete arms (e.g. int | str),
        # try each arm in order — BUT prefer str over int when str is an arm
        # and the value is not purely numeric.  This preserves orchestrator
        # group_ids like "GROUP_1" that would otherwise silently decode as
        # an int (int("GROUP_1") raises ValueError → str fallback is fine)
        # while pure-numeric strings like "42" still decode as int first.
        if union_arms:
            for arm in union_arms:
                try:
                    typed[key] = _coerce(arm, val)
                    break
                except (ValueError, TypeError):
                    continue
            else:
                typed[key] = val
        else:
            typed[key] = _coerce(target_type, val)
    return typed


# =============================================================================
# Direct numpy <-> Arrow Conversion
# =============================================================================


def _cf_to_arrow_table(cf, schema: pa.Schema, cf_type: str) -> pa.Table:
    """Convert a cashflow directly to a PyArrow Table from numpy arrays.

    Skips pandas entirely.  Each FLOW/STOCK/RATIO array field becomes a column.
    cf_id and cf_type are repeated for every row (one row per period).

    Args:
        cf:       A cashflow dataclass instance.
        schema:   The expected Arrow schema for this type.
        cf_type:  "scheduled" or "actual".

    Returns:
        pa.Table matching the schema.

    Raises:
        SchemaValidationError: If the constructed table doesn't match the schema.
    """
    n = len(cf.period)
    arrays: dict[str, pa.Array] = {
        "cf_id": pa.array([cf.cf_id] * n, type=pa.string()),
        "cf_type": pa.array([cf_type] * n, type=pa.string()),
    }
    for f in dc_fields(type(cf)):
        kind = f.metadata.get("kind")
        if f.metadata.get("derived"):
            # Derived fields are recomputed by __post_init__ on read; never written.
            continue
        if f.name == "period":
            arrays[f.name] = pa.array(getattr(cf, f.name), type=pa.int64())
        elif kind in (FieldKind.FLOW, FieldKind.STOCK, FieldKind.RATIO):
            arrays[f.name] = pa.array(getattr(cf, f.name), type=pa.float64())

    table = pa.table(arrays, schema=schema)
    return table


def _arrow_table_to_cf(table: pa.Table, cls: type, meta: dict) -> object:
    """Convert a PyArrow Table back to a cashflow using direct numpy extraction.

    Derived fields (those with metadata ``"derived": True``, e.g. act_prin,
    act_cash, total_bal, sched_cash) are skipped on read for two reasons:

      1. They are computed by the dataclass ``__post_init__`` from primitive
         flows / stocks, so passing them as constructor kwargs is unnecessary.
      2. They are declared with ``init=False``, so the constructor would
         reject them as keyword arguments.

    Defensively filtering on read keeps the path robust against older
    Parquet files written before the derived fields existed (or by future
    callers writing additional columns). The current write path
    (``_cf_to_table``) also skips derived fields, so a fresh round-trip
    never produces extra columns.

    Args:
        table:  Arrow table with array field columns (cf_id and cf_type excluded).
        cls:    BMAScheduledCashflow or BMAActualCashflow.
        meta:   Typed scalar META fields dict.

    Returns:
        A new frozen cashflow instance.
    """
    derived_field_names = {
        f.name for f in dc_fields(cls) if f.metadata.get("derived")
    }
    kwargs: dict = {}
    for col_name in table.column_names:
        if col_name in ("cf_id", "cf_type") or col_name in derived_field_names:
            continue
        kwargs[col_name] = table.column(col_name).to_numpy()
    kwargs.update(meta)
    return cls(**kwargs)


# =============================================================================
# Write
# =============================================================================


def write_cashflow(
    cf: BMAScheduledCashflow | BMAActualCashflow,
    path: str | Path | None = None,
    mode: str = "append",
) -> Path:
    """Write a cashflow to a Parquet file with schema validation.

    Array fields (FLOW, STOCK, RATIO, period) become columns.  Scalar META
    fields are stored as JSON in the Parquet file-level metadata footer.
    A cf_type column ("scheduled" / "actual") makes the file self-describing.

    Args:
        cf:    The cashflow to write.
        path:  File path.  If None, creates ``./cf_{cf_id}.parquet``.
        mode:  ``"write"`` (overwrite), ``"append"`` (default, may duplicate),
               or ``"upsert"`` (replace existing cf_id, else append).

    Returns:
        Path to the written file.

    Raises:
        ValueError: If mode is invalid.
        SchemaValidationError: If appending to a file with incompatible schema.
        TypeError: If cf is not a recognized cashflow type.
    """
    if mode not in ("write", "append", "upsert"):
        raise ValueError(f"mode must be 'write', 'append', or 'upsert', got {mode!r}")

    type_info = _TYPE_INFO.get(type(cf))
    if type_info is None:
        raise TypeError(f"Cannot write {type(cf).__name__} — expected BMAScheduledCashflow or BMAActualCashflow")
    schema, cf_type = type_info

    if path is None:
        path = Path(f"cf_{cf.cf_id}.parquet")
    else:
        path = Path(path)

    # Build Arrow table directly from numpy arrays
    table = _cf_to_arrow_table(cf, schema, cf_type)
    meta_dict = _encode_meta(cf)

    if mode == "write" or not path.exists():
        # Write fresh file
        cf_meta_store = {cf.cf_id: meta_dict}
        file_meta = {b"cf_meta": json.dumps(cf_meta_store).encode()}
        table = table.replace_schema_metadata(file_meta)
        pq.write_table(table, path)
        return path

    # File exists — read existing data
    existing_table = pq.read_table(path)

    # Schema compatibility check: existing file must have same columns
    # (allow metadata differences, just check column names and types)
    existing_cols = set(existing_table.column_names)
    new_cols = set(table.column_names)
    if existing_cols != new_cols:
        raise SchemaValidationError(
            f"Cannot append: column mismatch. "
            f"File has {sorted(existing_cols)}, new data has {sorted(new_cols)}"
        )

    # Extract existing metadata store
    existing_raw_meta = existing_table.schema.metadata or {}
    cf_meta_store = {}
    if b"cf_meta" in existing_raw_meta:
        cf_meta_store = json.loads(existing_raw_meta[b"cf_meta"])

    if mode == "upsert":
        # Remove rows with this cf_id
        cf_id_col = existing_table.column("cf_id").to_pylist()
        keep_indices = [i for i, cid in enumerate(cf_id_col) if cid != cf.cf_id]
        if keep_indices:
            existing_table = existing_table.take(keep_indices)
        else:
            existing_table = None

    # Combine tables
    if existing_table is not None and len(existing_table) > 0:
        # Cast new table to match existing schema exactly (handles metadata diffs)
        combined = pa.concat_tables([existing_table, table.cast(existing_table.schema)])
    else:
        combined = table

    # Update metadata store
    cf_meta_store[cf.cf_id] = meta_dict
    final_meta = {b"cf_meta": json.dumps(cf_meta_store).encode()}
    combined = combined.replace_schema_metadata(final_meta)
    pq.write_table(combined, path)
    return path


# =============================================================================
# Read
# =============================================================================


def _read_from_parquet(
    path: Path,
    cf_type_filter: str | None,
    target_cls: type | None,
    cf_id: str | None = None,
    loan_id: int | None = None,
    group_id: int | str | None = None,
) -> list:
    """Internal: read and filter cashflows from a Parquet file.

    Args:
        path:            Parquet file path.
        cf_type_filter:  "scheduled", "actual", or None (any type).
        target_cls:      The dataclass to construct, or None for auto-detect.
        cf_id:           Filter to one specific UUID.
        loan_id:         Filter by loan_id (from metadata).
        group_id:        Filter by group_id (from metadata).

    Returns:
        List of cashflow objects.
    """
    table = pq.read_table(path)

    # Validate cf_type column exists
    if "cf_type" not in table.column_names:
        raise SchemaValidationError(
            "Parquet file missing 'cf_type' column — not a cashflow persistence file"
        )

    # Extract metadata store
    raw_file_meta = table.schema.metadata or {}
    cf_meta_store: dict[str, dict] = {}
    if b"cf_meta" in raw_file_meta:
        cf_meta_store = json.loads(raw_file_meta[b"cf_meta"])

    # Convert to pandas-free filtering via Arrow compute
    cf_id_col = table.column("cf_id").to_pylist()
    cf_type_col = table.column("cf_type").to_pylist()

    # Get unique cf_ids in the file
    all_cf_ids = list(dict.fromkeys(cf_id_col))  # preserves order, removes dupes

    # Filter by requested identifiers
    target_ids = all_cf_ids
    if cf_id is not None:
        target_ids = [cf_id] if cf_id in all_cf_ids else []
    elif loan_id is not None or group_id is not None:
        target_ids = []
        for cid in all_cf_ids:
            meta = cf_meta_store.get(cid, {})
            if loan_id is not None and str(meta.get("loan_id", "")) != str(loan_id):
                continue
            if group_id is not None and str(meta.get("group_id", "")) != str(group_id):
                continue
            target_ids.append(cid)

    results = []
    for cid in target_ids:
        # Get rows for this cf_id
        row_indices = [i for i, c in enumerate(cf_id_col) if c == cid]
        if not row_indices:
            continue
        sub_table = table.take(row_indices)

        # Determine cf_type for this cf_id
        this_cf_type = cf_type_col[row_indices[0]]

        # Apply cf_type filter
        if cf_type_filter is not None and this_cf_type != cf_type_filter:
            continue

        # Resolve target class
        if target_cls is not None:
            cls = target_cls
        elif this_cf_type == "scheduled":
            cls = BMAScheduledCashflow
        elif this_cf_type == "actual":
            cls = BMAActualCashflow
        else:
            raise SchemaValidationError(f"Unknown cf_type: {this_cf_type!r}")

        # Decode metadata
        raw_meta = cf_meta_store.get(cid, {})
        typed_meta = _decode_meta(raw_meta, cls)

        # Construct cashflow from Arrow table (direct numpy extraction)
        cf_obj = _arrow_table_to_cf(sub_table, cls, typed_meta)
        results.append(cf_obj)

    return results


def read_scheduled(
    path: str | Path,
    cf_id: str | None = None,
    loan_id: int | None = None,
    group_id: int | str | None = None,
) -> BMAScheduledCashflow | list[BMAScheduledCashflow]:
    """Read scheduled cashflow(s) from a Parquet file.

    Validates that only scheduled-type rows are returned.  Raises if the file
    contains actual CFs and no scheduled CFs match the filter.

    Args:
        path:      Path to the Parquet file.
        cf_id:     Specific UUID.  Returns single object.
        loan_id:   Filter by loan_id.  Returns list.
        group_id:  Filter by group_id.  Returns list.

    Returns:
        Single BMAScheduledCashflow (if cf_id given) or list.

    Raises:
        ValueError: If cf_id not found.
        SchemaValidationError: If file is not a valid cashflow persistence file.
    """
    results = _read_from_parquet(
        Path(path), cf_type_filter="scheduled",
        target_cls=BMAScheduledCashflow,
        cf_id=cf_id, loan_id=loan_id, group_id=group_id,
    )
    if cf_id is not None:
        if not results:
            raise ValueError(f"cf_id {cf_id!r} not found (or not a scheduled CF) in {path}")
        return results[0]
    return results


def read_actual(
    path: str | Path,
    cf_id: str | None = None,
    loan_id: int | None = None,
    group_id: int | str | None = None,
) -> BMAActualCashflow | list[BMAActualCashflow]:
    """Read actual cashflow(s) from a Parquet file.

    Args:
        path:      Path to the Parquet file.
        cf_id:     Specific UUID.  Returns single object.
        loan_id:   Filter by loan_id.  Returns list.
        group_id:  Filter by group_id.  Returns list.

    Returns:
        Single BMAActualCashflow (if cf_id given) or list.

    Raises:
        ValueError: If cf_id not found.
    """
    results = _read_from_parquet(
        Path(path), cf_type_filter="actual",
        target_cls=BMAActualCashflow,
        cf_id=cf_id, loan_id=loan_id, group_id=group_id,
    )
    if cf_id is not None:
        if not results:
            raise ValueError(f"cf_id {cf_id!r} not found (or not an actual CF) in {path}")
        return results[0]
    return results


def read_cashflows(
    path: str | Path,
    cf_id: str | None = None,
    loan_id: int | None = None,
    group_id: int | str | None = None,
) -> list[BMAScheduledCashflow | BMAActualCashflow]:
    """Read any cashflow(s) from a Parquet file, auto-detecting type.

    Each cashflow's cf_type column determines whether it's constructed as
    BMAScheduledCashflow or BMAActualCashflow.

    Args:
        path:      Path to the Parquet file.
        cf_id:     Filter to one UUID.
        loan_id:   Filter by loan_id.
        group_id:  Filter by group_id.

    Returns:
        List of cashflow objects (may be mixed types).
    """
    return _read_from_parquet(
        Path(path), cf_type_filter=None, target_cls=None,
        cf_id=cf_id, loan_id=loan_id, group_id=group_id,
    )
