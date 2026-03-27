#!/usr/bin/env python3
"""Microbenchmarks for daycount/date helper performance.

This script is intentionally lightweight and dependency-tolerant. It compares
the package's daycount/date helpers against common native alternatives
(`datetime.timedelta`, `dateutil.relativedelta`, pandas offsets/ranges).

Usage:
    python scripts/bench_daycount.py
    python scripts/bench_daycount.py --scale 3
"""

from __future__ import annotations

import argparse
import datetime as dt
import platform
import statistics
import time
from dataclasses import dataclass
from typing import Callable, Any

import numpy as np
import pandas as pd

from bma_standard_formulas.formulas.daycount import (
    build_date_range_vector,
    day_count_30_360,
    day_count_30_360_vector,
    increment_date,
    increment_days,
    increment_months,
    increment_weeks,
    increment_years,
    next_business_day,
    year_fraction_actual_360,
    year_fraction_actual_365,
)

try:
    from dateutil.relativedelta import relativedelta
except Exception:  # pragma: no cover - optional fallback path
    relativedelta = None


@dataclass
class BenchResult:
    label: str
    seconds: float
    ops_per_second: float
    sample: Any


def _run_bench(label: str, fn: Callable[[], Any], iterations: int, repeats: int = 3) -> BenchResult:
    durations: list[float] = []
    sample: Any = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        for _ in range(iterations):
            sample = fn()
        durations.append(time.perf_counter() - t0)
    best = min(durations)
    return BenchResult(
        label=label,
        seconds=best,
        ops_per_second=iterations / best if best > 0 else float("inf"),
        sample=sample,
    )


def _print_results(title: str, results: list[BenchResult]) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    for r in results:
        print(f"{r.label:42s} {r.seconds:8.4f}s   {r.ops_per_second:12,.0f} ops/s   sample={r.sample}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark daycount/date helpers versus native alternatives.")
    parser.add_argument("--scale", type=int, default=1, help="Scale factor for iteration counts (default: 1)")
    args = parser.parse_args()
    scale = max(1, args.scale)

    print("Daycount benchmark")
    print(f"Python: {platform.python_version()}  Platform: {platform.platform()}")
    print(f"Scale: x{scale}")

    start = dt.date(2024, 1, 31)

    scalar_iters = 200_000 * scale
    vector_n = 300_000 * scale
    range_iters = 1_000 * scale

    scalar_results: list[BenchResult] = [
        _run_bench("increment_days wrapper", lambda: increment_days(start, 1, False), scalar_iters),
        _run_bench("timedelta(days=1) direct", lambda: start + dt.timedelta(days=1), scalar_iters),
        _run_bench("increment_weeks wrapper", lambda: increment_weeks(start, 1, False), scalar_iters),
        _run_bench("timedelta(weeks=1) direct", lambda: start + dt.timedelta(weeks=1), scalar_iters),
        _run_bench("increment_months wrapper", lambda: increment_months(start, 1, False), scalar_iters),
        _run_bench("increment_years wrapper", lambda: increment_years(start, 1, False), scalar_iters),
        _run_bench("increment_date dispatch monthly", lambda: increment_date(start, 1, "monthly", False), scalar_iters),
    ]
    if relativedelta is not None:
        scalar_results.extend(
            [
                _run_bench("dateutil.relativedelta(months=1)", lambda: start + relativedelta(months=1), scalar_iters),
                _run_bench("dateutil.relativedelta(years=1)", lambda: start + relativedelta(years=1), scalar_iters),
            ]
        )
    _print_results("Scalar increments", scalar_results)

    s_date, e_date = dt.date(2024, 2, 29), dt.date(2024, 3, 31)
    s_np, e_np = np.datetime64("2024-02-29"), np.datetime64("2024-03-31")
    s_str, e_str = "2024-02-29", "2024-03-31"
    daycount_scalar = [
        _run_bench("30/360 scalar python date", lambda: day_count_30_360(s_date, e_date, "NASD"), scalar_iters),
        _run_bench("30/360 scalar np.datetime64", lambda: day_count_30_360(s_np, e_np, "NASD"), scalar_iters),
        _run_bench("30/360 scalar ISO strings", lambda: day_count_30_360(s_str, e_str, "NASD"), max(40_000, scalar_iters // 4)),
    ]
    _print_results("30/360 scalar input types", daycount_scalar)

    actual_results = [
        _run_bench(
            "year_fraction_actual_360",
            lambda: year_fraction_actual_360(dt.date(2024, 1, 1), dt.date(2024, 7, 1)),
            scalar_iters,
        ),
        _run_bench(
            "year_fraction_actual_365",
            lambda: year_fraction_actual_365(dt.date(2024, 1, 1), dt.date(2024, 7, 1)),
            scalar_iters,
        ),
    ]
    _print_results("Actual year fractions (scalar)", actual_results)

    starts = np.array(["2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30"], dtype="datetime64[D]")
    ends = np.array(["2024-02-29", "2024-03-31", "2024-04-30", "2024-05-31"], dtype="datetime64[D]")
    starts = np.resize(starts, vector_n)
    ends = np.resize(ends, vector_n)

    t0 = time.perf_counter()
    out_current = day_count_30_360_vector(starts, ends, "NASD")
    t_current = time.perf_counter() - t0
    print("\n30/360 vector")
    print("-------------")
    print(
        f"{'day_count_30_360_vector(current)':42s} "
        f"{t_current:8.4f}s   {vector_n / t_current:12,.0f} pairs/s   sample={out_current[:4]}"
    )

    arr = np.array(["2024-03-01", "2024-03-02", "2024-03-03", "2024-03-04"], dtype="datetime64[D]")
    arr = np.resize(arr, vector_n)
    t0 = time.perf_counter()
    out_np = next_business_day(arr)
    t_np = time.perf_counter() - t0
    t0 = time.perf_counter()
    out_pd = (pd.DatetimeIndex(arr) + pd.offsets.BDay(0)).values.astype("datetime64[D]")
    t_pd = time.perf_counter() - t0
    print("\nBusiness day vector")
    print("-------------------")
    print(f"{'next_business_day(np array)':42s} {t_np:8.4f}s   {vector_n / t_np:12,.0f} elems/s   sample={out_np[:3]}")
    print(f"{'pandas BDay(0) vector':42s} {t_pd:8.4f}s   {vector_n / t_pd:12,.0f} elems/s   sample={out_pd[:3]}")

    t0 = time.perf_counter()
    out_a = None
    for _ in range(range_iters):
        out_a = build_date_range_vector(start, 360, "monthly", False)
    t_a = time.perf_counter() - t0

    t0 = time.perf_counter()
    out_b = None
    for _ in range(range_iters):
        out_b = (
            pd.date_range(start=start.replace(day=1), periods=360, freq="MS") + pd.Timedelta(days=start.day - 1)
        ).to_numpy(dtype="datetime64[D]")
    t_b = time.perf_counter() - t0

    print("\nDate range monthly")
    print("------------------")
    print(f"{'build_date_range_vector':42s} {t_a:8.4f}s   {range_iters / t_a:12,.0f} calls/s   sample_last={out_a[-1]}")
    print(f"{'pandas date_range + day offset':42s} {t_b:8.4f}s   {range_iters / t_b:12,.0f} calls/s   sample_last={out_b[-1]}")


if __name__ == "__main__":
    main()

