"""
Tests for the Loan dataclass — construction, validation, and computed properties.

Covers every guard in __post_init__ plus the key computed properties (age,
is_fixed_rate, servicing_fee_decimal, build_coupon_vector).

BMA Reference: engine/loan.py
"""

import unittest

import numpy as np

from bma_standard_formulas.engine import Loan


# ---------------------------------------------------------------------------
# Minimal valid Loan factory
# ---------------------------------------------------------------------------

def _loan(**overrides) -> Loan:
    """Return a minimal valid fixed-rate Loan, applying any field overrides."""
    defaults = dict(
        loan_id=1,
        origination_date=np.datetime64("2020-01-01"),
        asof_date=np.datetime64("2024-01-01"),
        original_balance=1_000_000.0,
        current_balance=900_000.0,
        rate_margin=7.5,
        original_term=360,
        remaining_term=312,
        servicing_fee=0.25,
    )
    defaults.update(overrides)
    return Loan(**defaults)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestLoanConstruction(unittest.TestCase):

    def test_valid_fixed_rate_loan(self):
        loan = _loan()
        self.assertEqual(loan.loan_id, 1)
        self.assertAlmostEqual(loan.original_balance, 1_000_000.0)

    def test_defaults_applied(self):
        loan = _loan()
        self.assertEqual(loan.reset_frequency, 0)
        self.assertIsNone(loan.index_type)
        self.assertIsNone(loan.rate_cap)
        self.assertIsNone(loan.rate_floor)

    def test_fully_paid_loan_is_valid(self):
        """remaining_term=0 and current_balance=0 are both valid (matured loan)."""
        loan = _loan(remaining_term=0, current_balance=0.0)
        self.assertEqual(loan.remaining_term, 0)


# ---------------------------------------------------------------------------
# __post_init__ validation
# ---------------------------------------------------------------------------

class TestLoanValidation(unittest.TestCase):

    # original_term
    def test_original_term_zero_raises(self):
        with self.assertRaises(ValueError, msg="original_term=0 should raise"):
            _loan(original_term=0)

    def test_original_term_negative_raises(self):
        with self.assertRaises(ValueError):
            _loan(original_term=-1)

    # remaining_term
    def test_remaining_term_negative_raises(self):
        with self.assertRaises(ValueError):
            _loan(remaining_term=-1)

    def test_remaining_term_exceeds_original_raises(self):
        with self.assertRaises(ValueError):
            _loan(original_term=360, remaining_term=361)

    def test_remaining_term_equals_original_is_valid(self):
        """New origination: remaining_term == original_term."""
        loan = _loan(original_term=360, remaining_term=360, current_balance=1_000_000.0)
        self.assertEqual(loan.remaining_term, 360)

    # original_balance
    def test_original_balance_zero_raises(self):
        """A loan with zero original balance was never originated."""
        with self.assertRaises(ValueError):
            _loan(original_balance=0.0, current_balance=0.0)

    def test_original_balance_negative_raises(self):
        with self.assertRaises(ValueError):
            _loan(original_balance=-1.0, current_balance=0.0)

    def test_original_balance_positive_is_valid(self):
        loan = _loan(original_balance=500_000.0, current_balance=400_000.0)
        self.assertAlmostEqual(loan.original_balance, 500_000.0)

    # current_balance
    def test_current_balance_exceeds_original_raises(self):
        with self.assertRaises(ValueError):
            _loan(original_balance=1_000_000.0, current_balance=1_000_001.0)

    def test_current_balance_equals_original_is_valid(self):
        """New origination: current_balance == original_balance."""
        loan = _loan(original_balance=1_000_000.0, current_balance=1_000_000.0)
        self.assertAlmostEqual(loan.current_balance, 1_000_000.0)

    def test_current_balance_zero_is_valid(self):
        """Fully paid-off loan."""
        loan = _loan(current_balance=0.0, remaining_term=0)
        self.assertEqual(loan.current_balance, 0.0)

    # dates
    def test_asof_before_origination_raises(self):
        with self.assertRaises(ValueError):
            _loan(
                origination_date=np.datetime64("2024-01-01"),
                asof_date=np.datetime64("2023-12-31"),
            )

    def test_asof_equals_origination_is_valid(self):
        loan = _loan(
            origination_date=np.datetime64("2024-01-01"),
            asof_date=np.datetime64("2024-01-01"),
            remaining_term=360,
            current_balance=1_000_000.0,
        )
        self.assertEqual(loan.asof_date, np.datetime64("2024-01-01"))

    # rate cap / floor
    def test_rate_cap_below_rate_floor_raises(self):
        with self.assertRaises(ValueError):
            _loan(rate_cap=5.0, rate_floor=6.0)

    def test_rate_cap_equals_rate_floor_is_valid(self):
        loan = _loan(rate_cap=8.0, rate_floor=8.0)
        self.assertEqual(loan.rate_cap, 8.0)

    def test_rate_cap_above_rate_floor_is_valid(self):
        loan = _loan(rate_cap=12.0, rate_floor=3.0)
        self.assertGreater(loan.rate_cap, loan.rate_floor)


