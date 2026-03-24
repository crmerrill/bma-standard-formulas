# CashFlow Aggregation System — Architecture & Design

> Version 3.0 | Updated to reflect Design Doc Compliance + flush/GUID/Parquet changes

> **Scope:** This document covers the detailed design of `PortfolioCashflow`
> (aggregation semantics, operator model, lazy evaluation, Numba compatibility,
> version history) and the design rationale for the two `CashFlow` leaf types.
> For the high-level package architecture and typical usage patterns see
> [`overview.md`](overview.md).
>
> **API note:** Section 4.6 refers to `generate_actual_cashflow()` as the
> bridge function.  In the current implementation this is
> `actual_cashflow_from_loan(loan, smm_curve, mdr_curve, severity_curve)` in
> `engine/loan.py`.  The design intent is the same; only the name differs.

---

## Implementation Summary

### Module Layout

```
loan.py           — Loan data model, rate conversion, wrapper functions
cashflows.py      — BMA C.3 leaf computation (scheduled + actual runners)
portfolio.py      — Tier 2: aggregation, waterfall, cross-collat, persistence
```

### Leaf Types

- **`BMAScheduledCashflow`** and **`BMAActualCashflow`** — frozen dataclasses with `FieldKind` metadata (FLOW/STOCK/RATIO/META) on every field
- **`CashFlowPair`** — validated wrapper binding scheduled + actual for the same loan
- **`cf_id`** — globally unique auto-incrementing int on every leaf CF, assigned at construction by the runner. Used for history tracking without storing object references

### Portfolio

- **`PortfolioCashflow`** — mutable container with lazy aggregation and trust waterfall
- **Modes:** `PortfolioMode` (SCHEDULED_ONLY | ACTUAL_ONLY | PAIRED) with LCD coercion
- **Cross-collat:** `CrossCollateralMode` (NONE | FULL | GROUP) with configurable cap
- **Aggregation:** FLOW fields summed via `fields_by_kind()` (metadata-driven). STOCK fields reconstructed from summed flows via cumsum. RATIO fields recomputed from first principles — NEVER weighted-averaged
- **Flush pattern:** `flush()` triggers aggregation, then clears `_pending` (constituent refs released for GC). Post-flush mutation moves the committed aggregate back to `_pending` as a single super-constituent
- **Version history:** `PortfolioEvent` stores `cf_id` + `loan_id` + scalar metadata (NOT object refs). ~200 bytes per event. Rewind requires external store: `rewind(version, store={cf_id: cf_obj})`
- **Parquet persistence:** `persistent_history=True` + `history_path` writes constituents to Parquet on flush. `load_constituents(path)` reads them back for rewind
- **`empty()`** class method for sum/reduce patterns

### Operators

| Left | Right | Mutates? | Returns |
|------|-------|----------|---------|
| cf | cf | No (frozen) | New `PortfolioCashflow` |
| portfolio | cf/pair | Yes | Same portfolio |
| portfolio | portfolio | No | New `PortfolioCashflow` |
| portfolio | scalar (*, /) | No | New `PortfolioCashflow` |
| cf | scalar (*, /) | No | New leaf cf (same type) |
| += | cf or portfolio | Yes | Same portfolio |
| -= | cf or portfolio | Yes | Same portfolio |
| *= | scalar | Yes | Same portfolio |

### LCD Mode Coercion

| A mode | B mode | LCD Result |
|--------|--------|------------|
| Scheduled | Scheduled | SCHEDULED_ONLY |
| Actual | Actual | ACTUAL_ONLY |
| Paired | Paired | PAIRED |
| Paired | Actual | ACTUAL_ONLY (extract .actual) |
| Paired | Scheduled | SCHEDULED_ONLY (extract .scheduled) |
| Actual | Scheduled | **Error** — `PortfolioModeError` |

### Performance

- **numba @njit** on both inner loops (scheduled floating-rate + actual CF)
- **Vectorized fixed-rate BAL path** — `amortized_balance_fraction` computed as a single numpy expression (no per-period loop)
- **Vectorized `generate_sda_curve`** (numpy piecewise, no Python loop)
- **accum-A single-pass accumulator** for FLOW aggregation in `_aggregate_actual` — one Python loop over constituents, in-place slice-add into a pre-allocated `(n_fields, n_periods)` accumulator. The accumulator stays in CPU cache for the full run (~13× faster than per-field `np.stack` loops that each allocate large intermediate arrays and blow the cache). See `scripts/profile_aggregation_strategies.py` for benchmarks.
- **10k floating-rate portfolio:** ~3.3s end-to-end

### Deferred (not yet implemented)

- **2D matrix storage** (keep named fields for readability)
- **`__hash__`** on cashflows (numpy arrays not hashable)
- **Column-index constants** (depends on 2D matrix)
- **`weight` metadata on RATIO fields** (dropped — ratios are recomputed from first principles, weight key adds maintenance burden)
- **Dual stacks for PAIRED mode** (dropped — single stack is simpler, mutations are always atomic)
- **Cross-asset support:** auto loans (Act/365, no FCL), student loans (multiple capitalization events), CMBS (IO periods, balloon, lockout). See comments in runners for RMBS-specific assumptions

### Implemented Operator Semantics

| Left | Right | Mutates? | Returns |
|------|-------|----------|---------|
| cf | cf | No | New `PortfolioCashflow` |
| portfolio | cf/pair | Yes | Same portfolio |
| portfolio | portfolio | No | New `PortfolioCashflow` |
| portfolio | scalar (*, /) | Yes (in-place) | Same portfolio |
| cf | scalar (*, /) | No | New leaf cf |

### Implemented LCD Mode Coercion

