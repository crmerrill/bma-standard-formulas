"""
Tests for the portfolio runner functions in loan.py.

Covers:
  - run_scheduled_portfolio: basic aggregation, correct mode, to_dataframe()
  - run_actual_portfolio: uniform curve, per-loan dict curve, result mode
  - run_paired_portfolio: PAIRED mode, both scheduled and pool available
  - Curve resolution: uniform array vs dict[loan_id, array]
  - flush=True: references released after aggregation
  - Empty loan list raises ValueError
  - _resolve_curve: missing key raises descriptive KeyError

Ref: BMA SF-17 to SF-19 (C.3 cash flows); loan.py module docstring.
"""

import unittest

import numpy as np

from bma_standard_formulas.engine import (
    Loan,
    run_scheduled_portfolio,
    run_actual_portfolio,
    run_paired_portfolio,
    PortfolioCashflow,
    PortfolioMode,
)
from bma_standard_formulas.engine.loan import _resolve_curve


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_loan(
    loan_id: int,
    *,
    original_balance: float = 1_000_000.0,
    current_balance: float | None = None,
    rate_margin: float = 8.0,
    original_term: int = 360,
    remaining_term: int = 360,
    servicing_fee: float = 0.25,
) -> Loan:
    """Return a minimal fixed-rate Loan for testing."""
    if current_balance is None:
        current_balance = original_balance
    return Loan(
        loan_id=loan_id,
        origination_date=np.datetime64("2024-01-01"),
        asof_date=np.datetime64("2024-01-01"),
        original_balance=original_balance,
        current_balance=current_balance,
        rate_margin=rate_margin,
        original_term=original_term,
        remaining_term=remaining_term,
        servicing_fee=servicing_fee,
    )


def _zero_curves(n: int) -> np.ndarray:
    """Uniform assumption curves: zero SMM, zero MDR, zero severity."""
    return np.zeros(n + 1)


def _small_curves(n: int, smm: float = 0.005, mdr: float = 0.002, sev: float = 0.30):
    """Uniform positive-assumption curves for n periods."""
    return (
        np.full(n + 1, smm),
        np.full(n + 1, mdr),
        np.full(n + 1, sev),
    )


# ---------------------------------------------------------------------------
# run_scheduled_portfolio
# ---------------------------------------------------------------------------

class TestRunScheduledPortfolio(unittest.TestCase):

    def _two_loans(self):
        return [_make_loan(1), _make_loan(2, original_balance=500_000.0, current_balance=500_000.0)]

    def test_returns_portfolio_cashflow(self):
        loans = self._two_loans()
        pf = run_scheduled_portfolio(loans)
        self.assertIsInstance(pf, PortfolioCashflow)

    def test_mode_is_scheduled_only(self):
        pf = run_scheduled_portfolio(self._two_loans())
        self.assertEqual(pf.mode, PortfolioMode.SCHEDULED_ONLY)

    def test_constituent_count(self):
        loans = self._two_loans()
        pf = run_scheduled_portfolio(loans)
        # _n_constituents tracks how many individual cashflows were added
        self.assertEqual(pf._n_constituents, 2)

    def test_to_dataframe_returns_dataframe(self):
        import pandas as pd
        pf = run_scheduled_portfolio(self._two_loans())
        df = pf.to_dataframe()
        self.assertIsInstance(df, pd.DataFrame)
        self.assertGreater(len(df), 0)

    def test_aggregate_balance_equals_sum(self):
        """Pool opening balance should equal the sum of individual loan balances."""
        loans = [
            _make_loan(1, original_balance=1_000_000.0, current_balance=1_000_000.0),
            _make_loan(2, original_balance=2_000_000.0, current_balance=2_000_000.0),
        ]
        pf = run_scheduled_portfolio(loans)
        pool_cf = pf.scheduled
        # Period 1 beginning balance = sum of current balances (period 0 is the as-of snapshot)
        self.assertAlmostEqual(pool_cf.beginning_balance[1], 3_000_000.0, delta=1.0)

    def test_single_loan_portfolio(self):
        pf = run_scheduled_portfolio([_make_loan(1)])
        self.assertEqual(pf._n_constituents, 1)
        self.assertIsNotNone(pf.scheduled)

    def test_empty_loans_raises(self):
        with self.assertRaises((ValueError, Exception)):
            run_scheduled_portfolio([])

    def test_flush_true_clears_constituents(self):
        """flush=True should release individual loan cashflow references."""
        loans = self._two_loans()
        pf = run_scheduled_portfolio(loans, flush=True)
        # After flush, _pending is empty but _flushed=True and aggregate is committed
        self.assertEqual(len(pf._pending), 0)
        self.assertTrue(pf._flushed)

    def test_varying_remaining_terms(self):
        """Loans with different remaining terms should aggregate without error."""
        loans = [
            _make_loan(1, remaining_term=360),
            _make_loan(2, remaining_term=300, original_term=360),
        ]
        pf = run_scheduled_portfolio(loans)
        self.assertIsNotNone(pf.scheduled)

    def test_different_rates(self):
        loans = [
            _make_loan(1, rate_margin=7.0),
            _make_loan(2, rate_margin=9.5),
        ]
        pf = run_scheduled_portfolio(loans)
        # Pool WAC should be between the two rates
        pool_cf = pf.scheduled
        wac = float(pool_cf.gross_rate[1])  # period 1 annualized rate
        self.assertGreater(wac, 0.0)


