# Requires Python 3.12+
from __future__ import annotations

"""
Interest rate index time series for floating-rate loan cashflow modeling.

RateIndex encapsulates a dated time series of interest rates (e.g. SOFR, LIBOR,
Treasury yields) and provides methods to extract rate vectors for amortization
models.  It supports loading from FRED, CSV files, or in-memory arrays.

The output of RateIndex.get_rate_vector() feeds into run_bma_scheduled_cashflow's
``index`` parameter for floating-rate loans.

Architecture layering:
    rate_index.py    → market data sourcing (this module)
    loan.py          → Loan data model, rate conversion
    cashflows.py     → BMA C.3 leaf computation
    portfolio.py     → Tier 2: aggregation, waterfall
"""

import bisect
import calendar
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd


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
    def from_csv(
        cls,
        path: str | Path,
        date_col: str = "date",
        rate_col: str = "rate",
        name: str | None = None,
    ) -> RateIndex:
        """Load rates from a CSV file using pandas.

        Args:
            path:      Path to CSV file.
            date_col:  Column name containing dates (parsed automatically by pandas).
            rate_col:  Column name containing rate values (%).
            name:      Optional label for the index.

        Returns:
            RateIndex with dates and rates from the CSV.
        """
        df = pd.read_csv(path)
        df = df.dropna(subset=[date_col, rate_col]).sort_values(date_col)
        # format="mixed" handles varied date formats (M/D/YY, ISO, etc.) without warning
        dates = tuple(
            d.date() for d in pd.to_datetime(df[date_col], format="mixed", dayfirst=False)
        )
        # Strip optional "%" suffix from rate strings (e.g. "3.66%" → 3.66)
        raw_rates = df[rate_col].astype(str).str.rstrip("%")
        rates = tuple(float(v) for v in raw_rates)
        return cls(dates=dates, rates=rates, name=name)

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
