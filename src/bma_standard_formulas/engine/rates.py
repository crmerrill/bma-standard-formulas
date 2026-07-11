# Requires Python 3.12+
from __future__ import annotations

"""
Interest rate curves for floating-rate loan cashflow modeling.

RateIndex encapsulates a single dated time series of interest rates (e.g. SOFR,
LIBOR, Treasury yields) and provides methods to extract rate vectors for
amortization models.  It supports loading from FRED, CSV files, DataFrames, or
in-memory arrays.

RateDeck holds *several* RateIndex curves keyed by canonical index name, for
portfolios whose loans reference different indexes.  Each curve carries its own
date vector, so curves may be ragged (SOFR from 2018, LIBOR through 2023).
Look a curve up with ``deck[loan.index_type]`` — the lookup canonicalizes, so
the tape's "sofr_3m" and a rate file's "SOFR 3M" resolve to the same curve.

The output of RateIndex.get_rate_vector() feeds into run_bma_scheduled_cashflow's
``index`` parameter for floating-rate loans.

Architecture layering:
    rates.py         → market data sourcing (this module)
    loan.py          → Loan data model, rate conversion
    cashflows.py     → BMA C.3 leaf computation
    portfolio.py     → Tier 2: aggregation, waterfall

This module is the engine-side counterpart to bma_cfengine_app.orchestrator.rates,
which owns upload storage and preflight validation.  Canonical index names and
their aliases live *here*, so that HTTP callers and library callers resolve names
identically.
"""

import bisect
import calendar
from collections import Counter
from collections.abc import Hashable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar

import numpy as np
import pandas as pd

if TYPE_CHECKING:  # avoid a runtime cycle: loan.py imports this module
    from .loan import Loan


class RateDataError(ValueError):
    """Raised when a rates file contains cells that cannot be parsed.

    Distinct from a blank cell, which is an expected gap (market holiday, or a
    short curve padded out in a per-index-dates file) and is dropped silently.
    """


def _reject_unparseable(
    df: pd.DataFrame,
    col: Hashable,
    parsed: pd.Series,
    blank: pd.Series,
    name: str | None,
    kind: str,
    max_shown: int = 5,
) -> None:
    """Raise if any non-blank cell in ``col`` failed to parse."""
    bad = ~blank & parsed.isna()
    if not bad.any():
        return

    rows = df.index[bad]
    values = df[col][bad].tolist()
    shown = ", ".join(
        f"row {r}: {v!r}" for r, v in list(zip(rows, values))[:max_shown]
    )
    extra = f" (+{int(bad.sum()) - max_shown} more)" if int(bad.sum()) > max_shown else ""
    label = f"{name} " if name else ""
    raise RateDataError(
        f"{label}{kind} column {col!r} has {int(bad.sum())} unparseable "
        f"non-blank cell(s): {shown}{extra}. "
        f"Blank cells are fine — they are read as gaps (e.g. market holidays). "
        f"These are not blank, so they are being reported rather than dropped."
    )


