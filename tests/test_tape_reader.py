"""
Tests for the loan tape reader (tape.py).

Covers:
  - TapeSchema: construction, column_map override, subclassing, COLUMN_ALIASES,
    FIELD_SPECS, read(), to_dataframe()
  - Column alias resolution (COLUMN_ALIASES, custom column_map, direct field names)
  - Type conversion: dates, booleans, ints, floats, strings
  - Required field validation (missing column → TapeReadError)
  - asof_date injection (parameter overrides tape column; per-row tape column preserved)
  - origination_date derived from age/seasoning column (with UserWarning)
  - Row-level error collection (all errors in one TapeReadError, not just the first)
  - Empty tape → empty list
  - DataFrame passthrough (pass pre-loaded DataFrame, not a path)
  - loans_to_dataframe: round-trip fidelity and empty input
  - Non-standard column names via column_map override
  - Optional fields default correctly when absent
"""

import io
import textwrap
import unittest
import warnings

import numpy as np
import pandas as pd

from bma_standard_formulas.engine import (
    Loan,
    TapeSchema,
    FieldSpec,
    TapeReadError,
    read_loan_tape,
    loans_to_dataframe,
)


# ---------------------------------------------------------------------------
# Minimal valid tape helper
# ---------------------------------------------------------------------------

def _make_minimal_df(n: int = 2, **overrides) -> pd.DataFrame:
    """Return a minimal valid DataFrame with n loans, using canonical column names."""
    base = {
        "loan_id":           list(range(1, n + 1)),
        "origination_date":  ["2020-01-01"] * n,
        "asof_date":         ["2024-01-01"] * n,
        "original_balance":  [1_000_000.0] * n,
        "current_balance":   [950_000.0] * n,
        "rate_margin":       [8.0] * n,
        "original_term":     [360] * n,
        "remaining_term":    [312] * n,
    }
    base.update(overrides)
    return pd.DataFrame(base)


# ---------------------------------------------------------------------------
# Basic happy-path tests
# ---------------------------------------------------------------------------

class TestReadLoanTapeBasic(unittest.TestCase):

    def test_minimal_dataframe(self):
        """Minimal tape with canonical column names produces correct Loans."""
        df = _make_minimal_df(n=3)
        loans = read_loan_tape(df)
        self.assertEqual(len(loans), 3)
        self.assertIsInstance(loans[0], Loan)
        self.assertEqual(loans[0].loan_id, 1)
        self.assertAlmostEqual(loans[1].original_balance, 1_000_000.0)
        self.assertAlmostEqual(loans[2].rate_margin, 8.0)

    def test_single_loan(self):
        df = _make_minimal_df(n=1)
        loans = read_loan_tape(df)
        self.assertEqual(len(loans), 1)
        self.assertEqual(loans[0].original_term, 360)
        self.assertEqual(loans[0].remaining_term, 312)

    def test_empty_dataframe(self):
        df = _make_minimal_df(n=0)
        loans = read_loan_tape(df)
        self.assertEqual(loans, [])

    def test_empty_dataframe_no_columns(self):
        loans = read_loan_tape(pd.DataFrame())
        self.assertEqual(loans, [])

    def test_returns_list_of_loan(self):
        df = _make_minimal_df(n=2)
        loans = read_loan_tape(df)
        for loan in loans:
            self.assertIsInstance(loan, Loan)


# ---------------------------------------------------------------------------
# Column alias resolution
# ---------------------------------------------------------------------------

