# Execution Pipeline

This document explains how a full cashflow run works today using existing APIs.

## 0) Minimal runnable example

```python
import numpy as np
from bma_standard_formulas.engine import read_loan_tape, run_actual_portfolio

loans = read_loan_tape("data/tape.csv", asof_date=np.datetime64("2024-01-01"))
max_term = max(loan.original_term for loan in loans)

# age-indexed assumptions (length max_term + 1)
smm = np.full(max_term + 1, 0.005)   # 0.5% monthly prepay
mdr = np.full(max_term + 1, 0.001)   # 0.1% monthly default
sev = np.full(max_term + 1, 0.35)    # 35% loss severity

portfolio = run_actual_portfolio(
    loans=loans,
    smm_curves=smm,
    mdr_curves=mdr,
    severity_curves=sev,
    flush=True,
)

df = portfolio.to_dataframe()
print(df.head())
```

Use this as a baseline before adding per-loan curves or multi-scenario loops.

## 1) Canonical Flow (Current Implementation)

```text
Tape (CSV/DataFrame)
  -> read_loan_tape / TapeSchema
  -> list[Loan]
  -> choose assumptions (SMM/MDR/severity curves, optional RateIndex)
  -> run_*_portfolio entry point
  -> PortfolioCashflow
  -> outputs (to_dataframe, waterfall properties, parquet persistence)
```

## 2) Inputs

- Loan tape:
  - Parsed by `TapeSchema.read(...)` or convenience wrapper `read_loan_tape(...)`.
- Economic data for floating rates:
  - `RateIndex` passed to portfolio wrappers for floating loans.
- Assumption curves:
  - SMM/MDR/severity arrays, either:
    - one shared array for all loans, or
    - per-loan dict keyed by `loan_id`.

## 3) Engine Entry Points

### Scheduled-only run

- Function: `run_scheduled_portfolio(loans, rate_index=None, flush=False)`
- Uses:
  - `scheduled_cashflow_from_loan` for each loan
  - aggregates into `PortfolioCashflow(mode=SCHEDULED_ONLY)`

### Actual-only run

- Function:
  - `run_actual_portfolio(loans, smm_curves, mdr_curves, severity_curves, rate_index=None, severity_lag=12, months_to_liquidation=12, flush=False)`
- Uses:
  - scheduled wrapper as intermediate
  - actual wrapper per loan
  - aggregates into `PortfolioCashflow(mode=ACTUAL_ONLY)`

### Paired run (scheduled + actual retained)

- Function:
  - `run_paired_portfolio(...)`
- Uses:
  - builds both scheduled and actual cashflow for each loan
  - stores `CashFlowPair` constituents
  - aggregates into `PortfolioCashflow(mode=PAIRED)`

## 4) Per-Loan Runner Mechanics

`actual_cashflow_from_loan(...)` is the translation boundary:

- Assumption curves are accepted as age-indexed arrays.
- Wrapper slices them to period-indexed arrays for `run_bma_actual_cashflow`.
- Coupon vectors are derived via `Loan.build_coupon_vector(...)`.

Toy indexing example:

- loan at `age=2`, `remaining_term=5`
- wrapper needs source curves long enough to cover `age + remaining_term + 1 = 8`
- wrapper passes a period-indexed slice of length `6` (`remaining_term + 1`) to actual runner

## 5) Post-Run Access Patterns

| Run mode | Valid aggregate view | Waterfall outputs |
|---|---|---|
| `SCHEDULED_ONLY` | `portfolio.scheduled` | not applicable |
| `ACTUAL_ONLY` | `portfolio.pool` | available (`pt_*`, servicing, advance fields) |
| `PAIRED` | both `portfolio.scheduled` and `portfolio.pool` | available |

If you access a mode-incompatible view, portfolio aggregation raises an error at access time.

Also available:

- `portfolio.to_dataframe()`

## 6) Persistence and Rewind Pipeline

Optional persistent constituent history:

- Create with:
  - `PortfolioCashflow(..., persistent_history=True, history_path=...)`
- During run, there are two patterns:
  - wrapper flow: use `run_*_portfolio(..., flush=True)` for one end-of-run flush.
  - manual incremental flow: call `portfolio.flush()` periodically in large loops.
- Finalize:
  - context manager or explicit `close()`

Reload and replay:

- `store = PortfolioCashflow.load_rewind_components(path)`
- `rewound = portfolio.rewind(version, store=store)`

## 7) Current Gaps (Intentional Transparency)

The library currently provides primitives and wrappers, not a single "one command, one config file" orchestrator.

That orchestrator design is documented in:

- `engine_design.md`
- `assumptions_model.md`
- `scenario_runner.md`

These docs distinguish proposed architecture from implemented APIs.