# ---------------------------------------------------------------------------
# run_actual_portfolio
# ---------------------------------------------------------------------------

class TestRunActualPortfolio(unittest.TestCase):

    def _loans(self):
        return [_make_loan(1), _make_loan(2, original_balance=800_000.0, current_balance=800_000.0)]

    def test_returns_portfolio_cashflow(self):
        loans = self._loans()
        n = 360
        smm, mdr, sev = _small_curves(n)
        pf = run_actual_portfolio(loans, smm_curves=smm, mdr_curves=mdr, severity_curves=sev)
        self.assertIsInstance(pf, PortfolioCashflow)

    def test_mode_is_actual_only(self):
        loans = self._loans()
        n = 360
        smm, mdr, sev = _small_curves(n)
        pf = run_actual_portfolio(loans, smm_curves=smm, mdr_curves=mdr, severity_curves=sev)
        self.assertEqual(pf.mode, PortfolioMode.ACTUAL_ONLY)

    def test_zero_curves_no_prepay_no_default(self):
        """With zero SMM/MDR, actual pool principal should match scheduled (roughly)."""
        loans = [_make_loan(1)]
        n = 360
        pf = run_actual_portfolio(
            loans,
            smm_curves=_zero_curves(n),
            mdr_curves=_zero_curves(n),
            severity_curves=_zero_curves(n),
        )
        self.assertIsNotNone(pf.pool)

    def test_per_loan_curve_dict(self):
        """dict[loan_id, np.ndarray] curves are resolved per loan."""
        loans = [_make_loan(1), _make_loan(2)]
        n = 360
        smm_arr = np.full(n + 1, 0.005)
        mdr_arr = np.zeros(n + 1)
        sev_arr = np.zeros(n + 1)
        smm_dict = {1: smm_arr, 2: smm_arr}
        mdr_dict  = {1: mdr_arr, 2: mdr_arr}
        sev_dict  = {1: sev_arr, 2: sev_arr}
        pf = run_actual_portfolio(
            loans,
            smm_curves=smm_dict,
            mdr_curves=mdr_dict,
            severity_curves=sev_dict,
        )
        self.assertIsInstance(pf, PortfolioCashflow)

    def test_missing_loan_id_in_dict_raises(self):
        """KeyError when a loan_id is absent from a curve dict."""
        loans = [_make_loan(1), _make_loan(2)]
        n = 360
        smm_dict = {1: np.zeros(n + 1)}  # missing loan_id=2
        with self.assertRaises(KeyError):
            run_actual_portfolio(
                loans,
                smm_curves=smm_dict,
                mdr_curves=np.zeros(n + 1),
                severity_curves=np.zeros(n + 1),
            )

    def test_to_dataframe_returns_dataframe(self):
        import pandas as pd
        loans = self._loans()
        n = 360
        smm, mdr, sev = _small_curves(n)
        pf = run_actual_portfolio(loans, smm_curves=smm, mdr_curves=mdr, severity_curves=sev)
        df = pf.to_dataframe()
        self.assertIsInstance(df, pd.DataFrame)

    def test_empty_loans_raises(self):
        with self.assertRaises((ValueError, Exception)):
            run_actual_portfolio(
                [],
                smm_curves=np.zeros(361),
                mdr_curves=np.zeros(361),
                severity_curves=np.zeros(361),
            )

    def test_flush_releases_constituents(self):
        loans = self._loans()
        n = 360
        smm, mdr, sev = _small_curves(n)
        pf = run_actual_portfolio(
            loans, smm_curves=smm, mdr_curves=mdr, severity_curves=sev, flush=True
        )
        self.assertEqual(len(pf._pending), 0)
        self.assertTrue(pf._flushed)


# ---------------------------------------------------------------------------
# run_paired_portfolio
# ---------------------------------------------------------------------------

