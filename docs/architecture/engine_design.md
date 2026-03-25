# Engine Design

> Proposed orchestrator components in this document are not currently shipped
> product APIs. They describe how to compose existing APIs safely.

## 1) What Exists Today

The codebase already has an engine layer with composable pieces:

- ingestion: `TapeSchema`, `read_loan_tape`
- data model: `Loan`
- runner entry points:
  - `run_scheduled_portfolio`
  - `run_actual_portfolio`
  - `run_paired_portfolio`
- aggregation/waterfall:
  - `PortfolioCashflow`
  - `apply_waterfall`
- persistence I/O:
  - `write_cashflow`, `read_*`

Clarification:

- `write_cashflow` and `read_*` are in `engine/cashflow_persistence.py`.
- `load_rewind_components` is a `PortfolioCashflow` static method that uses
  `read_cashflows` internally to build replay stores.

This is functional, but distributed across API calls rather than one orchestrator object.

## 2) Proposed Thin Orchestrator (Not Implemented)

Goal: wrap existing APIs without changing formula or portfolio kernels.

Proposed components:

- `RunConfigLoader`
  - load/validate assumptions config (YAML/JSON)
- `InputLoader`
  - load tape/economic data from config paths
- `AssumptionBuilder`
  - resolve scenario assumptions into concrete SMM/MDR/severity arrays
- `ScenarioExecutor`
  - call one of `run_*_portfolio` entry points
- `OutputWriter`
  - write DataFrames/parquet/manifests

## 3) Responsibility Boundaries

- Orchestrator should be glue only.
- Mathematical correctness stays in:
  - formulas layer (`formulas/`)
  - existing wrappers (`engine/loan.py`)
- Aggregation/waterfall logic stays in `engine/portfolio.py`.

## 4) Grouping Strategy

Current code supports `group_id` in loans and `CrossCollateralMode.GROUP` in waterfall logic.

For future orchestrator:

- group-level reporting should be assembled from existing portfolio operations
- avoid introducing parallel bespoke grouping math paths

## 5) Extensibility Strategy

Suggested plugin-like extension points for orchestrator:

- tape adapter
- economic data adapter
- assumption builder strategy
- output sink (filesystem, database, object store)

None of this should alter the public formulas contracts.

## 6) Why This Design Fits Current Code

- current API already has clear seams (ingest -> run -> aggregate -> persist)
- wrappers already handle key complexity (age/period slicing, coupon path construction)
- portfolio type already handles history/rewind/persistence lifecycle

So the best next step is orchestration, not a rewrite of computational internals.
