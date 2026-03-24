# Architecture Overview

**Package:** `bma-standard-formulas` v0.5.0
**Reference:** BMA "Uniform Practices/Standard Formulas" (02/01/99)

---

## 1. Two-Layer Design

The package splits into two sub-packages with a strict one-way dependency:

```
bma_standard_formulas.formulas   ← math only, no application state
         ↑ imported by
bma_standard_formulas.engine     ← application layer: Loan, RateIndex, Portfolio
```

`formulas` never imports from `engine`. Everything in `formulas` is a pure
function or frozen dataclass that operates on plain Python/numpy values.
`engine` wraps those functions with the Loan data model, tape reader,
portfolio aggregation, and persistence.

---

## 2. Package Structure

```
src/bma_standard_formulas/
├── __init__.py                   version via importlib.metadata
│
├── formulas/
│   ├── __init__.py               re-exports all public symbols
│   ├── scheduled_payments.py     B.1: balance/payment/amortization factors
│   ├── payment_models.py         B.2–B.4, C: SMM/CPR/PSA/ABS/CDR/MDR/SDA
│   ├── cashflows.py              C.3: cashflow runners + result dataclasses
│   └── examples.py               reference examples from BMA document
│
└── engine/
    ├── __init__.py               re-exports all public symbols
    ├── loan.py                   Loan dataclass, curve slicing, portfolio runners
    ├── rate_index.py             RateIndex: dated rate curve for floating-rate loans
    ├── portfolio.py              PortfolioCashflow aggregation + trust waterfall
    ├── tape.py                   TapeSchema / read_loan_tape: CSV → list[Loan]
    └── cashflow_persistence.py   Parquet I/O for cashflow objects
```

---

## 3. Numeric Conventions

Understanding these conventions is essential before calling any function.

### 3.1 Coupon / Rate Units

All coupon and rate values are stored and passed as **PERCENT** (e.g. `8.0`
means 8%), matching market convention. The formulas internally divide by 1200
to get a monthly decimal rate:

```python
monthly_rate = coupon / 1200.0   # e.g. 8.0 / 1200 = 0.00667
```

This applies uniformly across `run_bma_scheduled_cashflow`,
`run_bma_actual_cashflow`, `Loan.rate_margin`, `RateIndex.rates`, and the
`coupon_vector` parameter.

The one exception is the `Loan.servicing_fee_decimal()` helper, which converts
the stored percent value to decimal for internal use.

### 3.2 Prepayment / Default Speed Units

| Symbol | Unit | Example |
|--------|------|---------|
| SMM    | decimal fraction | `0.005` = 0.5% monthly prepayment |
| MDR    | decimal fraction | `0.002` = 0.2% monthly default rate |
| CPR    | percent          | `6.0` = 6% annualized prepayment |
| PSA    | percent          | `100.0` = 100% PSA standard |
| CDR    | percent          | `2.0` = 2% annualized default rate |
| ABS    | percent          | `1.5` = 1.5% ABS speed |
| SDA    | percent          | `100.0` = 100% SDA standard |
| severity | decimal fraction | `0.35` = 35% loss given default |

The cashflow runners accept `smm_curve`, `mdr_curve`, and `severity_curve` as
numpy arrays of decimal fractions.  Use the conversion functions in
`payment_models` to go from CPR/PSA/CDR/SDA to the required SMM/MDR decimal.

### 3.3 Curve Indexing: Age-Indexed vs Period-Indexed

There are two different indexing conventions in the codebase, and they apply
at different layers:

**Age-indexed** (engine layer input): index 0 = loan origination.
A 30-year loan has a curve of length 361.  This is how curves are stored
in the `Loan` object and passed to `actual_cashflow_from_loan` and
`scheduled_cashflow_from_loan`.  The engine slices out the relevant
`[age : age + remaining_term + 1]` window automatically.

**Period-indexed** (formulas layer): index 0 = current observation period.
A loan with 300 months remaining has a curve of length 301.  This is the
convention for `smm_curve`, `mdr_curve`, and `severity_curve` passed directly
to `run_bma_actual_cashflow`.

