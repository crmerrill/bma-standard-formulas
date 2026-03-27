# Scenario Runner

This document explains scenario execution patterns using current APIs and a proposed batch-runner shape.

> Proposed sections in this file are design guidance only. There is no built-in
> `run_scenarios(...)` API in the library today.

## 1) Current Single-Scenario Pattern

Current code executes one scenario per function call:

- scheduled: `run_scheduled_portfolio`
- actual: `run_actual_portfolio`
- paired: `run_paired_portfolio`

Scenario identity is managed by your calling code (filename, folder, metadata).

Example (current single scenario):

```python
import numpy as np
from bma_standard_formulas.engine import read_loan_tape, run_actual_portfolio

loans = read_loan_tape("data/tape.csv", asof_date=np.datetime64("2024-01-01"))
max_term = max(l.original_term for l in loans)

smm = np.full(max_term + 1, 0.005)
mdr = np.full(max_term + 1, 0.001)
sev = np.full(max_term + 1, 0.35)

portfolio = run_actual_portfolio(loans, smm, mdr, sev, flush=True)
```

## 2) Current Multi-Scenario Pattern

Batch runs are performed by looping in user code:

1. load loans once
2. for each scenario:
   - construct curves
   - run selected portfolio function
   - save outputs

This pattern is fully supported today, just not wrapped in a dedicated class/CLI.

Example loop (current multi-scenario):

```python
scenarios = [
    {"name": "base", "smm": 0.005, "mdr": 0.001, "sev": 0.35},
    {"name": "stress", "smm": 0.008, "mdr": 0.002, "sev": 0.45},
]

for sc in scenarios:
    smm = np.full(max_term + 1, sc["smm"])
    mdr = np.full(max_term + 1, sc["mdr"])
    sev = np.full(max_term + 1, sc["sev"])
    p = run_actual_portfolio(loans, smm, mdr, sev, flush=True)
    p.to_dataframe().to_parquet(f"runs/{sc['name']}/portfolio.parquet")
```

## 3) Recommended Scenario Metadata (Today)

Even without a built-in runner, include this manifest per scenario:

- scenario name/id
- as-of date
- mode (`scheduled`/`actual`/`paired`)
- assumption parameters (PSA/SDA/etc. or direct curves)
- curve construction method
- library version
- timestamp

This makes results reproducible and auditable.

Example manifest payload:

```json
{
  "scenario_id": "base_case",
  "asof_date": "2024-01-01",
  "mode": "actual",
  "assumptions": {"smm": 0.005, "mdr": 0.001, "severity": 0.35},
  "library_version": "bma-standard-formulas:x.y.z",
  "timestamp_utc": "2026-03-25T21:15:00Z"
}
```

## 4) Proposed Batch Scenario Runner (Not Implemented)

Proposed interface (illustrative, not available today):

```python
results = FUTURE_run_scenarios(config_path="assumptions.yaml")
```

Proposed behavior:

- resolve global inputs once
- run N scenarios serially or in parallel
- produce per-scenario output folder
- emit a summary index file

Example (proposed summary index):

```json
{
  "run_id": "2026-03-25_001",
  "scenarios": [
    {"name": "base", "status": "success"},
    {"name": "stress", "status": "failed"}
  ]
}
```

## 5) Grouped Scenario Outputs

For grouped reporting (for example by `group_id`):

- retain base loan-level IDs in run artifacts
- output:
  - overall pool
  - grouped sub-pools
- keep grouping logic in orchestration/reporting layer, not inside formula kernels

Example grouped output files:

```text
runs/base_case/
  pool_overall.parquet
  pool_group_1.parquet
  pool_group_2.parquet
```

## 6) Proposed Failure Semantics (Not Implemented)

Recommended behavior for a future orchestrator:

- fail-fast per scenario
- continue batch unless `stop_on_error=true`
- write structured error report with scenario id and root cause

Today, these policies must be implemented by calling code.

Example status payload shape:

```json
{
  "scenario": "stress_case",
  "status": "failed",
  "error_type": "TapeReadError",
  "error_message": "3 row(s) could not be parsed"
}
```