| A mode | B mode | LCD Result |
|--------|--------|------------|
| Scheduled | Scheduled | SCHEDULED_ONLY |
| Actual | Actual | ACTUAL_ONLY |
| Paired | Paired | PAIRED |
| Paired | Actual | ACTUAL_ONLY (extract .actual) |
| Paired | Scheduled | SCHEDULED_ONLY (extract .scheduled) |
| Actual | Scheduled | **Error** — `PortfolioModeError` |

### FieldKind Aggregation Semantics

Every field on `BMAScheduledCashflow` and `BMAActualCashflow` carries a `FieldKind` tag in its dataclass metadata. This tag is the central invariant that makes pooling correct — it tells `_aggregate_actual` and `_aggregate_scheduled` exactly how each field must be combined when multiple loans are pooled.

| FieldKind | Pooling Rule | Rationale |
|-----------|-------------|-----------|
| `FLOW` | Sum across constituents | Dollar flows are additive (e.g. total interest = sum of per-loan interest) |
| `STOCK` | Reconstruct via `cumsum` from summed FLOWs | Direct sum violates the balance identity; stocks follow from the flow recurrence on the aggregate |
| `RATIO` | Recompute from defining formula on aggregate | Weighted averaging is systematically biased; pool CPR = implied by total prepays / total balance, not mean of loan CPRs |
| `META` | Field-dependent — see notes | Scalars summed (balances, accrued interest); identifiers zeroed (`loan_id=0` signals aggregate); dates taken as None or max |

**Why ratios must be recomputed, not averaged:**
A simple example: two loans, each with CPR 6%, but one 10× the balance of the other. The balance-weighted average CPR is still 6%, but if the larger loan has lower SMM the aggregate CPR from the defining formula will differ. More critically, loss severity = `prin_loss / prin_recov` at the pool level — this cannot be computed from per-loan severities because the denominator (recoveries) must be the pool total.

**Practical implication for new fields:**
Adding a new field to either dataclass? Tag it with the correct `FieldKind` and it automatically participates in aggregation without changing any aggregation function. This is the key forward-compatibility guarantee of the metadata-driven approach.

---

### Cross-Collateralization (Part H)

- **NONE:** No cross-collat (agency convention)
- **FULL:** Pool-level excess covers pool-level shortfall, up to `cross_collateral_cap` (0.0–1.0)
- **GROUP:** Partition by `group_id`; within-group reallocation (requires per-loan `group_id`)

---

## 1. Problem Statement

We have a Python dataclass called `CashFlow` whose fields are numpy vectors of fixed length `T` (one element per period). These fields fall into three semantic categories:

- **Flows** — additive quantities that represent period-level cash movements: scheduled principal, prepayment, interest, defaults, and similar.
- **Stocks** — balance quantities derived from the flow recurrence: beginning balance, ending balance, factor. These cannot be naively summed across assets.
- **Ratios** — intensive quantities such as CPR, CDR, WAC, and loss severity. These are recomputed from defining formulas applied to the aggregated flows and stocks. Computing them from first principles on the aggregate is both simpler and more correct.

We need a `PortfolioCashFlow` type that aggregates an arbitrary number of `CashFlow` instances as efficiently as possible, supports add, subtract, multiply, and divide operations, and maintains a reliable mutation history.

---

## 2. Objectives

- **Correctness** — flows must be summed; stocks must be derived from the summed flows; ratios must be recomputed from their defining formulas applied to the aggregated flows and stocks. No field category may be treated as another.
- **Performance** — minimise intermediate array allocations; exploit numpy/BLAS bulk operations; defer expensive computations until results are actually needed.
- **Immutability for leaf objects** — `CashFlow` instances are frozen at construction and never modified.
- **Tracked mutability for the portfolio** — `PortfolioCashFlow` is mutable, but every change is recorded in an append-only event log that supports version inspection and state reconstruction via `rewind()`.
- **Type consistency** — arithmetic operators return predictable, uniform types that callers never need to branch on.
- **Semantic honesty** — the type system reflects domain reality: a single asset is a `CashFlow`; anything involving aggregation is a `PortfolioCashFlow`.

---

## 3. Field Classification and the FieldKind Registry

The entire architecture rests on the observation that the three field kinds aggregate differently. Rather than hardcoding field lists in multiple places, each field carries a `FieldKind` annotation in its dataclass metadata. This registry drives both `CashFlow` and `PortfolioCashFlow` programmatically.

```python
from enum import Enum, auto

class FieldKind(Enum):
    FLOW  = auto()   # additive — sum across assets
    STOCK = auto()   # derived from aggregated flows, not summed
    RATIO = auto()   # recomputed from formula(flows, stocks) — never accumulated
```

Ratio fields carry an additional `weight` metadata key naming the STOCK field to use as denominator. Example:

```python
cpr: np.ndarray = field(metadata={'kind': FieldKind.RATIO, 'weight': 'beg_balance'})
```

A helper `class_fields(kind)` function inspects dataclass fields and returns only those with the matching `FieldKind`, keeping all downstream logic generic. Column indices are resolved once from the registry to `np.int64` module-level constants at class definition time. The registry itself is never consulted inside a hot-path function.

---

## 4. CashFlow Types

### 4.1 Two Independent Dataclasses

There are two concrete CashFlow types: `ScheduledCashFlow` and `ActualCashFlow`. They are **independent frozen dataclasses** with no inheritance relationship and no shared abstract parent. They are not siblings in a type hierarchy — they are simply two different classes that happen to share a small set of loan-identity and period-alignment fields because those are properties of the underlying loan, not of the cash flow type.

The reason to resist inheritance is domain-semantic: an `ActualCashFlow` was produced using a `ScheduledCashFlow` as a computational input, but once that computation is complete the scheduled flow has no presence in the actual object. It is not a field, not a base class, not a protocol constraint. The scheduled flow was consumed upstream. The `ActualCashFlow` object contains only actual results.

