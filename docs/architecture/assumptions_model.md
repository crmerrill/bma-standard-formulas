# Assumptions Model

This document has two parts:

- Part A: assumptions as they are consumed by the current implementation.
- Part B: a proposed assumptions-file structure for a future orchestrator.

## Part A: Current Implementation Assumptions

Current portfolio APIs consume assumptions as direct function arguments.

## 1) Required assumption inputs for actual runs

- `smm_curves`
- `mdr_curves`
- `severity_curves`

Each can be:

- single `np.ndarray` for all loans, or
- `dict[loan_id, np.ndarray]` for per-loan heterogeneity.

## 2) Optional execution assumptions

- `severity_lag` (default `12`)
- `months_to_liquidation` (default `12`)
- `rate_index` for floating-rate loans
- `flush` strategy (memory control)

## 3) Loan-level embedded assumptions

The following live on `Loan` and are consumed by wrappers/runners:

- `pi_advanced`
- `advance_months`
- `servicing_fee`
- optional `svc_rate_default`, `svc_rate_foreclosure`
- reset/cap/floor fields for floating loans

## 4) Units and indexing constraints

- Curves are decimal fractions.
- Rates on loans/rate index are percent.
- Wrapper curve inputs are age-indexed.
- Formulas runner inputs are period-indexed.

## Part B: Proposed Assumptions File (Not Implemented Yet)

The following is a design proposal for a future config-driven orchestration layer.

Important:

- there is currently no built-in assumptions-file parser in this library
- there is currently no built-in assumptions-file validator in this library
- there is currently no orchestrator CLI that consumes this schema

## 5) Proposed YAML layout

```yaml
run:
  name: "base_case_q2"
  asof_date: "2024-01-01"
  output_dir: "runs/base_case_q2"
  flush_every_n_loans: 500

inputs:
  tape_path: "data/tape/current_tape.csv"
  rate_index_path: "data/econ/sofr.csv"

scenario:
  mode: "actual"          # scheduled | actual | paired
  severity_lag: 12
  months_to_liquidation: 12
  cross_collateral_mode: "none"
  cross_collateral_cap: 1.0

assumptions:
  smm:
    source: "psa"
    psa_percent: 150
  mdr:
    source: "sda"
    sda_percent: 100
  severity:
    source: "constant"
    value: 0.35
```

## 6) Proposed precedence rules

Recommended precedence for future engine:

1. explicit per-loan overrides
2. scenario-level assumptions file
3. library defaults

## 7) Proposed validation rules

- hard fail on missing files
- hard fail on non-finite assumptions
- hard fail when curve lengths cannot satisfy age slicing
- emit run manifest with resolved assumptions snapshot

This section is intentionally labeled proposed and does not describe shipped code.
