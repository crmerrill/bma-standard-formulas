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

Requirements: Python 3.12+, NumPy, SciPy.

From source (development):

```bash
git clone https://github.com/crmerrill/bma-standard-formulas.git
cd bma-standard-formulas
pip install -e .
```

## Quick start

```python
from bma_standard_formulas import (
    sch_balance_factor_fixed_rate,
    run_bma_scheduled_cashflow,
    smm_to_cpr,
    generate_psa_curve,
)

# Scheduled balance factor (SF-4): 9.5%, 360-month loan, 348 months remaining
bal = sch_balance_factor_fixed_rate(9.5, 360, 348)
# => ~0.9942

# Scheduled cash flow (no prepay/default)
cf = run_bma_scheduled_cashflow(
    original_balance=1_000_000,
    current_balance=1_000_000,
    coupon=0.08,
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

Using the `Loan` object and wrappers:

```python
from bma_standard_formulas import Loan, scheduled_cashflow_from_loan
import numpy as np

loan = Loan(
    origination_date=np.datetime64("2020-01-01"),
    asof_date=np.datetime64("2024-01-01"),
    original_balance=1_000_000,
    current_balance=950_000,
    rate_margin=8.0,
    rate_index=None,  # fixed rate
    servicing_fee=0.25,
    original_term=360,
    remaining_term=312,
)
scheduled_cf = scheduled_cashflow_from_loan(loan)
```

## Module layout

| Module | Contents |
|--------|----------|
| `scheduled_payments` | B.1: balance factor, payment factor, am factor, vectors (fixed & floating) |
| `payment_models` | B.2–B.4, C: SMM/CPR/PSA/ABS conversions, PSA/SDA curves, historical recovery, pool aggregation |
| `cashflows` | C.3: `BMAScheduledCashflow`, `BMAActualCashflow`, `run_bma_scheduled_cashflow`, `run_bma_actual_cashflow`, `Loan`, wrappers |
| `examples` | BMA example data structures and reference scenarios |

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