Equally, a `ScheduledCashFlow` has no knowledge of prepayment or default behaviour — those fields are structurally absent, not zero. Two independent dataclasses avoid any pressure to carry fields that are meaningless to one of the types.

### 4.2 ScheduledCashFlow

Models the contractual cash flow assuming no prepayment and no defaults — derivable from loan terms alone:

- **Flows:** `scheduled_principal`, `scheduled_interest`
- **Stocks:** `beg_balance`, `end_balance`, `factor`
- **Ratios:** `wac`, `wam`
- **Identity / alignment:** `loan_id: np.int64`, `asof_year: np.int64`, `asof_month_num: np.int64`, `next_pay_year: np.int64`, `next_pay_month_num: np.int64`, `stub_accrual_fraction: np.float64`

### 4.3 ActualCashFlow

Models the projected or observed cash flow incorporating prepayment and default behaviour. It carries a richer field set — not because it extends `ScheduledCashFlow`, but because the phenomenon it describes is richer:

- **Flows:** `scheduled_principal`, `scheduled_interest`, `prepayment`, `default_principal`, `recovery`, `net_loss`
- **Stocks:** `beg_balance`, `end_balance`, `factor`, `cumulative_loss`
- **Ratios:** `cpr`, `cdr`, `loss_severity`, `wac`
- **Identity / alignment:** `loan_id: np.int64`, `asof_year: np.int64`, `asof_month_num: np.int64`, `next_pay_year: np.int64`, `next_pay_month_num: np.int64`, `stub_accrual_fraction: np.float64`

Overlapping field names (`scheduled_principal`, `beg_balance`, etc.) are intentional — those concepts are valid within an actual cash flow as part of the total decomposition. They are independently defined fields that share names because the domain concept is the same, not because one class inherits from the other.

### 4.4 CashFlowPair (Implemented)

`CashFlowPair` is a frozen dataclass holding exactly one `BMAScheduledCashflow` and one `BMAActualCashflow` for the same loan. It validates `loan_id`, `original_term`, `remaining_term`, and date fields (`asof_date`, `first_payment_date`, `maturity_date`) at construction. It exposes `scale_by(scalar)` returning a new `CashFlowPair` with scaled scheduled and actual. Used as the atomic unit in `PAIRED` mode.

### 4.5 Portfolio Mode and Mode Locking (Implemented)

`PortfolioCashflow` operates in one of three modes via `PortfolioMode` enum: `SCHEDULED_ONLY`, `ACTUAL_ONLY`, `PAIRED`. Mode is determined by the type of the first constituent and may be coerced when combining via LCD (least common denominator). `_extract_for_mode()` extracts the appropriate component from `CashFlowPair` (scheduled or actual) when mode is not PAIRED. Attempting to add `BMAActualCashflow` to `SCHEDULED_ONLY` or vice versa raises `PortfolioModeError`.

### 4.6 generate_actual_cashflow() — The Bridge Function

`generate_actual_cashflow()` is the **only function in the entire system** that has a foot in both CashFlow types. It always takes a `ScheduledCashFlow` as a required input — it cannot run without one, because the prepayment and default model operates against the contractual schedule — and it produces an `ActualCashFlow` by computing the prepayment and default overlays. The `ScheduledCashFlow` is a computational input, consumed by the function. What happens to it afterward depends on a single output mode flag.

The output mode is expressed as an enum rather than a boolean, for readability at the call site and extensibility:

```python
class ActualOutputMode(Enum):
    STANDALONE = auto()   # returns ActualCashFlow only
    PAIRED     = auto()   # returns CashFlowPair

def generate_actual_cashflow(
    scheduled:        ScheduledCashFlow,
    prepayment_model: ...,
    default_model:    ...,
    ...,
    output_mode: ActualOutputMode = ActualOutputMode.STANDALONE
) -> ActualCashFlow | CashFlowPair:
    actual = ActualCashFlow(...)   # computed from scheduled + models
    if output_mode == ActualOutputMode.PAIRED:
        return CashFlowPair(scheduled=scheduled, actual=actual)
    return actual
```

The `ActualCashFlow` produced is identical regardless of output mode — the flag controls only whether the `ScheduledCashFlow` that was used to compute it is preserved alongside it in a `CashFlowPair`, or discarded after computation. This is what makes it correct for `ActualCashFlow` to carry no reference to its originating `ScheduledCashFlow`.

For callers that want static type safety, Python's `@overload` decorator can narrow the return type based on the literal enum value passed.

This function is the natural seam for parallelisation: a pool of loans can each call `generate_actual_cashflow()` independently and in parallel, accumulating results as either a list of `ActualCashFlow` objects or a list of `CashFlowPair`s, before passing the batch to `PortfolioCashFlow` for aggregation. The generation step and the aggregation step are fully decoupled.

---

## 5. Period Alignment and the Month-Bucket Model

### 5.1 The Core Simplification

Cash flows are monthly. That single constraint eliminates most date-alignment complexity. The portfolio's time axis is a sequence of `(year, month)` integer pairs — a **month bucket** — not a sequence of exact dates. Any `AsOfDate` is snapped to its calendar month on entry. A loan with `AsOfDate = Jan 1`, a loan with `AsOfDate = Jan 15`, and a loan with `AsOfDate = Jan 28` all land in the January bucket and can be directly summed. Sub-monthly precision is not modelled at the portfolio level.

The stub period — the gap between `AsOfDate` and `NextPayDate` — is entirely a within-`CashFlow` concern. It determines which monthly buckets in the loan's own local vector contain zeros and what the accrual fraction is for the first non-zero payment period. By the time a `CashFlow` vector reaches `PortfolioCashFlow` it is simply a matrix with some zero rows at the front. The portfolio does not know or need to know why those zeros exist.