@dataclass(frozen=True)
class RateIndex:
    """Immutable time series of interest rates indexed by date.

    Encapsulates historical and/or projected index rates (e.g. SOFR, LIBOR,
    T-Bill) with associated dates.  Used to construct rate vectors for
    floating-rate loan amortization.

    The rates are stored as PERCENTAGES (e.g. 5.25 for 5.25%), matching
    market convention and the Loan dataclass.  The cashflow runners expect
    DECIMAL — conversion happens in the Loan wrapper or at the call site.

    Attributes:
        dates:  Sorted list of observation dates (ascending).
        rates:  Rate value (%) for each date.  Same length as dates.
        name:   Optional label (e.g. "SOFR", "1Y_CMT") for display/audit.

    Example:
        >>> idx = RateIndex.from_arrays(
        ...     dates=["2024-01-01", "2024-02-01", "2024-03-01"],
        ...     rates=[5.25, 5.30, 5.35],
        ...     name="SOFR",
        ... )
        >>> vec = idx.get_rate_vector(
        ...     next_payment_date=date(2024, 1, 1),
        ...     next_reset_date=date(2024, 1, 1),
        ...     reset_frequency=12,
        ...     remaining_term=360,
        ... )
    """
    dates: tuple[date, ...] = ()
    rates: tuple[float, ...] = ()
    name: str | None = None

    def __post_init__(self) -> None:
        """Validate and sort by date."""
        if len(self.dates) != len(self.rates):
            raise ValueError(
                f"dates and rates must have same length: {len(self.dates)} vs {len(self.rates)}"
            )
        if self.dates:
            # Sort by date (frozen=True requires object.__setattr__)
            combined = sorted(zip(self.dates, self.rates))
            sorted_dates, sorted_rates = zip(*combined)
            object.__setattr__(self, "dates", tuple(sorted_dates))
            object.__setattr__(self, "rates", tuple(sorted_rates))

    def get_rate_vector(
        self,
        next_payment_date: date,
        next_reset_date: date,
        reset_frequency: int,
        remaining_term: int,
    ) -> np.ndarray:
        """Build a rate vector for floating-rate amortization.

        Constructs an array of length ``remaining_term`` where each element is
        the index rate (%) for that monthly period.  The rate resets every
        ``reset_frequency`` months starting from ``next_reset_date``.  Between
        resets, the rate is held constant.

        Rate lookup uses binary search (O(log n) per reset) to find the latest
        available rate at or before each reset date.

        Args:
            next_payment_date:  Date of the first payment period in the vector.
            next_reset_date:    Date of the next rate reset (may equal next_payment_date).
            reset_frequency:    Months between rate resets (e.g. 12 for annual,
                                1 for monthly).  0 means no resets (use initial rate).
            remaining_term:     Number of monthly periods to generate.

        Returns:
            np.ndarray of length ``remaining_term``, rates in PERCENT (e.g. 5.25).

        Raises:
            ValueError: If no rate data is loaded.
        """
        if not self.dates or not self.rates:
            raise ValueError("No rate data loaded in RateIndex.")

        # Already sorted in __post_init__; use lists for bisect compatibility.
        dates_list = list(self.dates)
        rates_list = list(self.rates)

        result = np.empty(remaining_term, dtype=float)
        curr_rate = rates_list[0]  # fallback: earliest known rate

        # Design notes for this loop:
        #
        # Historical / forward splice
        #   The rate index typically contains historical rates (before asof_date)
        #   merged with a forward curve (after asof_date) via RateIndex.merge().
        #   No special handling is needed at the splice point: bisect_right on
        #   each period_date naturally picks the latest entry at or before that
        #   date, whether it is historical or projected.
        #
        # asof_date falls mid-reset-period
        #   next_reset_date and next_payment_date are loan-level fields already
        #   set relative to asof_date (i.e. they are future dates).  If the
        #   as-of snapshot lands partway through a reset cycle, next_reset_date
        #   is already the *next* upcoming reset, so the loop starts in the
        #   correct state without any special mid-period logic.
        #
        # Reset date with no matching rate entry
        #   bisect_right returns the insertion point; subtracting 1 gives the
        #   latest entry at or before period_date.  If the reset date predates
        #   all entries in the index (idx < 0), curr_rate stays at its
        #   initialised value (rates_list[0] — the earliest known rate).
        #
        # Fixed-rate loans
        #   reset_frequency == 0, so the reset branch never fires.  The period-0
        #   initialisation sets curr_rate from the index and it never changes.
        current_reset_date = next_reset_date

        for i in range(remaining_term):
            # Calendar date for period i — proper month roll using calendar.monthrange
            # so that dates like Jan 31 advance correctly to Feb 28/29, Mar 31, etc.
            year_offset, month = divmod(next_payment_date.month - 1 + i, 12)
            new_year = next_payment_date.year + year_offset
            new_month = month + 1
            period_date = next_payment_date.replace(
                year=new_year,
                month=new_month,
                day=min(next_payment_date.day, calendar.monthrange(new_year, new_month)[1]),
            )

            # A reset fires when the period has reached or passed the next
            # scheduled reset date (and floating resets are enabled).
            # After each reset, advance current_reset_date by reset_frequency
            # months so the next reset fires at the correct calendar date.
            if reset_frequency > 0 and period_date >= current_reset_date:
                # Binary search: latest rate at or before this period's date.
                idx = bisect.bisect_right(dates_list, period_date) - 1
                if idx >= 0:
                    curr_rate = rates_list[idx]
                # Advance to the next reset date — same proper month roll.
                rf_year_offset, rf_month = divmod(
                    current_reset_date.month - 1 + reset_frequency, 12
                )
                rd_year = current_reset_date.year + rf_year_offset
                rd_month = rf_month + 1
                current_reset_date = current_reset_date.replace(
                    year=rd_year,
                    month=rd_month,
                    day=min(current_reset_date.day, calendar.monthrange(rd_year, rd_month)[1]),
                )
            elif i == 0:
                # Period 0 always initialises the rate (covers fixed-rate path
                # and the case where next_reset_date is in the future).
                idx = bisect.bisect_right(dates_list, period_date) - 1
                if idx >= 0:
                    curr_rate = rates_list[idx]

            result[i] = curr_rate

        return result

    # ── Factory methods ─────────────────────────────────────────────────

    @classmethod
    def from_fred(
        cls,
        series_id: str,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
    ) -> RateIndex:
        """Retrieve historical rates from FRED (Federal Reserve Economic Data).

        Requires the ``pandas_datareader`` package (``pip install pandas-datareader``).

        Args:
            series_id:   FRED series ID (e.g. "DGS10" for 10-year Treasury,
                         "SOFR" for Secured Overnight Financing Rate).
            start_date:  Start of data range (str "YYYY-MM-DD" or date). Default: all available.
            end_date:    End of data range. Default: today.

        Returns:
            RateIndex with dates and rates from the FRED series.

        Raises:
            ImportError: If pandas_datareader is not installed.
        """
        try:
            import pandas_datareader.data as web
        except ImportError:
            raise ImportError(
                "pandas_datareader is required for FRED access. "
                "Install with: pip install pandas-datareader"
            )
        sdate = pd.to_datetime(start_date) if start_date else "1900-01-01"
        edate = pd.to_datetime(end_date) if end_date else pd.Timestamp.today()
        df = web.DataReader(series_id, "fred", sdate, edate)
        valid = df[series_id].dropna()
        dates = tuple(d.date() for d in valid.index.to_pydatetime())
        rates = tuple(float(v) for v in valid.values)
        return cls(dates=dates, rates=rates, name=series_id)

    @classmethod
    def from_frame(
        cls,
        df: pd.DataFrame,
        date_col: Hashable = "date",
        rate_col: Hashable = "rate",
        name: str | None = None,
    ) -> RateIndex:
        """Build a RateIndex from two columns of a DataFrame.

        This is the shared construction primitive: ``from_csv`` and the
        ``RateDeck`` readers all funnel through it, so date parsing, ``%``
        stripping, and blank handling happen in exactly one place.

        Blank cells and non-blank junk are *different things* and are treated
        differently:

        **Blank** (empty cell / NaN) — an expected gap.  A rates series has no
        observation on a market holiday, and a short curve in a per-index-dates
        file is padded with blanks.  Blanks are dropped: the curve simply has no
        point there, and ``get_rate_vector`` bisects to the latest rate at or
        before each period, so a gap needs no filling.

        **Non-blank but unparseable** ("5.2x", "5,33", "N/R") — corruption.
        Nobody pads a file with "5.2x".  These raise, naming the column and the
        offending values, rather than silently vanishing and leaving a curve
        that is quietly missing observations.

        Args:
            df:        Source DataFrame.
            date_col:  Column holding observation dates.
            rate_col:  Column holding rate values (%).  May carry a trailing
                       "%" (e.g. "3.66%") and may contain blanks.
            name:      Optional label for the index.

        Returns:
            RateIndex over the non-blank rows.

        Raises:
            RateDataError: If any non-blank cell cannot be parsed.
        """
        raw_dates, raw_rates = df[date_col], df[rate_col]

        # format="mixed" handles varied date formats (M/D/YY, ISO, etc.) without warning
        dates = pd.to_datetime(
            raw_dates, format="mixed", dayfirst=False, errors="coerce"
        )
        # Strip an optional "%" suffix (e.g. "3.66%" → 3.66) before parsing.
        as_text = raw_rates.astype(str).str.strip().str.rstrip("%")
        rates = pd.to_numeric(as_text, errors="coerce")

        # A cell is blank if it was NaN on read (pandas maps "", "NA", "N/A" and
        # friends to NaN) or is an empty string after stripping.
        date_blank = raw_dates.isna() | raw_dates.astype(str).str.strip().eq("")
        rate_blank = raw_rates.isna() | as_text.eq("")

        _reject_unparseable(df, date_col, dates, date_blank, name, "date")
        _reject_unparseable(df, rate_col, rates, rate_blank, name, "rate")

        keep = dates.notna() & rates.notna()
        dates, rates = dates[keep], rates[keep]

        return cls(
            dates=tuple(d.date() for d in dates),
            rates=tuple(float(v) for v in rates),
            name=name,
        )

    @classmethod
    def from_csv(
        cls,
        path: str | Path,
        date_col: str = "date",
        rate_col: str = "rate",
        name: str | None = None,
    ) -> RateIndex:
        """Load rates from a CSV file using pandas.

        Thin wrapper: reads the file, then delegates to ``from_frame``.

        Args:
            path:      Path to CSV file.
            date_col:  Column name containing dates (parsed automatically by pandas).
            rate_col:  Column name containing rate values (%).
            name:      Optional label for the index.

        Returns:
            RateIndex with dates and rates from the CSV.
        """
        return cls.from_frame(pd.read_csv(path), date_col, rate_col, name)

    @classmethod
    def from_arrays(
        cls,
        dates: list[str | date],
        rates: list[float],
        date_format: str | None = None,
        name: str | None = None,
    ) -> RateIndex:
        """Construct RateIndex directly from lists of dates and rates.

        Args:
            dates:        List of date strings or date objects.
            rates:        List of rate values (%) corresponding to each date.
            date_format:  Optional strftime format for parsing date strings
                          (e.g. "%Y-%m-%d"). If None, uses ``date.fromisoformat()``.
            name:         Optional label for the index.

        Returns:
            RateIndex with the provided dates and rates.
        """
        date_objs: list[date] = []
        for d in dates:
            if isinstance(d, date):
                date_objs.append(d)
            elif date_format:
                date_objs.append(datetime.strptime(d, date_format).date())
            else:
                date_objs.append(date.fromisoformat(d))
        return cls(
            dates=tuple(date_objs),
            rates=tuple(float(r) for r in rates),
            name=name,
        )

    @classmethod
    def merge(cls, *indexes: RateIndex, name: str | None = None) -> RateIndex:
        """Merge multiple RateIndex objects into one, sorted by date.

        Combines dates and rates from all inputs.  When the same date appears
        in more than one source, the **later argument wins** — so pass the
        historical series first and the forward curve second to let forward
        projections override any overlap at the splice point.

        Args:
            *indexes:  One or more RateIndex objects to combine.
            name:      Optional label for the merged index.

        Returns:
            A new RateIndex spanning the union of all input date ranges.

        Example::

            hist = RateIndex.from_csv("SOFR_historical.csv")
            fwd  = RateIndex.from_csv("SOFR_fwd.csv", date_col="ResetDate", rate_col="Rate")
            sofr = RateIndex.merge(hist, fwd, name="SOFR")
        """
        combined: dict[date, float] = {}
        for idx in indexes:
            for d, r in zip(idx.dates, idx.rates):
                combined[d] = r  # later argument wins on duplicate dates
        items = sorted(combined.items())
        return cls(
            dates=tuple(d for d, _ in items),
            rates=tuple(r for _, r in items),
            name=name,
        )

    @classmethod
    def from_constant(cls, rate: float, name: str | None = None) -> RateIndex:
        """Create a flat (constant) rate index.

        Useful for fixed-rate scenarios or testing.  The single rate is assigned
        to date(1900, 1, 1) so it's always "available" for any lookup date.

        Args:
            rate:  The constant rate value (%).
            name:  Optional label.

        Returns:
            RateIndex with a single rate valid for all dates.
        """
        return cls(dates=(date(1900, 1, 1),), rates=(float(rate),), name=name)

    def __len__(self) -> int:
        """Number of rate observations."""
        return len(self.dates)

    def __repr__(self) -> str:
        n = len(self)
        if n == 0:
            return f"RateIndex(empty, name={self.name!r})"
        return (
            f"RateIndex({n} obs, {self.dates[0]}..{self.dates[-1]}, "
            f"name={self.name!r})"
        )