class TestColumnAliasResolution(unittest.TestCase):

    def test_tape_columns_aliases(self):
        """Recognized TAPE_COLUMNS aliases map to correct Loan fields."""
        df = pd.DataFrame({
            "loanid":         [42],
            "note_date":      ["2019-06-01"],
            "cutoff_date":    ["2024-01-01"],
            "orig_upb":       [500_000.0],
            "upb":            [480_000.0],
            "coupon_rate":    [7.5],
            "orig_term":      [360],
            "rem_term":       [300],
        })
        loans = read_loan_tape(df)
        self.assertEqual(loans[0].loan_id, 42)
        self.assertEqual(loans[0].original_term, 360)
        self.assertEqual(loans[0].remaining_term, 300)
        self.assertAlmostEqual(loans[0].rate_margin, 7.5)

    def test_case_insensitive_columns(self):
        """Column names are matched case-insensitively."""
        df = pd.DataFrame({
            "Loan_ID":           [1],
            "Origination_Date":  ["2020-01-01"],
            "AsOf_Date":         ["2024-01-01"],
            "Original_Balance":  [1_000_000.0],
            "Current_Balance":   [900_000.0],
            "Rate_Margin":       [6.5],
            "Original_Term":     [360],
            "Remaining_Term":    [300],
        })
        loans = read_loan_tape(df)
        self.assertEqual(loans[0].loan_id, 1)
        self.assertAlmostEqual(loans[0].rate_margin, 6.5)

    def test_custom_column_map_override(self):
        """column_map takes priority over TAPE_COLUMNS."""
        df = pd.DataFrame({
            "GrossWAC":    [9.0],
            "LoanBal":     [750_000.0],
            "loan_id":     [5],
            "origination_date": ["2018-03-01"],
            "asof_date":   ["2024-01-01"],
            "original_balance": [800_000.0],
            "original_term":    [360],
            "remaining_term":   [240],
        })
        loans = read_loan_tape(df, column_map={"GrossWAC": "rate_margin", "LoanBal": "current_balance"})
        self.assertAlmostEqual(loans[0].rate_margin, 9.0)
        self.assertAlmostEqual(loans[0].current_balance, 750_000.0)

    def test_unrecognized_columns_ignored(self):
        """Columns not in TAPE_COLUMNS and not Loan fields are silently ignored."""
        df = _make_minimal_df(n=1)
        df["FICO_score"] = 740
        df["LTV"] = 80.0
        df["state"] = "CA"
        loans = read_loan_tape(df)
        self.assertEqual(len(loans), 1)


# ---------------------------------------------------------------------------
# Type conversion
# ---------------------------------------------------------------------------

class TestTypeConversion(unittest.TestCase):

    def test_date_string_iso(self):
        df = _make_minimal_df(n=1)
        loans = read_loan_tape(df)
        self.assertIsInstance(loans[0].origination_date, np.datetime64)
        self.assertEqual(loans[0].origination_date, np.datetime64("2020-01-01", "D"))

    def test_date_from_pandas_timestamp(self):
        df = _make_minimal_df(n=1)
        df["origination_date"] = pd.to_datetime(df["origination_date"])
        loans = read_loan_tape(df)
        self.assertIsInstance(loans[0].origination_date, np.datetime64)

    def test_bool_string_true_variants(self):
        for truthy in ("true", "True", "TRUE", "yes", "YES", "1", "y"):
            df = _make_minimal_df(n=1, pi_advanced=[truthy])
            loans = read_loan_tape(df)
            self.assertTrue(loans[0].pi_advanced, msg=f"Expected True for {truthy!r}")

    def test_bool_string_false_variants(self):
        for falsy in ("false", "False", "FALSE", "no", "NO", "0", "n"):
            df = _make_minimal_df(n=1, pi_advanced=[falsy])
            loans = read_loan_tape(df)
            self.assertFalse(loans[0].pi_advanced, msg=f"Expected False for {falsy!r}")

    def test_bool_numeric(self):
        df = _make_minimal_df(n=1, pi_advanced=[0])
        loans = read_loan_tape(df)
        self.assertFalse(loans[0].pi_advanced)

    def test_int_fields(self):
        df = _make_minimal_df(n=1, advance_months=[4], reset_frequency=[12])
        loans = read_loan_tape(df)
        self.assertEqual(loans[0].advance_months, 4)
        self.assertEqual(loans[0].reset_frequency, 12)

    def test_float_as_string(self):
        """Rate passed as a string in the CSV should parse correctly."""
        df = _make_minimal_df(n=1)
        df["rate_margin"] = ["8.125"]
        loans = read_loan_tape(df)
        self.assertAlmostEqual(loans[0].rate_margin, 8.125)

    def test_optional_string_field(self):
        df = _make_minimal_df(n=1, index_type=["SOFR"])
        loans = read_loan_tape(df)
        self.assertEqual(loans[0].index_type, "SOFR")