### 5.2 CashFlow Local Time Axis

Each `CashFlow` stores its period-alignment information as four `np.int64` scalar fields: `asof_year`, `asof_month_num`, `next_pay_year`, `next_pay_month_num`. Period `k` in every vector corresponds to `asof_month + k months`. Period 0 is always `AsOfDate`.

The `stub_accrual_fraction` (`np.float64`) records the day-count fraction for the broken period between `AsOfDate` and the first full payment period. This affects interest in period 0 or period 1 depending on convention. It is stored for audit; already baked into the flow vectors at construction time.

**Example:** `OriginationDate = 12/15/25`, `AsOfDate = 01/01/26`, `NextPayDate = 03/01/26`:

```
asof_year / asof_month_num  = 2026, 1
next_pay_year / month_num   = 2026, 3

flows.interest   = [stub_accrual, 0.0, first_full_payment, ...]
flows.principal  = [0.0,          0.0, sched_principal,    ...]
```

Period 0 holds any stub accrual interest. Period 1 is legitimately zero — the loan exists and has a balance, but `NextPayDate` has not yet arrived. Period 2 is the first full payment.

### 5.3 Portfolio Master Calendar

`PortfolioCashFlow` establishes a master calendar at construction time from the first constituent added:

- **`origin_year`, `origin_month_num`** (`np.int64`) — the earliest `AsOfDate` across all constituents, or an explicitly provided portfolio `AsOfDate`.
- **`T_max`** (`np.int64`) — length of the master calendar in months, extended as longer-maturity loans are added.

All internal matrices (`_committed`, `_pending` entries) are expressed in master calendar coordinates: row `k` corresponds to `origin_month + k months`.

### 5.4 Alignment at Ingestion

When a `CashFlow` is added to the portfolio, it is projected onto the master calendar before being pushed onto `_pending`. The projection is three lines:

```python
def _align(self, cf: ScheduledCashFlow | ActualCashFlow) -> np.ndarray:
    offset = (cf.asof_year - self.origin_year) * 12 \
           + (cf.asof_month_num - self.origin_month_num)
    padded = np.zeros((self.T_max, N_FLOW_FIELDS), dtype=np.float64)
    padded[offset : offset + len(cf._flow_matrix), :] = cf._flow_matrix
    return padded
```

If `cf` extends beyond the current `T_max`, `T_max` is extended and `_committed` is zero-padded to match before the new entry is pushed. The alignment operation zero-pads both the front (loans with a later `AsOfDate` than the portfolio origin) and the tail (loans with shorter remaining term than `T_max`). Both cases are handled identically by the `np.zeros` initialisation plus slice assignment.

### 5.5 Conformability Rules

Given the month-bucket simplification, only one hard conformability check remains:

**Payment frequency must be monthly.** Any `CashFlow` whose `payment_frequency != 1` raises `CashFlowConformabilityError` immediately on attempted addition. Different `AsOfDate` values, different lengths, and different stub structures are all handled automatically by the alignment logic and are not errors.

### 5.6 Future Frequency Expansion (Non-Monthly Sources)

> This is not required now but is noted here as a forward-looking extensibility constraint.

If a non-monthly `CashFlow` type were introduced (e.g., quarterly), `PortfolioCashFlow` must **not** be modified to understand non-monthly schedules internally. Instead, a frequency adapter layer sits between the source `CashFlow` and the ingestion path. Its job is to expand the compact non-monthly vector into a monthly-aligned matrix before `_align()` is called.

The expansion rule is straightforward: a payment that occurs at quarter-end is placed in the appropriate month bucket; the other two months of the quarter receive zeros. The result is semantically identical to a sparse monthly vector.

**General design principle: `PortfolioCashFlow` is frequency-naive by design.** It operates on the master calendar frequency (monthly). Any constituent that does not match is the responsibility of an adapter to expand at ingestion time. The portfolio's internal representation and all lazy computation logic are never modified for frequency concerns.

---

## 6. CashFlow — The Immutable Leaf Type

### 6.1 Construction and Immutability

`CashFlow` is a **frozen dataclass**. All field values including stocks and ratios are computed eagerly in `__post_init__` and stored as regular fields. Because the object is frozen and constructed once, there is nothing to cache or invalidate — `functools.cached_property` and manual dirty flags are both irrelevant here. Compute everything up front and be done with it.

### 6.2 Arithmetic Operator Semantics

**`__add__` and `__sub__`:** When you write `cf1 + cf2` you are, by definition, holding two assets. The result is a portfolio — not a single asset. Returning a `CashFlow` here would be a type lie. These operators **must** return `PortfolioCashFlow`. There is no ambiguity; this is semantically mandated by the domain.

**`__mul__`, `__rmul__`, `__truediv__`, `__neg__`:** These involve only a single `CashFlow` and a scalar. The result could technically remain a `CashFlow`, but returning `PortfolioCashFlow` is the preferred choice for type uniformity: callers never need to branch on whether an arithmetic result is a `CashFlow` or `PortfolioCashFlow`.

Implementation: `CashFlow` arithmetic operators are thin wrappers that construct a `PortfolioCashFlow` and delegate:

```python
def __add__(self, other: 'CashFlow') -> 'PortfolioCashFlow':
    return PortfolioCashFlow([self, other])

def __mul__(self, scalar: np.float64) -> 'PortfolioCashFlow':
    return PortfolioCashFlow([self]) * scalar
```

`CashFlow` never defines `__iadd__` or `__imul__` — in-place mutation of a frozen object is nonsensical.

### 6.3 The sum() Pattern

Python's built-in `sum()` seeds with integer `0`, so `sum([cf1, cf2])` calls `0 + cf1`, which fails. Always use the explicit start form:

