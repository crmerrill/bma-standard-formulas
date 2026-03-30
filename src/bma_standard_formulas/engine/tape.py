# Requires Python 3.12+
# Uses native type hints: list[x], dict[x], X | None (PEP 585, PEP 604)
from __future__ import annotations

"""
Loan tape reader: CSV or DataFrame → list[Loan].

A "loan tape" (or collateral tape) is a flat file — typically CSV or Excel —
containing one row per mortgage loan with columns for balance, rate, term, and
other loan-level attributes.

The primary entry point is TapeSchema, which encapsulates the column alias map
and per-field parsing rules in a single inspectable, subclassable object::

    schema = TapeSchema()
    loans  = schema.read("tape.csv", asof_date="2024-01-01")

    # Custom column aliases for a non-standard tape
    schema = TapeSchema({"GrossWAC": "rate_margin", "LoanBal": "current_balance"})

    # Or subclass to fully override the schema for your data source
    class AgencySchema(TapeSchema):
        COLUMN_ALIASES = {**TapeSchema.COLUMN_ALIASES, "pool_wac": "rate_margin"}

The module-level read_loan_tape() and loans_to_dataframe() functions are
convenience wrappers around TapeSchema for common use cases.

Column name resolution
----------------------
Column names are matched case-insensitively after stripping whitespace and
normalizing separators (spaces, hyphens, dots → underscores).  Standard aliases
are resolved via TapeSchema.COLUMN_ALIASES.  Columns not recognized by any
mapping are silently ignored — loan tapes routinely contain collateral fields
(LTV, FICO, state, property type) that the Loan dataclass doesn't use.

Rate convention
---------------
Rates in the tape should be in PERCENT (e.g. 8.0 for 8%), matching the market
convention stored in Loan.  The cashflow runners convert to decimal internally.

Ref: BMA SF-4 (scheduled payment), SF-18 (C.3 cash flow variables).
"""

import warnings
import re
from dataclasses import dataclass, fields as dc_fields
from pathlib import Path
from typing import Any, ClassVar, Literal

import numpy as np
import pandas as pd

from .loan import Loan


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TapeReadError(ValueError):
    """Raised when one or more rows in a loan tape cannot be parsed.

    The message lists all row-level errors found in a single pass so the caller
    can fix them together.  The first five errors are shown inline; additional
    errors are summarised by count.
    """


# ---------------------------------------------------------------------------
# Column name normalization
# ---------------------------------------------------------------------------


def _normalize_col(name: str) -> str:
    """Normalize a column label to lowercase snake_case for alias lookup.

    Strips leading/trailing whitespace, converts to lowercase, and replaces
    spaces, hyphens, and dots with underscores.  This is a module-level utility
    used by TapeSchema internally.

    Examples::

        "Note Rate"  → "note_rate"
        "orig-bal"   → "orig_bal"
        "LOAN.ID"    → "loan_id"
    """
    return name.strip().lower().replace(" ", "_").replace("-", "_").replace(".", "_")


