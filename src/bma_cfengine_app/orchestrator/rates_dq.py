"""Rates-file data quality: diagnose, propose repairs, preview, apply.

The same four verbs as tape_repair.py — ``diagnose_rates`` → ``available_repairs``
→ ``preview_repair`` → ``apply_repair`` — so rate files reach the Problems Panel
through the pipeline tapes already use.  Nothing here fixes anything silently:
every finding is reported, every repair is previewed, and the user approves.

Division of labour with the engine
----------------------------------
This module parses *leniently* so it can report what is wrong.
``RateIndex.from_frame`` parses *strictly* and refuses to guess.  A file passes
through DQ first; once its problems are resolved or accepted, the cleaned frame
satisfies the engine's strict reader.

Detection, and why it is shaped this way
----------------------------------------
Calibrated against tests/fixtures/SOFR_historical.csv — real SOFR, 2018-2026,
spanning the March-2020 collapse (1.10% → 0.01% in weeks), the 2021 ZIRP trough,
and the 2022 hiking cycle.

*Blank vs corrupt.*  90 of that fixture's rate cells are NaN.  They are US market
holidays — no SOFR is published, so there is no observation.  A blank is a gap in
the calendar, not an error.  Non-blank junk ("5.2x", "5,33") is corruption.  The
two are reported as different things.

*Outliers are found against a LOCAL window, excluding the cell under test.*  A
global mean is useless: rates moved 500x across this fixture, so measuring 2021
against the 8-year average flags the entire ZIRP era — 323 false positives on
clean data.  A 5-day window gives 0.

*The window must be short.*  Genuine rate history contains 28x moves inside 21
days (March 2020).  A fat-finger is a single-point *spike* — it disagrees with
both neighbours, who agree with each other.  A crash is a *step* — it agrees with
its successor.  A 5-day window separates them; a 21-day one does not.

*Fixes are applied as we go.*  One bad cell contaminates the window of every
neighbour, so a single pass flags the culprit plus innocents around it.  Fixing
the most extreme cell and re-measuring converges on the true error alone.

*Scale cannot always be inferred, and we do not pretend otherwise.*  2021 SOFR in
percent reads 0.05.  5% SOFR in decimal also reads 0.05.  Identical data, opposite
correct actions, and no in-file statistic separates them.  When a column's maximum
sits below 1.0 we surface both readings with their implied ranges and make the
user choose, rather than guessing.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from bma_standard_formulas.engine.rates import (
    RateDeck,
    RateDeckError,
    canonicalize_index_name,
    is_date_column,
)

# A fat-finger is a single-point spike. Five days is wide enough to establish a
# local level and narrow enough that a genuine regime shift reads as a step
# rather than an outlier. See the module docstring for the calibration.
DEFAULT_WINDOW = 5

# Scale slips are x100 or /100. Genuine 5-day moves stay well inside 10x.
OUTLIER_THRESHOLD = 10.0

# Above this, a value cannot be a decimal-scaled rate (it would be >100%), so the
# column is unambiguously in percent. At or below it, percent and decimal
# readings are both plausible and the user must decide.
AMBIGUOUS_SCALE_MAX = 1.0

# Plausible band for a real interest rate, in percent.
PLAUSIBLE_RATE_MIN = 0.001
PLAUSIBLE_RATE_MAX = 30.0

MAX_ITERATIONS = 50


def windowed_loo_ratio(s: pd.Series, window: int = DEFAULT_WINDOW) -> pd.Series:
    """Ratio of each cell to the mean of its neighbours, excluding itself.

    Leave-one-out: the cell under test is removed from the mean it is judged
    against, so a bad value cannot inflate its own baseline.

    NaN-aware: holidays neither break the computation nor count as neighbours,
    and they yield a NaN ratio so they can never be mistaken for outliers.
    """
    w = s.rolling(window, center=True, min_periods=2)
    neighbours = w.count() - s.notna().astype(int)
    total = w.sum() - s.fillna(0)
    return s / (total / neighbours.replace(0, np.nan))


def _numeric(s: pd.Series) -> pd.Series:
    """Lenient parse: strip a "%" suffix, coerce junk to NaN so it can be reported."""
    text = s.astype(str).str.strip().str.rstrip("%")
    return pd.to_numeric(text, errors="coerce")


def _blank(s: pd.Series) -> pd.Series:
    """True where a cell is genuinely empty (vs. present but unparseable)."""
    return s.isna() | s.astype(str).str.strip().eq("")


def detect_scale(s: pd.Series) -> dict[str, Any]:
    """Decide whether a rate column is in percent or decimal.

    Returns a verdict of "percent", "decimal", or "ambiguous".  Ambiguous is a
    real answer, not a failure: a column whose values all sit below 1.0 could be
    ZIRP-era rates in percent or normal rates in decimal, and no statistic drawn
    from the column can tell.  Both readings are returned with their implied
    ranges so the user can pick.
    """
    v = _numeric(s).dropna()
    if v.empty:
        return {"scale": "unknown", "reason": "no parseable values"}

    lo, hi = float(v.min()), float(v.max())

    if hi > AMBIGUOUS_SCALE_MAX:
        return {
            "scale": "percent",
            "confident": True,
            "observed_range": [lo, hi],
            "reason": (
                f"max value {hi:.4f} exceeds {AMBIGUOUS_SCALE_MAX}; as a decimal that "
                f"would be {hi * 100:.1f}%, which is not a plausible rate."
            ),
        }

    as_percent = [lo, hi]
    as_decimal = [lo * 100, hi * 100]
    decimal_plausible = PLAUSIBLE_RATE_MIN <= hi * 100 <= PLAUSIBLE_RATE_MAX
    percent_plausible = PLAUSIBLE_RATE_MIN <= hi <= PLAUSIBLE_RATE_MAX

    return {
        "scale": "ambiguous",
        "confident": False,
        "observed_range": [lo, hi],
        "if_percent": {
            "implied_range_pct": as_percent,
            "plausible": percent_plausible,
            "reads_as": "near-zero rates (a ZIRP-era series)",
        },
        "if_decimal": {
            "implied_range_pct": as_decimal,
            "plausible": decimal_plausible,
            "reads_as": "ordinary rates recorded as decimals",
        },
        "reason": (
            f"every value sits at or below {AMBIGUOUS_SCALE_MAX}. Read as percent this is "
            f"{as_percent[0]:.4f}%-{as_percent[1]:.4f}%; read as decimal it is "
            f"{as_decimal[0]:.2f}%-{as_decimal[1]:.2f}%. Both are real possibilities "
            f"(2021 SOFR really was ~0.05%), so this must be declared, not guessed."
        ),
    }


def _rate_columns(df: pd.DataFrame) -> list[Any]:
    return [c for c in df.columns if not is_date_column(c)]


def find_outliers(
    s: pd.Series,
    window: int = DEFAULT_WINDOW,
    threshold: float = OUTLIER_THRESHOLD,
) -> list[dict[str, Any]]:
    """Locate scale-slip cells, re-measuring after each fix.

    A bad cell contaminates its neighbours' windows, so a single pass flags the
    culprit *and* innocents around it.  We fix the most extreme cell, re-measure,
    and repeat — which converges on the genuinely bad cells alone.

    The proposed correction snaps to the x100 / /100 signature of a decimal-point
    slip, which is what these errors actually are.
    """
    work = _numeric(s).copy()
    found: list[dict[str, Any]] = []

    for _ in range(MAX_ITERATIONS):
        r = windowed_loo_ratio(work, window)
        flagged = np.where((r < 1 / threshold) | (r > threshold))[0]
        if not len(flagged):
            break

        # Most extreme first: its neighbours' verdicts are the least trustworthy
        # until it is dealt with.
        ratios = r.iloc[flagged].to_numpy()
        worst = int(flagged[int(np.argmax(np.abs(np.log10(np.abs(ratios)))))])

        ratio = float(r.iloc[worst])
        factor = 100.0 if ratio < 1 else 0.01
        observed = float(work.iloc[worst])
        proposed = observed * factor

        found.append({
            "row": int(work.index[worst]),
            "observed": observed,
            "proposed": proposed,
            "neighbour_mean": observed / ratio if ratio else None,
            "ratio_to_neighbours": ratio,
            "detail": (
                f"{observed:g} is {1/ratio:.0f}x below its neighbours"
                if ratio < 1
                else f"{observed:g} is {ratio:.0f}x above its neighbours"
            ),
        })
        work.iloc[worst] = proposed

    return found


def diagnose_rates(df: pd.DataFrame) -> dict[str, Any]:
    """Scan a rates file and report every problem found. Fixes nothing.

    Returns a summary with one entry per problem, each carrying a severity and,
    where one exists, the id of a repair that would address it.
    """
    problems: list[dict[str, Any]] = []

    # Layout first: if we cannot tell which columns are dates, nothing else means
    # anything.
    try:
        layout = RateDeck.infer_layout(df)
    except RateDeckError as e:
        return {
            "layout": None,
            "total_rows": len(df),
            "problems": [{
                "kind": "unreadable_layout",
                "severity": "blocking",
                "column": None,
                "detail": str(e),
                "repair": None,
            }],
        }

    for col in _rate_columns(df):
        raw = df[col]
        blank = _blank(raw)
        parsed = _numeric(raw)

        corrupt = ~blank & parsed.isna()
        if corrupt.any():
            problems.append({
                "kind": "unparseable_cells",
                "severity": "blocking",
                "column": str(col),
                "rows": [int(i) for i in df.index[corrupt]],
                "values": [repr(v) for v in raw[corrupt].tolist()[:10]],
                "detail": (
                    f"{int(corrupt.sum())} non-blank cell(s) cannot be read as a number. "
                    f"Blank cells are fine (a market holiday has no observation); these "
                    f"are not blank."
                ),
                "repair": None,   # needs a human: we will not guess what "5.2x" meant
            })
            continue          # scale/outlier findings would be noise until this is fixed

        if parsed.notna().sum() == 0:
            problems.append({
                "kind": "empty_curve",
                "severity": "blocking",
                "column": str(col),
                "detail": "every value in this column is blank; the curve has no data.",
                "repair": None,
            })
            continue

        gaps = int(blank.sum())
        if gaps:
            problems.append({
                "kind": "calendar_gaps",
                "severity": "info",
                "column": str(col),
                "count": gaps,
                "detail": (
                    f"{gaps} blank cell(s) — read as gaps in the observation calendar "
                    f"(e.g. market holidays). No observation is recorded on those dates; "
                    f"rate lookup uses the latest value at or before each period."
                ),
                "repair": None,
            })

        scale = detect_scale(raw)
        if scale.get("scale") == "ambiguous":
            problems.append({
                "kind": "scale_ambiguous",
                "severity": "blocking",
                "column": str(col),
                "detail": scale["reason"],
                "evidence": scale,
                "repair": f"declare_scale:{col}",
            })

        for hit in find_outliers(parsed):
            problems.append({
                "kind": "outlier_cell",
                "severity": "warning",
                "column": str(col),
                "row": hit["row"],
                "observed": hit["observed"],
                "proposed": hit["proposed"],
                "detail": (
                    f"row {hit['row']}: {hit['detail']} "
                    f"(neighbour mean {hit['neighbour_mean']:.4g}). "
                    f"Consistent with a decimal-point slip."
                ),
                "repair": f"rescale_cell:{col}:{hit['row']}",
            })

    return {
        "layout": layout,
        "total_rows": len(df),
        "rate_columns": [str(c) for c in _rate_columns(df)],
        "problems": problems,
    }


def available_repairs(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Repairs applicable to this file, derived from the diagnosis."""
    diag = diagnose_rates(df)
    repairs: list[dict[str, Any]] = []

    for p in diag["problems"]:
        rid = p.get("repair")
        if not rid:
            continue
        if p["kind"] == "scale_ambiguous":
            repairs.append({
                "id": f"scale_to_percent:{p['column']}",
                "column": p["column"],
                "kind": "declare_scale",
                "description": (
                    f"Treat {p['column']} as decimal and multiply by 100 "
                    f"(implied {p['evidence']['if_decimal']['implied_range_pct'][0]:.2f}%"
                    f"-{p['evidence']['if_decimal']['implied_range_pct'][1]:.2f}%)"
                ),
                "requires_confirmation": True,
            })
            repairs.append({
                "id": f"scale_keep_percent:{p['column']}",
                "column": p["column"],
                "kind": "declare_scale",
                "description": (
                    f"Treat {p['column']} as already in percent, leave unchanged "
                    f"(implied {p['evidence']['if_percent']['implied_range_pct'][0]:.4f}%"
                    f"-{p['evidence']['if_percent']['implied_range_pct'][1]:.4f}%)"
                ),
                "requires_confirmation": True,
            })
        elif p["kind"] == "outlier_cell":
            repairs.append({
                "id": rid,
                "column": p["column"],
                "kind": "rescale_cell",
                "row": p["row"],
                "description": (
                    f"Rescale row {p['row']} of {p['column']}: "
                    f"{p['observed']:g} → {p['proposed']:g}"
                ),
                "requires_confirmation": True,
            })

    return repairs