```
Age-indexed (engine):   [orig, age1, age2, ..., age60, ..., age360]
                                        ↑ loan at age 60, sliced here →
Period-indexed (formulas):             [period0, period1, ..., period300]
```

The `_slice_curve` helper in `loan.py` performs this slice and raises
`ValueError` if the curve is too short to cover `loan.age + remaining_term + 1`.

---

## 4. The Formulas Layer

### 4.1 Scheduled Payments (B.1)

`scheduled_payments.py` provides scalar and vector functions for fixed-rate
and floating-rate mortgage amortization:

- `sch_balance_factor_fixed_rate(coupon, original_term, remaining_term)`
- `sch_payment_factor_fixed_rate(coupon, original_term, remaining_term)`
- `sch_am_factor_fixed_rate(coupon, remaining_term)`
- `sch_payment_factor(coupon, remaining_term)` — same, no M₀ needed
- `am_factor(beginning_balance, coupon, remaining_term)`
- `sch_payment_factor_vector(rate_vector, original_term)` — floating-rate
- `sch_balance_factors(rate_vector, original_term)` — full age-0..M₀ vector
- `sch_ending_balance_factor(rate_vector, original_term)` — scalar final balance

### 4.2 Payment Models (B.2–B.4, C)

`payment_models.py` provides prepayment speed conversions and curve generators:

**SMM ↔ CPR ↔ PSA conversions:**
`smm_to_cpr`, `cpr_to_smm`, `smm_from_factors`, `psa_to_cpr`, `cpr_to_psa`,
`psa_to_smm`, `generate_psa_curve`, `generate_smm_curve_from_psa`

**ABS (asset-backed) prepayment:**
`abs_to_smm`, `smm_to_abs`, `historical_abs`, `generate_smm_curve_from_abs`
ABS speed formula (BMA SF-15): `SMM = (100 × ABS) / (100 − ABS × (n−1))`

**Default models:**
`cdr_to_mdr`, `cdr_to_mdr_vector`, `sda_to_cdr`, `generate_sda_curve`

**Historical speed recovery (B.3):**
`smm_from_factors` — back-calculates SMM from a beginning factor, ending
factor, and scheduled amortization. Pool-level variants accept dicts with
`original_face`, `original_term`, `beginning_age`, `beginning_factor`,
`ending_factor`, and `coupon_vector`.

### 4.3 Cashflow Runners (C.3)

`cashflows.py` contains the two core BMA computation functions and their
result types:

**`run_bma_scheduled_cashflow(coupon, original_term, remaining_term, ...)`**
Returns a `BMAScheduledCashflow` — no prepayment, no defaults.  For fixed-rate
loans, the vectorized path through `sch_balance_factors` is used; for
floating-rate, a loop over the rate vector.

**`run_bma_actual_cashflow(coupon_vector, original_term, remaining_term, smm_curve, mdr_curve, severity_curve, ...)`**
Returns a `BMAActualCashflow` — includes prepayment and defaults.  Takes
period-indexed numpy arrays.

Both functions accept an optional ABS stub parameter for asset-backed
securities with non-standard prepayment profiles.

**Result dataclasses** (`BMAScheduledCashflow`, `BMAActualCashflow`):
Frozen dataclasses where every field carries `FieldKind` metadata
(`FLOW`, `STOCK`, `RATIO`, or `META`). This metadata drives aggregation in
`PortfolioCashflow` without hardcoding field lists.

`CashFlowPair` binds one scheduled and one actual cashflow for the same loan,
validated at construction.

`compare_arrays(bma_array, test_array)` compares two arrays element-wise,
reports the worst mismatch period and magnitude, and warns (not silently
truncates) if lengths differ.

---

## 5. The Engine Layer

### 5.1 Loan Dataclass

`Loan` is the central application-layer object.  It holds all loan-level
inputs in market units (% for rates, $ for balances, months for terms) and
provides the bridge to the formulas layer.