```python
portfolio = sum(cashflows, start=PortfolioCashFlow.empty(T))
```

`PortfolioCashFlow.empty(T)` is a class method that returns a zero-filled portfolio of the correct period length. It is also the additive identity for `reduce()` patterns.

---

## 7. PortfolioCashFlow — The Mutable Computation Type

### 7.1 Internal Storage (Implemented)

The portfolio maintains:

- **`_pending`** — list of leaf cashflows (BMAScheduledCashflow | BMAActualCashflow | CashFlowPair) or extracted components per mode. Each add appends here.
- **`_committed`** — dict caching computed results: `_scheduled`, `_pool`, `_waterfall`. Cleared by `_invalidate()` on mutation.
- **`_history`** — append-only list of `PortfolioEvent` (version, timestamp, op, operand_id, operands) for rewind.

### 7.2 Lazy Evaluation Strategy

Flows, stocks, and ratios form a strict dependency chain:

```
_pending arrays  →  committed flows  →  stocks  →  ratios
```

Each level is computed lazily using `functools.cached_property`. The property writes its result into the instance's `__dict__` on first access. Invalidation on mutation is simply deletion of the relevant `__dict__` keys — **no boolean dirty flags needed**.

```python
@cached_property
def flows(self) -> np.ndarray:
    if self._pending:
        stack = np.stack(self._pending, axis=0)   # (n_pending, T, n_fields)
        reduced = stack.sum(axis=0)               # (T, n_fields)
        self._committed = (
            reduced if self._committed is None
            else self._committed + reduced
        )
        self._pending.clear()
    return self._committed

@cached_property
def stocks(self) -> np.ndarray:
    return _derive_stocks(self.flows)   # accesses flows, triggering its cache

@cached_property
def ratios(self) -> np.ndarray:
    return _derive_ratios(self.flows, self.stocks)
```

Individual field access (e.g., `portfolio.cpr`) is a property that routes through the appropriate cached group. The dependency chain is expressed as normal Python attribute access — no manual orchestration.

Mutation invalidation:

```python
def _invalidate(self):
    self.__dict__.pop('flows', None)
    self.__dict__.pop('stocks', None)
    self.__dict__.pop('ratios', None)
```

Note: `cached_property` requires a writable `__dict__`, which means no `__slots__` on `PortfolioCashFlow`.

### 7.3 Why Stack-and-Sum, Not Incremental Addition

Incremental pairwise summation in a loop forces `O(n)` sequential numpy calls and allocates a new intermediate array at each step. **Stack-and-sum** defers all arithmetic until the loop ends, then reduces the entire stack in a single numpy call — a single BLAS operation over a contiguous memory block.

```python
# Incremental — bad: O(n) allocations
for cf in cashflows:
    portfolio += cf   # would allocate a new array each time if eager

# Stack-and-sum — good: one allocation at reduction time
stack = np.stack(pending, axis=0)   # (n, T, n_fields)
total = stack.sum(axis=0)           # (T, n_fields)
```

The pending list accumulates array references (not copies) until flush. An explicit `flush()` method is exposed so callers can force reduction at a known point without needing to access a field to trigger it. A configurable `max_pending` threshold can trigger an automatic partial flush mid-loop to bound memory pressure for very large portfolios.

### 7.4 Stock Derivation

Stocks are derived from the aggregated flow matrix using numpy accumulate primitives where the recurrence is linear. For standard mortgage cash flows:

```python
end_balance[t] = beg_balance[t] - scheduled_principal[t]
                                 - prepayment[t] - defaults[t]
beg_balance[t] = end_balance[t-1]
```

This sequential recurrence is handled by `numpy.subtract.accumulate` in the common linear case. The derivation logic lives in `_derive_stocks()` — a standalone module-level function, not a method — so it is a clean `@numba.njit` target.

### 7.5 Ratio Derivation

Ratios are **recomputed from their defining formulas** applied entirely to the aggregated flow and stock matrices. They are not accumulated, averaged, or carried through the pending stack in any form. The pending stack holds **flow fields only**. Ratios are the final step in the dependency chain, computed after stocks are settled:

```python
# Applied to (T,) slices of the aggregated flow and stock matrices
cpr = 1 - (1 - prepayment / beg_balance) ** 12
cdr = 1 - (1 - default_principal / beg_balance) ** 12
wac = (scheduled_interest / beg_balance) * 12
sev = net_loss / default_principal
```

Each formula is a vectorised numpy operation over arrays already present in the aggregated matrices. Division-by-zero in late periods (when balance or default principal reaches zero) is handled with `np.where` guards inside each formula function.

This approach is cleaner than weighted averaging for three reasons. First, it is semantically unambiguous — portfolio CDR is definitionally the rate implied by total defaults against total balance, not the balance-weighted mean of constituent CDRs. For most ratios these are mathematically equivalent, but for severity they are not: portfolio severity is net loss over defaulted principal, which requires the aggregated totals. Second, the pending stack only ever holds flow columns, simplifying both the data model and the Numba-compatible type layout. Third, defining-formula application is trivially `@njit`-able with no additional accumulation state.

---

## 8. Arithmetic Operators on PortfolioCashFlow

`PortfolioCashFlow` is explicitly mutable and **only exposes in-place operators**. There are no non-mutating forms — the version history exists precisely to track mutations, so copying is never needed. If two portfolios diverging from a common starting point are required, construct two independent portfolios and add the appropriate loans to each.

