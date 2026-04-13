# Outputs and Persistence

This document covers current output surfaces and persistence behavior.

## 1) Primary Output Surfaces

### In-memory objects

- `BMAScheduledCashflow`
- `BMAActualCashflow`
- `CashFlowPair`
- `PortfolioCashflow`

### DataFrame views

- leaf:
  - `scheduled_cf.to_dataframe()`
  - `actual_cf.to_dataframe()`
- portfolio:
  - `portfolio.to_dataframe()`
  - includes pool + waterfall side-by-side for actual/paired modes

## 2) Persistence APIs

- `write_cashflow(cf, path, mode)`
- `read_scheduled(...)`
- `read_actual(...)`
- `read_cashflows(...)`

Example:

```python
from bma_standard_formulas.engine import write_cashflow, read_actual

write_cashflow(actual_cf, path="out/loan_1_actual.parquet", mode="write")
loaded = read_actual("out/loan_1_actual.parquet", cf_id=actual_cf.cf_id)
```

`mode` values for `write_cashflow`:

- `write`: overwrite/create file
- `append`: append rows (requires compatible schema)
- `upsert`: replace same `cf_id` rows if present, otherwise append

### Important constraints

- files must include `cf_type` column
- append requires schema compatibility
- mismatches raise `SchemaValidationError`

## 3) Persistent Portfolio History

`PortfolioCashflow` supports writing pending constituents to parquet over time:

- constructor options:
  - `persistent_history=True`
  - `history_path=...`
- operation:
  - `flush()` writes current pending constituents
- finalize:
  - `close()` writes metadata footer and closes writer

Lifecycle safety:

- context manager is preferred
- unclosed writer triggers `ResourceWarning` in `__del__` with best-effort close

## 4) Metadata Fidelity

Scalar META is encoded in parquet metadata and decoded with dataclass type hints.

This is critical for round-trip fidelity of:

- identifiers
- terms/balances
- optional dates
- boolean flags

## 5) Rewind Output Contract

- reload:
  - `PortfolioCashflow.load_rewind_components(path)` returns `dict[cf_id, cashflow]`
- replay:
  - `portfolio.rewind(version, store)`

Failure modes:

- `ValueError` if version is older than retained history window
- `KeyError` if required `cf_id` is missing from supplied store

## 6) Recommended Output Layout (Operational Convention)

Not enforced by code, but recommended:

```text
runs/<run_name>/
  manifest.json
  assumptions_resolved.json
  portfolio_pool.parquet
  portfolio_scheduled.parquet
  constituents.parquet
  logs.txt
```

This keeps model outputs reproducible and reviewable.

## 7) Deal Run Manifest Provenance

Structuring deal runs and solver runs now persist collateral context in the run manifest
to make replay and audit easier.

- persisted at top-level manifest keys:
  - `tape_id`
  - `tape_mapping_id`
  - `pool_id`
  - `pool_version`
- persisted as full mirrored object:
  - `deal_context.collateral_risk_settings`
- source of truth:
  - extracted from the saved deal snapshot used for run/solve execution
  - not inferred from transient UI state at execution time
