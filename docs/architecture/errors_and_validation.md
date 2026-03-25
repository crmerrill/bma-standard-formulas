# Errors and Validation

This document lists current error/validation behavior by subsystem.

## 1) Tape Ingestion

Primary exception:

- `TapeReadError`

Behavior:

- required-column failures raise immediately
- row parse issues are aggregated into one error with:
  - row index
  - `loan_id` when available
  - exception type
  - compact cause chain

Parser strictness:

- integer fields are strict by user-visible behavior:
  - integer-like text is accepted
  - float/scientific/decimal formats are rejected for integer fields
- float coercion for integer fields is rejected

Unexpected exceptions:

- only `ValueError` and `TypeError` are wrapped during row parse aggregation
- other exceptions propagate

## 2) Loan Validation

`Loan.__post_init__` raises `ValueError` for:

- invalid term/balance relationships
- invalid cap/floor ordering
- required date missing or unparsable
- provided optional date unparsable
- as-of date before origination

## 3) Formula Runner Validation

`run_bma_scheduled_cashflow` and `run_bma_actual_cashflow` validate:

- nonnegative/positive balance/term inputs
- finite coupon vectors
- coupon-vector length compatibility
- curve length/domain constraints

`payment_models` functions include explicit domain guards in key entry points:

- `smm_from_factors`
- `historical_psa`
- `historical_psa_pool`

## 4) Portfolio Validation

`PortfolioCashflow` raises:

- `PortfolioModeError` for invalid type-mode combinations
- `ValueError` for invalid history cap or missing constituent on subtract
- `ValueError` in `rewind` for unavailable historical versions (trimmed history)
- `TypeError` when a requested aggregate view (`scheduled`/`pool`) finds
  incompatible constituent types during lazy aggregation

Lifecycle warning:

- `ResourceWarning` when persistent writer was not closed explicitly/context-managed

## 5) Persistence Validation

`SchemaValidationError` is used for:

- missing `cf_type` column
- unknown `cf_type`
- append schema mismatch
- invalid persistence file structure

ID filter behavior:

- `read_scheduled(path, cf_id=...)` raises `ValueError` if `cf_id` is missing
  or belongs to a non-scheduled row.
- `read_actual(path, cf_id=...)` raises `ValueError` if `cf_id` is missing
  or belongs to a non-actual row.
- `read_cashflows(...)` returns a possibly empty list for unmatched filters.

## 6) Recommended Error Reporting Pattern for Integrators

For orchestration scripts/services:

- catch and log:
  - `TapeReadError`
  - `SchemaValidationError`
  - `PortfolioModeError` (from `bma_standard_formulas.formulas`)
  - `CashFlowPairValidationError` (from `bma_standard_formulas.formulas`)
  - `ValueError` (domain issues)
  - `TypeError` (view/type mismatch during lazy portfolio aggregation)
- include:
  - scenario id
  - input file paths
  - loan id when available
  - root cause chain

Additional portfolio-specific validation failures:

- `PortfolioCashflow.load_rewind_components(...)` raises `ValueError` for
  duplicate `cf_id` entries in persisted history files.