```python
def __iadd__(self, other: ScheduledCashFlow | ActualCashFlow | CashFlowPair):
    self._pending.append(self._align(other._flow_matrix))
    self._record_event('add', other.loan_id)
    self._invalidate()
    return self

def __isub__(self, other: ScheduledCashFlow | ActualCashFlow | CashFlowPair):
    self._pending.append(self._align(other._flow_matrix) * np.float64(-1.0))
    self._record_event('subtract', other.loan_id)
    self._invalidate()
    return self

def __imul__(self, scalar: np.float64) -> 'PortfolioCashFlow':
    _ = self.flows              # force flush before scaling
    self._committed *= scalar
    self._record_event('scale', scalar=scalar)
    self._invalidate()
    return self

def __itruediv__(self, scalar: np.float64) -> 'PortfolioCashFlow':
    return self.__imul__(np.float64(1.0) / scalar)
```

`__imul__` forces a flush before scaling because scaling must apply to the fully reduced committed matrix. This is the one case where lazy evaluation is deliberately short-circuited.

**Subtraction semantics:** subtracting a constituent reduces the aggregated flows. It does not restore the portfolio to any prior state — it produces a new flow total from which stocks and ratios are freshly derived. The event log records what was subtracted and when; the prior state can be recovered via `rewind()` if needed.

---

## 9. Version History and Mutation Tracking

### 9.1 Event Log Model

History is an append-only log of `PortfolioEvent` objects. Each event records what happened and when, **not a full snapshot of state**. Snapshots of large numpy arrays would be prohibitively expensive — the log avoids this by storing only `loan_id` references, not the `CashFlow` objects themselves.

```python
@dataclass
class PortfolioEvent:
    version:    np.int64
    timestamp:  datetime
    op:         Literal['add', 'subtract', 'scale']
    operand_id: np.int64        # loan_id for add/subtract
    scalar:     np.float64      # only populated for scale operations
```

Events are recorded at logical mutation time (when `__iadd__` is called), not at reduction time. The portfolio's logical state changes when an asset is added, not when the arithmetic is executed.

### 9.2 Memory Cost

The event log stores `loan_id` references, not `CashFlow` objects. The `CashFlow` objects live wherever the caller keeps them. For a portfolio of 10,000 loans, the event log is 10,000 small structs — a few integers and a timestamp each, on the order of a few hundred kilobytes at most. This is negligible relative to the flow matrices themselves, which are `(T_max, n_flow_fields)` `float64` arrays that dwarf the history by orders of magnitude.

The portfolio has no ownership over the constituent objects and makes no attempt to retain them. Retaining `CashFlow` objects in the event log would prevent garbage collection and grow memory proportionally with history length.

### 9.3 The rewind() Method (Implemented)

`rewind(version, store)` reconstructs the portfolio at any prior version by replaying `_history` up to that version. Each `PortfolioEvent` stores `operands` (tuple of constituents added/removed) so replay does not require an external store. If `store` is provided, removed constituents from subtract events are appended to it. Returns a fresh `PortfolioCashflow` with `_version` and `_history` trimmed to the requested version.

### 9.4 Correctness Guarantee

Because `ScheduledCashFlow` and `ActualCashFlow` are frozen dataclasses they can never be mutated after construction. This means `rewind()` is **always exact** as long as the caller has not discarded the objects from their store.

If a `loan_id` in the event log is not present in the store passed to `rewind()`, a `KeyError` is raised immediately naming the missing `loan_id` — the method never silently produces a partial reconstruction. If the caller cannot guarantee that their store is complete (e.g., objects may have been evicted from a cache), they should catch `KeyError` and treat it as a signal that the requested version is unrestorable from the available data.

---

## 10. Numba JIT Compatibility Constraints

The classes are designed today so that the computationally hot paths can be JIT-compiled with Numba in the future without requiring structural changes.

### 10.1 The Two-Layer Architecture

No class needs to become a Numba `jitclass` in its entirety. The correct target for JIT compilation is the computational core — the pure functions that do arithmetic on numpy arrays — not the Python wrapper that manages state, history, and lazy evaluation.

- **Data / computation layer** — numpy arrays with explicit dtypes, scalar numeric fields, identity fields as integers. Numba-compatible by construction. The hot functions (`_derive_stocks`, `_derive_ratios`, `_align`, stack-and-sum reduction) are standalone `@numba.njit` functions from day one, even before Numba is a dependency. They are plain functions until the decorator is added.
- **Behaviour layer** — `cached_property`, `__post_init__`, arithmetic dunders, event log, mode locking, `CashFlowPair` validation. Pure Python. Never a JIT target. Calls into the data layer functions for all computation.

Numba is adopted incrementally: decorate the hot functions one by one as profiling identifies bottlenecks, with no changes to the class structure.

### 10.2 Field Type Rules

Every field in `ScheduledCashFlow` and `ActualCashFlow` must follow these rules:

- **All flow, stock, and ratio arrays:** `np.ndarray` with explicit `dtype=np.float64`. Never plain `float[]`, never untyped `np.ndarray`.
- **`loan_id`:** `np.int64` — a numeric surrogate key or hash. Numba cannot hold Python strings in a jitclass. The human-readable string label lives in a Python-layer lookup table outside the object entirely.
- **Date fields:** Four separate `np.int64` scalars (`asof_year`, `asof_month_num`, `next_pay_year`, `next_pay_month_num`). No `datetime` objects, no tuple, no enum in the data layer.
- **`stub_accrual_fraction`:** `np.float64` — scalar, fine.
- **`payment_frequency`:** `np.int64` — encode as integer (e.g., `1` = monthly, `3` = quarterly). Not an enum.

These rules apply to the data-carrying fields only. Python-layer fields (event log entries, mode enum on `PortfolioCashFlow`, `cached_property` results) are exempt.

### 10.3 No Python Objects in Hot-Path Functions

Every function that is a candidate for `@numba.njit` must accept and return only Numba-compatible types: numpy arrays, numpy scalars, integers, floats, and homogeneous tuples thereof:

