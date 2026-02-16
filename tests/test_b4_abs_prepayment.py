"""
Unit tests for BMA Section B.4 ABS prepayment rate functions.

Tests ABS-to-SMM conversion, historical ABS recovery, and the ABS prepayment
model for asset-backed securities.

Version: 0.1.0
Last Updated: 2026-01-29
Status: Active

================================================================================
FUNCTIONS UNDER TEST:
================================================================================
- abs_to_smm: Convert ABS speed to SMM for a given month (SF-13)
- historical_abs: Recover ABS speed from observed factors (SF-14)
- smm_to_abs: Convert SMM back to ABS speed (STUB — not yet implemented)
- generate_smm_curve_from_abs: Generate SMM curve from ABS speed (STUB)

================================================================================
TEST DATA SOURCES:
================================================================================
- SF-13 formula: SMM = (100 * ABS) / [100 - ABS * (MONTH - 1)]
- SF-14 example: 36-month car loans, WAM 34 months, 2% ABS, month 11
  SMM = 200 / 80 = 2.5000%
- SF-14 conversion table (selected values):
  Month | 0.50 ABS | 1.00 ABS | 1.50 ABS | 2.00 ABS
  1     | 0.50     | 1.00     | 1.50     | 2.00
  10    | 0.52     | 1.10     | 1.73     | 2.44
  20    | 0.55     | 1.23     | 2.10     | 3.23
  30    | 0.58     | 1.41     | 2.65     | 4.76
  40    | 0.62     | 1.64     | 3.61     | 9.09
  50    | 0.66     | 1.96     | 5.66     | 100.00

- SF-14 historical ABS formula:
  ABS = 100 * [(F2/F1) - (BAL2/BAL1)] / [AGE1*(F2/F1) - AGE2*(BAL2/BAL1)]

================================================================================
"""

import unittest
import numpy as np
from bma_standard_formulas.payment_models import (
    abs_to_smm,
    historical_abs,
    smm_to_abs,
    generate_smm_curve_from_abs,
)
from bma_standard_formulas.scheduled_payments import (
    sch_balance_factor_fixed_rate,
)


# =============================================================================
# SF-14 Conversion Table (selected values)
# =============================================================================

ABS_CONVERSION_TABLE = [
    # (month, abs_speed, expected_smm_pct)
    (1,  0.50, 0.50),
    (1,  1.00, 1.00),
    (1,  1.50, 1.50),
    (1,  2.00, 2.00),
    (10, 0.50, 0.52),
    (10, 1.00, 1.10),
    (10, 1.50, 1.73),
    (10, 2.00, 2.44),
    (20, 0.50, 0.55),
    (20, 1.00, 1.23),
    (20, 1.50, 2.10),
    (20, 2.00, 3.23),
    (30, 0.50, 0.58),
    (30, 1.00, 1.41),
    (30, 1.50, 2.65),
    (30, 2.00, 4.76),
    (40, 0.50, 0.62),
    (40, 1.00, 1.64),
    (40, 1.50, 3.61),
    (40, 2.00, 9.09),
    (50, 0.50, 0.66),
    (50, 1.00, 1.96),
    (50, 1.50, 5.66),
    (50, 2.00, 100.00),
]


# =============================================================================
# Test Classes
# =============================================================================

class TestB4AbsToSmm(unittest.TestCase):
    """Test abs_to_smm against SF-13 formula and SF-14 examples."""

    def test_sf14_car_loan_example(self):
        """SF-14: 2% ABS, month 11 → SMM = 2.5000%."""
        smm = abs_to_smm(2.0, 11)
        self.assertAlmostEqual(smm, 2.5, places=4)

    def test_month_1_equals_abs(self):
        """At month 1, SMM = ABS (denominator = 100)."""
        for abs_speed in [0.5, 1.0, 1.5, 2.0, 3.0]:
            smm = abs_to_smm(abs_speed, 1)
            self.assertAlmostEqual(smm, abs_speed, places=8,
                                   msg=f"ABS={abs_speed}%: month 1 SMM should equal ABS")

    def test_month_0_returns_zero(self):
        """At month 0 (origination), SMM = 0 for any ABS speed."""
        for abs_speed in [0.5, 1.0, 2.0, 5.0]:
            smm = abs_to_smm(abs_speed, 0)
            self.assertEqual(smm, 0.0,
                             msg=f"ABS={abs_speed}%: month 0 should return 0")

    def test_increasing_over_time(self):
        """ABS model: SMM increases monotonically with month."""
        for abs_speed in [0.5, 1.0, 1.5]:
            prev_smm = 0.0
            for month in range(1, 40):
                smm = abs_to_smm(abs_speed, month)
                self.assertGreaterEqual(smm, prev_smm,
                                        msg=f"ABS={abs_speed}%, month {month}: SMM should increase")
                prev_smm = smm

    def test_conversion_table(self):
        """Validate against SF-14 conversion table (selected values)."""
        for month, abs_speed, expected_smm in ABS_CONVERSION_TABLE:
            smm = abs_to_smm(abs_speed, month)
            self.assertAlmostEqual(
                smm, expected_smm, places=2,
                msg=f"ABS={abs_speed}%, month={month}: "
                    f"expected SMM={expected_smm}%, got {smm:.4f}%"
            )

    def test_denominator_hits_zero(self):
        """When denominator <= 0, all remaining loans prepay (SMM = 100%)."""
        # 2% ABS at month 51: denominator = 100 - 2*(51-1) = 0
        smm = abs_to_smm(2.0, 51)
        self.assertEqual(smm, 100.0)

    def test_formula_direct(self):
        """Verify formula: SMM = (100 * ABS) / [100 - ABS * (MONTH - 1)]."""
        test_cases = [
            (1.5, 12),  # SMM = 150 / (100 - 1.5*11) = 150 / 83.5
            (0.5, 25),  # SMM = 50 / (100 - 0.5*24) = 50 / 88
            (3.0, 10),  # SMM = 300 / (100 - 3*9) = 300 / 73
        ]
        for abs_speed, month in test_cases:
            expected = (100.0 * abs_speed) / (100.0 - abs_speed * (month - 1))
            actual = abs_to_smm(abs_speed, month)
            self.assertAlmostEqual(actual, expected, places=8,
                                   msg=f"ABS={abs_speed}%, month={month}")