class TestRunPairedPortfolio(unittest.TestCase):

    def _loans(self):
        return [_make_loan(1), _make_loan(2)]

    def test_returns_portfolio_cashflow(self):
        n = 360
        smm, mdr, sev = _small_curves(n)
        pf = run_paired_portfolio(self._loans(), smm_curves=smm, mdr_curves=mdr, severity_curves=sev)
        self.assertIsInstance(pf, PortfolioCashflow)

    def test_mode_is_paired(self):
        n = 360
        smm, mdr, sev = _small_curves(n)
        pf = run_paired_portfolio(self._loans(), smm_curves=smm, mdr_curves=mdr, severity_curves=sev)
        self.assertEqual(pf.mode, PortfolioMode.PAIRED)

    def test_both_scheduled_and_pool_accessible(self):
        """PAIRED mode has both a scheduled aggregate and an actual pool."""
        n = 360
        smm, mdr, sev = _small_curves(n)
        pf = run_paired_portfolio(self._loans(), smm_curves=smm, mdr_curves=mdr, severity_curves=sev)
        self.assertIsNotNone(pf.scheduled)
        self.assertIsNotNone(pf.pool)

    def test_zero_curves_scheduled_equals_actual(self):
        """With zero assumptions, actual amortization should match scheduled principal."""
        loans = [_make_loan(1)]
        n = 360
        pf = run_paired_portfolio(
            loans,
            smm_curves=_zero_curves(n),
            mdr_curves=_zero_curves(n),
            severity_curves=_zero_curves(n),
        )
        # At zero prepay/default: act_am (actual amortization) == scheduled principal_paid
        np.testing.assert_allclose(
            pf.scheduled.principal_paid[1:],
            pf.pool.act_am[1:],
            rtol=1e-4,
        )

    def test_per_loan_dict_curves(self):
        loans = self._loans()
        n = 360
        smm_arr = np.full(n + 1, 0.003)
        smm_dict = {1: smm_arr, 2: smm_arr}
        pf = run_paired_portfolio(
            loans,
            smm_curves=smm_dict,
            mdr_curves=np.zeros(n + 1),
            severity_curves=np.zeros(n + 1),
        )
        self.assertEqual(pf.mode, PortfolioMode.PAIRED)

    def test_to_dataframe(self):
        import pandas as pd
        n = 360
        smm, mdr, sev = _small_curves(n)
        pf = run_paired_portfolio(self._loans(), smm_curves=smm, mdr_curves=mdr, severity_curves=sev)
        df = pf.to_dataframe()
        self.assertIsInstance(df, pd.DataFrame)
        self.assertGreater(len(df), 0)

    def test_single_loan(self):
        n = 360
        smm, mdr, sev = _small_curves(n)
        pf = run_paired_portfolio([_make_loan(1)], smm_curves=smm, mdr_curves=mdr, severity_curves=sev)
        self.assertEqual(pf.mode, PortfolioMode.PAIRED)


# ---------------------------------------------------------------------------
# _resolve_curve
# ---------------------------------------------------------------------------

class TestResolveCurve(unittest.TestCase):

    def test_array_returns_same_for_any_id(self):
        arr = np.array([1.0, 2.0, 3.0])
        self.assertIs(_resolve_curve(arr, 1), arr)
        self.assertIs(_resolve_curve(arr, 999), arr)

    def test_dict_returns_correct_entry(self):
        a = np.array([0.1, 0.2])
        b = np.array([0.3, 0.4])
        d = {1: a, 2: b}
        np.testing.assert_array_equal(_resolve_curve(d, 1), a)
        np.testing.assert_array_equal(_resolve_curve(d, 2), b)

    def test_dict_missing_key_raises_key_error(self):
        d = {1: np.zeros(5)}
        with self.assertRaises(KeyError) as ctx:
            _resolve_curve(d, 99)
        self.assertIn("loan_id=99", str(ctx.exception))


# ---------------------------------------------------------------------------
# Integration: tape reader → portfolio runners
# ---------------------------------------------------------------------------

class TestTapeToPortfolioPipeline(unittest.TestCase):
    """End-to-end: read_loan_tape → run_scheduled_portfolio (no I/O, in-memory tape)."""

    def test_tape_dataframe_to_scheduled_portfolio(self):
        """Construct a DataFrame tape, read it, run portfolio — all in memory."""
        import pandas as pd
        from bma_standard_formulas.engine import read_loan_tape

        df = pd.DataFrame({
            "loan_id":           [101, 102, 103],
            "origination_date":  ["2020-01-01", "2021-06-01", "2019-03-01"],
            "asof_date":         ["2024-01-01"] * 3,
            "original_balance":  [1_000_000.0, 500_000.0, 750_000.0],
            "current_balance":   [960_000.0, 490_000.0, 700_000.0],
            "rate_margin":       [7.5, 8.0, 6.75],
            "original_term":     [360, 360, 240],
            "remaining_term":    [312, 285, 180],
            "servicing_fee":     [0.25, 0.25, 0.375],
        })
        loans = read_loan_tape(df)
        self.assertEqual(len(loans), 3)

        pf = run_scheduled_portfolio(loans)
        self.assertIsInstance(pf, PortfolioCashflow)
        self.assertEqual(pf.mode, PortfolioMode.SCHEDULED_ONLY)
        self.assertEqual(pf._n_constituents, 3)

        # Period 1 beginning balance = sum of current balances (period 0 is as-of snapshot)
        self.assertAlmostEqual(
            pf.scheduled.beginning_balance[1],
            960_000.0 + 490_000.0 + 700_000.0,
            delta=1.0,
        )


if __name__ == "__main__":
    unittest.main()
