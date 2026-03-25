"""
Unit tests for BMA Section B.4 ABS prepayment rate functions.

Tests ABS-to-SMM conversion, historical ABS recovery, and the ABS prepayment
model for asset-backed securities.

Version: 0.2.0
Last Updated: 2026-03-23
Status: Active

================================================================================
FUNCTIONS UNDER TEST:
================================================================================
- abs_to_smm: Convert ABS speed to SMM for a given month (SF-13)
- smm_to_abs: Convert SMM back to ABS speed (inverse of abs_to_smm, SF-13)
- generate_smm_curve_from_abs: Generate SMM decimal curve from ABS speed (SF-13)
- historical_abs: Recover ABS speed from observed factors (SF-14)

================================================================================
TEST DATA SOURCES:
================================================================================
- BMA SF-13 formula: SMM = (100 * ABS) / [100 - ABS * (MONTH - 1)]
- BMA SF-14 example: 36-month car loans, WAM 34 months, 2% ABS, month 11
  SMM = 200 / 80 = 2.5000%
- BMA SF-15 "Conversion of ABS to SMM" table (50 months × 7 ABS speeds).
  Fixture: tests/fixtures/bma_sf15_abs_to_smm.csv
  Tolerance: ±0.005 (half unit in the last place of the 2-decimal BMA table).
- SF-14 historical ABS formula:
  ABS = 100 * [(F2/F1) - (BAL2/BAL1)] / [AGE1*(F2/F1) - AGE2*(BAL2/BAL1)]

================================================================================
"""

import csv
import unittest
from pathlib import Path

import numpy as np

from bma_standard_formulas.formulas.payment_models import (
    abs_to_smm,
    historical_abs,
    smm_to_abs,
    generate_smm_curve_from_abs,
)
from bma_standard_formulas.formulas.scheduled_payments import (
    sch_balance_factor_fixed_rate,
)

# ---------------------------------------------------------------------------
# Fixture loader
# ---------------------------------------------------------------------------

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_sf15_table() -> list[dict]:
    """Load the BMA SF-15 ABS-to-SMM conversion table from CSV."""
    rows = []
    with open(_FIXTURE_DIR / "bma_sf15_abs_to_smm.csv", newline="") as f:
        for row in csv.DictReader(f):
            rows.append({k: float(v) for k, v in row.items()})
    return rows


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


class TestSmmToAbs(unittest.TestCase):
    """Tests for smm_to_abs — the inverse of abs_to_smm."""

    def test_round_trip_at_various_months(self):
        """smm_to_abs(abs_to_smm(a, n), n) should recover the original ABS speed."""
        for abs_speed in [0.5, 1.0, 1.5, 2.0]:
            for month in [1, 5, 10, 20, 30]:
                smm = abs_to_smm(abs_speed, month)
                recovered = smm_to_abs(smm, month)
                self.assertAlmostEqual(
                    recovered, abs_speed, places=10,
                    msg=f"Round-trip failed: ABS={abs_speed}, month={month}",
                )

    def test_month_zero_returns_zero(self):
        """Period 0 is the origination snapshot — no prepayment occurs."""
        self.assertEqual(smm_to_abs(1.0, 0), 0.0)
        self.assertEqual(smm_to_abs(0.5, -1), 0.0)

    def test_known_values(self):
        """Verify against the ABS formula manually: ABS = 100·SMM / (100 + SMM·(n-1))."""
        # At month 1, denominator = 100, so ABS = SMM
        self.assertAlmostEqual(smm_to_abs(1.0, 1), 1.0, places=10)
        # At month 10, SMM(1% ABS) = 100/91; inverse should give 1.0
        smm_m10 = abs_to_smm(1.0, 10)
        self.assertAlmostEqual(smm_to_abs(smm_m10, 10), 1.0, places=10)