class TestB4HistoricalAbs(unittest.TestCase):
    """Test historical_abs for ABS speed recovery from factors."""

    def test_roundtrip_single_month(self):
        """Generate factor with known ABS, then recover ABS speed."""
        abs_speed = 2.0
        coupon = 8.0
        orig_term = 36  # short-term (auto loans)
        age1 = 5
        age2 = 6

        f1 = sch_balance_factor_fixed_rate(coupon, orig_term, orig_term - age1)
        bal1 = f1  # no prepays in scheduled balance

        smm_pct = abs_to_smm(abs_speed, age2)
        smm_decimal = smm_pct / 100.0

        bal2 = sch_balance_factor_fixed_rate(coupon, orig_term, orig_term - age2)
        # Actual factor after prepayment
        f2 = f1 * (bal2 / bal1) * (1.0 - smm_decimal)

        recovered = historical_abs(age1, f1, bal1, age2, f2, bal2)
        self.assertAlmostEqual(recovered, abs_speed, places=2)

    def test_roundtrip_multi_month(self):
        """Generate factors over 6-month window with known ABS, then recover."""
        abs_speed = 1.5
        coupon = 8.0
        orig_term = 36
        age1 = 3
        age2 = 9
        window = age2 - age1

        bal1 = sch_balance_factor_fixed_rate(coupon, orig_term, orig_term - age1)
        bal2 = sch_balance_factor_fixed_rate(coupon, orig_term, orig_term - age2)

        # Build actual factor by applying ABS month by month
        f = bal1  # start at scheduled (no prior prepays)
        for m in range(window):
            month = age1 + m + 1
            smm_pct = abs_to_smm(abs_speed, month)
            smm_dec = smm_pct / 100.0
            bal_m_start = sch_balance_factor_fixed_rate(coupon, orig_term, orig_term - (age1 + m))
            bal_m_end = sch_balance_factor_fixed_rate(coupon, orig_term, orig_term - (age1 + m + 1))
            f = f * (bal_m_end / bal_m_start) * (1.0 - smm_dec)

        recovered = historical_abs(age1, bal1, bal1, age2, f, bal2)
        self.assertAlmostEqual(recovered, abs_speed, places=1)

    def test_no_prepay_returns_zero(self):
        """When actual factor equals scheduled, ABS = 0."""
        coupon = 8.0
        orig_term = 36
        age1 = 5
        age2 = 11

        bal1 = sch_balance_factor_fixed_rate(coupon, orig_term, orig_term - age1)
        bal2 = sch_balance_factor_fixed_rate(coupon, orig_term, orig_term - age2)

        recovered = historical_abs(age1, bal1, bal1, age2, bal2, bal2)
        self.assertAlmostEqual(recovered, 0.0, places=4)


class TestB4Stubs(unittest.TestCase):
    """Verify stub functions raise NotImplementedError properly."""

    def test_smm_to_abs_is_stub(self):
        """smm_to_abs is not yet implemented."""
        result = smm_to_abs(1.0, 10)
        self.assertIs(result, NotImplementedError)

    def test_generate_smm_curve_from_abs_is_stub(self):
        """generate_smm_curve_from_abs is not yet implemented."""
        result = generate_smm_curve_from_abs(1.5, 36)
        self.assertIs(result, NotImplementedError)


if __name__ == '__main__':
    unittest.main()