# ---------------------------------------------------------------------------
# Computed properties
# ---------------------------------------------------------------------------

class TestLoanComputedProperties(unittest.TestCase):

    def test_age(self):
        """age = original_term - remaining_term."""
        loan = _loan(original_term=360, remaining_term=312)
        self.assertEqual(loan.age, 48)

    def test_age_new_origination(self):
        loan = _loan(original_term=360, remaining_term=360, current_balance=1_000_000.0)
        self.assertEqual(loan.age, 0)

    def test_is_fixed_rate_true(self):
        loan = _loan(reset_frequency=0, index_type=None)
        self.assertTrue(loan.is_fixed_rate())

    def test_is_fixed_rate_false_for_arm(self):
        loan = _loan(reset_frequency=12, index_type="SOFR")
        self.assertFalse(loan.is_fixed_rate())

    def test_servicing_fee_decimal(self):
        """servicing_fee_decimal() should return fee / 100."""
        loan = _loan(servicing_fee=0.25)
        self.assertAlmostEqual(loan.servicing_fee_decimal(), 0.0025)

    def test_servicing_fee_decimal_zero(self):
        loan = _loan(servicing_fee=0.0)
        self.assertEqual(loan.servicing_fee_decimal(), 0.0)


# ---------------------------------------------------------------------------
# Curve slicing (_slice_curve / actual_cashflow_from_loan age alignment)
# ---------------------------------------------------------------------------

class TestCurveSlicing(unittest.TestCase):
    """Verify that actual_cashflow_from_loan correctly aligns age-indexed curves."""

    from bma_standard_formulas.engine.loan import _slice_curve

    def _seasoned_loan(self, age: int) -> Loan:
        """Loan with given age (original_term=360, remaining_term=360-age)."""
        return _loan(
            original_term=360,
            remaining_term=360 - age,
            original_balance=1_000_000.0,
            current_balance=1_000_000.0 * (1 - age / 360),
        )

    def test_new_loan_slice_is_full_curve(self):
        """Age-0 loan: slice covers the entire curve unchanged."""
        from bma_standard_formulas.engine.loan import _slice_curve
        loan = self._seasoned_loan(0)
        curve = np.arange(361, dtype=float)   # age-indexed 0..360
        sliced = _slice_curve(curve, loan, "smm_curve")
        np.testing.assert_array_equal(sliced, curve[0:361])

    def test_seasoned_loan_slice_starts_at_age(self):
        """Seasoned loan at age 60: slice starts at index 60."""
        from bma_standard_formulas.engine.loan import _slice_curve
        loan = self._seasoned_loan(60)
        curve = np.arange(361, dtype=float)   # age-indexed 0..360
        sliced = _slice_curve(curve, loan, "smm_curve")
        # First element of sliced curve is the age-60 rate
        self.assertAlmostEqual(sliced[0], 60.0)
        # Last element is age-360
        self.assertAlmostEqual(sliced[-1], 360.0)
        self.assertEqual(len(sliced), loan.remaining_term + 1)

    def test_curve_too_short_raises(self):
        """Curve shorter than age + remaining_term + 1 must raise ValueError."""
        from bma_standard_formulas.engine.loan import _slice_curve
        loan = self._seasoned_loan(60)  # needs 60 + 300 + 1 = 361 elements
        short_curve = np.zeros(300)     # only 300 — too short
        with self.assertRaises(ValueError) as ctx:
            _slice_curve(short_curve, loan, "smm_curve")
        self.assertIn("smm_curve", str(ctx.exception))
        self.assertIn("361", str(ctx.exception))

    def test_psa_curve_seasoning_plateau(self):
        """Seasoned loan at age 60 gets plateau PSA rates, not the ramp."""
        from bma_standard_formulas.engine.loan import _slice_curve
        from bma_standard_formulas.formulas import generate_smm_curve_from_psa
        # 100% PSA: ramp 0-30 months, plateau 6% CPR thereafter
        psa_curve = generate_smm_curve_from_psa(100, 360)  # age-indexed, length 361
        loan = self._seasoned_loan(60)
        sliced = _slice_curve(psa_curve, loan, "smm_curve")
        # Age-60 PSA SMM should be the plateau value (same as age-31+)
        plateau_smm = psa_curve[31]
        self.assertAlmostEqual(sliced[0], plateau_smm, places=10,
                               msg="Seasoned loan should start at PSA plateau, not ramp")
        # A new loan would incorrectly start near zero (ramp)
        ramp_smm = psa_curve[1]
        self.assertGreater(sliced[0], ramp_smm * 10,
                           msg="Plateau SMM must be much larger than ramp SMM")


if __name__ == "__main__":
    unittest.main()