def preview_repair(df: pd.DataFrame, rule_id: str, limit: int = 20) -> dict[str, Any]:
    """Show what a repair would change, without changing it."""
    kind, col, *rest = rule_id.split(":")

    if col not in df.columns:
        raise ValueError(f"Column {col!r} not in file. Columns: {list(df.columns)}")

    before = _numeric(df[col])

    if kind == "scale_to_percent":
        after = before * 100
        rows = before.notna()
    elif kind == "scale_keep_percent":
        after = before
        rows = pd.Series(False, index=before.index)
    elif kind == "rescale_cell":
        row = int(rest[0])
        after = before.copy()
        hits = [h for h in find_outliers(before) if h["row"] == row]
        if not hits:
            raise ValueError(f"Row {row} of {col!r} is no longer flagged as an outlier.")
        after.at[row] = hits[0]["proposed"]
        rows = pd.Series(False, index=before.index)
        rows.at[row] = True
    else:
        raise ValueError(f"Unknown repair {rule_id!r}")

    sample = [
        {"row": int(i), "before": float(before.at[i]), "after": float(after.at[i])}
        for i in list(before.index[rows])[:limit]
    ]
    return {
        "rule_id": rule_id,
        "column": col,
        "changed_count": int(rows.sum()),
        "sample": sample,
    }


