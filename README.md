# bma-standard-formulas

[![CI](https://github.com/crmerrill/bma-standard-formulas/actions/workflows/ci.yml/badge.svg)](https://github.com/crmerrill/bma-standard-formulas/actions/workflows/ci.yml)
[![License: GPL v2](https://img.shields.io/badge/License-GPL%20v2-blue.svg)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Python implementations of the **Bond Market Association (BMA) Standard Formulas** for mortgage-backed securities: scheduled payments, prepayment and default models, and cash flow generation. The formulas follow the BMA *Uniform Practices/Standard Formulas* document (February 1, 1999).

## Overview

This package provides:

- **Scheduled payments (B.1)** — Balance factors, payment factors, and amortization for fixed- and floating-rate loans (SF-4).
- **Prepayment and default models (B.2–B.4, C)** — SMM, CPR, PSA, ABS, SDA, CDR/MDR; historical speed recovery and pool aggregation (SF-5 through SF-22).
- **Cash flows (C.3)** — Scheduled and actual cash flow runners (SF-17 to SF-19), plus a `Loan` dataclass and wrappers to run cash flows from a loan object.
- **Example data** — Structured BMA examples for testing and reference.

All functions are documented with BMA section and formula references. The code is intended for transparency and alignment with the BMA document, not as a certified production engine.

## Installation

```bash
pip install bma-standard-formulas
```

Requirements: Python 3.12+, NumPy, SciPy, pandas, pyarrow.

From source (development):

```bash
git clone https://github.com/crmerrill/bma-standard-formulas.git
cd bma-standard-formulas
pip install -e .
```

## Quick start

The package is split into two sub-packages that reflect the natural layering:

```python
# BMA math — factors, speeds, cashflow runners
from bma_standard_formulas.formulas import (
    sch_balance_factor_fixed_rate,
    run_bma_scheduled_cashflow,
    smm_to_cpr,
    generate_psa_curve,
)

# Scheduled balance factor (SF-4): 9.5%, 360-month loan, 348 months remaining
bal = sch_balance_factor_fixed_rate(9.5, 360, 348)
# => ~0.9942

# Scheduled cash flow (no prepay/default); coupon_vector in PERCENT (8.0 = 8%)
cf = run_bma_scheduled_cashflow(
    original_balance=1_000_000,
    current_balance=1_000_000,
    coupon_vector=8.0,
    original_term=360,
    remaining_term=360,
)
# cf.period, cf.principal_paid, cf.interest_paid, etc.

# Prepayment conversions (SF-6)
smm = 0.005   # 0.5% SMM
cpr = smm_to_cpr(smm)  # annualized CPR %

# PSA curve (SF-6–SF-10)
cpr_curve = generate_psa_curve(100, 360)  # 100% PSA, 360 months
```

Loading a loan tape from CSV and running a portfolio:

```python
# Application layer — Loan, tape reader, portfolio runners
from bma_standard_formulas.engine import read_loan_tape, run_scheduled_portfolio
import numpy as np

# Read a CSV tape → list[Loan]; asof_date inferred from tape or supplied here
loans = read_loan_tape("tape.csv", asof_date=np.datetime64("2024-01-01"))

# Run scheduled cashflows and aggregate to pool level
portfolio = run_scheduled_portfolio(loans)
df = portfolio.to_dataframe()  # pandas DataFrame, one row per period
```

Using the `Loan` object and wrappers:

```python
from bma_standard_formulas.engine import Loan, scheduled_cashflow_from_loan
import numpy as np

loan = Loan(
    loan_id=1,
    origination_date=np.datetime64("2020-01-01"),
    asof_date=np.datetime64("2024-01-01"),
    original_balance=1_000_000,
    current_balance=950_000,
    rate_margin=8.0,        # fixed-rate: full coupon in % (reset_frequency=0 default)
    servicing_fee=0.25,
    original_term=360,
    remaining_term=312,
)
scheduled_cf = scheduled_cashflow_from_loan(loan)
```

## Numeric conventions

All rates and speeds follow the conventions in the BMA Standard Formulas document. The table below summarizes the values as stored and passed throughout this library:

| Quantity | Convention | Example |
|----------|-----------|---------|
| Coupon / WAC / rate_margin | **PERCENT** | `8.0` = 8% annual |
| CPR | **PERCENT** | `6.0` = 6% annualized prepayment |
| PSA | **PERCENT** | `100.0` = 100% PSA standard ramp |
| CDR | **PERCENT** | `2.0` = 2% annualized default rate |
| ABS | **PERCENT** | `1.5` = 1.5% ABS speed |
| SDA | **PERCENT** | `100.0` = 100% SDA standard curve |
| SMM | **decimal fraction** | `0.005` = 0.5% monthly prepayment |
| MDR | **decimal fraction** | `0.002` = 0.2% monthly default rate |
| Loss severity | **decimal fraction** | `0.35` = 35% loss given default |
| Servicing fee (`servicing_fee`) | **PERCENT** | `0.25` = 25 bps annual |
| Servicing rate (`svc_rate_performing`) | **decimal fraction** | `0.0025` = 25 bps annual |

The cashflow runners convert internally: `monthly_rate = coupon / 1200.0`. Use the conversion functions in `payment_models` (e.g. `cpr_to_smm`, `psa_to_smm`) to move between PERCENT and decimal fraction forms.

## Package layout

### `bma_standard_formulas.formulas` — BMA math

| Module | Contents |
|--------|----------|
| `scheduled_payments` | B.1: balance factor, payment factor, am factor, vectors (fixed & floating) |
| `payment_models` | B.2–B.4, C: SMM/CPR/PSA/ABS conversions, PSA/SDA curves, historical recovery, pool aggregation |
| `cashflows` | C.3: `BMAScheduledCashflow`, `BMAActualCashflow`, `run_bma_scheduled_cashflow`, `run_bma_actual_cashflow`, `CashFlowPair` |
| `examples` | BMA reference examples and scenario data structures |

### `bma_standard_formulas.engine` — Application layer

| Module | Contents |
|--------|----------|
| `loan` | `Loan` dataclass, `build_rate_vector`, per-loan cashflow wrappers, portfolio runner functions |
| `portfolio` | `PortfolioCashflow`, `PortfolioMode`, waterfall aggregation (`apply_waterfall`) |
| `tape` | `TapeSchema`, `read_loan_tape`, `loans_to_dataframe`: CSV/DataFrame → `list[Loan]` |
| `rate_index` | `RateIndex`: dated market rate curve for floating-rate loans |
| `cashflow_persistence` | Parquet I/O: `write_cashflow`, `read_scheduled`, `read_actual` |

## AI assistance disclosure

This project was developed with the assistance of AI coding tools for documentation, formatting, and implementation scaffolding. All formula logic and mathematical content have been reviewed by the authors against the BMA *Uniform Practices/Standard Formulas* (02/01/99) document.

## License

This project is licensed under the **GNU General Public License v2.0 (GPL-2.0-only)**. You may use, modify, and distribute it under the terms of the GPLv2; derivative works must be released under the same license. See [LICENSE](LICENSE) for the full text.

## Authors

- Daniel Akiva  
- Idriss Maoui  
- Charles R. Merrill  

## References

- Bond Market Association, *Uniform Practices/Standard Formulas for the Pricing of Mortgage-Backed Securities*, February 1, 1999.