- `_derive_stocks(flow_matrix: np.ndarray) -> np.ndarray` — takes and returns 2D `float64` arrays only.
- `_derive_ratios(flow_matrix: np.ndarray, stock_matrix: np.ndarray) -> np.ndarray` — same.
- `_align(flow_matrix: np.ndarray, offset: np.int64, t_max: np.int64) -> np.ndarray` — integer scalars for positioning, `float64` array for data.
- `_reduce_pending(pending: numba.typed.List) -> np.ndarray` — the stack-and-sum function.

These functions are written as **module-level functions, not methods**, so they can be decorated with `@numba.njit` without any class dependency. The class methods are thin wrappers that call them.

### 10.4 FieldKind Registry is Python-Layer Only

The `FieldKind` enum and the field registry are used at class definition time and at portfolio ingestion time to map field names to column indices. They are never consulted at computation time inside a hot-path function. Column indices are resolved once, stored as `np.int64` constants at module level, and passed directly to array slicing operations.

```python
INTEREST_COL:   np.int64 = np.int64(0)
PRINCIPAL_COL:  np.int64 = np.int64(1)
PREPAYMENT_COL: np.int64 = np.int64(2)
```

### 10.5 The _pending List

In pure Python operation, `_pending` is a plain Python list of `np.ndarray` objects — lower per-append overhead than `numba.typed.List`. If the reduction function is JIT-compiled, `_pending` is converted to `numba.typed.List` once at flush time:

```python
from numba.typed import List as NumbaList

def _maybe_reduce(self):
    if self._pending:
        typed = NumbaList(self._pending)   # convert at boundary, once
        self._committed = _reduce_pending(typed, self._committed)
        self._pending.clear()
```

### 10.6 Python-Only Coordinator Types

`CashFlowPair`, `PortfolioModeError`, `CashFlowPairingError`, `CashFlowConformabilityError`, `ActualOutputMode`, and `PortfolioEvent` are all pure Python constructs. They are coordinator and error types that exist at the boundary layer. None of them are JIT targets and none need Numba-compatible field types. They may freely use strings, enums, datetimes, and Python objects.

### 10.7 Type Hint Discipline

All function signatures must use numpy dtype-specific annotations consistently:

```python
# Arrays
flows: np.ndarray[tuple[int, int], np.dtype[np.float64]]

# Scalars
loan_id: np.int64
fraction: np.float64
```

Avoid `typing.Optional` for any field that will live in the data layer. If a field may be absent, represent absence as a sentinel value (`np.int64(-1)` for an unset `loan_id`, `np.float64(np.nan)` for a missing ratio) rather than `None`, which Numba cannot handle.

---

## 11. Additional Design Considerations

### 11.1 Period Conformability

Conformability rules are fully specified in Section 5.5. The only hard check at addition time is that `payment_frequency == 1` (monthly). Length mismatches and `AsOfDate` differences are resolved automatically by `_align()` — they are handled, not rejected.

### 11.2 Negative Balances and Validation

After stock derivation, validate that balance fields do not go negative (unless short positions are explicitly modelled). Make this a configurable validation pass controlled by a `validate_stocks: bool` flag, defaulting to `True`. Disable for bulk processing where inputs are already known good.

### 11.3 Numeric Precision

Repeated floating-point addition of many small vectors accumulates rounding error. For high-precision requirements on critical fields (e.g., running balance), consider Kahan compensated summation or `np.sum` with higher-precision accumulators. At minimum, document the precision characteristics and test round-trip invariants.

### 11.4 Thread Safety

`cached_property` is not thread-safe: concurrent reads on an uncached property can race. `PortfolioCashFlow` is designed as a **single-writer object**. Document this constraint explicitly. If multi-threaded access is needed, add a `threading.Lock` around `_invalidate()` and the `cached_property` compute paths.

### 11.5 Serialization

The event log must be serialisable for persistence and audit. `CashFlow` objects referenced in events are stored by `loan_id` (`np.int64`) rather than by value — no large arrays appear in the log. `CashFlow` should support `__hash__` via a hash of its flow arrays (stocks and ratios are derived and need not be hashed).

### 11.6 Empty Portfolio

Define `PortfolioCashFlow.empty(T)` as a class method returning a zero-filled portfolio of period length `T`. This is the additive identity and the correct `start` argument for `sum()` and `reduce()` patterns.

---

## 12. Decision Summary

