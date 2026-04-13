# Frontend Integration (Current DealStudio Surface)

This document captures the current app-first integration that is implemented in this repository.

## 1) Runtime Topology

```text
React/Vite UI
  -> FastAPI routers (/api)
  -> Orchestrator services (run, deal-run, solve, storage)
  -> bma_standard_formulas engine + deals runtime
```

The frontend is bundled under `src/bma_cfengine_app/ui` and is no longer hypothetical.

## 2) Current UI Surfaces

- Tape Intake, Tape View, Run Setup, Results, and Run History.
- Structuring Studio (`DealEditor`) with `Design | Solver | IR` tabs.
- Structured Deal Analysis page for artifact browsing and solver-run comparisons.

## 3) Structuring Studio Contracts

### Open Session + Persistence

- Studio draft state is session-persisted (`sessionStorage`) and includes:
  - active tab
  - deal name and deal id context
  - generated IR JSON
  - solver draft state
  - mirrored collateral/risk settings
  - serialized Blockly workspace layout
- Named pool snapshots are versioned and persisted through `/api/deals/pools`
  so tape/pool context can be saved and reloaded across sessions.
- Session dirty state is tracked and enforced:
  - beforeunload warning when unsaved changes exist
  - in-app navigation confirmation when leaving structuring with unsaved changes
  - explicit "Close deal" action with discard confirmation

### Blockly + Property Panel

- Blockly remains the primary graphical authoring surface.
- Property panel edits are canonicalized by entity name and synchronized to all matching blocks.
- Property coverage currently includes:
  - bonds (size dollars, % pool, coupon, index, CE estimate, usage count)
  - accounts (initial mode/value, usage count)
  - residuals, triggers, fees, split-account rows (entity visibility + counts)
  - fee controls include editable basis, frequency, and annual input values:
    - `Pool BPS`: annual bps quote (e.g. 50 = 0.50% annualized on collateral balance)
    - `Fixed $`: annual dollar amount
    - `Per Loan $`: annual dollars per loan
    - `Frequency` controls payout cadence (`Monthly` / `Quarterly` / `Annual`)
- Bond type behavior is dynamic:
  - `FLOATING` bonds show editable `Index` and `Spread/Margin`
  - `FIXED` bonds hide those controls and IR serialization forces them to `null`

## 4) Mirrored Collateral/Risk Settings Model

A shared `CollateralRiskSettings` model is used by both:

- Structuring Studio Property panel
- Structured Deal Analysis collateral/risk panel

Mirrored fields are real-time synchronized through app-level state:

- product profile controls (`Prime Jumbo` vs `Non-QM/QRM`) with one-click profile presets
- core credit assumptions (`CPR`, `CDR`, `Severity`, `Horizon`)
- rate scenario controls (scenario name, spread/yield shocks)
- execution options (run mode, artifact scope, baseline compare run)
- validation status
- tape/pool binding context:
  - `tapeId` is selected from upload library (searchable dropdown with user-friendly labels)
  - `tapeMappingId` is auto-resolved from saved mappings and locked in the editor
  - pool metadata fields are maintained for manifest compatibility but are not primary UI controls

The Structuring Studio now exposes product-aware controls in both surfaces:

- Properties (shared shell):
  - profile selector and profile preset apply action
  - pool-notional helpers and per-bond CE target solve shortcuts
- Solver tab:
  - shared shell presets plus product-specific preset packs for Prime Jumbo and Non-QM/QRM

Advanced override controls remain out of the mirrored default editor.

## 5) API Endpoints in Active Use

- Uploads and mappings:
  - `POST /uploads`
  - `PATCH /uploads/{id}` (rename display name)
  - `GET /uploads/{id}/profile|stats|preview`
  - `POST /mappings/validate|save`
- Portfolio runs:
  - `POST /runs`
  - `GET /runs/{id}`, `/runs/{id}/preview/{section}`, `/runs/{id}/artifacts`
- Structuring deals and solver:
  - `GET/POST /deals`
  - `GET /deals/{deal_id}`
  - `POST /deals/{deal_id}/runs`
  - `POST /deals/{deal_id}/solve`
  - `GET /deals/{deal_id}/runs/{run_id}/progress`
  - `POST /deals/{deal_id}/runs/{run_id}/cancel`
  - `GET /deals/{deal_id}/solver-catalog`
  - `GET/POST /deals/{deal_id}/solver-presets`

## 6) UI/Engine Boundary Rules

The frontend is orchestration-only. It must not reimplement:

- core formula math
- waterfall execution logic
- deal solver numeric routines
- storage decoding rules

UI responsibilities are state composition, user workflows, validation feedback, and artifact visualization.