```python
@dataclass(slots=True)
class Loan:
    loan_id: int
    origination_date: np.datetime64 | date
    asof_date: np.datetime64 | date
    original_balance: float          # $ at origination
    current_balance: float           # $ at asof_date
    rate_margin: float               # annual % (full coupon for fixed; spread for ARM)
    original_term: int               # months (M₀)
    remaining_term: int              # months at asof
    servicing_fee: float = 0.0       # annual %
    reset_frequency: int = 0         # 0 = fixed; 12 = annual ARM
    index_type: str | None = None    # "SOFR", "LIBOR", etc.
    rate_cap: float | None = None    # life cap (%)
    rate_floor: float | None = None  # life floor (%)
    group_id: int | None = None      # for GROUP cross-collateralization
    # ... plus servicer advance fields, date fields
```

Computed properties: `loan.age` = `original_term - remaining_term`.

`__post_init__` validates: `original_term > 0`, `remaining_term >= 0`,
`remaining_term <= original_term`, `original_balance > 0`,
`current_balance <= original_balance`, `asof_date >= origination_date`,
`rate_cap >= rate_floor` if both set.

### 5.2 Per-Loan Cashflow Functions

Three convenience wrappers in `loan.py` call the formulas layer:

```python
scheduled_cashflow_from_loan(loan: Loan) -> BMAScheduledCashflow
actual_cashflow_from_loan(
    loan: Loan,
    smm_curve: np.ndarray,   # age-indexed, length >= loan.age + remaining_term + 1
    mdr_curve: np.ndarray,   # same
    severity_curve: np.ndarray,  # same
) -> BMAActualCashflow
```

`actual_cashflow_from_loan` calls `_slice_curve` on each input to extract
the period-aligned window for this loan, then calls `run_bma_actual_cashflow`.

For floating-rate loans, `build_rate_vector(loan, rate_index)` constructs the
coupon vector by calling `RateIndex.get_rate_vector` and adding the margin.

### 5.3 Portfolio Runner Functions

Three batch functions process a `list[Loan]` into a portfolio:

```python
run_scheduled_portfolio(loans) -> PortfolioCashflow   # SCHEDULED_ONLY mode
run_actual_portfolio(loans, smm_curve, mdr_curve, severity_curve) -> PortfolioCashflow
run_paired_portfolio(loans, smm_curve, mdr_curve, severity_curve) -> PortfolioCashflow
```

These iterate over loans, generate per-loan cashflows, and accumulate into a
`PortfolioCashflow` via `+=`.

### 5.4 RateIndex

`RateIndex` is an immutable (frozen dataclass) time series of dated rates for
floating-rate loan modeling.  Rates are stored in **PERCENT**.

```python
# Construction
idx = RateIndex.from_arrays(dates=[...], rates=[5.0, 5.25, ...], name="SOFR")
idx = RateIndex.from_csv("SOFR_historical.csv", name="SOFR")      # std column names
idx = RateIndex.from_csv("fwd.csv", date_col="ResetDate", rate_col="Rate")
idx = RateIndex.from_constant(5.25, name="flat")
idx = RateIndex.from_fred("SOFR")                                   # requires pandas-datareader

# Rate vector generation
vec = idx.get_rate_vector(
    next_payment_date=date(2024, 1, 1),
    next_reset_date=date(2024, 1, 1),   # future = loan is mid-cycle
    reset_frequency=12,                  # 0=fixed, 1=monthly, 12=annual
    remaining_term=360,
)  # -> np.ndarray of length remaining_term, rates in %
```

Rate lookup uses binary search (`bisect`). Resets fire on calendar date
rather than modular index count, so seasoned mid-cycle loans get the correct
rate even when the as-of date is between reset dates.

### 5.5 PortfolioCashflow

`PortfolioCashflow` aggregates leaf cashflows lazily. Detailed design in
[`cashflow_aggregation_design.md`](cashflow_aggregation_design.md).

Key semantics:

- **Mode locking**: first constituent determines the mode
  (`SCHEDULED_ONLY` | `ACTUAL_ONLY` | `PAIRED`). Wrong type raises
  `PortfolioModeError`.
