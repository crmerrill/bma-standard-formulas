# Cashflow Aggregation Design (`PortfolioCashflow`)

This document describes the **current implementation** of portfolio aggregation, mutation history, rewind, and persistent constituent storage.

For package-level architecture, see `docs/architecture/overview.md`.

Read this after you can run one scenario end-to-end. This is an internals-focused document.

Terminology:

- **C.3**: BMA section covering actual cashflow math with defaults/prepayments.
- **trust waterfall**: allocation logic from pooled loan cashflows to trust-level outputs.
- **`pt_*` fields**: trust-level pass-through outputs (`pt_principal`, `pt_interest`, `pt_cashflow`).

## 1) Why This Type Exists

`PortfolioCashflow` solves three practical needs:

- Aggregate many leaf cashflows (`BMAScheduledCashflow`, `BMAActualCashflow`, `CashFlowPair`) without re-deriving formulas manually.
- Keep operations composable (`+`, `-`, scaling, merge).
- Preserve enough mutation history to reconstruct prior states (`rewind`) while keeping memory bounded.

## 2) Data Model

### Leaf objects (immutable)

- `BMAScheduledCashflow`: contractual path (no prepays/defaults).
- `BMAActualCashflow`: C.3 path with prepay/default/servicing/advance tracking.
- `CashFlowPair`: validated scheduled+actual pair for same loan.

All leaf dataclasses are frozen and their numpy arrays are write-protected.

### Portfolio object (mutable)

`PortfolioCashflow` maintains:

- `_pending`: current constituents to aggregate.
- `_committed`: cache for computed aggregate outputs (`_scheduled`, `_pool`, `_waterfall`).
- `_history`: append-only event log (`PortfolioEvent`) for replay.
- `_max_history_events`: optional retention cap (`5000` default).
- `_history_dropped_events`: cumulative count of trimmed-front events.

## 3) FieldKind-Driven Aggregation

Every leaf field is tagged with `FieldKind`:

- `FLOW`: additive (sum across constituents).
- `STOCK`: reconstructed from aggregate flow recurrences.
- `RATIO`: recomputed from aggregate identities (never averaged directly).
- `META`: scalar metadata handling.

This keeps aggregation logic generic and avoids hardcoded per-field lists.

## 4) Portfolio Modes and Compatibility

Portfolio modes:

- `SCHEDULED_ONLY`
- `ACTUAL_ONLY`
- `PAIRED`

Compatibility and coercion are handled by `_lcd_mode(...)` and `_extract_for_mode(...)`.

### Combination rules

| A | B | Result |
|---|---|---|
| Scheduled | Scheduled | `SCHEDULED_ONLY` |
| Actual | Actual | `ACTUAL_ONLY` |
| Paired | Paired | `PAIRED` |
| Paired | Scheduled | `SCHEDULED_ONLY` (extract `.scheduled`) |
| Paired | Actual | `ACTUAL_ONLY` (extract `.actual`) |
| Scheduled | Actual | error (`PortfolioModeError`) |

## 5) Operator Semantics (Intentional)

### Leaf operators

- `cf + cf` returns a new `PortfolioCashflow`.
- Leaf scaling returns a new scaled leaf object.

### Portfolio operators

- `portfolio + cf` mutates `portfolio` and returns `portfolio`.
  - This is intentional for build-loop performance.
  - Use `+=` for readability; behavior is the same.
- `portfolio + portfolio` returns a new merged portfolio; neither input is mutated.
  - merge settings come from the left operand for cross-collateral mode/cap.
  - if left and right operands use different cross-collateral settings, callers
    should normalize settings explicitly before merge.
- `portfolio - cf` mutates by removing by object identity.
- `portfolio - portfolio` returns a new portfolio with non-shared constituents.
- `portfolio * scalar` returns new scaled portfolio.
- `portfolio *= scalar` mutates in place.

## 6) Lazy Aggregation and Flush

Aggregation is lazy:

- Accessing `.scheduled` computes and caches scheduled aggregate when needed.
- Accessing `.pool` computes and caches actual aggregate when needed.
- Accessing waterfall-derived properties computes and caches `_waterfall`.

`flush()` forces aggregation and clears `_pending` references. This is useful for long runs where you want lower memory retention after batching.

If a flushed portfolio is mutated later, committed aggregate is moved back to `_pending` as a super-constituent before applying the mutation.

## 7) Cross-Collateralized Waterfall

Waterfall outputs are computed from pooled actual cashflow with cross-collateral rules:

- `CrossCollateralMode.NONE`
- `CrossCollateralMode.FULL`
- `CrossCollateralMode.GROUP`

Key trust-level outputs include servicing paid/shortfall, advance reimbursements, and trust-level `adv_unrecoverable`.

Important distinction:

- `pool.adv_unrecoverable` is a pre-cross-collateral diagnostic flow sum.
- `portfolio.adv_unrecoverable` is trust-level post-waterfall unrecoverable amount.

## 8) History, Retention, and Rewind

Each mutation appends a `PortfolioEvent` with version metadata.

Retention behavior:

- If `max_history_events` is `None`, history is unbounded.
- Otherwise, oldest events are trimmed once cap is exceeded.
- Each trim increments `history_dropped_events` and emits a log message with dropped/retained totals.
- `portfolio + portfolio` may immediately trigger front-trimming on the merged
  history when total events exceed `max_history_events`.

`rewind(version, store)` replay behavior:

- Replays retained events up to target version into a fresh portfolio.
- Requires `store: dict[cf_id -> cashflow object]` for all referenced `ADD`/`SUBTRACT` events.
- Raises `ValueError` if version predates earliest retained event.
- Raises `KeyError` if `store` is missing required `cf_id`.
- For merged portfolios, rewind horizon is effectively constrained by retained
  tails after merge-time trimming.

## 9) Persistent Constituent History

When `persistent_history=True` and `history_path` is provided:

- `flush()` appends current constituents to Parquet row groups.
- Scalar metadata is accumulated and finalized in the footer on `close()`.
- Writer lifecycle is owned by `PortfolioCashflow`.

### Required lifecycle usage

- Preferred: context manager (`with PortfolioCashflow(...) as p:`).
- Alternative: explicit `close()`.

If a persistent writer remains open at GC time:

- `__del__` emits `ResourceWarning`.
- `__del__` attempts best-effort `close()`.
- Destructor never raises.

### Reload path for rewind

Use:

- `PortfolioCashflow.load_rewind_components(path) -> dict[cf_id, cashflow]`

This path uses schema-aware persistence readers and preserves scalar metadata types.

## 10) Performance Characteristics

Main performance choices:

- Numba-compiled hot loops in formulas layer (scheduled floating loop and actual loop).
- Metadata-driven aggregation to keep portfolio logic simple and vectorized where possible.
- Lazy reduction to avoid unnecessary repeated aggregation work.

Main memory controls:

- `flush()` to drop constituent references.
- `max_history_events` to bound event-log growth.

## 11) Testing Invariants to Protect

Critical invariants covered by tests:

- Single-loan portfolio aggregate matches leaf arrays.
- Zero-CPR/zero-CDR actual cashflow equals scheduled cashflow (kernel + wrapper paths, fixed + floating coupon vectors).
- Mode enforcement raises on incompatible adds.
- Rewind round-trip with complete store reproduces expected state.
- Rewind-before-retained-history raises clear `ValueError`.
- Persistent writer lifecycle:
  - unclosed writer emits `ResourceWarning`
  - context manager path avoids warning
- Parquet persistence schema contracts raise `SchemaValidationError` for malformed files.

## 12) Design Boundaries

What this type intentionally does not do:

- It does not keep full snapshots for every version.
- It does not guarantee rewind for versions that were trimmed by retention.
- It does not manage external object-store durability; caller owns `store`.
- It does not hide mutating `portfolio + cf` semantics.

These boundaries are intentional and documented so behavior is predictable in production and educational use.
