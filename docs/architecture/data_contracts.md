# Data Contracts

This document defines file and in-memory contracts used by the current engine APIs.

## 1) Loan Tape Contract

Primary parser: `TapeSchema`.

Accepted sources:

- CSV path
- pandas `DataFrame`

Key behavior:

- Column aliases are normalized and mapped to `Loan` fields.
- Unknown columns are ignored.
- Missing required fields raise `TapeReadError`.
- Row parse errors are aggregated and raised as one `TapeReadError`.

### Required canonical fields

| Field | Type |
|---|---|
| `loan_id` | int |
| `origination_date` | date |
| `asof_date` | date |
| `original_balance` | float |
| `current_balance` | float |
| `rate_margin` | float |
| `original_term` | int |
| `remaining_term` | int |

Minimal CSV example:

```csv
loan_id,origination_date,asof_date,original_balance,current_balance,rate_margin,original_term,remaining_term
1,2020-01-01,2024-01-01,100000,95000,8.0,360,312
2,2021-06-01,2024-01-01,250000,240000,7.5,360,330
```

### Strict integer parsing

Integer fields accept:

- integer types
- integer-like strings (`"12"`, `"-3"`)

They reject:

- float types (`12.0`)
- decimal/scientific strings (`"12.0"`, `"1e3"`)
- booleans

### Date parsing

- Date fields parse through pandas timestamp conversion in tape parsing.
- `Loan.__post_init__` then validates required and provided optional date parseability/order.

## 2) `Loan` Object Contract

Core fields expected by wrappers:

- identity: `loan_id`
- dates: `origination_date`, `asof_date` (required)
- balances/terms: `original_balance`, `current_balance`, `original_term`, `remaining_term`
- coupon model:
  - fixed: `reset_frequency == 0` and `rate_margin` as full coupon percent
  - floating: `reset_frequency > 0` plus `RateIndex`
- derived property:
  - `age = original_term - remaining_term` (used for assumption-curve slicing)

Validation highlights:

- `original_term > 0`
- `remaining_term >= 0`
- `remaining_term <= original_term`
- `original_balance > 0`
- `current_balance <= original_balance`
- `asof_date >= origination_date`
- if both set: `rate_cap >= rate_floor`

## 3) Assumption Curve Contract

For actual cashflow runs:

- `smm_curve`: decimal monthly prepayment
- `mdr_curve`: decimal monthly default
- `severity_curve`: decimal loss severity

Accepted by portfolio wrappers as:

- one shared `np.ndarray`, or
- `dict[loan_id, np.ndarray]`

Wrapper expectation:

- age-indexed arrays long enough to slice:
  - `loan.age + loan.remaining_term + 1`

Example:

- if `loan.age=2` and `loan.remaining_term=5`, wrapper requires length `8`
- it then slices to period-indexed length `6` for the actual runner

Direct formulas runner expectation:

- period-indexed arrays (`remaining_term + 1`) where slot 0 is snapshot.

## 4) Floating Rate Economic Data Contract

Source object: `RateIndex`.

Contract:

- `dates` + `rates` time series
- rates stored in percent
- `get_rate_vector(...)` returns period rates in percent
- wrappers build coupon path by adding `Loan.rate_margin`

## 5) Persistence File Contract

Persistence API:

- `write_cashflow`
- `read_scheduled`
- `read_actual`
- `read_cashflows`

Key file expectations:

- must contain `cf_type` column (`scheduled` or `actual`)
- schema validation on read/append enforces compatibility
- scalar META is stored in parquet metadata (`cf_meta`)
- metadata is type-decoded using dataclass annotations on read

Malformed files raise `SchemaValidationError`.

## 6) Rewind Store Contract

`PortfolioCashflow.rewind(version, store=...)` expects:

- `store` is `dict[cf_id, cashflow_obj]`
- must include all `cf_id` references up to requested version

Helper:

- `PortfolioCashflow.load_rewind_components(path)` loads this dict from persistence files.
- returned values are `BMAScheduledCashflow` or `BMAActualCashflow` objects
  keyed by `cf_id`.
- duplicate `cf_id` entries in persisted files raise `ValueError` during load.
