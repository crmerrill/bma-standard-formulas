"""Tests for CRT sample tape mapping into engine Loan schema."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from bma_standard_formulas.engine import (
    CRT_FILE_LAYOUT_COLUMN_MAP,
    read_loan_tape,
    run_scheduled_portfolio,
)


def _crt_fixture_path() -> Path:
    return Path(__file__).parent / "fixtures" / "sample_crt_tape.csv"


def test_crt_map_has_required_keys() -> None:
    """CRT adapter map should cover the non-canonical sample header fields."""
    required = {
        "int",
        "loan",
        "month",
        "odate",
        "current_interest_rate",
        "remaining_legal_term",
        "remaing_term",
    }
    assert required.issubset(set(CRT_FILE_LAYOUT_COLUMN_MAP))


def test_crt_fixture_ingests_with_adapter() -> None:
    """CRT sample rows should parse into canonical Loan objects."""
    df = pd.read_csv(_crt_fixture_path(), nrows=25)
    loans = read_loan_tape(df, column_map=CRT_FILE_LAYOUT_COLUMN_MAP)

    assert len(loans) == 25
    first = loans[0]
    assert first.loan_id == 99539880
    assert first.group_id == 0
    assert first.asof_date == np.datetime64("2024-09-01", "D")
    assert first.origination_date == np.datetime64("2020-03-01", "D")
    assert first.rate_margin == 4.25
    assert first.remaining_term == 307


def test_crt_fixture_runs_scheduled_portfolio() -> None:
    """CRT-adapted loans should run through scheduled portfolio engine path."""
    df = pd.read_csv(_crt_fixture_path(), nrows=20)
    loans = read_loan_tape(df, column_map=CRT_FILE_LAYOUT_COLUMN_MAP)
    portfolio = run_scheduled_portfolio(loans)
    scheduled_df = portfolio.scheduled.to_dataframe()
    assert not scheduled_df.empty
    assert float(scheduled_df["beginning_balance"].max()) > 0.0