- **LCD coercion**: `PAIRED + ACTUAL_ONLY → ACTUAL_ONLY`.
  `ACTUAL_ONLY + SCHEDULED_ONLY → PortfolioModeError`.
- **Operators**: `cf + cf` → new portfolio; `portfolio += cf` → mutates;
  `portfolio + portfolio` → new portfolio without mutating either.
- **Aggregation**: `FLOW` fields summed; `STOCK` fields derived from summed
  flows; `RATIO` fields recomputed from first principles. Driven by
  `FieldKind` metadata, no hardcoded field lists.
- **Flush pattern**: `flush()` forces stack-and-sum reduction and releases
  pending constituent references (GC-friendly for large pools).
- **Cross-collateralization**: `CrossCollateralMode` (`NONE` | `FULL` |
  `GROUP`) with configurable cap. Applied via `apply_waterfall()`.
- **History / rewind**: append-only `PortfolioEvent` log stores loan_id
  references (not object references). `rewind(version, store)` replays.
- **Persistence**: `persistent_history=True` + `history_path` writes
  constituents to Parquet on flush.

### 5.6 TapeSchema and read_loan_tape

```python
schema = TapeSchema(
    loan_id=FieldSpec("LOAN_NUMBER", int),
    original_balance=FieldSpec("ORIG_BALANCE", float),
    ...
)
loans: list[Loan] = read_loan_tape("collateral.csv", schema)
df: pd.DataFrame  = loans_to_dataframe(loans)
```

`TapeSchema` maps arbitrary CSV column names to `Loan` fields. `FieldSpec`
carries the column name, Python type, and optional default. `TapeReadError`
is raised with a descriptive message if required columns are missing or
contain unparseable values.

### 5.7 Cashflow Persistence

```python
# Write
write_cashflow(scheduled_cf, path="output/loan_001_sch.parquet")
write_cashflow(actual_cf,    path="output/loan_001_act.parquet")

# Read
sch: BMAScheduledCashflow = read_scheduled("output/loan_001_sch.parquet")
act: BMAActualCashflow    = read_actual("output/loan_001_act.parquet")

# Read either type; dispatch on Parquet schema metadata
cf = read_cashflows("output/loan_001_sch.parquet")
```

Schema is validated on read via `SCHEDULED_SCHEMA` / `ACTUAL_SCHEMA`
constants. `SchemaValidationError` raised on mismatch.

---

## 6. Typical Usage Patterns

### 6.1 Fixed-Rate Single Loan

```python
from bma_standard_formulas.formulas import (
    generate_smm_curve_from_psa,
    cdr_to_mdr_vector,
    run_bma_scheduled_cashflow,
    run_bma_actual_cashflow,
)
import numpy as np

coupon    = 7.5       # %
term      = 360
remaining = 300

# Scheduled (no prepay, no defaults)
sch = run_bma_scheduled_cashflow(coupon=coupon, original_term=term, remaining_term=remaining)

# Actual (100% PSA, 1% CDR, 35% severity)
smm = generate_smm_curve_from_psa(100, remaining)          # period-indexed
mdr = cdr_to_mdr_vector(np.full(remaining + 1, 1.0))       # % CDR to MDR decimal
sev = np.full(remaining + 1, 0.35)

act = run_bma_actual_cashflow(
    coupon_vector=np.full(remaining + 1, coupon),
    original_term=term,
    remaining_term=remaining,
    smm_curve=smm,
    mdr_curve=mdr,
    severity_curve=sev,
)
```

### 6.2 Loan Tape → Portfolio

```python
from bma_standard_formulas.engine import (
    Loan, TapeSchema, FieldSpec, read_loan_tape, run_actual_portfolio
)
import numpy as np

schema = TapeSchema(
    loan_id=FieldSpec("LOAN_NUM", int),
    original_balance=FieldSpec("ORIG_BAL", float),
    current_balance=FieldSpec("CUR_BAL", float),
    rate_margin=FieldSpec("COUPON", float),
    original_term=FieldSpec("ORIG_TERM", int),
    remaining_term=FieldSpec("REM_TERM", int),
    origination_date=FieldSpec("ORIG_DATE", str),
    asof_date=FieldSpec("ASOF_DATE", str),
)
loans = read_loan_tape("collateral.csv", schema)

max_term = max(l.remaining_term for l in loans)
smm_curve = generate_smm_curve_from_psa(150, max_term)      # age-indexed
mdr_curve = cdr_to_mdr_vector(np.full(max_term + 1, 1.5))
sev_curve = np.full(max_term + 1, 0.40)

portfolio = run_actual_portfolio(loans, smm_curve, mdr_curve, sev_curve)
```

