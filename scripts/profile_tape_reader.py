#!/usr/bin/env python
"""
Profile three tape-parsing strategies against the current iterrows() implementation.

Strategies:
  current     iterrows() — one pd.Series per row (current implementation)
  to_dict     df.to_dict('records') — plain Python dicts, no Series overhead
  vectorized  Column-by-column conversion then zip into Loan objects —
              no per-row Python loop over FIELD_SPECS; error handling is
              column-level rather than row-level

All three produce identical Loan lists.  The benchmark measures only Step 6
(the parse loop) on a pre-built DataFrame with canonical column names, isolating
the iteration strategy from CSV loading and alias resolution.

Tape sizes: 100, 1k, 10k, 100k loans.
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from bma_standard_formulas.engine.tape import TapeSchema, FieldSpec
from bma_standard_formulas.engine.loan import Loan

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SIZES   = [100, 1_000, 10_000, 100_000]
N_RUNS  = 7

RNG_SEED    = 42
ASOF_DATE   = date(2026, 3, 1)

# ---------------------------------------------------------------------------
# Synthetic tape builder
# ---------------------------------------------------------------------------

def _make_tape(n: int, rng: np.random.Generator) -> pd.DataFrame:
    """Build a DataFrame with canonical Loan field names, no alias resolution needed."""
    ages         = rng.integers(0, 121, size=n)
    orig_terms   = rng.choice([180, 240, 360], size=n)
    orig_balance = rng.uniform(100_000, 750_000, size=n)
    rate_margin  = rng.uniform(5.0, 9.0, size=n)

    origination_dates = [
        (ASOF_DATE - timedelta(days=int(a * 30.44))).isoformat()
        for a in ages
    ]
    remaining_terms = (orig_terms - ages).clip(min=1)

    # Compute approx current balance
    def approx_bal(ob, r, ot, age):
        if age == 0:
            return ob
        r_mo = r / 1200.0
        rem = ot - age
        if r_mo == 0 or rem <= 0:
            return ob * max(0, 1 - age / ot)
        return ob * (1 - (1 + r_mo) ** (-rem)) / (1 - (1 + r_mo) ** (-ot))

    curr_balance = [
        approx_bal(float(orig_balance[i]), float(rate_margin[i]),
                   int(orig_terms[i]), int(ages[i]))
        for i in range(n)
    ]

    return pd.DataFrame({
        "loan_id":          np.arange(1, n + 1, dtype=int),
        "origination_date": origination_dates,
        "asof_date":        ASOF_DATE.isoformat(),
        "original_balance": orig_balance,
        "current_balance":  curr_balance,
        "rate_margin":      rate_margin,
        "original_term":    orig_terms,
        "remaining_term":   remaining_terms,
        "servicing_fee":    rng.uniform(0.1, 0.5, size=n),
        "pi_advanced":      rng.choice([True, False], size=n),
        "reset_frequency":  rng.choice([0, 12], size=n),
        "index_type":       rng.choice(["SOFR", None, None, None], size=n),
        "first_payment_date": [
            (ASOF_DATE - timedelta(days=int(a * 30.44) - 30)).replace(day=1).isoformat()
            for a in ages
        ],
    })


# ---------------------------------------------------------------------------
# Strategy A: current (iterrows)
# ---------------------------------------------------------------------------

def _parse_iterrows(schema: TapeSchema, df: pd.DataFrame) -> list[Loan]:
    loans: list[Loan] = []
    errors: list[str] = []
    for idx, row in df.iterrows():
        try:
            loans.append(schema._parse_row(row))
        except Exception as exc:
            errors.append(f"  Row {idx}: {exc}")
    if errors:
        raise ValueError("\n".join(errors))
    return loans


# ---------------------------------------------------------------------------
# Strategy B: to_dict('records')
# ---------------------------------------------------------------------------

def _parse_row_dict(schema: TapeSchema, row: dict) -> Loan:
    """_parse_row equivalent for plain dict rows."""
    kwargs: dict[str, Any] = {}
    for spec in schema.FIELD_SPECS:
        if spec.name not in row:
            if spec.required:
                raise ValueError(f"required field '{spec.name}' is missing")
            if spec.default is not None:
                kwargs[spec.name] = spec.default
            continue

        raw = row[spec.name]
        null = False
        try:
            null = bool(pd.isna(raw))
        except (TypeError, ValueError):
            pass

        if null:
            if spec.required:
                raise ValueError(f"required field '{spec.name}' is null")
            if spec.default is not None:
                kwargs[spec.name] = spec.default
            continue

        try:
            if spec.kind == "date":
                kwargs[spec.name] = schema._parse_date(raw)
            elif spec.kind == "bool":
                kwargs[spec.name] = schema._parse_bool(raw)
            elif spec.kind == "int":
                kwargs[spec.name] = int(float(raw))
            elif spec.kind == "float":
                kwargs[spec.name] = float(raw)
            else:
                kwargs[spec.name] = str(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"field '{spec.name}': {exc}") from exc

    return Loan(**kwargs)


def _parse_to_dict(schema: TapeSchema, df: pd.DataFrame) -> list[Loan]:
    loans: list[Loan] = []
    errors: list[str] = []
    for idx, row in enumerate(df.to_dict("records")):
        try:
            loans.append(_parse_row_dict(schema, row))
        except Exception as exc:
            errors.append(f"  Row {idx}: {exc}")
    if errors:
        raise ValueError("\n".join(errors))
    return loans


# ---------------------------------------------------------------------------
# Strategy C: vectorized column conversion
# ---------------------------------------------------------------------------

def _vec_dates(series: pd.Series) -> list:
    """Vectorized date conversion: entire column at once."""
    ts = pd.to_datetime(series, errors="coerce")
    return [
        None if pd.isna(t) else np.datetime64(t.date(), "D")
        for t in ts
    ]


def _parse_vectorized(schema: TapeSchema, df: pd.DataFrame) -> list[Loan]:
    """
    Convert each column in one vectorized pass, then zip into Loan objects.

    Trade-off vs current/to_dict:
      + No per-row FIELD_SPECS loop — all type conversion is column-at-a-time
      + Date columns parsed with pd.to_datetime (vectorized) rather than
        per-cell pd.Timestamp() calls
      - Error reporting is column-level, not row-level
      - Slightly more code to maintain if Loan fields change
    """
    cols = set(df.columns)

    # Required scalar columns — vectorized cast
    loan_ids        = df["loan_id"].astype(int).tolist()
    orig_balances   = df["original_balance"].astype(float).tolist()
    curr_balances   = df["current_balance"].astype(float).tolist()
    rate_margins    = df["rate_margin"].astype(float).tolist()
    orig_terms      = df["original_term"].astype(int).tolist()
    rem_terms       = df["remaining_term"].astype(int).tolist()

    # Required date columns — vectorized
    orig_dates  = _vec_dates(df["origination_date"])
    asof_dates  = _vec_dates(df["asof_date"])

    # Optional columns with defaults
    svc_fees    = df["servicing_fee"].astype(float).tolist() if "servicing_fee" in cols \
                  else [0.0] * len(df)
    pi_advanced = df["pi_advanced"].astype(bool).tolist() if "pi_advanced" in cols \
                  else [True] * len(df)
    reset_freq  = df["reset_frequency"].astype(int).tolist() if "reset_frequency" in cols \
                  else [0] * len(df)

    # Optional nullable columns
    index_types = df["index_type"].where(df["index_type"].notna(), None).tolist() \
                  if "index_type" in cols else [None] * len(df)
    first_pmts  = _vec_dates(df["first_payment_date"]) if "first_payment_date" in cols \
                  else [None] * len(df)

    loans = []
    for i in range(len(df)):
        kwargs: dict[str, Any] = {
            "loan_id":            loan_ids[i],
            "origination_date":   orig_dates[i],
            "asof_date":          asof_dates[i],
            "original_balance":   orig_balances[i],
            "current_balance":    curr_balances[i],
            "rate_margin":        rate_margins[i],
            "original_term":      orig_terms[i],
            "remaining_term":     rem_terms[i],
            "servicing_fee":      svc_fees[i],
            "pi_advanced":        pi_advanced[i],
            "reset_frequency":    reset_freq[i],
        }
        if index_types[i] is not None:
            kwargs["index_type"] = index_types[i]
        if first_pmts[i] is not None:
            kwargs["first_payment_date"] = first_pmts[i]
        loans.append(Loan(**kwargs))
    return loans


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

def _time(fn, n_runs: int) -> np.ndarray:
    times = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return np.array(times)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    rng    = np.random.default_rng(RNG_SEED)
    schema = TapeSchema()

    print("=" * 72)
    print("TAPE READER PARSE STRATEGY BENCHMARK")
    print(f"  {N_RUNS} runs each, reporting median  |  Step 6 only (no CSV load / alias resolution)")
    print("=" * 72)

    # Header
    print()
    print(f"  {'Loans':>8}  {'strategy':>12}  {'median (ms)':>12}  {'min (ms)':>10}  {'vs current':>12}")
    print(f"  {'--------':>8}  {'------------':>12}  {'------------':>12}  {'----------':>10}  {'------------':>12}")

    for n in SIZES:
        df = _make_tape(n, rng)

        strategies = [
            ("current",    lambda: _parse_iterrows(schema, df)),
            ("to_dict",    lambda: _parse_to_dict(schema, df)),
            ("vectorized", lambda: _parse_vectorized(schema, df)),
        ]

        # Warm up
        for _, fn in strategies:
            fn()

        # Correctness check
        ref = _parse_iterrows(schema, df)
        for label, fn in strategies[1:]:
            result = fn()
            assert len(result) == len(ref), f"{label}: length mismatch at n={n}"
            for j, (a, b) in enumerate(zip(ref, result)):
                assert a.loan_id == b.loan_id, f"{label}: loan_id mismatch at row {j}"
                assert abs(a.current_balance - b.current_balance) < 1e-6, \
                    f"{label}: current_balance mismatch at row {j}"

        times: dict[str, np.ndarray] = {}
        for label, fn in strategies:
            times[label] = _time(fn, N_RUNS)

        baseline_ms = float(np.median(times["current"])) * 1e3
        for label, t in times.items():
            med_ms  = float(np.median(t)) * 1e3
            min_ms  = float(t.min()) * 1e3
            ratio   = baseline_ms / med_ms
            marker  = " ← baseline" if label == "current" else f"  {ratio:.2f}x faster"
            print(f"  {n:>8,}  {label:>12}  {med_ms:>11.2f}ms  {min_ms:>9.2f}ms  {marker}")
        print()


if __name__ == "__main__":
    main()