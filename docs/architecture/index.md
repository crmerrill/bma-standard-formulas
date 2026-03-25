# Architecture Docs Index

This folder contains implementation-aligned architecture documents for `bma-standard-formulas`.

Before reading architecture docs, you should be comfortable with:

- basic Python and NumPy arrays
- pandas DataFrames
- basic mortgage terms (CPR, SMM, MDR, severity)

Recommended prep:

- `docs/notation_reference.md`
- `docs/BMA_FORMULAS.md`

Read in this order if you are new:

1. [Overview](overview.md)
2. [Execution Pipeline](execution_pipeline.md)
3. [Data Contracts](data_contracts.md)
4. [Assumptions Model](assumptions_model.md)
5. [Engine Design](engine_design.md)
6. [Scenario Runner](scenario_runner.md)
7. [Outputs and Persistence](outputs_and_persistence.md)
8. [Errors and Validation](errors_and_validation.md)
9. [Frontend Integration](frontend_integration.md)
10. [Cashflow Aggregation Design](cashflow_aggregation_design.md)
11. [Operational Playbook](operational_playbook.md)

### Reading paths

- **Path A: run your first scenario**
  1. [Overview](overview.md)
  2. [Execution Pipeline](execution_pipeline.md)
  3. [Data Contracts](data_contracts.md)
  4. [Operational Playbook](operational_playbook.md)
- **Path B: understand internals**
  1. [Cashflow Aggregation Design](cashflow_aggregation_design.md)
  2. [Outputs and Persistence](outputs_and_persistence.md)
  3. [Errors and Validation](errors_and_validation.md)

---

## Scope and Authority

- These docs describe current implementation in `src/` unless explicitly labeled "Proposed".
- Historical review/remediation markdown files are not architecture authority.
- Code is always the final source of truth when docs and implementation diverge.

Runtime baseline:

- Python 3.12+
- NumPy, pandas, SciPy, pyarrow (and optional extras where used)

### Mortgage mini-glossary

- **scheduled cashflow**: contractual payment path without prepayment/default.
- **actual cashflow**: scheduled path plus prepayment/default assumptions.
- **SMM**: monthly prepayment rate (decimal fraction).
- **MDR**: monthly default rate (decimal fraction).
- **CPR/CDR**: annualized prepayment/default rates (percent).
- **severity**: loss fraction on defaulted balance at liquidation.
- **PSA/SDA**: standard prepayment/default speed conventions.

### Label Legend

- **Implemented**: behavior that exists in current code.
- **Proposed**: future architecture that is not currently shipped.
- **Ops convention**: recommended runbook practice, not enforced by library code.
- **Integration pattern**: external application/service guidance.

---

## What Is Implemented Today

Primary imports:

```python
from bma_standard_formulas.engine import (
    Loan, TapeSchema, read_loan_tape,
    run_scheduled_portfolio, run_actual_portfolio, run_paired_portfolio,
    PortfolioCashflow, apply_waterfall,
    write_cashflow, read_scheduled, read_actual, read_cashflows,
)
```

- Loan model and wrappers:
  - `Loan`
  - `scheduled_cashflow_from_loan`
  - `actual_cashflow_from_loan`
- Portfolio runner entry points:
  - `run_scheduled_portfolio`
  - `run_actual_portfolio`
  - `run_paired_portfolio`
- Aggregation/waterfall:
  - `PortfolioCashflow`
  - `apply_waterfall`
- Tape parsing:
  - `TapeSchema`
  - `read_loan_tape`
- Persistence:
  - `write_cashflow`
  - `read_scheduled`
  - `read_actual`
  - `read_cashflows`
  - `PortfolioCashflow.load_rewind_components`

---

## What Is Not Yet a Built Product Feature

- A first-class "single config file execution engine" that reads assumptions + tape + economic files in one command.
- A bundled frontend application.

These are documented as proposed architecture in this folder, not as current behavior.