| Decision Point | Resolution |
|---|---|
| CashFlow type model | Two independent frozen dataclasses: `ScheduledCashFlow` and `ActualCashFlow`. No inheritance, no shared parent. Related only by `loan_id` at the portfolio level. |
| `CashFlowPair` | Frozen container holding one `ScheduledCashFlow` and one `ActualCashFlow` for the same loan. Validates `loan_id` and `asof_month` match at construction. Atomic unit of addition in `PAIRED` mode. |
| Portfolio mode | Three modes: `SCHEDULED_ONLY`, `ACTUAL_ONLY`, `PAIRED`. Determined by the type of the first addition and locked permanently. Wrong type raises `PortfolioModeError` immediately. |
| `PAIRED` mode storage | Two independent pending stacks and committed matrices — one scheduled, one actual — aligned to the same master calendar. Stocks and ratios computed independently. |
| `PAIRED` mode variance properties | Derived quantities (e.g., excess prepayment) available only in `PAIRED` mode. Access on other modes raises `PortfolioModeError`. |
| `CashFlow` mutability | Frozen dataclass. All fields computed eagerly in `__post_init__`. No caching needed. |
| `CashFlow __add__ / __sub__` return type | Must return `PortfolioCashFlow`. Semantically mandated: two assets in hand equals a portfolio by definition. |
| `CashFlow __mul__ / __div__ / __neg__` return type | Should return `PortfolioCashFlow` for type uniformity. Weaker semantic pressure but eliminates branching for callers. |
| `PortfolioCashFlow` mutability | Mutable via `__i*__` operators only. No non-mutating forms defined. Version history tracks all mutations. |
| Flow aggregation strategy | Stack-and-sum: each `__iadd__` appends to `_pending` list. Reduction is a single `np.stack + sum(axis=0)` deferred until first flow access. |
| Lazy evaluation mechanism | `functools.cached_property` for flows, stocks, and ratios. Invalidation via `__dict__.pop()`. No boolean dirty flags. |
| Dependency chain | `pending → flows → stocks → ratios`. Expressed as Python attribute access. |
| Stock computation | Derived from aggregated flows using numpy accumulate primitives. Never summed across assets. |
| Ratio computation | Recomputed from defining formulas (e.g., `CPR = 1-(1-prepayment/beg_balance)^12`) applied to aggregated flows and stocks. Never accumulated or weighted-averaged. Pending stack holds flow fields only. |
| Event log model | Append-only log of `PortfolioEvent`. Stores `loan_id` references, not `CashFlow` objects. Events recorded at logical mutation time, not reduction time. |
| Event log memory cost | Negligible — stores `loan_id` (`np.int64`) and timestamps only. ~few hundred KB for 10,000-loan portfolio. |
| `rewind()` method | Replays event log up to target version against caller-supplied `dict[loan_id -> CashFlow]`. Returns fresh portfolio. Original untouched. |
| `rewind()` correctness | Exact as long as store is complete. Frozen `CashFlow` objects cannot be mutated. Missing `loan_id` raises `KeyError` immediately. |
| Period alignment model | Month-bucket: `AsOfDate` snapped to `(year, month)`. Sub-monthly precision not modelled at portfolio level. |
| Constituent alignment | `offset = month difference` between loan `AsOfDate` and portfolio `origin_month`. Zero-pad front and tail via `np.zeros` + slice assignment. |
| Stub period handling | Within-`CashFlow` concern only. Stored as four `np.int64` date scalars + `stub_accrual_fraction`. Portfolio sees only the resulting vector. |
| Non-monthly frequency (future) | Adapter layer expands to monthly before `_align()`. `PortfolioCashFlow` remains frequency-naive; never modified for frequency concerns. |
| Conformability checking | Only hard check is monthly frequency. Length and `AsOfDate` differences resolved automatically by `_align()` padding. Non-monthly raises `CashFlowConformabilityError`. |
| `sum()` / `reduce()` pattern | Use `sum(cashflows, start=PortfolioCashFlow.empty(T))` — never rely on implicit seed of integer `0`. |
| Numba compatibility model | Two-layer split: data/computation layer (Numba-compatible) vs behaviour layer (pure Python). Hot functions are standalone `@njit` candidates from day one. |
| `loan_id` type | `np.int64` surrogate key in all `CashFlow` dataclasses. String label lives in a Python-layer lookup table only. |
| Date fields | Four separate `np.int64` scalars. No `datetime` objects, no tuples, no enums in data layer. |
| numpy array dtype | All flow/stock/ratio arrays declared as explicit `dtype=np.float64`. Untyped `np.ndarray` not permitted in data layer fields. |
| `FieldKind` registry at runtime | Never consulted inside hot-path functions. Column indices resolved to `np.int64` module-level constants at class definition time. |
| `_pending` list boundary | Plain Python list for accumulation. Converted to `numba.typed.List` once at flush time before passing to `@njit` reduction function. |
| `Optional` fields | No `typing.Optional` in data layer. Absent values represented by `np.int64(-1)` or `np.float64(nan)` sentinels. |
| Thread safety | Single-writer by design. Document constraint. Add `threading.Lock` if concurrent access is required. |

---

## 13. Critical Testing Invariants

**Invariant 1 — Single-asset round trip.** For a portfolio containing exactly one asset, all derived fields must agree with the originating `CashFlow` within numerical tolerance:

```python
cf = ScheduledCashFlow(...)
portfolio = PortfolioCashFlow([cf])

assert np.allclose(portfolio.wac, cf.wac)
assert np.allclose(portfolio.beg_balance, cf.beg_balance)
assert np.allclose(portfolio.scheduled_interest, cf.scheduled_interest)
```

This round-trip test catches errors in ratio formula application, stock derivation recurrence, and flow accumulation. It must pass before any multi-asset tests are attempted.

**Invariant 2 — Stub period preservation.** Using the example from Section 5.2 (`OriginationDate = 12/15/25`, `AsOfDate = 01/01/26`, `NextPayDate = 03/01/26`):

```python
# Stub accrual survives alignment unchanged
assert portfolio.flows[0, INTEREST_COL] == cf.flows[0, INTEREST_COL]
# Period 1 is legitimately zero — not an alignment artifact
assert portfolio.flows[1, :].sum() == 0.0
# First real payment lands in period 2
assert portfolio.flows[2, PRINCIPAL_COL] > 0.0
```

**Invariant 3 — Same-month-bucket alignment.** Two loans with different `AsOfDate` values within the same month bucket (e.g., Jan 1 and Jan 15) must produce portfolio flows exactly equal to the direct element-wise sum of their vectors with no offset between them, confirming the month-bucket snapping rule.

**Invariant 4 — rewind() round trip.** For a portfolio built by adding `n` loans, `rewind(version=n, store=store)` must reproduce the current portfolio state exactly:

```python
store = {cf.loan_id: cf for cf in cashflows}
rewound = portfolio.rewind(version=len(cashflows), store=store)

assert np.allclose(rewound.flows, portfolio.flows)
```

**Invariant 5 — Mode enforcement.** Adding a `ScheduledCashFlow` to an `ACTUAL_ONLY` or `PAIRED` portfolio must raise `PortfolioModeError` immediately, before any arithmetic is performed.

---

*End of Document — For Independent Review and Implementation*