# ---------------------------------------------------------------------------
# Optional fields and defaults
# ---------------------------------------------------------------------------

class TestOptionalFieldDefaults(unittest.TestCase):

    def test_servicing_fee_defaults_to_zero(self):
        df = _make_minimal_df(n=1)
        loans = read_loan_tape(df)
        self.assertAlmostEqual(loans[0].servicing_fee, 0.0)

    def test_pi_advanced_defaults_to_true(self):
        df = _make_minimal_df(n=1)
        loans = read_loan_tape(df)
        self.assertTrue(loans[0].pi_advanced)

    def test_advance_months_defaults_to_minus_one(self):
        df = _make_minimal_df(n=1)
        loans = read_loan_tape(df)
        self.assertEqual(loans[0].advance_months, -1)

    def test_optional_dates_default_to_none(self):
        df = _make_minimal_df(n=1)
        loans = read_loan_tape(df)
        self.assertIsNone(loans[0].maturity_date)
        self.assertIsNone(loans[0].first_payment_date)
        self.assertIsNone(loans[0].next_reset_date)

    def test_group_id_default_none(self):
        df = _make_minimal_df(n=1)
        loans = read_loan_tape(df)
        self.assertIsNone(loans[0].group_id)

    def test_servicing_fee_present(self):
        df = _make_minimal_df(n=1, servicing_fee=[0.25])
        loans = read_loan_tape(df)
        self.assertAlmostEqual(loans[0].servicing_fee, 0.25)


# ---------------------------------------------------------------------------
# asof_date injection
# ---------------------------------------------------------------------------

class TestAsofDateInjection(unittest.TestCase):

    def test_asof_date_injected_when_missing(self):
        """Parameter asof_date fills in when tape has no asof_date column."""
        df = _make_minimal_df(n=2)
        df = df.drop(columns=["asof_date"])
        loans = read_loan_tape(df, asof_date=np.datetime64("2024-06-01"))
        for loan in loans:
            self.assertEqual(loan.asof_date, np.datetime64("2024-06-01", "D"))

    def test_asof_date_string_accepted(self):
        df = _make_minimal_df(n=1)
        df = df.drop(columns=["asof_date"])
        loans = read_loan_tape(df, asof_date="2024-03-31")
        self.assertIsInstance(loans[0].asof_date, np.datetime64)

    def test_tape_asof_date_takes_precedence(self):
        """If tape already has asof_date, the parameter is not applied."""
        df = _make_minimal_df(n=2)
        df["asof_date"] = ["2023-06-01", "2023-09-01"]
        loans = read_loan_tape(df, asof_date="2024-01-01")
        self.assertEqual(loans[0].asof_date, np.datetime64("2023-06-01", "D"))
        self.assertEqual(loans[1].asof_date, np.datetime64("2023-09-01", "D"))


# ---------------------------------------------------------------------------
# origination_date derived from age/seasoning
# ---------------------------------------------------------------------------

class TestOriginationFromAge(unittest.TestCase):

    def test_age_column_derives_origination_date(self):
        """origination_date back-calculated from 'age' + asof_date with UserWarning."""
        df = _make_minimal_df(n=1)
        df = df.drop(columns=["origination_date"])
        df["age"] = [24]  # 24 months seasoning; asof_date = 2024-01-01
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            loans = read_loan_tape(df)
        self.assertTrue(any(issubclass(x.category, UserWarning) for x in w))
        # Expected origination: 2024-01-01 minus 24 months = 2022-01-01
        self.assertEqual(loans[0].origination_date, np.datetime64("2022-01-01", "D"))

    def test_seasoning_alias(self):
        """'seasoning' column also triggers origination_date derivation."""
        df = _make_minimal_df(n=1)
        df = df.drop(columns=["origination_date"])
        df["seasoning"] = [12]
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            loans = read_loan_tape(df)
        self.assertIsNotNone(loans[0].origination_date)

    def test_age_without_asof_raises(self):
        """Cannot derive origination_date from age if asof_date is also missing."""
        df = _make_minimal_df(n=1)
        df = df.drop(columns=["origination_date", "asof_date"])
        df["age"] = [12]
        with self.assertRaises(TapeReadError):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                read_loan_tape(df)