class TestGenerateSmmCurveFromAbs(unittest.TestCase):
    """Tests for generate_smm_curve_from_abs."""

    def test_returns_array_of_correct_length(self):
        """Output length must be term + 1 (period 0 through period term)."""
        for term in [12, 36, 360]:
            curve = generate_smm_curve_from_abs(1.0, term)
            self.assertEqual(len(curve), term + 1)

    def test_period_zero_is_zero(self):
        """Origination period has no prepayment."""
        curve = generate_smm_curve_from_abs(1.5, 36)
        self.assertEqual(curve[0], 0.0)

    def test_values_are_decimal(self):
        """SMM values must be in [0, 1], not percentage."""
        curve = generate_smm_curve_from_abs(1.0, 36)
        self.assertTrue(np.all(curve >= 0.0))
        self.assertTrue(np.all(curve <= 1.0))

    def test_matches_abs_to_smm_pointwise(self):
        """Each entry must equal abs_to_smm(abs_speed, t) / 100."""
        abs_speed = 1.5
        term = 36
        curve = generate_smm_curve_from_abs(abs_speed, term)
        for t in range(1, term + 1):
            expected = abs_to_smm(abs_speed, t) / 100.0
            self.assertAlmostEqual(
                curve[t], expected, places=12,
                msg=f"Mismatch at period {t}",
            )

    def test_curve_is_increasing(self):
        """ABS SMM rises over time as the outstanding pool shrinks."""
        curve = generate_smm_curve_from_abs(1.0, 60)
        # Exclude period 0 (always 0)
        self.assertTrue(
            np.all(np.diff(curve[1:]) >= 0),
            "SMM curve should be non-decreasing for positive ABS speed",
        )

    def test_round_trip_with_smm_to_abs(self):
        """smm_to_abs applied pointwise to the curve must recover the original speed."""
        abs_speed = 1.2
        term = 24
        curve = generate_smm_curve_from_abs(abs_speed, term)
        for t in range(1, term + 1):
            recovered = smm_to_abs(curve[t] * 100.0, t)
            self.assertAlmostEqual(recovered, abs_speed, places=10)


class TestBMASF15Table(unittest.TestCase):
    """
    Validate abs_to_smm against the full BMA SF-15 "Conversion of ABS to SMM"
    table (50 months × 7 ABS speeds).

    The BMA table reports SMM rounded to 2 decimal places, so we allow ±0.005
    (half a unit in the last place). Every cell in the fixture is checked —
    350 values in total.

    Fixture: tests/fixtures/bma_sf15_abs_to_smm.csv
    Source:  BMA Uniform Practices/Standard Formulas (02/01/99), SF-15.
    """

    # Column name → ABS speed mapping (matches CSV header)
    ABS_SPEEDS = {
        "abs_0.50": 0.50,
        "abs_0.75": 0.75,
        "abs_1.00": 1.00,
        "abs_1.25": 1.25,
        "abs_1.50": 1.50,
        "abs_1.75": 1.75,
        "abs_2.00": 2.00,
    }
    # Half a unit in the last BMA-reported decimal place (2 d.p.), plus a
    # small epsilon to handle exact midpoint values (e.g. 0.625 rounds to
    # 0.63 in the BMA table) where floating-point diff == 0.005 exactly.
    TOLERANCE = 0.005 + 1e-9

    def test_every_cell_matches_bma_sf15(self):
        """
        Check abs_to_smm against every cell in the BMA SF-15 table.

        350 (month, ABS speed) pairs are tested. Failures are collected and
        reported together so the full mismatch picture is visible at once.
        """
        table = _load_sf15_table()
        errors = []

        for row in table:
            month = int(row["month"])
            for col, abs_speed in self.ABS_SPEEDS.items():
                bma_smm = row[col]              # BMA table value (percentage)
                calc_smm = abs_to_smm(abs_speed, month)  # our implementation

                diff = abs(calc_smm - bma_smm)
                if diff > self.TOLERANCE:
                    errors.append(
                        f"month={month:2d}, ABS={abs_speed:.2f}: "
                        f"BMA={bma_smm:.2f}, calc={calc_smm:.4f}, diff={diff:.4f}"
                    )

        self.assertEqual(
            len(errors), 0,
            f"BMA SF-15 mismatches ({len(errors)} of 350):\n" + "\n".join(errors),
        )

    def test_generate_smm_curve_from_abs_matches_sf15(self):
        """
        Check generate_smm_curve_from_abs against the BMA SF-15 table.

        The curve function returns SMM as decimal (0-1); multiply by 100
        before comparing to the BMA percentage table.
        """
        table = _load_sf15_table()
        errors = []

        for col, abs_speed in self.ABS_SPEEDS.items():
            curve = generate_smm_curve_from_abs(abs_speed, 50)
            for row in table:
                month = int(row["month"])
                bma_smm = row[col]
                calc_smm = curve[month] * 100.0  # convert decimal → percentage

                diff = abs(calc_smm - bma_smm)
                if diff > self.TOLERANCE:
                    errors.append(
                        f"month={month:2d}, ABS={abs_speed:.2f}: "
                        f"BMA={bma_smm:.2f}, calc={calc_smm:.4f}, diff={diff:.4f}"
                    )

        self.assertEqual(
            len(errors), 0,
            f"generate_smm_curve_from_abs SF-15 mismatches ({len(errors)} of 350):\n"
            + "\n".join(errors),
        )


if __name__ == '__main__':
    unittest.main()