def apply_repair(df: pd.DataFrame, rule_id: str) -> tuple[pd.DataFrame, int]:
    """Apply a repair, returning a new frame and the number of cells changed."""
    prev = preview_repair(df, rule_id, limit=0)
    kind, col, *rest = rule_id.split(":")

    out = df.copy()
    values = _numeric(out[col])

    if kind == "scale_to_percent":
        out[col] = values * 100
    elif kind == "scale_keep_percent":
        out[col] = values
    elif kind == "rescale_cell":
        row = int(rest[0])
        hits = [h for h in find_outliers(values) if h["row"] == row]
        if not hits:
            raise ValueError(f"Row {row} of {col!r} is no longer flagged as an outlier.")
        values.at[row] = hits[0]["proposed"]
        out[col] = values
    else:
        raise ValueError(f"Unknown repair {rule_id!r}")

    return out, prev["changed_count"]


def is_ingestible(df: pd.DataFrame) -> tuple[bool, list[str]]:
    """True if the file has no blocking problems left.

    Warnings (outlier cells) do not block: the user may legitimately accept a
    value we find surprising.  Blocking problems (corrupt cells, undeclared
    scale, empty curves, unreadable layout) must be resolved first.
    """
    diag = diagnose_rates(df)
    blockers = [
        f"{p['column']}: {p['detail']}" if p.get("column") else p["detail"]
        for p in diag["problems"]
        if p["severity"] == "blocking"
    ]
    return not blockers, blockers