# ---------------------------------------------------------------------------
# Required field validation
# ---------------------------------------------------------------------------

class TestRequiredFieldValidation(unittest.TestCase):

    def _drop_and_check(self, field: str):
        df = _make_minimal_df(n=1)
        df = df.drop(columns=[field])
        with self.assertRaises(TapeReadError) as ctx:
            read_loan_tape(df)
        self.assertIn(field, str(ctx.exception))

    def test_missing_loan_id(self):
        self._drop_and_check("loan_id")

    def test_missing_origination_date(self):
        self._drop_and_check("origination_date")

    def test_missing_asof_date(self):
        # asof_date can be supplied via parameter; drop both column AND parameter
        df = _make_minimal_df(n=1)
        df = df.drop(columns=["asof_date"])
        with self.assertRaises(TapeReadError):
            read_loan_tape(df)  # no asof_date parameter either

    def test_missing_original_balance(self):
        self._drop_and_check("original_balance")

    def test_missing_rate_margin(self):
        self._drop_and_check("rate_margin")

    def test_missing_original_term(self):
        self._drop_and_check("original_term")

    def test_missing_remaining_term(self):
        self._drop_and_check("remaining_term")


# ---------------------------------------------------------------------------
# Row-level error collection
# ---------------------------------------------------------------------------

class TestRowLevelErrors(unittest.TestCase):

    def test_bad_date_raises_tape_read_error(self):
        df = _make_minimal_df(n=1)
        df["origination_date"] = ["not-a-date"]
        with self.assertRaises(TapeReadError):
            read_loan_tape(df)

    def test_all_row_errors_collected(self):
        """All bad rows reported in one TapeReadError, not just the first."""
        df = _make_minimal_df(n=5)
        df.loc[0, "rate_margin"] = "bad"
        df.loc[2, "original_balance"] = "bad"
        df.loc[4, "original_term"] = "bad"
        with self.assertRaises(TapeReadError) as ctx:
            read_loan_tape(df)
        msg = str(ctx.exception)
        # Should report 3 row errors
        self.assertIn("3 row(s)", msg)

    def test_error_message_shows_row_index(self):
        df = _make_minimal_df(n=3)
        df.loc[1, "rate_margin"] = "bad"
        with self.assertRaises(TapeReadError) as ctx:
            read_loan_tape(df)
        self.assertIn("Row 1", str(ctx.exception))

    def test_invalid_bool_raises(self):
        df = _make_minimal_df(n=1, pi_advanced=["maybe"])
        with self.assertRaises(TapeReadError):
            read_loan_tape(df)

    def test_remaining_term_exceeds_original_term(self):
        """Loan.__post_init__ raises ValueError for invalid terms → caught as row error."""
        df = _make_minimal_df(n=1, remaining_term=[400])  # > original_term=360
        with self.assertRaises(TapeReadError):
            read_loan_tape(df)


# ---------------------------------------------------------------------------
# CSV path loading
# ---------------------------------------------------------------------------

class TestCSVPath(unittest.TestCase):

    def test_csv_string_content(self):
        """Build a minimal CSV in-memory and read via StringIO-backed DataFrame."""
        csv_text = textwrap.dedent("""\
            loan_id,origination_date,asof_date,original_balance,current_balance,rate_margin,original_term,remaining_term
            1,2020-01-01,2024-01-01,500000,480000,7.5,360,312
            2,2019-06-01,2024-01-01,300000,290000,6.0,180,150
        """)
        df = pd.read_csv(io.StringIO(csv_text))
        loans = read_loan_tape(df)
        self.assertEqual(len(loans), 2)
        self.assertAlmostEqual(loans[0].rate_margin, 7.5)
        self.assertEqual(loans[1].original_term, 180)