### 6.3 Floating-Rate ARM Loan

```python
from bma_standard_formulas.engine import Loan, RateIndex, build_rate_vector, actual_cashflow_from_loan
import numpy as np
from datetime import date

sofr = RateIndex.from_csv("SOFR_historical.csv", name="SOFR")

loan = Loan(
    loan_id=1,
    origination_date=date(2020, 1, 1),
    asof_date=date(2024, 7, 1),
    original_balance=500_000.0,
    current_balance=460_000.0,
    rate_margin=1.5,              # 150 bp spread over SOFR
    original_term=360,
    remaining_term=300,
    reset_frequency=12,           # annual reset
    index_type="SOFR",
    next_reset_date=date(2025, 1, 1),   # mid-cycle: last reset was Jan 2024
    rate_cap=9.0,
    rate_floor=2.0,
)

rate_vec = build_rate_vector(loan, sofr)   # length = remaining_term

# Age-indexed curves for engine layer
age = loan.age   # 60
n   = age + loan.remaining_term + 1  # 361 elements needed
smm_curve = generate_smm_curve_from_psa(100, loan.original_term)  # length 361
mdr_curve = np.full(n, 0.002)
sev_curve = np.full(n, 0.35)

act = actual_cashflow_from_loan(loan, smm_curve, mdr_curve, sev_curve)
```

---

## 7. Optional Dependencies

| Extra | Package | Enables |
|-------|---------|---------|
| `numba` | `numba>=0.59` | JIT-compiled cashflow loops (significant speedup for large portfolios) |
| `fred`  | `pandas-datareader>=0.10` | `RateIndex.from_fred()` |
| `all`   | both above | all extras |
| `dev`   | `pytest`, `pytest-asyncio` | test suite |

Install: `pip install bma-standard-formulas[numba]`

---

## 8. BMA Section → Code Map

| BMA Section | Content | Python Location |
|-------------|---------|-----------------|
| SF-3 | Computational accuracy | Tolerance convention: `rtol=1e-9`, `atol=1e-10` |
| SF-4 (B.1) | Balance/payment factors | `formulas.scheduled_payments` |
| SF-5–9 (B.2) | SMM/CPR/PSA conversions | `formulas.payment_models` |
| SF-10–14 (B.3) | Historical prepayment speeds | `formulas.payment_models` (historical_*) |
| SF-15 (B.4) | ABS prepayment speeds | `formulas.payment_models` (abs_to_smm, generate_smm_curve_from_abs) |
| SF-16–17 (C.1–C.2) | Default concepts/definitions | Docstrings in `formulas.cashflows` |
| SF-18–19 (C.3) | Cashflow formulas with defaults | `formulas.cashflows.run_bma_actual_cashflow` |
| SF-20–22 (C.4) | SDA standard | `formulas.payment_models.generate_sda_curve` |
| D | Generic pool assumptions | `formulas.examples` (BMAExample dataclass) |
| F | Settlement, FEST | Not yet implemented |
| G | Yield, duration, convexity | Not yet implemented |

---

## 9. Related Documents

- [`cashflow_aggregation_design.md`](cashflow_aggregation_design.md) — detailed
  design for `PortfolioCashflow`: field kinds, lazy evaluation, operator
  semantics, Numba compatibility, version history
- [`../BMA_FORMULAS.md`](../BMA_FORMULAS.md) — full mathematical reference for
  all BMA sections (equations, notation, examples)
- [`../notation_reference.md`](../notation_reference.md) — symbol table and
  indexing conventions
