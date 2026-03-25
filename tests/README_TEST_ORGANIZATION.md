# Test Organization

This repository uses `pytest` with focused module-level coverage, not legacy `unittest` orchestration.

## Running Tests

### Full suite

```bash
pytest
```

### Fast subset

```bash
pytest tests/test_b1_payments.py tests/test_b2_prepayment.py tests/test_c3_cashflows.py
```

### Single module

```bash
pytest tests/test_portfolio.py -q
```

### Single test

```bash
pytest tests/test_tape_reader.py::TestTapeSchemaRead::test_int_field_decimal_string_rejected -q
```

## Current Test Modules

- `test_b1_payments.py` - B.1 scheduled factor/payment math.
- `test_b2_prepayment.py` - B.2 conversion helpers (SMM/CPR/PSA).
- `test_b3_historical_speeds.py` - historical speed recovery and input validation.
- `test_b4_abs_prepayment.py` - ABS conversions and related formulas.
- `test_c3_cashflows.py` - scheduled/actual cashflow runners and contracts.
- `test_c3b1_consistency.py` - consistency between C.3 outputs and B.1 identities.
- `test_loan.py` - `Loan` model behavior and wrapper inputs.
- `test_rate_index.py` - `RateIndex` construction/lookups.
- `test_tape_reader.py` - tape aliasing/parsing/error contracts.
- `test_portfolio.py` - aggregation, mode behavior, history/rewind, persistence lifecycle.
- `test_portfolio_runners.py` - high-level portfolio runner entry points.
- `test_parquet_persistence.py` - schema-aware Parquet contracts.
- `test_examples_verification.py` - fixture/reference alignment checks.
- `test_suite.py` - convenience umbrella checks and regression grouping.

## Key Reliability Contracts Covered

- Scheduled/actual parity under zero CPR/CDR in both direct and wrapper paths.
- Floating coupon path support (`coupon_vector` scalar and full vector contracts).
- Strict integer tape parsing (no float coercion, no scientific notation).
- Narrow tape exception wrapping (`ValueError`/`TypeError` only) with rich error context.
- Schema-validation failures for malformed persistence files.
- `PortfolioCashflow` rewind retention boundaries (`max_history_events` behavior).
- Persistent-history lifecycle correctness (`ResourceWarning` on unclosed writers, clean context-manager behavior).

## Practical Guidance for Contributors

- When touching formulas, run at least:
  - `test_b1_payments.py`
  - `test_b2_prepayment.py`
  - `test_c3_cashflows.py`
  - `test_c3b1_consistency.py`
- When touching engine I/O or lifecycle code, run at least:
  - `test_tape_reader.py`
  - `test_parquet_persistence.py`
  - `test_portfolio.py`
  - `test_portfolio_runners.py`
- Always run full `pytest` before finalizing broad refactors.