# ---------------------------------------------------------------------------
# Field specification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    """Parsing specification for one Loan field in a tape.

    Instances live in TapeSchema.FIELD_SPECS.  They drive type conversion in
    TapeSchema._parse_row and can be inspected to understand the schema contract.

    Attributes:
        name:     Canonical Loan field name (must match a field on the Loan
                  dataclass exactly).
        kind:     Value type used for parsing.  One of "date", "bool", "int",
                  "float", or "str".
        required: If True, a missing or null value raises TapeReadError.
                  Required fields have no Loan default that could compensate.
        default:  Fallback value when the column is absent or null and the
                  field is not required.  None means omit the keyword argument
                  entirely and let Loan's own dataclass default apply.

    Ref: BMA SF-18 (C.3 variable list).
    """

    name: str
    kind: Literal["date", "bool", "int", "float", "str"]
    required: bool = False
    default: Any = None


# ---------------------------------------------------------------------------
# TapeSchema
# ---------------------------------------------------------------------------


class TapeSchema:
    """Schema for reading a loan tape: column aliases and field parsing rules.

    Two class-level attributes define the full contract:

    ``COLUMN_ALIASES``
        Maps common tape column names (normalized to lowercase snake_case) to
        canonical Loan field names.  Covers ~50 aliases used across agency and
        non-agency MBS tapes.  Override by subclassing or by passing
        ``column_map`` to the constructor.

    ``FIELD_SPECS``
        A tuple of FieldSpec objects — one per Loan field — specifying the
        value type ("date", "bool", "int", "float", "str"), whether the field
        is required, and the fallback default when absent or null.

    Both attributes are intentionally public: inspect them to understand the
    schema contract, and override them by subclassing for non-standard formats.

    Usage::

        # Default schema — covers standard tape column names
        schema = TapeSchema()
        loans = schema.read("tape.csv", asof_date="2024-01-01")

        # Extend with custom aliases for this tape
        schema = TapeSchema({"GrossWAC": "rate_margin"})

        # Subclass to fully replace the alias map for a proprietary data source
        class AgencySchema(TapeSchema):
            COLUMN_ALIASES = {**TapeSchema.COLUMN_ALIASES, "pool_wac": "rate_margin"}
    """

    # ------------------------------------------------------------------
    # Column alias map (class attribute — inspectable, overridable)
    # ------------------------------------------------------------------

    #: Maps normalized tape column names to canonical Loan field names.
    #: Keys are lowercase with underscores (normalized form of the alias).
    #: Values are exact field names on the Loan dataclass.
    COLUMN_ALIASES: ClassVar[dict[str, str]] = {
        # ── loan_id ─────────────────────────────────────────────────────────
        "loanid":               "loan_id",
        "loan_number":          "loan_id",
        "loan_num":             "loan_id",
        "loan_no":              "loan_id",
        "loan":                 "loan_id",
        "loan_identifier":      "loan_id",
        # ── origination_date ─────────────────────────────────────────────────
        "orig_date":            "origination_date",
        "origdate":             "origination_date",
        "origin_date":          "origination_date",
        "note_date":            "origination_date",
        "close_date":           "origination_date",
        "closing_date":         "origination_date",
        "odate":                "origination_date",
        # ── asof_date ────────────────────────────────────────────────────────
        "as_of_date":           "asof_date",
        "asofdate":             "asof_date",
        "report_date":          "asof_date",
        "reporting_date":       "asof_date",
        "cutoff_date":          "asof_date",
        "cut_off_date":         "asof_date",
        "settlement_date":      "asof_date",
        "month":                "asof_date",
        "monthly_reporting_period": "asof_date",
        # ── original_balance ─────────────────────────────────────────────────
        "orig_balance":         "original_balance",
        "orig_bal":             "original_balance",
        "original_bal":         "original_balance",
        "original_upb":         "original_balance",
        "orig_upb":             "original_balance",
        "face_amount":          "original_balance",
        "face_value":           "original_balance",
        "loan_amount":          "original_balance",
        # ── current_balance ──────────────────────────────────────────────────
        "curr_balance":         "current_balance",
        "curr_bal":             "current_balance",
        "current_bal":          "current_balance",
        "current_upb":          "current_balance",
        "curr_upb":             "current_balance",
        "upb":                  "current_balance",
        "balance":              "current_balance",
        "outstanding_balance":  "current_balance",
        "outstanding_upb":      "current_balance",
        # ── rate_margin ──────────────────────────────────────────────────────
        # Fixed-rate: full coupon.  Floating-rate: spread over the index.
        "coupon":               "rate_margin",
        "coupon_rate":          "rate_margin",
        "note_rate":            "rate_margin",
        "gross_rate":           "rate_margin",
        "interest_rate":        "rate_margin",
        "gross_coupon":         "rate_margin",
        "margin":               "rate_margin",
        "rate":                 "rate_margin",
        "current_interest_rate": "rate_margin",
        "original_interest_rate": "rate_margin",
        "mortgage_margin":      "rate_margin",
        # ── original_term ────────────────────────────────────────────────────
        "orig_term":            "original_term",
        "loan_term":            "original_term",
        "term":                 "original_term",
        "amortization_term":    "original_term",
        "amort_term":           "original_term",
        # ── remaining_term ───────────────────────────────────────────────────
        "rem_term":             "remaining_term",
        "months_remaining":     "remaining_term",
        "remaining_months":     "remaining_term",
        "months_to_maturity":   "remaining_term",
        "remaining_legal_term": "remaining_term",
        "remaining_months_to_legal_maturity": "remaining_term",
        "remaing_term":         "remaining_term",
        # ── servicing_fee ────────────────────────────────────────────────────
        "svc_fee":              "servicing_fee",
        "servicing_spread":     "servicing_fee",
        "servicing_rate":       "servicing_fee",
        "service_fee":          "servicing_fee",
        # ── group_id ─────────────────────────────────────────────────────────
        "groupid":              "group_id",
        "pool_id":              "group_id",
        "poolid":               "group_id",
        "group":                "group_id",
        "int":                  "group_id",
        "reference_pool_id":    "group_id",
        # ── accrued_interest ─────────────────────────────────────────────────
        "accrued_int":          "accrued_interest",
        "ai":                   "accrued_interest",
        # ── optional date fields ─────────────────────────────────────────────
        "maturity":             "maturity_date",
        "mat_date":             "maturity_date",
        "final_maturity":       "maturity_date",
        "first_pay_date":       "first_payment_date",
        "first_payment":        "first_payment_date",
        "fpd":                  "first_payment_date",
        "next_pay_date":        "next_payment_date",
        "npd":                  "next_payment_date",
        "last_pay_date":        "last_payment_date",
        "lpd":                  "last_payment_date",
        "paid_thru_date":       "last_payment_date",
        "last_paid_installment_date": "last_payment_date",
        # ── ARM / floating-rate fields ───────────────────────────────────────
        "index":                "index_type",
        "rate_index":           "index_type",
        "arm_index":            "index_type",
        "floating_index":       "index_type",
        "reset_freq":           "reset_frequency",
        "arm_reset_freq":       "reset_frequency",
        "adjustment_frequency": "reset_frequency",
        "interest_rate_adjustment_frequency": "reset_frequency",
        "next_reset":           "next_reset_date",
        "arm_reset_date":       "next_reset_date",
        "reset_date":           "next_reset_date",
        "next_adjustment_date": "next_reset_date",
        "next_interest_rate_adjustment_date": "next_reset_date",
        "per_cap":              "periodic_cap",
        "rate_cap_periodic":    "periodic_cap",
        "adjustment_cap":       "periodic_cap",
        "arm_cap":              "periodic_cap",
        "periodic_interest_rate_cap_up_percent": "periodic_cap",
        "per_floor":            "periodic_floor",
        "adjustment_floor":     "periodic_floor",
        "life_cap":             "rate_cap",
        "ceiling_rate":         "rate_cap",
        "max_rate":             "rate_cap",
        "rate_ceiling":         "rate_cap",
        "lifetime_interest_rate_cap_up_percent": "rate_cap",
        "life_floor":           "rate_floor",
        "floor_rate":           "rate_floor",
        "min_rate":             "rate_floor",
        # ── servicer advance behavior ─────────────────────────────────────────
        "advancing":            "pi_advanced",
        "servicer_advancing":   "pi_advanced",
        "advance":              "pi_advanced",
        "advancing_months":     "advance_months",
        # ── days_past_due ─────────────────────────────────────────────────────
        "dpd":                      "days_past_due",
        "days_delinquent":          "days_past_due",
        "months_delinquent":        "days_past_due",
        "dqstatus":                 "days_past_due",
        # ── loan_status ───────────────────────────────────────────────────────
        "performance_status":       "loan_status",
        "dlq_status":               "loan_status",
    }

    # ------------------------------------------------------------------
    # Field specs (class attribute — inspectable, overridable)
    # ------------------------------------------------------------------

    #: One FieldSpec per Loan field: value type, required flag, and default.
    #: Required fields appear first, then optional fields with explicit defaults,
    #: then optional fields that default to None (omitted from kwargs).
    FIELD_SPECS: ClassVar[tuple[FieldSpec, ...]] = (
        # ── Required ─────────────────────────────────────────────────────────
        FieldSpec("loan_id",           "int",   required=True),
        FieldSpec("origination_date",  "date",  required=True),
        FieldSpec("asof_date",         "date",  required=True),
        FieldSpec("original_balance",  "float", required=True),
        FieldSpec("current_balance",   "float", required=True),
        FieldSpec("rate_margin",       "float", required=True),
        FieldSpec("original_term",     "int",   required=True),
        FieldSpec("remaining_term",    "int",   required=True),
        # ── Optional with explicit non-None defaults ──────────────────────────
        FieldSpec("servicing_fee",     "float", default=0.0),
        FieldSpec("accrued_interest",  "float", default=0.0),
        FieldSpec("pi_advanced",       "bool",  default=True),
        FieldSpec("advance_months",    "int",   default=-1),
        FieldSpec("reset_frequency",   "int",   default=0),
        # ── Optional, nullable (default=None → omit from kwargs) ─────────────
        FieldSpec("group_id",             "group_id"),
        FieldSpec("maturity_date",        "date"),
        FieldSpec("first_payment_date",   "date"),
        FieldSpec("next_payment_date",    "date"),
        FieldSpec("last_payment_date",    "date"),
        FieldSpec("svc_rate_default",     "float"),
        FieldSpec("svc_rate_foreclosure", "float"),
        FieldSpec("index_type",           "str"),
        FieldSpec("next_reset_date",      "date"),
        FieldSpec("periodic_cap",         "float"),
        FieldSpec("periodic_floor",       "float"),
        FieldSpec("rate_cap",             "float"),
        FieldSpec("rate_floor",           "float"),
        # ── Delinquency / performance status ──────────────────────────────
        FieldSpec("days_past_due",        "int",   default=0),
        FieldSpec("loan_status",          "str",   default="current"),
    )

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(self, column_map: dict[str, str] | None = None) -> None:
        """Create a schema, optionally extending or overriding column aliases.

        Args:
            column_map: Additional aliases or overrides, e.g.
                        ``{"GrossWAC": "rate_margin"}``.  Keys are normalized
                        (case-insensitive, spaces/hyphens → underscores) before
                        lookup.  Takes priority over COLUMN_ALIASES for any
                        conflicting key.
        """
        self.column_map: dict[str, str] = dict(self.COLUMN_ALIASES)
        if column_map:
            self.column_map.update(
                {_normalize_col(alias): canonical for alias, canonical in column_map.items()}
            )

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def read(
        self,
        source: str | Path | pd.DataFrame,
        asof_date: str | np.datetime64 | None = None,
    ) -> list[Loan]:
        """Read a loan tape CSV or DataFrame into a list of Loan objects.

        Args:
            source:    File path (str or Path) to a CSV, or an existing
                       pandas DataFrame.  Excel files should be loaded with
                       ``pd.read_excel`` and passed as a DataFrame.
            asof_date: Portfolio-level as-of date.  Applied to every row when
                       the tape has no ``asof_date`` column.  Ignored if the
                       tape already has per-row as-of dates.

        Returns:
            list[Loan] in the same row order as the input tape.

        Raises:
            TapeReadError: If required columns are absent from the tape, or if
                           one or more rows contain unparseable values.  All row
                           errors are collected into a single exception message.
            FileNotFoundError: If ``source`` is a path that does not exist.

        Examples::

            schema = TapeSchema()
            loans = schema.read("tape.csv", asof_date="2024-01-01")

            # Pre-loaded Excel sheet
            df = pd.read_excel("tape.xlsx", sheet_name="Collateral")
            loans = schema.read(df, asof_date="2024-01-01")
        """
        # ── Step 1: Load ─────────────────────────────────────────────────────
        df = source.copy() if isinstance(source, pd.DataFrame) else pd.read_csv(source)

        if df.empty:
            return []

        # ── Step 2: Resolve column aliases ───────────────────────────────────
        df = df.rename(columns=self._resolve_columns(list(df.columns)))
        if df.columns.has_duplicates:
            # Multiple raw columns may intentionally map to the same canonical
            # field (for example typo + corrected variants in source files).
            # Collapse duplicate columns deterministically in left-to-right
            # order so row dict materialization remains unambiguous.
            df = df.T.groupby(level=0, sort=False).first().T

        # ── Step 3: Inject portfolio-level asof_date if column is absent ──────
        if asof_date is not None and "asof_date" not in df.columns:
            df["asof_date"] = asof_date

        # ── Step 4: Derive origination_date from age/seasoning if needed ──────
        # Many tapes report seasoning (months since origination) rather than
        # an origination date.  We check for these column names explicitly
        # because "age" is a computed Loan property, not a tape field.
        for age_alias in ("age", "seasoning", "loan_age", "months_seasoned"):
            if age_alias in df.columns and "origination_date" not in df.columns:
                if "asof_date" not in df.columns:
                    raise TapeReadError(
                        "Cannot derive origination_date from age without asof_date. "
                        "Provide asof_date as a parameter or as a tape column."
                    )
                warnings.warn(
                    f"origination_date not found; deriving from '{age_alias}' + asof_date. "
                    "This is an approximation — same calendar day is assumed each month.",
                    UserWarning,
                    stacklevel=2,
                )
                asof_ts = pd.to_datetime(df["asof_date"])
                age_months = pd.to_numeric(df[age_alias], errors="coerce").fillna(0).astype(int)
                df["origination_date"] = [
                    (asof_ts.iloc[i] - pd.DateOffset(months=int(age_months.iloc[i]))).date()
                    for i in range(len(df))
                ]
                break

        # ── Step 5: Check required columns are present ────────────────────────
        required = {spec.name for spec in self.FIELD_SPECS if spec.required}
        missing = required - set(df.columns)
        if missing:
            raise TapeReadError(
                f"Required column(s) not found in tape: {', '.join(sorted(missing))}.\n"
                f"Use column_map to remap non-standard names, or inspect "
                f"TapeSchema.COLUMN_ALIASES for supported aliases."
            )

        # ── Step 6: Parse each row ────────────────────────────────────────────
        loans: list[Loan] = []
        errors: list[str] = []
        for idx, row in enumerate(df.to_dict("records")):
            try:
                loans.append(self._parse_row(row))
            except (ValueError, TypeError) as exc:
                loan_id = row.get("loan_id", "<missing>")
                details = self._format_exception_chain(exc)
                errors.append(
                    f"  Row {idx} (loan_id={loan_id!r}): "
                    f"{type(exc).__name__}: {exc}{details}"
                )

        if errors:
            n = len(errors)
            shown = errors[:5]
            if n > 5:
                shown.append(f"  ... and {n - 5} more error(s)")
            raise TapeReadError(f"{n} row(s) could not be parsed:\n" + "\n".join(shown))

        return loans

    @staticmethod
    def to_dataframe(loans: list[Loan]) -> pd.DataFrame:
        """Convert a list of Loan objects to a pandas DataFrame.

        Each Loan becomes one row.  Date fields are stored as pandas Timestamps;
        all others as their native Python type.  This is the inverse of read()
        and is useful for inspecting, filtering, or re-exporting a loan list.

        Args:
            loans: List of Loan objects.

        Returns:
            pandas DataFrame with one row per loan and one column per Loan
            field.  Column names match the canonical Loan field names exactly.

        Examples::

            schema = TapeSchema()
            loans = schema.read("tape.csv", asof_date="2024-01-01")
            df = schema.to_dataframe(loans)
            print(df[["loan_id", "current_balance", "rate_margin"]].head())
        """
        if not loans:
            return pd.DataFrame(columns=[f.name for f in dc_fields(Loan)])
        rows = []
        for loan in loans:
            row: dict[str, Any] = {}
            for f in dc_fields(Loan):
                val = getattr(loan, f.name)
                if isinstance(val, np.datetime64):
                    val = pd.Timestamp(val)
                row[f.name] = val
            rows.append(row)
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_columns(self, df_columns: list[str]) -> dict[str, str]:
        """Map DataFrame column labels to canonical Loan field names.

        Resolution order (first match wins):
          1. This schema's column_map (merged COLUMN_ALIASES + constructor overrides).
          2. The normalized column name already equals a Loan field name verbatim.

        Unrecognized columns are omitted — loan tapes routinely carry fields
        (LTV, FICO, state) that the Loan dataclass doesn't use.
        """
        loan_field_names = frozenset(spec.name for spec in self.FIELD_SPECS)
        resolved: dict[str, str] = {}
        for col in df_columns:
            norm = _normalize_col(col)
            if norm in self.column_map:
                resolved[col] = self.column_map[norm]
            elif norm in loan_field_names:
                resolved[col] = norm
        return resolved

    def _parse_row(self, row: dict) -> Loan:
        """Parse one tape row (with canonical field names) into a Loan.

        Iterates FIELD_SPECS to type-convert each field.  Missing or null
        optional fields use their FieldSpec default (or are omitted from
        kwargs, letting Loan's own default apply).

        Raises:
            ValueError: If a required field is missing/null, or if a value
                        cannot be converted to the expected type.
        """
        kwargs: dict[str, Any] = {}
        for spec in self.FIELD_SPECS:
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
                    kwargs[spec.name] = self._parse_date(raw)
                elif spec.kind == "bool":
                    kwargs[spec.name] = self._parse_bool(raw)
                elif spec.kind == "int":
                    kwargs[spec.name] = self._parse_int_strict(raw)
                elif spec.kind == "group_id":
                    kwargs[spec.name] = self._parse_group_id(raw)
                elif spec.kind == "float":
                    kwargs[spec.name] = float(raw)
                else:
                    kwargs[spec.name] = str(raw)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"field '{spec.name}': {exc}") from exc

        return Loan(**kwargs)

    @staticmethod
    def _parse_date(val: Any) -> np.datetime64 | None:
        """Convert a date-like value to np.datetime64[D], or None if missing.

        Accepts strings, datetime objects, pandas Timestamps, numpy datetime64.
        Returns None for NaN, NaT, None, or empty strings.

        Raises:
            ValueError: If the value is non-null but cannot be parsed as a date.
        """
        if val is None:
            return None
        try:
            if pd.isna(val):
                return None
        except (TypeError, ValueError):
            pass
        try:
            ts = pd.Timestamp(val)
            if pd.isna(ts):
                return None
            return np.datetime64(ts.date(), "D")
        except Exception as exc:
            raise ValueError(f"cannot parse {val!r} as a date") from exc

    @staticmethod
    def _parse_bool(val: Any) -> bool:
        """Convert a bool-like value to Python bool.

        Accepts bool, int, float, or string representations:
        "true" / "yes" / "1" / "y"  → True
        "false" / "no"  / "0" / "n" → False

        Raises:
            ValueError: If the value cannot be interpreted as a boolean.
        """
        if isinstance(val, (bool, np.bool_)):
            return bool(val)
        if isinstance(val, (int, float)):
            return bool(val)
        s = str(val).strip().lower()
        if s in ("true", "yes", "1", "y"):
            return True
        if s in ("false", "no", "0", "n"):
            return False
        raise ValueError(f"cannot parse {val!r} as boolean (expected true/false/yes/no/1/0)")

    @staticmethod
    def _parse_int_strict(val: Any) -> int:
        """Parse integers without float coercion.

        Accepted:
          - Python / numpy integer types
          - strings matching ^[+-]?\\d+$ (after strip)

        Rejected:
          - float types (including 12.0)
          - decimal/scientific notation strings (e.g. "12.0", "1e3")
          - booleans
        """
        if isinstance(val, (bool, np.bool_)):
            raise ValueError(f"cannot parse {val!r} as integer")
        if isinstance(val, (int, np.integer)):
            return int(val)
        if isinstance(val, (float, np.floating)):
            raise ValueError(f"cannot parse {val!r} as integer")

        s = str(val).strip()
        if re.fullmatch(r"[+-]?\d+", s):
            return int(s)
        raise ValueError(f"cannot parse {val!r} as integer")

    @staticmethod
    def _parse_group_id(val: Any) -> int | str:
        """Parse group ID as int when numeric, otherwise as non-empty text.

        Real-world tapes commonly use either numeric pool IDs (e.g. 7) or text
        labels (e.g. "A", "Prime_2024Q1"). This parser preserves that intent:
        strict numeric values remain integers; non-numeric values remain strings.

        Raises:
            ValueError: If value is null/blank or boolean.
        """
        if isinstance(val, (bool, np.bool_)):
            raise ValueError(f"cannot parse {val!r} as group_id")
        try:
            if pd.isna(val):
                raise ValueError("group_id is null")
        except (TypeError, ValueError):
            pass

        if isinstance(val, (int, np.integer)):
            return int(val)
        if isinstance(val, (float, np.floating)):
            if np.isfinite(val) and float(val).is_integer():
                return int(val)
            raise ValueError(f"cannot parse {val!r} as group_id")

        s = str(val).strip()
        if not s:
            raise ValueError("group_id is blank")
        if re.fullmatch(r"[+-]?\d+", s):
            return int(s)
        return s

    @staticmethod
    def _format_exception_chain(exc: Exception) -> str:
        """Return a compact 'caused by' chain for aggregated row errors."""
        chain: list[str] = []
        current = exc.__cause__
        seen = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            chain.append(f"{type(current).__name__}: {current}")
            current = current.__cause__
        if not chain:
            return ""
        return " | caused by: " + " -> ".join(chain)


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


# Mapping for Fannie Mae CRT/SF Loan Performance sample tapes, based on
# "Single-Family Loan Performance Dataset and Credit Risk Transfer - Glossary
# and File Layout" (see docs/reference/crt_file_layout_and_glossary.md).
CRT_FILE_LAYOUT_COLUMN_MAP: dict[str, str] = {
    # ── Identity & grouping ────────────────────────────────────────────
    "int": "group_id",                          # Field 1: Reference Pool ID
    "loan": "loan_id",                          # Field 2: Loan Identifier
    # ── Dates ──────────────────────────────────────────────────────────
    "month": "asof_date",                       # Field 3: Monthly Reporting Period
    "odate": "origination_date",                # Field 14: Origination Date
    "first_payment_date": "first_payment_date", # Field 15: First Payment Date
    "maturity_date": "maturity_date",           # Field 19: Maturity Date
    "paid_thru_date": "last_payment_date",      # Field 51: Last Paid Installment Date
    # ── Rates ──────────────────────────────────────────────────────────
    "current_interest_rate": "rate_margin",     # Field 9: Current Interest Rate
    # ── Balances ───────────────────────────────────────────────────────
    "original_upb": "original_balance",         # Field 10: Original UPB
    "current_upb": "current_balance",           # Field 12: Current Actual UPB
    # ── Term ───────────────────────────────────────────────────────────
    "original_term": "original_term",           # Field 13: Original Loan Term
    "remaining_legal_term": "remaining_term",   # Field 17: Remaining Months to Legal Maturity
    "remaing_term": "remaining_term",           # Observed typo in sample header
    # ── ARM fields ─────────────────────────────────────────────────────
    "interest_rate_adjustment_frequency": "reset_frequency",  # Field 91
    "next_interest_rate_adjustment_date": "next_reset_date",  # Field 92
    "periodic_interest_rate_cap_up_percent": "periodic_cap",  # Field 97
    "lifetime_interest_rate_cap_up_percent": "rate_cap",      # Field 98
    "mortgage_margin": "rate_margin",           # Field 99: ARM Mortgage Margin
}


def read_loan_tape(
    source: str | Path | pd.DataFrame,
    asof_date: str | np.datetime64 | None = None,
    schema: TapeSchema | None = None,
    column_map: dict[str, str] | None = None,
) -> list[Loan]:
    """Read a loan tape CSV or DataFrame into a list of Loan objects.

    Thin wrapper around TapeSchema.read().  For full control — subclassing,
    custom field specs, or reusing a schema across multiple reads — construct
    a TapeSchema directly.

    Args:
        source:     File path (str or Path) to a CSV, or an existing DataFrame.
                    Excel files should be loaded with pd.read_excel and passed
                    as a DataFrame.
        asof_date:  Portfolio-level as-of date.  Applied to every row when the
                    tape has no asof_date column.
        schema:     TapeSchema instance (or subclass) to use.  When provided,
                    column_map is ignored — configure aliases on the schema
                    instead.
        column_map: Shorthand for TapeSchema(column_map).  Ignored if schema
                    is provided.  Use for a one-off alias override without
                    constructing a schema explicitly.

    Returns:
        list[Loan] in the same row order as the input tape.

    Raises:
        TapeReadError: If required columns are absent or rows have parse errors.
        FileNotFoundError: If source is a path that does not exist.

    Examples::

        # Minimal — tape has standard column names
        loans = read_loan_tape("tape.csv", asof_date="2024-01-01")

        # Non-standard column names via one-off column_map
        loans = read_loan_tape(
            "tape.csv",
            asof_date="2024-01-01",
            column_map={"GrossWAC": "rate_margin", "LoanBal": "current_balance"},
        )

        # Full control: custom schema instance
        schema = TapeSchema({"GrossWAC": "rate_margin"})
        loans = schema.read("tape.csv", asof_date="2024-01-01")

        # Pre-loaded DataFrame (e.g. from Excel)
        df = pd.read_excel("tape.xlsx", sheet_name="Collateral")
        loans = read_loan_tape(df, asof_date="2024-01-01")
    """
    if schema is None:
        schema = TapeSchema(column_map)
    return schema.read(source, asof_date)


def loans_to_dataframe(loans: list[Loan]) -> pd.DataFrame:
    """Convert a list of Loan objects to a pandas DataFrame.

    Thin wrapper around TapeSchema.to_dataframe().  Column names match
    canonical Loan field names exactly.

    Args:
        loans: List of Loan objects (from read_loan_tape or constructed manually).

    Returns:
        pandas DataFrame with one row per loan, one column per Loan field.

    Examples::

        loans = read_loan_tape("tape.csv", asof_date="2024-01-01")
        df = loans_to_dataframe(loans)
        print(df[["loan_id", "current_balance", "rate_margin"]].head())
    """
    return TapeSchema.to_dataframe(loans)