# ---------------------------------------------------------------------------
# loans_to_dataframe
# ---------------------------------------------------------------------------

class TestLoansToDataframe(unittest.TestCase):

    def test_empty_list(self):
        df = loans_to_dataframe([])
        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(len(df), 0)
        # Should still have all Loan field column names
        from dataclasses import fields as dc_fields
        expected_cols = {f.name for f in dc_fields(Loan)}
        self.assertEqual(set(df.columns), expected_cols)

    def test_round_trip_canonical_fields(self):
        """read_loan_tape → loans_to_dataframe preserves numeric fields."""
        df_in = _make_minimal_df(n=3)
        loans = read_loan_tape(df_in)
        df_out = loans_to_dataframe(loans)
        self.assertEqual(len(df_out), 3)
        for i, loan in enumerate(loans):
            self.assertEqual(df_out.iloc[i]["loan_id"], loan.loan_id)
            self.assertAlmostEqual(df_out.iloc[i]["rate_margin"], loan.rate_margin)
            self.assertAlmostEqual(df_out.iloc[i]["current_balance"], loan.current_balance)

    def test_round_trip_dates(self):
        """Date fields survive the round-trip as pandas-compatible types."""
        df_in = _make_minimal_df(n=1)
        loans = read_loan_tape(df_in)
        df_out = loans_to_dataframe(loans)
        # Should be a pandas Timestamp or datetime-compatible, not raw np.datetime64
        self.assertIsNotNone(df_out.iloc[0]["origination_date"])

    def test_optional_none_fields_present(self):
        """Optional None fields still appear as columns in the output."""
        df_in = _make_minimal_df(n=1)
        loans = read_loan_tape(df_in)
        df_out = loans_to_dataframe(loans)
        self.assertIn("maturity_date", df_out.columns)
        self.assertIn("index_type", df_out.columns)

    def test_column_names_are_canonical(self):
        """Output DataFrame uses canonical Loan field names."""
        from dataclasses import fields as dc_fields
        df_in = _make_minimal_df(n=2)
        loans = read_loan_tape(df_in)
        df_out = loans_to_dataframe(loans)
        expected = {f.name for f in dc_fields(Loan)}
        self.assertEqual(set(df_out.columns), expected)


# ---------------------------------------------------------------------------
# TapeSchema class
# ---------------------------------------------------------------------------