# ── Canonical index vocabulary ──────────────────────────────────────────
#
# These live in the engine, not the app layer, so that a rate file's column
# header and a loan tape's index_type cell resolve to the same key whether the
# caller arrived over HTTP or from a notebook.

CANONICAL_INDEXES: frozenset[str] = frozenset({
    "CMT1Y", "CMT3Y", "CMT5Y",
    "CODI", "COFI", "MTA12M",
    "LIBOR1M", "LIBOR3M", "LIBOR6M", "LIBOR1Y",
    "PRIME",
    "SOFR", "SOFR1M", "SOFR3M",
})

INDEX_ALIASES: dict[str, str] = {
    "sofr_1m": "SOFR1M",
    "sofr_3m": "SOFR3M",
    "sofr": "SOFR",
    "1y_cmt": "CMT1Y",
    "1yr_cmt": "CMT1Y",
    "3y_cmt": "CMT3Y",
    "5y_cmt": "CMT5Y",
    "cmt_1y": "CMT1Y",
    "cmt_3y": "CMT3Y",
    "cmt_5y": "CMT5Y",
    "libor_1m": "LIBOR1M",
    "libor_3m": "LIBOR3M",
    "libor_6m": "LIBOR6M",
    "libor_1y": "LIBOR1Y",
    "wsj_prime": "PRIME",
    "prime": "PRIME",
    "mta": "MTA12M",
    "mta_12m": "MTA12M",
    "cofi": "COFI",
    "codi": "CODI",
}


