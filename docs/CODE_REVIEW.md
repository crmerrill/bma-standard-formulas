# Code Review: bma-standard-formulas

**Reviewer:** Independent automated review
**Date:** 2026-03-23
**Methodology:** [Google Engineering Practices](https://google.github.io/eng-practices/review/reviewer/)
**Scope:** All source files under `src/`, `tests/`, `scripts/`, `docs/`, and configuration

---

## Overall Grade: B+

The codebase is in genuinely good shape for a quantitative finance library. The two-layer architecture (formulas / engine) is clean and well-reasoned. Immutability discipline is strong — arrays are write-protected after construction. The `FieldKind` metadata pattern for auto-discovered aggregation is elegant. Formula citations (SF-17, SF-18, B.1 eq. 3, etc.) throughout the code are excellent.

The grade stops at B+ because of three meaningful correctness problems: a silently-ignored `servicing_fee` parameter, two public functions missing from `__all__`, and an O(n²) Parquet flush. There is also a systematic violation of Python's `__add__` contract and a Python loop in the waterfall critical path that belongs in numpy. None of these are hard to fix, but they need to be fixed before a 1.0 release.

---

## Scoring Breakdown

| Category | Score (0–10) | Notes |
|---|---|---|
| Correctness | 7/10 | `servicing_fee` silently ignored; `adv_unrecoverable` design ambiguity; `__add__` semantics wrong |
| Test coverage | 8/10 | Strong fixture-based coverage; missing edge cases for `remaining_term=0`, `flush()` after mutation |
| Documentation | 7/10 | Formula citations excellent; stale `servicing_fee` docstring; architecture doc lags implementation |
| Code style / Pythonic | 8/10 | Generally good; `iterrows()` anti-pattern; unnecessary list comprehension in BAL path |
| Architecture / Design | 8/10 | Clean layer separation; `__add__` mutation semantic breaks Python contract |
| Performance | 7/10 | Accum-A aggregation is great; O(n²) flush; Python loop in waterfall; `iterrows()` on tapes |
| Security | 10/10 | No issues found |

---

## Critical Issues

### C-1: `servicing_fee` accepted and documented but never used in `run_bma_scheduled_cashflow`

**File:** `src/bma_standard_formulas/formulas/cashflows.py:874`
**Severity:** Critical — silent wrong answer
**Description:** `run_bma_scheduled_cashflow` accepts `servicing_fee: float = 0.0`, validates it (`< 0` raises), and documents it as "Annual servicing fee as PERCENT (e.g. 0.25 for 25 bps)." However, the parameter is never referenced in the computation — it is never subtracted from the coupon to produce a net rate, never stored on the returned `BMAScheduledCashflow`, and never passed downstream. Any caller passing a non-zero value gets silently wrong output that looks correct.
**Impact:** Every scheduled cashflow generated with a non-zero servicing fee is incorrect. The gross rate equals the net rate, making WAC/WAM calculations wrong for any downstream pricing model.
**Fix:** Either (a) use `servicing_fee` to compute a net coupon vector (`net_rate = coupon - servicing_fee`) and store both on the returned object, matching what `BMAActualCashflow` already does via `net_rate`; or (b) remove the parameter and its validation entirely if scheduled cashflows are intentionally gross-only. Option (a) is strongly preferred for consistency. The docstring must be updated to match whichever choice is made.

---

### C-2: `smm_to_abs` and `generate_smm_curve_from_abs` missing from `formulas/__init__.py __all__`

**File:** `src/bma_standard_formulas/formulas/__init__.py:89`
**Severity:** Critical — public functions inaccessible via package
**Description:** `abs_to_smm` is exported in `__all__`, but its inverse `smm_to_abs` (line 1185 of `payment_models.py`) and the associated curve builder `generate_smm_curve_from_abs` (line 1218) are not. Both functions are fully implemented, tested, and referenced in module docstrings — they are simply not exported. Users doing `from bma_standard_formulas.formulas import smm_to_abs` get `ImportError`.
**Impact:** Public ABS prepayment API is one-directional. Users cannot recover ABS speed from observed SMM without importing from the internal `payment_models` module.
**Fix:** Add both names to `__all__` in `formulas/__init__.py`:
```python
"smm_to_abs",
"generate_smm_curve_from_abs",
```

---

### C-3: `_write_constituents_to_parquet` reads and rewrites the entire file on every flush

**File:** `src/bma_standard_formulas/engine/portfolio.py:841` (also `engine/cashflow_persistence.py`)
**Severity:** Critical — O(n²) in flush count
**Description:** On every call to `flush()` (when `persistent_history=True`), `_write_constituents_to_parquet` reads the entire existing Parquet file into memory, concatenates the new batch, and writes the entire combined dataset back. For a portfolio flushed after every 100-loan batch across 10,000 loans, this means 100 full file reads/writes with a file that grows to 100× the per-batch size. A 10k-loan portfolio flushed in 100-loan batches does ~5,000 total file read+write operations instead of 100.
**Impact:** Persistent-history portfolios become prohibitively slow for anything other than a single flush. The memory footprint also balloons — the full history is materialized in Python memory on every flush.
**Fix:** Use PyArrow's `ParquetWriter` in append mode, or write each batch to a separate Parquet file (shard-per-flush) and merge on `load_constituents`. The simplest correct fix: open a `pyarrow.parquet.ParquetWriter` once and keep it open across flushes, closing it on `__del__` or explicit `close()`. Alternatively, write each flush as an independent file and aggregate on read.

---

## Major Issues

### ~~M-4~~: `PortfolioCashflow.__add__` mutation — RESOLVED: intentional, documented

**File:** `src/bma_standard_formulas/engine/portfolio.py:1029`
**Severity:** Major
**Description:** Python's data model specifies that `__add__` must return a new object without mutating either operand. `__iadd__` (in-place) is where mutation is allowed. `PortfolioCashflow.__add__` currently mutates `self` when the right operand is a leaf cashflow (`portfolio + cf`), and the docstring explicitly says "mutates self, returns self." This means `b = a + cf` silently modifies `a`. Only the `portfolio + portfolio` branch correctly returns a new object.
**Impact:** Any code that does `result = portfolio + new_cf` expecting a new portfolio gets a mutated original. This is a silent correctness bug for callers following normal Python idioms.
**Fix:** `__add__` should always return a new `PortfolioCashflow`. Move mutation to `__iadd__` only. The current `__iadd__` already calls `__add__`, so the fix is to make `__add__` copy-on-write:
```python
def __add__(self, other):
    if isinstance(other, PortfolioCashflow):
        # existing merge logic — already returns new
        ...
    # portfolio + cf: return NEW portfolio
    new = PortfolioCashflow([], mode=self._mode, ...)
    new._pending = list(self._pending)
    new._n_constituents = self._n_constituents
    # then add other to new
    ...
    return new

def __iadd__(self, other):
    # mutate self directly (existing logic)
    ...
    return self
```

---

### M-5: `_compute_waterfall` advance rollforward uses a Python loop

**File:** `src/bma_standard_formulas/engine/portfolio.py:635`
**Severity:** Major
**Description:** The trust advance rollforward loop (lines 635–675) iterates over all `n` periods in Python to track `trust_adv_prin_out[i]` and `trust_adv_int_out[i]`, checking for reimbursements period by period. For a 361-period pool this is a tight Python loop of 361 iterations. The loop is called every time `.pool` is first accessed.
**Impact:** For large portfolios with many periods, this is a measurable bottleneck. More importantly, the pattern is inconsistent — all other stock reconstruction in `_reconstruct_stocks_and_ratios` uses `np.cumsum` for exactly this kind of rollforward.
**Fix:** The cumulative advance outstanding is just `np.cumsum(adv_prin)` and `np.cumsum(adv_int)`. Reimbursements depend on `prin_recov` (which is not conditioned on prior state), so the loop can be vectorized with careful use of `np.cumsum` and `np.minimum`. The cross-collateralization loop in `CrossCollateralMode.FULL` is harder to vectorize and can remain as-is for now with a comment.

---

### M-6: `TapeSchema.read()` uses `df.iterrows()`

**File:** `src/bma_standard_formulas/engine/tape.py:431`
**Severity:** Major
**Description:** `TapeSchema.read()` iterates over all rows of the input DataFrame using `df.iterrows()` to build `Loan` objects one at a time. `iterrows()` is the slowest pandas iteration method — 10–100× slower than vectorized alternatives — because it boxes each row into a `pd.Series`, performing dtype inference on every column on every row.
**Impact:** Loading a 10,000-loan tape takes substantially longer than necessary. For 100k-loan tapes (common in agency RMBS), the difference is multiple seconds vs milliseconds.
**Fix:** Replace with `df.itertuples(index=False, name=None)` for a 3–5× speedup with minimal code change. For maximum performance, build `Loan` objects via vectorized column extraction: `[Loan(loan_id=row[0], ...) for row in zip(df['loan_id'], df['original_balance'], ...)]`. This avoids per-row Series construction entirely.

---

### M-7: `BMAActualCashflow` missing `accrued_interest` META field

**File:** `src/bma_standard_formulas/formulas/cashflows.py:1095`
**Severity:** Major
**Description:** `BMAScheduledCashflow` has `accrued_interest: float` as a META field (line 480) and `_aggregate_scheduled` correctly sums it across constituents (`accrued_interest=sum(cf.accrued_interest for cf in cfs)`). `BMAActualCashflow` has no such field. Since actual cashflows are derived from scheduled cashflows (same loan, different scenario), the asymmetry means accrued interest cannot be tracked through the actual-cashflow pipeline. The `run_bma_actual_cashflow` function accepts `accrued_interest` as a parameter but stores it nowhere on the output.
**Impact:** Accrued interest is silently discarded in the actual cashflow path. Any downstream settlement calculation (dirty price, accrued stub) is missing this value.
**Fix:** Add `accrued_interest: float = field(default=0.0, metadata={"kind": FieldKind.META})` to `BMAActualCashflow`. Store the value in `run_bma_actual_cashflow`. Add it to `_aggregate_actual` via `accrued_interest=sum(cf.accrued_interest for cf in cfs)` in `_reconstruct_stocks_and_ratios`.

---

### M-8: `adv_unrecoverable` FLOW field vs waterfall output creates design ambiguity

**File:** `src/bma_standard_formulas/engine/portfolio.py:677–716`
**Severity:** Major
**Description:** `BMAActualCashflow` has `adv_unrecoverable` as a FLOW field — the loan-level estimate of advance write-offs, summed across constituents by `_aggregate_actual`. However, `_compute_waterfall` re-derives `adv_unrecoverable` from scratch at the pool level (`pool.adv_prin + pool.adv_int - adv_reimbursed_prin - adv_reimbursed_int`). The `PortfolioCashflow.adv_unrecoverable` property returns the waterfall-derived value. The pool-level FLOW field `pool.adv_unrecoverable` (sum of constituent estimates) is never exposed to the caller and never used downstream — it exists as dead data in `flow_sums`.
**Impact:** Two different values exist for "advance write-offs" — the constituent-summed FLOW field (accessible via `portfolio.pool.adv_unrecoverable`) and the waterfall-derived estimate (accessible via `portfolio.adv_unrecoverable`). They can diverge under cross-collateralization and are never reconciled. This is confusing and can lead to incorrect analysis.
**Fix:** Either (a) remove `adv_unrecoverable` from `BMAActualCashflow`'s FLOW fields and only compute it in the waterfall (preferred — it is a trust-level concept, not a loan-level one); or (b) add a note to the docstring explaining the divergence. If (a), update `_reconstruct_stocks_and_ratios` and `fields_by_kind` accordingly.

---

### M-9: `amortized_balance_fraction` computation for fixed-rate loans uses per-element function calls

**File:** `src/bma_standard_formulas/formulas/cashflows.py:977`
**Severity:** Major
**Description:** For fixed-rate loans, `amortized_balance_fraction` is computed via a list comprehension that calls `sch_balance_factor_fixed_rate(coupon_pct, original_term, int(m))` once per period (lines 978–983). This is `remaining_term` individual Python function calls, each computing `(1 - (1+r)^(-m)) / (1 - (1+r)^(-M₀))`. For a 30-year loan this is 361 calls. The formula is fully vectorizable: the denominator is a scalar, and `(1 - (1+r)^(-m))` is a vector operation.
**Impact:** Construction of `BMAScheduledCashflow` is slower than necessary. For a 10k-loan portfolio this is 3.6M Python function calls that should be one numpy expression.
**Fix:**
```python
remaining_at_period = remaining_term - np.arange(periods)
r = coupon_pct / 1200.0
denom = 1.0 - (1 + r) ** (-original_term) if r > 0 else original_term
numer = np.where(remaining_at_period > 0,
    1.0 - (1 + r) ** (-remaining_at_period) if r > 0 else remaining_at_period / original_term,
    0.0)
amortized_balance_fraction = numer / denom if r > 0 else numer
```

---

### M-10: `cashflows.py` is 1,797 lines — should be split

**File:** `src/bma_standard_formulas/formulas/cashflows.py`
**Severity:** Major
**Description:** The file contains: the `FieldKind` enum and registry (~80 lines), two dataclasses with `__post_init__` and `scale_by`/`to_dataframe` methods (~600 lines), numba loop implementations (~200 lines), `run_bma_scheduled_cashflow` (~200 lines), `run_bma_actual_cashflow` (~300 lines), and `compare_arrays`. This is too many responsibilities in one file.
**Impact:** Navigation is difficult. The numba compilation section is easy to miss. Adding new cashflow types (e.g. commercial MBS) would make the file 2,500+ lines.
**Fix:** Split into:
- `formulas/_fields.py` — `FieldKind`, `fields_by_kind`, `PortfolioModeError`
- `formulas/_dataclasses.py` — `BMAScheduledCashflow`, `BMAActualCashflow`, `CashFlowPair`
- `formulas/_loops.py` — numba-compiled inner loops
- `formulas/cashflows.py` — `run_bma_scheduled_cashflow`, `run_bma_actual_cashflow`, `compare_arrays`

Keep `formulas/__init__.py` exporting everything via the same names — no public API change.

---

## Minor Issues

### mn-1: `engine/__init__.py` missing `__all__`

**File:** `src/bma_standard_formulas/engine/__init__.py`
**Description:** The engine package has no `__all__` definition. Every name imported in `__init__.py` is publicly accessible, including internal implementation details. Compare: `formulas/__init__.py` has an explicit `__all__`.
**Fix:** Add `__all__ = ["Loan", "RateIndex", "TapeSchema", "PortfolioCashflow", ...]` listing only the intended public API.

---

### mn-2: `RateIndex._add_months` clamps day to 28 unconditionally

**File:** `src/bma_standard_formulas/engine/rate_index.py`
**Description:** Month advancement clamps the day to 28 to avoid end-of-month errors. This is unnecessary — use `calendar.monthrange(y, m)[1]` for the actual last day, or simply set the day to 1 since rate index dates are always month-start by convention.
**Fix:** If dates are always the first of the month (as the SOFR forward fixture uses), replace the helper with `d.replace(year=y, month=mo, day=1)`. If variable day is needed, use `min(d.day, calendar.monthrange(y, mo)[1])`.

---

### mn-3: Bare `except Exception` in `tape.py`

**File:** `src/bma_standard_formulas/engine/tape.py`
**Description:** At least one `except Exception` block swallows the exception type and re-raises or logs without the original cause. This makes debugging tape-loading errors unnecessarily hard.
**Fix:** Either catch specific exceptions (`ValueError`, `KeyError`, `pd.errors.ParserError`) or use `except Exception as e: raise TapeReadError(...) from e` to preserve the cause chain.

---

### mn-4: LLM review instructions block in production test docstring

**File:** `tests/test_b1_payments.py`
**Description:** The module docstring contains a multi-paragraph block titled "LLM REVIEW INSTRUCTIONS" directing AI assistants how to interpret the tests. This is development scaffolding that has leaked into committed test code. It does not affect test execution but adds noise and confusion for human reviewers.
**Fix:** Move this block to `tests/README_TEST_ORGANIZATION.md` (which already exists) and remove it from the test module docstring. Keep test docstrings to describe what the tests verify, not how AI tools should read them.

---

### mn-5: `load_constituents` duplicates `from_dataframe` logic

**File:** `src/bma_standard_formulas/engine/portfolio.py:870`
**Description:** `PortfolioCashflow.load_constituents` manually reconstructs `BMAActualCashflow` and `BMAScheduledCashflow` from a DataFrame by introspecting column names. `BMAActualCashflow.from_dataframe` and `BMAScheduledCashflow.from_dataframe` already exist for this purpose. The duplication means if a new field is added to either dataclass, `load_constituents` silently drops it.
**Fix:** Replace the manual reconstruction in `load_constituents` with:
```python
for cf_id, group in df.groupby("cf_id"):
    group = group.sort_values("period").reset_index(drop=True)
    cf = (BMAActualCashflow if "perf_bal" in group.columns else BMAScheduledCashflow).from_dataframe(group)
    result[str(cf_id)] = cf
```

---

### mn-6: `OriginationParams.original_term` typed `float` instead of `int`

**File:** `src/bma_standard_formulas/formulas/examples.py`
**Description:** `OriginationParams.original_term` is annotated as `float` but the BMA formula spec requires it to be an integer (number of monthly periods). All downstream functions that accept `original_term` type-hint it as `int`. The mismatch causes silent `float`→`int` coercions.
**Fix:** Change the annotation to `int`.

---

### mn-7: `build_coupon_vector`'s sequential reset logic is undocumented

**File:** `src/bma_standard_formulas/engine/loan.py`
**Description:** `build_coupon_vector` implements an annual reset schedule by iterating through reset dates and applying the current SOFR rate. The logic for handling partially-elapsed reset periods and the splice between historical and forward SOFR is non-trivial but has no inline explanation of the algorithm or the edge cases it handles.
**Fix:** Add a block comment above the reset loop explaining: (a) how historical vs. forward rates are resolved, (b) what happens when `asof_date` falls mid-reset-period, and (c) the fallback behavior when a reset date has no matching rate.

---

### mn-8: `sch_balance_factor_fixed_rate` does not guard against `original_term=0`

**File:** `src/bma_standard_formulas/formulas/scheduled_payments.py`
**Description:** When `remaining_term=0`, the function warns and returns `0.0` correctly. But if `original_term=0` is passed (and `remaining_term=0` too), the expression `1 - (1+r)^(-original_term)` is `0`, producing `ZeroDivisionError` before the warning fires.
**Fix:** Add `if original_term <= 0: raise ValueError(...)` before the coupon calculation.

---

### mn-9: `PortfolioCashflow` module docstring operator semantics contradict Python contract

**File:** `src/bma_standard_formulas/engine/portfolio.py:14–17`
**Description:** The module docstring states `portfolio + cf -> mutates portfolio`. This is documented wrong behavior (see M-4). If M-4 is fixed, update the docstring to `portfolio + cf -> new PortfolioCashflow`.

---

### mn-10: `compare_arrays` tolerance documentation is misleading

**File:** `src/bma_standard_formulas/formulas/cashflows.py`
**Description:** `compare_arrays` uses `rtol=0, atol=0.005` (half a basis point on dollar amounts) but the docstring says "within BMA rounding tolerances." BMA uses different tolerances for different field types — 0.005 is appropriate for dollar flows but not for rate ratios like `smm` (where 0.005 would be 50bps). The function applies the same tolerance to all field types.
**Fix:** Either (a) document the specific tolerance and why it is appropriate, or (b) add a `tolerance` parameter with a sensible default so callers can specify per-field tolerances.

---

## Documentation Gaps

### Doc-1: Architecture overview does not reflect current `_aggregate_actual` implementation

**Location:** `docs/architecture/cashflow_aggregation_design.md`
**Current state:** Describes the original per-field `_pad_sum_field` loop approach
**Gap:** The current implementation uses the accum-A single-pass accumulator pattern (13× faster). The document's "performance considerations" section describes behavior that no longer matches the code.
**Proposed addition:** Update Section 4 to describe the accumulator pattern with a note explaining the cache-efficiency rationale. Add a pointer to `profile_aggregation_strategies.py` for the benchmarks.

---

### Doc-2: `run_bma_actual_cashflow` rate-convention for `servicing_fee` undocumented

**Location:** `src/bma_standard_formulas/formulas/cashflows.py` — `run_bma_actual_cashflow` docstring
**Current state:** Parameter list mentions `servicing_fee` briefly
**Gap:** The docstring does not state whether `servicing_fee` is in percent (0.25 for 25 bps) or decimal (0.0025). `run_bma_scheduled_cashflow` explicitly says "percent (e.g. 0.25 for 25 bps)"; the actual cashflow function is silent.
**Proposed addition:** Align documentation to explicitly state `servicing_fee: Annual servicing fee in PERCENT (e.g. 0.25 for 25 bps). Subtracted from gross coupon to produce net_rate.`

---

### Doc-3: `fields_by_kind` aggregation semantics not described at package level

**Location:** `docs/architecture/overview.md` and `docs/architecture/cashflow_aggregation_design.md`
**Current state:** `FieldKind` enum is mentioned in passing
**Gap:** Neither doc explains the aggregation rule each `FieldKind` implies: FLOW = sum, STOCK = reconstruct via cumsum from summed flows, RATIO = recompute from first principles on aggregate, META = carry from constituent or sum (depends on field). This is the central invariant that makes the aggregation correct, and it exists only as inline comments.
**Proposed addition:** Add a table to the aggregation design doc:

| FieldKind | Pooling Rule | Rationale |
|---|---|---|
| FLOW | Sum across constituents | Dollar flows are additive |
| STOCK | Reconstruct via cumsum from summed FLOWs | Stocks follow from flows; direct sum can violate balance identity |
| RATIO | Recompute from defining formula on aggregate | Weighted average is systematically biased |
| META | Field-dependent (see notes) | Identifiers copied; scalars summed or taken from pool |

---

### Doc-4: `CrossCollateralMode.GROUP` raises `NotImplementedError` but docstring says it is supported

**Location:** `src/bma_standard_formulas/engine/portfolio.py:107`
**Current state:** `CrossCollateralMode` docstring describes GROUP mode as "Within-group reallocation only (partitioned by loan group_id). Used for multi-group/multi-collateral deals."
**Gap:** The implementation immediately raises `NotImplementedError` when GROUP is used. A user reading the enum docstring would reasonably expect it to work.
**Proposed addition:** Add `# NOT YET IMPLEMENTED` to the GROUP enum member docstring, or change the description to `GROUP: Reserved for future multi-group implementation. Raises NotImplementedError.`

---

### Doc-5: README rate convention examples are inconsistent with implementation

**Location:** `README.md`
**Current state:** Some examples show `coupon=8.0` (percent) without clarifying convention; `servicing_fee` examples show values that would be wrong if the function were ever fixed to use the parameter
**Gap:** The README should have a single "Rate conventions" callout box that states clearly: coupons in %, SMM/MDR as decimal, CPR/PSA/CDR in %, SDA in %. This is in the architecture overview but not the README.
**Proposed addition:** Add a "Numeric Conventions" table to the README introduction matching the table in `docs/architecture/overview.md`.

---

## Proposed Fixes (for agent review)

Ordered by priority. Each item is specific enough for a separate implementation pass.

1. **Fix servicing_fee silently ignored** — `formulas/cashflows.py:874` — Compute net coupon vector (`coupon - servicing_fee`) inside `run_bma_scheduled_cashflow`; store `net_rate` on `BMAScheduledCashflow`; update docstring. Alternatively, document explicitly that scheduled cashflows are gross-only and remove the parameter.

2. **Export smm_to_abs and generate_smm_curve_from_abs** — `formulas/__init__.py:89` — Add both names to `__all__`. Two-line fix.

3. **Fix O(n²) Parquet flush** — `engine/portfolio.py:841` — Replace read-rewrite pattern with `pyarrow.parquet.ParquetWriter` held open across flushes, or shard-per-flush + merge on `load_constituents`.

4. **Fix `__add__` mutation semantics** — `engine/portfolio.py:1029` — `__add__` must return a new object. Move mutation to `__iadd__` only. Update module docstring operator table.

5. **Vectorize waterfall advance rollforward** — `engine/portfolio.py:635` — Replace per-period Python loop with `np.cumsum(adv_prin)` / `np.cumsum(adv_int)` for the running totals; keep `FULL` cross-collat loop as Python with a comment.

6. **Replace `iterrows()` with `itertuples()`** — `engine/tape.py:431` — One-line change; 3–5× speedup for tape loading.

7. **Add `accrued_interest` to `BMAActualCashflow`** — `formulas/cashflows.py:1095` — Add META field, store in `run_bma_actual_cashflow`, sum in `_aggregate_actual`.

8. **Resolve `adv_unrecoverable` dual-source ambiguity** — `engine/portfolio.py` — Either remove it from FLOW fields (preferred) and compute only in waterfall, or add explicit documentation reconciling the two values.

9. **Vectorize `amortized_balance_fraction` for fixed-rate loans** — `formulas/cashflows.py:977` — Replace per-period `sch_balance_factor_fixed_rate` loop with numpy vector expression.

10. **Add `__all__` to `engine/__init__.py`** — `engine/__init__.py` — Enumerate the public API explicitly.

11. **Split `cashflows.py`** — `formulas/cashflows.py` — Extract `FieldKind`/`fields_by_kind` to `_fields.py`, dataclasses to `_dataclasses.py`, numba loops to `_loops.py`. No public API change.

12. **Replace `load_constituents` reconstruction with `from_dataframe`** — `engine/portfolio.py:870` — 10-line fix; eliminates maintenance drift.

13. **Fix `OriginationParams.original_term` type** — `formulas/examples.py` — Change annotation from `float` to `int`.

14. **Add `CrossCollateralMode.GROUP` not-implemented notice to docstring** — `engine/portfolio.py:107` — One-line docstring update.

15. **Document `build_coupon_vector` reset logic** — `engine/loan.py` — Add block comment above reset loop explaining historical/forward splice and partial-period behavior.

16. **Move LLM review instructions out of test docstring** — `tests/test_b1_payments.py` — Move to `tests/README_TEST_ORGANIZATION.md`.

17. **Update `compare_arrays` tolerance documentation** — `formulas/cashflows.py` — State tolerance explicitly; optionally add `atol` parameter.

18. **Fix `sch_balance_factor_fixed_rate` for `original_term=0`** — `formulas/scheduled_payments.py` — Add guard against `original_term <= 0` before division.

19. **Update aggregation design doc to reflect accum-A** — `docs/architecture/cashflow_aggregation_design.md` — Replace the performance section; add pointer to benchmark script.

20. **Add FieldKind aggregation semantics table to architecture docs** — `docs/architecture/cashflow_aggregation_design.md` — Add FLOW/STOCK/RATIO/META pooling rules table.

21. **Add Numeric Conventions table to README** — `README.md` — Mirror the table from `docs/architecture/overview.md`.

22. **Align `run_bma_actual_cashflow` servicing_fee convention docs** — `formulas/cashflows.py` — State explicitly that servicing_fee is in percent.

23. **Fix `RateIndex._add_months` day clamping** — `engine/rate_index.py` — Use `day=1` (if dates are always month-start) or `calendar.monthrange` for correct last-day clamping.

24. **Add `except ... from e` in `tape.py`** — `engine/tape.py` — Replace bare `except Exception` with typed catches or `raise X from e` to preserve cause chain.

---

## Positive Observations

These should be preserved and extended:

- **Immutability discipline**: `flags.writeable = False` on all output arrays after construction. This prevents a whole class of mutation bugs that plague numpy-heavy libraries.
- **FieldKind metadata pattern**: Using dataclass `field(metadata={"kind": FieldKind.FLOW})` for auto-discovered aggregation is elegant and forward-compatible. Adding a new cashflow field automatically participates in aggregation without changing any aggregation function.
- **Formula citations throughout**: References like "SF-18 identity", "BMA B.1 eq. 3", "FNMA F-1-20" in inline comments are excellent. They make auditing correctness against the specification straightforward.
- **Numba fallback decorator**: The `_njit` no-op fallback means the library works without numba installed, with a clean performance upgrade path. The fallback is correct and handles both calling conventions.
- **`RateIndex.merge` splice semantics**: Later argument wins on duplicate dates, with the rule documented inline. Merging historical + forward SOFR is a clean one-liner.
- **Fixture-based test coverage**: Tests validate against known-correct example outputs from the BMA specification itself, not against the implementation's own output. This is the right approach for a reference implementation.
- **Clean two-layer architecture**: The formulas / engine separation is meaningful — formulas are stateless pure functions; engine manages state, I/O, and orchestration. This makes the formulas layer independently testable and portable.
- **PyArrow-direct persistence**: Using `pyarrow` instead of `pandas.to_parquet` for storage gives correct type preservation and better performance. The schema metadata approach is the right way to store typed array data.
- **`_reconstruct_stocks_and_ratios`**: Fully vectorized stock rollforward with `np.cumsum` and ratio recomputation from first principles on the aggregate. This is the correct approach — never weighted-averaging ratios across constituents.