class TestTapeSchema(unittest.TestCase):

    def test_default_construction(self):
        schema = TapeSchema()
        self.assertIsInstance(schema, TapeSchema)

    def test_column_map_override(self):
        """Constructor merges user aliases with COLUMN_ALIASES."""
        schema = TapeSchema({"GrossWAC": "rate_margin"})
        # Normalized "grosswac" should be in the resolved column_map
        self.assertIn("grosswac", schema.column_map)
        self.assertEqual(schema.column_map["grosswac"], "rate_margin")

    def test_column_map_case_insensitive(self):
        """Alias keys in column_map are normalized before storage."""
        schema = TapeSchema({"Gross WAC": "rate_margin"})
        self.assertIn("gross_wac", schema.column_map)

    def test_column_map_takes_priority_over_class_aliases(self):
        """User override wins over COLUMN_ALIASES for the same normalized key."""
        schema = TapeSchema({"note_rate": "accrued_interest"})  # unusual but valid
        self.assertEqual(schema.column_map["note_rate"], "accrued_interest")

    def test_schema_read_returns_loans(self):
        df = _make_minimal_df(n=2)
        schema = TapeSchema()
        loans = schema.read(df)
        self.assertEqual(len(loans), 2)
        self.assertIsInstance(loans[0], Loan)

    def test_schema_read_with_custom_alias(self):
        df = _make_minimal_df(n=1)
        df = df.rename(columns={"rate_margin": "GrossWAC"})
        schema = TapeSchema({"GrossWAC": "rate_margin"})
        loans = schema.read(df)
        self.assertAlmostEqual(loans[0].rate_margin, 8.0)

    def test_to_dataframe_static(self):
        """to_dataframe works as a static method on the class."""
        df_in = _make_minimal_df(n=2)
        loans = TapeSchema().read(df_in)
        df_out = TapeSchema.to_dataframe(loans)
        self.assertEqual(len(df_out), 2)

    def test_to_dataframe_instance(self):
        """to_dataframe also works on an instance."""
        df_in = _make_minimal_df(n=1)
        schema = TapeSchema()
        loans = schema.read(df_in)
        df_out = schema.to_dataframe(loans)
        self.assertEqual(len(df_out), 1)

    def test_subclassing_override_aliases(self):
        """Subclass can extend COLUMN_ALIASES without affecting the parent."""
        class MySchema(TapeSchema):
            COLUMN_ALIASES = {**TapeSchema.COLUMN_ALIASES, "wac": "rate_margin"}

        df = _make_minimal_df(n=1)
        df = df.rename(columns={"rate_margin": "wac"})
        loans = MySchema().read(df)
        self.assertAlmostEqual(loans[0].rate_margin, 8.0)
        # Parent schema should NOT know about "wac"
        self.assertNotIn("wac", TapeSchema.COLUMN_ALIASES)

    def test_column_aliases_is_dict(self):
        self.assertIsInstance(TapeSchema.COLUMN_ALIASES, dict)

    def test_column_aliases_values_are_loan_fields(self):
        """Every value in COLUMN_ALIASES must be a canonical Loan field name."""
        from dataclasses import fields as dc_fields
        loan_fields = {f.name for f in dc_fields(Loan)}
        for alias, canonical in TapeSchema.COLUMN_ALIASES.items():
            self.assertIn(
                canonical, loan_fields,
                msg=f"COLUMN_ALIASES[{alias!r}] = {canonical!r} is not a Loan field",
            )

    def test_common_aliases_present(self):
        self.assertIn("upb", TapeSchema.COLUMN_ALIASES)
        self.assertIn("note_rate", TapeSchema.COLUMN_ALIASES)
        self.assertIn("orig_term", TapeSchema.COLUMN_ALIASES)
        self.assertIn("rem_term", TapeSchema.COLUMN_ALIASES)
        self.assertIn("loanid", TapeSchema.COLUMN_ALIASES)

    def test_field_specs_is_tuple_of_field_spec(self):
        self.assertIsInstance(TapeSchema.FIELD_SPECS, tuple)
        for spec in TapeSchema.FIELD_SPECS:
            self.assertIsInstance(spec, FieldSpec)

    def test_field_spec_required_fields(self):
        required = {spec.name for spec in TapeSchema.FIELD_SPECS if spec.required}
        expected = {
            "loan_id", "origination_date", "asof_date",
            "original_balance", "current_balance",
            "rate_margin", "original_term", "remaining_term",
        }
        self.assertEqual(required, expected)

    def test_field_spec_names_match_loan_fields(self):
        """Every FieldSpec name must be a real Loan field."""
        from dataclasses import fields as dc_fields
        loan_fields = {f.name for f in dc_fields(Loan)}
        for spec in TapeSchema.FIELD_SPECS:
            self.assertIn(
                spec.name, loan_fields,
                msg=f"FieldSpec name {spec.name!r} is not a Loan field",
            )

    def test_field_spec_covers_all_loan_fields(self):
        """FIELD_SPECS should cover every field on the Loan dataclass."""
        from dataclasses import fields as dc_fields
        spec_names = {spec.name for spec in TapeSchema.FIELD_SPECS}
        loan_fields = {f.name for f in dc_fields(Loan)}
        self.assertEqual(spec_names, loan_fields)


if __name__ == "__main__":
    unittest.main()