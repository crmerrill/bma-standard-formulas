# Operational Playbook

Practical guidance for running, validating, and troubleshooting portfolio runs.

## 1) Baseline Run Checklist

1. Validate tape load:
   - run `read_loan_tape(...)`
   - inspect count and key columns
2. Validate assumptions:
   - curve lengths cover `age + remaining_term + 1`
   - units are correct
3. Run selected mode:
   - scheduled/actual/paired
4. Export and review outputs:
   - portfolio DataFrame
   - optional persistence artifacts

## 2) Common Failure Modes

- Tape parse errors:
  - fix `TapeReadError` rows first
- Curve length mismatch:
  - ensure age-indexed arrays are long enough for seasoned loans
- Mode mismatch:
  - avoid adding scheduled leaves to actual-only portfolios
- Persistence schema mismatch:
  - avoid appending incompatible cashflow types into one parquet stream

## 3) Memory Management

Large pools can retain many leaf objects in `_pending`.

Use:

- `flush=True` in runner wrappers when appropriate
- periodic `portfolio.flush()` in manual loops
- bounded history via `max_history_events`

## 4) Persistent Writer Lifecycle

When using persistent history:

- always use context manager or explicit `close()`
- treat `ResourceWarning` as a lifecycle bug in calling code

## 5) Verification Tests to Run After Engine Changes

Minimum regression set:

- `tests/test_c3_cashflows.py`
- `tests/test_c3b1_consistency.py`
- `tests/test_portfolio.py`
- `tests/test_tape_reader.py`
- `tests/test_parquet_persistence.py`

Full confidence:

- run full `pytest`.

## 6) Profiling Guidance

For performance investigations:

- use provided profiling scripts in `scripts/`
- start with:
  - `scripts/profile_10k_floating_rate.py`
  - `scripts/bench_fixed_rate_vectorize.py`
- compare before/after on:
  - total runtime
  - memory footprint
  - large-pool behavior with and without flush

## 7) Reproducibility Practices

Per run, capture:

- exact assumptions payload
- input file paths and hashes
- package version
- timestamp and scenario id

Store this manifest next to outputs.
