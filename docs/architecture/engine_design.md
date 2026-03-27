# Engine Design and Roadmap

> Proposed orchestrator components in this document are not currently shipped
> product APIs. They describe how to compose existing APIs safely.

This document now serves two purposes:

- design notes (what the orchestrator should look like)
- implementation roadmap (how to build it in safe, incremental steps)

## 1) Current Baseline (Already Implemented)

The current engine layer already provides all core primitives:

- ingestion: `TapeSchema`, `read_loan_tape`
- loan model: `Loan`
- scenario execution entry points:
  - `run_scheduled_portfolio`
  - `run_actual_portfolio`
  - `run_paired_portfolio`
- aggregation/waterfall:
  - `PortfolioCashflow`
  - `apply_waterfall`
- persistence:
  - `write_cashflow`, `read_scheduled`, `read_actual`, `read_cashflows`
  - `PortfolioCashflow.load_rewind_components`

This means the roadmap is an orchestration roadmap, not a formula rewrite roadmap.

Example (today, no orchestrator):

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

## 2) Target Architecture (Thin Orchestrator)

Goal: add a config-driven runtime layer without changing formula or portfolio kernels.

Proposed components:

- `RunConfigLoader`
  - load and validate run config (YAML/JSON)
- `InputLoader`
  - load tape and optional economic data sources from configured paths
- `AssumptionBuilder`
  - resolve assumptions into concrete SMM/MDR/severity arrays
- `ScenarioExecutor`
  - dispatch to `run_scheduled_portfolio`, `run_actual_portfolio`, or `run_paired_portfolio`
- `OutputWriter`
  - persist portfolio outputs and run manifest

Example orchestrator flow (proposed):

```python
cfg = RunConfigLoader.load("assumptions.yaml")
inputs = InputLoader.load(cfg.inputs)
assumptions = AssumptionBuilder.build(cfg.scenario, inputs)
result = ScenarioExecutor.run(cfg, inputs, assumptions)
OutputWriter.write(result, cfg.run.output_dir)
```

## 3) Responsibility Boundaries (Non-Negotiable)

- Orchestrator is glue only.
- Mathematical correctness remains in:
  - formulas layer (`formulas/`)
  - existing wrappers (`engine/loan.py`)
- Aggregation/waterfall logic remains in `engine/portfolio.py`.
- Persistence schema logic remains in `engine/cashflow_persistence.py`.

If any roadmap step starts duplicating formula math, it is off-architecture.

Boundary example:

- good: `ScenarioExecutor` calls `run_actual_portfolio(...)`.
- bad: `ScenarioExecutor` re-implements MDR/SMM projection loops directly.

## 4) Implementation Roadmap

## Phase 0 - Contract Freeze and Scaffolding

Deliverables:

- freeze assumptions schema v0 (documented, not necessarily final)
- define manifest schema (run id, inputs, assumptions, version, timestamp)
- create orchestration package/module skeleton

Acceptance criteria:

- no behavior change to existing `run_*_portfolio` APIs
- full backward compatibility for current library users

Example deliverable:

- `schemas/assumptions.schema.json`
- `schemas/run_manifest.schema.json`
- `engine_orchestrator/__init__.py`

## Phase 1 - Single Scenario Runner

Deliverables:

- implement one-shot orchestrator path:
  - load tape
  - resolve assumptions
  - run one scenario
  - write output + manifest
- support mode selection: scheduled/actual/paired

Acceptance criteria:

- output numerically matches direct wrapper calls for same inputs
- deterministic output for identical inputs/config

Example CLI shape (proposed):

```bash
python -m bma_engine.run --config assumptions.yaml --scenario base_case
```

## Phase 2 - Multi-Scenario Execution

Deliverables:

- scenario list support (N scenarios in one run)
- per-scenario output directories
- per-scenario status reporting and aggregate summary index

Acceptance criteria:

- one failed scenario does not corrupt successful scenario outputs
- option for stop-on-first-failure vs continue-on-error is explicit

Example output structure:

```text
runs/2026-03-25/
  base_case/
  stress_case/
  low_prepay_case/
  summary.json
```

## Phase 3 - Grouped Reporting and Rewind Integration

Deliverables:

- grouped output views driven by existing `group_id` and portfolio operations
- optional persistent-history run mode with documented lifecycle behavior
- helper command/util to rebuild rewind store from persisted constituents

Acceptance criteria:

- grouped outputs are derived from current portfolio semantics (no duplicate math path)
- rewind reproducibility documented and tested for retained-history window behavior

Example grouped artifact names:

- `pool_overall.parquet`
- `pool_group_1.parquet`
- `pool_group_2.parquet`
- `rewind_components.parquet`

## Phase 4 - UX and Service Integration

Deliverables:

- service-friendly orchestration API (for thin frontend)
- standardized run status payload and error payload shape
- optional async execution hooks

Acceptance criteria:

- frontend/service layer never calls private internals directly
- all user-facing errors map to documented error contracts

Example service endpoint set (proposed):

- `POST /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/artifacts`

## 5) Milestones and Exit Criteria

Use these milestone gates to avoid overbuilding:

- M1: one config -> one scenario -> one output package
- M2: one config -> many scenarios with stable manifests
- M3: grouped outputs and rewind workflows fully documented
- M4: service/frontend handoff contract stable

Do not start Phase N+1 until Phase N acceptance criteria are green.

Example phase gate checklist:

- M1 done -> one scenario produces manifest + output + reproducibility hash.
- M2 done -> multi-scenario run recovers cleanly from one scenario failure.
- M3 done -> grouped outputs and rewind replay are validated by tests.

## 6) Risk Register and Mitigations

- **Risk:** assumptions schema churn breaks reproducibility.
  - **Mitigation:** version schema and persist resolved assumptions in manifest.
- **Risk:** duplicated formula logic appears in orchestration code.
  - **Mitigation:** enforce wrapper-only execution path in code review.
- **Risk:** grouped outputs diverge from core portfolio semantics.
  - **Mitigation:** build grouped views from existing portfolio operations only.
- **Risk:** persistent-history lifecycle misuse in long runs.
  - **Mitigation:** require explicit context-managed execution in orchestrator when enabled.

Example operational guardrail:

```python
with PortfolioCashflow([], mode="actual_only", persistent_history=True, history_path=path) as p:
    ...
```

## 7) Grouping Strategy

Current code already supports:

- loan `group_id`
- `CrossCollateralMode.GROUP` in waterfall logic

Roadmap rule:

- grouped reporting must reuse current portfolio semantics
- do not add parallel bespoke grouping math paths

Example:

- preferred: filter loans by `group_id`, run existing portfolio logic, then aggregate reports.
- avoid: custom per-group cashflow kernels that diverge from `PortfolioCashflow` behavior.

## 8) Extensibility Strategy

Optional extension points once core roadmap is complete:

- tape adapter
- economic data adapter
- assumption builder strategy
- output sink (filesystem, database, object store)

Each extension point must be additive and must not alter public formulas contracts.

Example extension:

- output sink plugin `S3OutputWriter` writes same manifest/data contract to object storage.

## 9) Why This Roadmap Fits the Current Code

- clear seams already exist: ingest -> run -> aggregate -> persist
- wrappers already handle hard parts: age/period slicing and coupon path construction
- portfolio already handles lifecycle concerns: flush/history/rewind/persistence

So the right path is progressive orchestration on top of stable computational kernels.
