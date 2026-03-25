# Architecture Overview

This document is the implementation-aligned map of the package. It prioritizes exact API behavior over historical design ideas.

## 1) Layering Model

The package is organized around formulas and engine responsibilities:

```text
bma_standard_formulas.formulas   # math and leaf cashflow objects
bma_standard_formulas.engine     # loan model, tape parsing, portfolio, persistence
```

- Most computational flow is from engine wrappers into formulas functions.
- `formulas.cashflows` includes lazy imports into `engine.portfolio` for leaf arithmetic convenience (`cf + cf` returning `PortfolioCashflow`).
- `engine` composes formulas into practical workflows (loan tape -> per-loan CFs -> pooled CFs).

## 2) Core API Surface

Primary imports:

```python
from bma_standard_formulas.engine import (
    Loan, TapeSchema, read_loan_tape,
    run_scheduled_portfolio, run_actual_portfolio, run_paired_portfolio,
    PortfolioCashflow, apply_waterfall,
)
from bma_standard_formulas.formulas import (
    run_bma_scheduled_cashflow, run_bma_actual_cashflow, CashFlowPair,
)
```

### Formulas layer

- `run_bma_scheduled_cashflow(...) -> BMAScheduledCashflow`
- `run_bma_actual_cashflow(...) -> BMAActualCashflow`
- `CashFlowPair(scheduled, actual)` with strict validation.
- Prepayment/default conversion and historical functions in `payment_models.py`.

### Engine layer

- `Loan` dataclass with domain/date validation in `__post_init__`.
- Wrappers:
  - `scheduled_cashflow_from_loan(loan, rate_index=None)`
  - `actual_cashflow_from_loan(loan, scheduled_cf, smm_curve, mdr_curve, severity_curve, ...)`
- Portfolio runners:
  - `run_scheduled_portfolio(...)`
  - `run_actual_portfolio(...)`
  - `run_paired_portfolio(...)`
- Tape I/O: `TapeSchema`, `read_loan_tape`, `loans_to_dataframe`.
- Persistence: `write_cashflow`, `read_scheduled`, `read_actual`, `read_cashflows`.

## 3) Numeric and Indexing Contracts

### Units

- Coupons/rates in market **percent** (`8.0` means 8% annual).
- SMM/MDR/severity in **decimal fractions** (`0.005` means 0.5% monthly).
- Loan servicing fee (`Loan.servicing_fee`) is in percent.
- Actual-runner servicing rates (`svc_rate_performing/default/foreclosure`) are decimal fractions.

### Indexing

- **Age-indexed curves** (engine wrappers): index `0` is origination age.
- **Period-indexed curves** (direct actual runner): index `0` is as-of snapshot (loop starts at period 1).

`actual_cashflow_from_loan` slices age-indexed curves to the required period-indexed window using `_slice_curve`.

## 4) Coupon Vector Contract (Scheduled + Actual)

Both cashflow runners share normalization behavior:

- Accept scalar `coupon_vector` or numpy array.
- Expand fixed-like scalar/constant short input to `remaining_term`.
- Reject short non-constant floating paths with `ValueError`.
- Trim overlong input to `remaining_term`.
- `run_bma_actual_cashflow` additionally accepts `remaining_term + 1` period-indexed coupon paths (slot 0 dropped).

This contract is centralized in `_normalize_coupon_vector(...)` in `cashflows.py`.

## 5) Loan Validation and Readability Philosophy

`Loan.__post_init__` does:

- Domain checks (`original_term`, `remaining_term`, balances, cap/floor ordering).
- Parseability checks for required dates and any provided optional dates.
- Date ordering checks (`asof_date >= origination_date`).

Design intent: strict on correctness, but still compact and readable for learners.

## 6) PortfolioCashflow Semantics

See detailed doc: `docs/architecture/cashflow_aggregation_design.md`. High-level behavior:

- Modes: `SCHEDULED_ONLY`, `ACTUAL_ONLY`, `PAIRED`.
- Lazy aggregation from `_pending` into cached `_committed`.
- `FieldKind` drives aggregation behavior (`FLOW`, `STOCK`, `RATIO`, `META`).
- Trust waterfall outputs computed from pooled actual cashflow.

### Operator behavior (intentional and current)

- `cf + cf` -> new `PortfolioCashflow`.
- `portfolio + cf` -> **mutates portfolio and returns same object** (intentional performance behavior).
- `portfolio + portfolio` -> returns a new portfolio (non-mutating for both operands).

## 7) History, Rewind, and Persistence Lifecycle

- Event history is append-only and bounded by `max_history_events` (default `5000`).
- Oldest events are trimmed when cap is exceeded.
- Total dropped count is exposed via `history_dropped_events` and trimming is logged.
- `rewind(version, store)` requires external `store: dict[cf_id, cashflow]`.
- If requested version predates retained history, rewind raises `ValueError`.

For persistent constituent history:

- Use `PortfolioCashflow(..., persistent_history=True, history_path=...)`.
- Prefer context manager (`with ... as p:`) or call `close()`.
- Unclosed persistent writer triggers `ResourceWarning` in `__del__` and best-effort cleanup.
- Reload for rewind with `PortfolioCashflow.load_rewind_components(path)`.

## 8) Tape Parsing Error Contract

`TapeSchema.read(...)` primary row-loop behavior is strict and explicit:

- Integer fields use strict parser (`_parse_int_strict`):
  - accepts integers and integer-like strings only
  - rejects floats, decimal strings, scientific notation, booleans
- Row parsing in the main per-row loop catches `ValueError` and `TypeError` for aggregation.
- Error messages include row index, `loan_id`, exception type, and cause chain.
- Some helper-level parsing branches may have their own exception handling behavior.

## 9) Parquet Persistence Contract

- Files are self-describing via `cf_type` column (`scheduled`/`actual`).
- Scalar META fields are encoded in file metadata and type-decoded using dataclass annotations (`get_type_hints`) on read.
- Schema mismatch raises `SchemaValidationError` (including missing `cf_type`).
- Mixed scheduled and actual writes to one file are schema-validated and may reject incompatible append operations.

## 10) Known Intentional Behaviors (Not Bugs)

- Scheduled runner validates but does not apply `servicing_fee` in amortization math.
- Short assumption curves for direct actual-runner assumptions may be padded in fixed-like cases by normalization logic.
- `portfolio + cf` mutates by design for build-loop performance.

## 11) Related Docs

- `docs/architecture/index.md` - architecture reading order and scope boundaries.
- `docs/architecture/execution_pipeline.md` - end-to-end run flow from tape to outputs.
- `docs/architecture/data_contracts.md` - tape, loan, curve, and persistence contracts.
- `docs/architecture/assumptions_model.md` - current assumptions inputs and proposed file model.
- `docs/architecture/engine_design.md` - current engine seams and proposed thin orchestrator.
- `docs/architecture/scenario_runner.md` - single vs batch scenario execution patterns.
- `docs/architecture/outputs_and_persistence.md` - output surfaces, lifecycle, rewind contracts.
- `docs/architecture/errors_and_validation.md` - failure contracts by subsystem.
- `docs/architecture/frontend_integration.md` - thin UI/service integration guidance.
- `docs/architecture/operational_playbook.md` - practical run/test/troubleshooting guide.
- `docs/architecture/cashflow_aggregation_design.md` - deep dive on aggregation, operators, waterfall, rewind.
- `docs/BMA_FORMULAS.md` - mathematical reference text (BMA notation first).
- `docs/notation_reference.md` - notation/index glossary.

## 12) Flush Glossary

The word "flush" appears in three contexts:

- `run_*_portfolio(..., flush=True)`:
  - end-of-run convenience call that flushes once before return.
- `PortfolioCashflow.flush()`:
  - explicit operation to force aggregation and clear pending references.
- proposed config key `flush_every_n_loans`:
  - orchestration-level cadence suggestion; not a current library parameter.
