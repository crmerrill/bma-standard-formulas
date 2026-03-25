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

## 2) Current Multi-Scenario Pattern

Batch runs are performed by looping in user code:

1. load loans once
2. for each scenario:
   - construct curves
   - run selected portfolio function
   - save outputs

This pattern is fully supported today, just not wrapped in a dedicated class/CLI.

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

## 5) Grouped Scenario Outputs

For grouped reporting (for example by `group_id`):

- retain base loan-level IDs in run artifacts
- output:
  - overall pool
  - grouped sub-pools
- keep grouping logic in orchestration/reporting layer, not inside formula kernels

## 6) Proposed Failure Semantics (Not Implemented)

Recommended behavior for a future orchestrator:

- fail-fast per scenario
- continue batch unless `stop_on_error=true`
- write structured error report with scenario id and root cause

Today, these policies must be implemented by calling code.