def _normalize_col(name: str) -> str:
    """Normalize a column label to lowercase snake_case for alias lookup.

    Strips leading/trailing whitespace, converts to lowercase, and replaces
    spaces, hyphens, and dots with underscores.

    Examples::

        "Note Rate"  → "note_rate"
        "orig-bal"   → "orig_bal"
        "LOAN.ID"    → "loan_id"
    """
    return name.strip().lower().replace(" ", "_").replace("-", "_").replace(".", "_")


def canonicalize_index_name(name: str) -> str | None:
    """Resolve an index label to its canonical name, or None if unrecognized.

    Recognizes both the canonical spellings (``"SOFR3M"``) and the registered
    aliases (``"sofr_3m"``, ``"SOFR 3M"``).

    Examples::

        canonicalize_index_name("sofr_3m")  → "SOFR3M"
        canonicalize_index_name("WSJ Prime") → "PRIME"
        canonicalize_index_name("Notes")     → None
    """
    norm = _normalize_col(name)
    if norm.upper() in CANONICAL_INDEXES:
        return norm.upper()
    return INDEX_ALIASES.get(norm)


def _deck_key(name: str) -> str:
    """Canonical name if recognized, else the normalized label uppercased.

    Unregistered indexes are still usable so long as the tape and the rate file
    spell them consistently — they simply don't get alias resolution.
    """
    return canonicalize_index_name(name) or _normalize_col(name).upper()


