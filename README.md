# bma-standard-formulas

[![CI](https://github.com/crmerrill/bma-standard-formulas/actions/workflows/ci.yml/badge.svg)](https://github.com/crmerrill/bma-standard-formulas/actions/workflows/ci.yml)
[![License: GPL v2](https://img.shields.io/badge/License-GPL%20v2-blue.svg)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Python implementation of the Bond Market Association (BMA) standard formulas for mortgage cashflow modeling: scheduled amortization, prepayment/default assumptions, and loan-to-pool aggregation.

This library is designed to be transparent and teachable (for both Python and finance novices) while still being strict about core modeling contracts.

## What This Library Covers

- **B.1 scheduled mortgage math**: balance/payment/amortization factors for fixed and floating coupons.
- **B.2-B.4 prepayment and default math**: SMM/CPR/PSA/ABS, CDR/MDR/SDA, and historical speed recovery.
- **C.3 cashflow runners**: scheduled and actual loan-level projections.
- **Engine layer**: `Loan`, `TapeSchema`, portfolio runners, aggregation/waterfall, and Parquet persistence.

## Installation

```bash
pip install bma-standard-formulas
```

Requirements: Python 3.12+, NumPy, SciPy, pandas, pyarrow.

## Quick Start

### 1) Formulas layer (math-first)

```python
import numpy as np
from bma_standard_formulas.formulas import (
    run_bma_scheduled_cashflow,
    run_bma_actual_cashflow,
    generate_smm_curve_from_psa,
    cdr_to_mdr_vector,
)

scheduled = run_bma_scheduled_cashflow(
    original_balance=1_000_000,
    current_balance=1_000_000,
    coupon_vector=8.0,      # annual percent
    original_term=360,
    remaining_term=360,
)

smm = generate_smm_curve_from_psa(100, 360)              # decimal SMM, len=361
mdr = cdr_to_mdr_vector(np.full(361, 1.0))               # 1% annual CDR -> decimal MDR
sev = np.full(361, 0.35)                                 # 35% severity

actual = run_bma_actual_cashflow(
    scheduled_cf=scheduled,
    smm_curve=smm,                # period-indexed, index 0 is snapshot
    mdr_curve=mdr,
    severity_curve=sev,
    coupon_vector=8.0,            # scalar or vector in annual percent
)
```

### 2) Engine layer (loan and portfolio workflow)

```python
import numpy as np
from bma_standard_formulas.engine import (
    read_loan_tape,
    run_actual_portfolio,
)

loans = read_loan_tape("tape.csv", asof_date=np.datetime64("2024-01-01"))
max_term = max(l.original_term for l in loans)

smm = np.full(max_term + 1, 0.005)    # age-indexed SMM
mdr = np.full(max_term + 1, 0.001)    # age-indexed MDR
sev = np.full(max_term + 1, 0.35)     # age-indexed severity

portfolio = run_actual_portfolio(loans, smm, mdr, sev, flush=True)
pool_df = portfolio.pool.to_dataframe()
```

## Core Conventions (Important)

### Units

| Quantity | Unit in API | Example |
|---|---|---|
| Coupon / `rate_margin` / WAC | **percent** | `8.0` = 8% |
| CPR / CDR / PSA / ABS / SDA | **percent** | `100.0` PSA |
| SMM / MDR / severity | **decimal fraction** | `0.005` = 0.5% |
| `servicing_fee` on `Loan` / scheduled runner | **percent** | `0.25` = 25 bps |
| `svc_rate_performing/default/foreclosure` in actual runner | **decimal fraction** | `0.0025` = 25 bps |

### Curve indexing

- **Age-indexed**: index 0 = origination age (`Loan` wrapper inputs).
- **Period-indexed**: index 0 = as-of snapshot (`run_bma_actual_cashflow` inputs).

The engine wrappers convert age-indexed curves into period-indexed windows automatically.

### Coupon-vector contract

- `run_bma_scheduled_cashflow` and `run_bma_actual_cashflow` accept `coupon_vector` as scalar or vector.
- Scalar and constant short vectors are expanded to `remaining_term`.
- Non-constant short vectors are rejected with `ValueError`.
- `run_bma_actual_cashflow` also accepts `remaining_term + 1` period-indexed coupon vectors and drops slot 0.

### Scheduled `servicing_fee` behavior

`run_bma_scheduled_cashflow` validates `servicing_fee` but does not currently alter scheduled principal/interest math with it. This is intentional: scheduled cashflow here is contractual amortization; servicing fee can be used downstream in custom trust/reporting logic.

## Package Layout

### `bma_standard_formulas.formulas`

- `scheduled_payments`: B.1 factors and vectors.
- `payment_models`: B.2-B.4/C conversions, curves, historical recovery.
- `cashflows`: C.3 runners and leaf dataclasses (`BMAScheduledCashflow`, `BMAActualCashflow`, `CashFlowPair`).
- `examples`: reference scenarios and fixtures.

### `bma_standard_formulas.engine`

- `loan`: `Loan`, wrapper runners, portfolio runner entry points.
- `portfolio`: `PortfolioCashflow`, lazy aggregation, waterfall, rewind/history.
- `tape`: strict tape parsing (`TapeSchema`, `read_loan_tape`).
- `rate_index`: floating-rate index vectors.
- `cashflow_persistence`: schema-aware Parquet read/write (`write_cashflow`, `read_cashflows`, etc.).

## Persistence and Rewind Notes

- Use `PortfolioCashflow(..., persistent_history=True, history_path=...)` with a context manager or call `close()`.
- `PortfolioCashflow.load_rewind_components(path)` loads persisted constituents as `dict[cf_id -> cashflow]` using the schema-aware reader.
- Rewind history is bounded by `max_history_events` (default `5000`); dropped-front count is tracked via `history_dropped_events`.

## More Documentation

- `docs/architecture/overview.md` - architecture and API contracts.
- `docs/architecture/cashflow_aggregation_design.md` - deep design notes for `PortfolioCashflow`.
- `docs/BMA_FORMULAS.md` - mathematical reference (BMA notation-focused).
- `docs/notation_reference.md` - notation and indexing glossary.

## License

GPL-2.0-only. See `LICENSE`.