_DATE_COL_TOKENS = frozenset({"period", "month"})


def is_date_column(col: object) -> bool:
    """True if a column header names a date column.

    Detection is by *name*, deliberately.  Content sniffing misfires badly here:
    ``pd.to_datetime`` happily parses a column of rates like 5.25 as nanosecond
    epochs.
    """
    norm = _normalize_col(str(col))
    return "date" in norm or norm in _DATE_COL_TOKENS


class RateDeckError(ValueError):
    """Raised when a rate deck cannot be built or a curve cannot be resolved.

    Note this is a ValueError, not a KeyError, even for failed lookups — a
    missing curve is a data-integrity problem, not a routine absent-key check.
    """


@dataclass(frozen=True)
class RateDeck:
    """A set of RateIndex curves keyed by canonical index name.

    A portfolio whose loans reference different floating indexes (SOFR, Prime,
    legacy LIBOR) needs one curve per index.  Each curve owns its own date
    vector, so curves may be ragged — SOFR starting in 2018, LIBOR ending in
    2023 — with no shared date grid.

    Lookup canonicalizes, so a loan tape's ``index_type`` cell resolves to the
    curve built from a differently-spelled rate file header::

        deck = RateDeck.from_frame(df)          # header "SOFR 3M"
        curve = deck["sofr_3m"]                 # tape cell — same curve

    Fixed-rate loans have no index.  Guard on ``loan.is_fixed_rate()`` before
    subscripting; ``deck[None]`` raises.

    Attributes:
        indexes:  Mapping of canonical index name → RateIndex.
        name:     Optional label for the deck (e.g. the source filename).
    """

    indexes: Mapping[str, RateIndex] = field(default_factory=dict)
    name: str | None = None

    CANONICAL: ClassVar[frozenset[str]] = CANONICAL_INDEXES
    ALIASES: ClassVar[dict[str, str]] = INDEX_ALIASES

    def __post_init__(self) -> None:
        """Canonicalize keys and freeze the mapping."""
        keyed: dict[str, RateIndex] = {}
        for raw_key, curve in self.indexes.items():
            if not isinstance(curve, RateIndex):
                raise RateDeckError(
                    f"RateDeck values must be RateIndex, got {type(curve).__name__} "
                    f"for {raw_key!r}"
                )
            key = _deck_key(str(raw_key))
            if key in keyed:
                raise RateDeckError(
                    f"Duplicate index {key!r} in RateDeck — two sources resolve to "
                    f"the same canonical name."
                )
            # An empty curve must never sit in the deck: missing_for() would see
            # the key and report full coverage, and the failure would surface
            # much later as "No rate data loaded" from deep inside pricing.
            if len(curve) == 0:
                raise RateDeckError(
                    f"Rate curve {key!r} has zero observations. Every value in its "
                    f"column was blank. A curve with no data cannot price a loan, "
                    f"and an empty curve in the deck would masquerade as coverage."
                )
            keyed[key] = curve
        object.__setattr__(self, "indexes", MappingProxyType(keyed))

    # ── Lookup ──────────────────────────────────────────────────────────

    @staticmethod
    def canonicalize(name: str) -> str | None:
        """Resolve a label to its canonical index name, or None if unrecognized."""
        return canonicalize_index_name(name)

    def __getitem__(self, name: str | None) -> RateIndex:
        """Look up a curve by index name, canonicalizing the key.

        Raises:
            RateDeckError: If ``name`` is None (a floating loan with no
                ``index_type``), or names an index this deck doesn't carry.
        """
        if name is None:
            raise RateDeckError(
                "Cannot look up a rate curve for index_type=None. "
                "Fixed-rate loans should not reach a RateDeck lookup — guard on "
                "loan.is_fixed_rate() first. A floating loan with no index_type "
                "is a tape defect."
            )
        key = _deck_key(str(name))
        if key not in self.indexes:
            available = ", ".join(sorted(self.indexes)) or "<empty deck>"
            raise RateDeckError(
                f"No rate curve for index {key!r} (from {name!r}). "
                f"Deck carries: {available}"
            )
        return self.indexes[key]

    def __contains__(self, name: object) -> bool:
        if name is None or not isinstance(name, str):
            return False
        return _deck_key(name) in self.indexes

    def __iter__(self) -> Iterator[str]:
        return iter(self.indexes)

    def __len__(self) -> int:
        """Number of curves in the deck."""
        return len(self.indexes)

    def keys(self):  # noqa: D102 - Mapping-like convenience
        return self.indexes.keys()

    def missing_for(self, loans: Iterable["Loan"]) -> dict[str | None, int]:
        """Which indexes the floating loans need that this deck doesn't carry.

        Returns a mapping of index name → number of loans referencing it,
        including a ``None`` entry counting floating loans whose ``index_type``
        is unset.  An empty result means every floating loan can be priced.

        Memory is O(distinct indexes), not O(loans) — this is a set difference,
        not a per-loan resolution table.

        Example::

            if missing := deck.missing_for(loans):
                raise RateDeckError(f"Rate deck is missing curves: {missing}")
        """
        needed = Counter(loan.index_type for loan in loans if not loan.is_fixed_rate())
        return {
            name: count
            for name, count in needed.items()
            if name is None or name not in self
        }

    # ── Factory methods ─────────────────────────────────────────────────

    @classmethod
    def from_curves(
        cls, curves: Mapping[str, RateIndex], name: str | None = None
    ) -> RateDeck:
        """Build a deck from an existing mapping of name → RateIndex."""
        return cls(indexes=dict(curves), name=name)

    @classmethod
    def from_frame(
        cls,
        df: pd.DataFrame,
        layout: str | None = None,
        columns: Mapping[str, str] | None = None,
        name: str | None = None,
    ) -> RateDeck:
        """Build a deck from a rates DataFrame in either supported layout.

        The layouts differ only in *whose dates* each curve reads.  Either way,
        every index becomes its own RateIndex and the deck is just the container.

        **shared_dates** — one date column, one column per index.  Every curve
        reads the same date column::

            Date        SOFR    PRIME   LIBOR1M
            2024-01-01  5.33    8.50    5.44

        **per_index_dates** — one date column per index, each immediately
        followed by its rate column.  Every curve reads its own dates::

            Date        SOFR    Date        PRIME
            2024-01-01  5.33    2024-01-15  8.50

        per_index_dates is the general case; shared_dates is the special case
        where every curve happens to observe on the same calendar.  Vendors
        export the former because observation calendars genuinely differ — SOFR
        is daily, Prime only moves when the Fed does — and reindexing them onto
        one calendar would mean inventing data.

        Note that even in a shared_dates file each curve ends up owning its own
        date vector: after blanks are dropped, a column that starts late has
        fewer observations than its neighbours.  The deck never assumes a shared
        grid regardless of which layout the file arrived in.

        Layout is inferred from the number of date-named columns unless
        ``layout`` is given.  Inference is deliberately strict: anything it
        can't classify unambiguously raises rather than guessing.

        Args:
            df:       Source DataFrame (already read from CSV/Excel).
            layout:   "shared_dates" or "per_index_dates".  None (default)
                      infers from the headers.
            columns:  Optional explicit mapping of canonical index name → the
                      rate column header to use.  Overrides header inference,
                      and lets you pick up columns whose names aren't
                      recognized aliases.
            name:     Optional label for the deck.

        Returns:
            RateDeck with one curve per index.

        Raises:
            RateDeckError: If the layout can't be determined, the date/rate
                columns don't line up, or ``columns`` names a missing column.
        """
        date_cols = [c for c in df.columns if is_date_column(c)]

        if layout is None:
            layout = cls._infer_layout(df, date_cols)

        if layout == "shared_dates":
            if len(date_cols) != 1:
                raise RateDeckError(
                    f"layout='shared_dates' needs exactly one date column, found "
                    f"{len(date_cols)}: {date_cols}"
                )
            return cls._from_shared_dates(df, date_cols[0], columns, name)
        if layout == "per_index_dates":
            return cls._from_per_index_dates(df, date_cols, columns, name)
        raise RateDeckError(f"Unknown layout {layout!r} — expected 'shared_dates' or 'per_index_dates'")

    @classmethod
    def infer_layout(cls, df: pd.DataFrame) -> str:
        """Classify a rates file as "shared_dates" or "per_index_dates" from its headers alone.

        Cheap — inspects column names only, parses nothing.  Preflight uses this
        to surface an unreadable layout as a blocking error before committing to
        a full parse.

        Raises:
            RateDeckError: If the layout is ambiguous or there is no date column.
        """
        return cls._infer_layout(df, [c for c in df.columns if is_date_column(c)])

    @staticmethod
    def _infer_layout(df: pd.DataFrame, date_cols: list) -> str:
        """Classify the file layout, or raise if it's ambiguous."""
        n_dates, n_cols = len(date_cols), len(df.columns)
        if n_dates == 0:
            raise RateDeckError(
                f"No date column found in rates file. Columns: {list(df.columns)}. "
                f"A date column is one named 'date' (in any case, possibly with a "
                f"prefix/suffix), 'period', or 'month'."
            )
        if n_dates == 1:
            return "shared_dates"
        if n_cols == 2 * n_dates:
            return "per_index_dates"
        raise RateDeckError(
            f"Ambiguous rates file layout: {n_dates} date columns among {n_cols} "
            f"total columns. shared_dates needs exactly 1 date column; per_index_dates "
            f"needs each date column followed by its rate column (2x{n_dates}="
            f"{2 * n_dates} columns, found {n_cols}). "
            f"Pass layout='shared_dates' or layout='per_index_dates' to override. "
            f"Columns: {list(df.columns)}"
        )

    @classmethod
    def _from_shared_dates(
        cls,
        df: pd.DataFrame,
        date_col: object,
        columns: Mapping[str, str] | None,
        name: str | None,
    ) -> RateDeck:
        """One date column, N rate columns sharing that date grid."""
        if columns:
            pairs = list(columns.items())
            for _, file_col in pairs:
                if file_col not in df.columns:
                    raise RateDeckError(
                        f"Rate column {file_col!r} not present in file. "
                        f"Columns: {list(df.columns)}"
                    )
        else:
            # Unrecognized columns are ignored — rates files routinely carry
            # notes/source columns. Same convention as TapeSchema. Pass an
            # explicit `columns` mapping to force an unregistered index in.
            pairs = [
                (canon, col)
                for col in df.columns
                if col != date_col and (canon := canonicalize_index_name(str(col)))
            ]

        # Built with an explicit loop, not a dict comprehension: a comprehension
        # would silently collapse two columns that canonicalize to the same
        # index ("SOFR" and "sofr") before __post_init__ could reject them.
        curves: dict[str, RateIndex] = {}
        for canon, file_col in pairs:
            key = _deck_key(canon)
            if key in curves:
                raise RateDeckError(
                    f"Duplicate index {key!r}: more than one column resolves to it. "
                    f"Columns: {list(df.columns)}"
                )
            curves[key] = RateIndex.from_frame(df, date_col, file_col, name=key)
        return cls(indexes=curves, name=name)

    @classmethod
    def _from_per_index_dates(
        cls,
        df: pd.DataFrame,
        date_cols: list,
        columns: Mapping[str, str] | None,
        name: str | None,
    ) -> RateDeck:
        """Date/rate column pairs, bound positionally.

        Binding is positional, not by name, because real files repeat the literal
        header "Date" and pandas mangles the duplicates to "Date", "Date.1",
        "Date.2" — so name-based binding breaks on exactly the files this layout
        exists to read.
        """
        cols = list(df.columns)
        wanted = set(columns.values()) if columns else None

        curves: dict[str, RateIndex] = {}
        for date_col in date_cols:
            i = cols.index(date_col)
            if i + 1 >= len(cols):
                raise RateDeckError(
                    f"per_index_dates layout: date column {date_col!r} is the last column, "
                    f"with no rate column following it."
                )
            rate_col = cols[i + 1]
            if is_date_column(rate_col):
                raise RateDeckError(
                    f"per_index_dates layout: date column {date_col!r} is followed by another "
                    f"date column {rate_col!r}, not a rate column."
                )
            if wanted is not None and rate_col not in wanted:
                continue
            key = _deck_key(str(rate_col))
            if key in curves:
                raise RateDeckError(
                    f"Duplicate index {key!r}: more than one date/rate pair resolves "
                    f"to it. Columns: {cols}"
                )
            curves[key] = RateIndex.from_frame(df, date_col, rate_col, name=key)

        if columns:
            for canon, file_col in columns.items():
                if file_col not in cols:
                    raise RateDeckError(
                        f"Rate column {file_col!r} not present in file. "
                        f"Columns: {cols}"
                    )
                if _deck_key(canon) not in curves:
                    raise RateDeckError(
                        f"Rate column {file_col!r} has no date column bound to it."
                    )

        return cls(indexes=curves, name=name)

    def __repr__(self) -> str:
        if not self.indexes:
            return f"RateDeck(empty, name={self.name!r})"
        curves = ", ".join(f"{k}({len(v)})" for k, v in sorted(self.indexes.items()))
        return f"RateDeck({curves}, name={self.name!r})"
