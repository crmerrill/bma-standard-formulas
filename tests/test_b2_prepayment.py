"""
Unit tests for BMA Section B.2 prepayment conversion functions.

Tests prepayment rate conversions between SMM, CPR, and PSA formats.
Validates against BMA reference tables (SF-7, SF-8) and conversion fixtures.

Version: 0.1.0
Last Updated: 2026-01-29
Status: Active

================================================================================
FUNCTIONS UNDER TEST:
================================================================================
- smm_from_factors: Calculate SMM from pool factors and scheduled balances
- cpr_to_smm: Convert CPR (annual %) to SMM (decimal)
- smm_to_cpr: Convert SMM (decimal) to CPR (annual %)
- cpr_to_smm_vector: Vectorized CPR to SMM conversion
- smm_to_cpr_vector: Vectorized SMM to CPR conversion
- psa_to_cpr: Convert PSA speed to CPR for a given month
- cpr_to_psa: Convert CPR to PSA speed for a given month
- generate_psa_curve: Generate full PSA CPR curve for a term

================================================================================
TEST DATA SOURCES:
================================================================================
- SF-7 example: GNMA 9.0% pool, month 17 prepayment calculation
- SF-8 conversion table: SMM/CPR/PSA conversion reference
- 1m_PSAtoSMM_conversion.csv: PSA to SMM conversions by month and PSA speed
- bma_prepay_rate_conversion_table.csv: SMM/CPR/PSA30 conversion table

================================================================================
"""

import csv
import os
import unittest
import numpy as np
from bma_standard_formulas.payment_models import (
    smm_from_factors,
    cpr_to_smm,
    smm_to_cpr,
    cpr_to_smm_vector,
    smm_to_cpr_vector,
    psa_to_cpr,
    cpr_to_psa,
    generate_psa_curve,
)
from bma_standard_formulas.scheduled_payments import sch_balance_factor_fixed_rate

# =============================================================================
# Test Parameters
# =============================================================================

DECIMAL_PLACES_FOR_ASSERTIONS: int = 6  # decimal places for assertAlmostEqual
DECIMAL_PLACES_FOR_PERCENT: int = 1  # decimal places for percentage comparisons

# Module-level test data (populated by setUpModule)
PSA_TO_SMM_DATA: list[dict] = []
PREPAY_CONVERSION_TABLE: list[dict] = []


# =============================================================================
# Module Setup/Teardown
# =============================================================================

def setUpModule():
    """Load test fixtures from CSV files."""
    global PSA_TO_SMM_DATA, PREPAY_CONVERSION_TABLE
    
    # Load 1m_PSAtoSMM_conversion.csv
    fixture_dir = os.path.join(
        os.path.dirname(__file__),
        'fixtures'
    )
    psa_to_smm_path = os.path.join(fixture_dir, '1m_PSAtoSMM_conversion.csv')
    prepay_table_path = os.path.join(fixture_dir, 'bma_prepay_rate_conversion_table.csv')
    
    # Load PSA to SMM conversion table
    PSA_TO_SMM_DATA = []
    if os.path.exists(psa_to_smm_path):
        with open(psa_to_smm_path, 'r') as f:
            lines = f.readlines()
            # Find header line (first non-comment line)
            header_idx = None
            for i, line in enumerate(lines):
                if not line.strip().startswith('#'):
                    header_idx = i
                    break
            
            if header_idx is not None:
                reader = csv.DictReader(lines[header_idx:])
                for row in reader:
                    try:
                        month = int(row['Month'])
                        for psa_col in [col for col in row.keys() if col.startswith('PSA')]:
                            psa_speed = int(psa_col.replace('PSA', ''))
                            smm_pct = float(row[psa_col])
                            PSA_TO_SMM_DATA.append({
                                'month': month,
                                'psa_speed': psa_speed,
                                'smm_pct': smm_pct,
                                'smm_decimal': smm_pct / 100.0,
                            })
                    except (ValueError, KeyError):
                        continue
    
    # Load prepayment rate conversion table
    PREPAY_CONVERSION_TABLE = []
    if os.path.exists(prepay_table_path):
        with open(prepay_table_path, 'r') as f:
            lines = f.readlines()
            # Find header line (first non-comment line)
            header_idx = None
            for i, line in enumerate(lines):
                if not line.strip().startswith('#'):
                    header_idx = i
                    break
            
            if header_idx is not None:
                reader = csv.DictReader(lines[header_idx:])
                for row in reader:
                    try:
                        smm_pct = float(row['SMM'])
                        cpr_pct = float(row['CPR'])
                        psa30 = float(row['PSA30'])
                        PREPAY_CONVERSION_TABLE.append({
                            'smm_pct': smm_pct,
                            'smm_decimal': smm_pct / 100.0,
                            'cpr_pct': cpr_pct,
                            'psa30': psa30,
                        })
                    except (ValueError, KeyError):
                        continue
    
    # Validate that data was loaded
    if not PSA_TO_SMM_DATA:
        raise RuntimeError("setUpModule failed: No PSA to SMM data loaded")
    if not PREPAY_CONVERSION_TABLE:
        raise RuntimeError("setUpModule failed: No prepayment conversion table loaded")


def tearDownModule():
    """Clean up module-level data."""
    global PSA_TO_SMM_DATA, PREPAY_CONVERSION_TABLE
    PSA_TO_SMM_DATA.clear()
    PREPAY_CONVERSION_TABLE.clear()


# =============================================================================
# Test Classes
# =============================================================================

class TestB2SmmFromFactors(unittest.TestCase):
    """Test smm_from_factors using SF-7 example."""
    
    def test_sf7_example_single_month(self):
        """Test smm_from_factors against SF-7 example.
        
        SF-7 Example (GNMA 9.0% pool, month 17):
        - Pool factors: F1 = 0.85150625, F2 = 0.84732282
        - Scheduled balances: bal1 = 0.99213300, bal2 = 0.99157471
        - Expected SMM = 0.00435270 (0.435270%)
        """
        # SF-7 example values
        f1 = 0.85150625
        f2 = 0.84732282
        bal1 = 0.99213300
        bal2 = 0.99157471
        expected_smm = 0.00435270
        
        # Calculate SMM from factors
        computed_smm = smm_from_factors(f1, f2, bal1, bal2, window_months=1)
        
        self.assertAlmostEqual(
            computed_smm, expected_smm, places=DECIMAL_PLACES_FOR_ASSERTIONS,
            msg=f"SF-7 SMM: expected {expected_smm:.8f}, got {computed_smm:.8f}"
        )
    
    def test_sf7_example_verification(self):
        """Verify SF-7 example calculation step by step.
        
        From SF-7:
        - Scheduled factor: F_sched = F1 * (bal2/bal1) = 0.85102709
        - Prepayments = F_sched - F2 = 0.00370427
        - SMM = Prepayments / F_sched = 0.435270%
        """
        f1 = 0.85150625
        f2 = 0.84732282
        bal1 = 0.99213300
        bal2 = 0.99157471
        
        # Calculate scheduled factor
        f_sched = f1 * (bal2 / bal1)
        expected_f_sched = 0.85102709
        self.assertAlmostEqual(f_sched, expected_f_sched, places=8)
        
        # Calculate prepayments
        prepayments = f_sched - f2
        expected_prepayments = 0.00370427
        self.assertAlmostEqual(prepayments, expected_prepayments, places=8)
        
        # Calculate SMM using the function
        computed_smm = smm_from_factors(f1, f2, bal1, bal2, window_months=1)
        
        # Verify SMM = prepayments / f_sched
        expected_smm = prepayments / f_sched
        self.assertAlmostEqual(computed_smm, expected_smm, places=DECIMAL_PLACES_FOR_ASSERTIONS)
        
        # Verify expected SMM percentage
        expected_smm_pct = 0.435270 / 100.0
        self.assertAlmostEqual(computed_smm, expected_smm_pct, places=6)


class TestB2CprSmmConversions(unittest.TestCase):
    """Test CPR <-> SMM conversions against conversion table."""
    
    def test_cpr_to_smm_matches_table(self):
        """Verify cpr_to_smm against conversion table.
        
        Note: Table values are rounded, so we allow small differences.
        """
        for entry in PREPAY_CONVERSION_TABLE:
            with self.subTest(cpr_pct=entry['cpr_pct'], expected_smm_pct=entry['smm_pct']):
                # cpr_to_smm takes CPR as percentage, returns SMM as decimal
                computed_smm = cpr_to_smm(entry['cpr_pct'])
                expected_smm = entry['smm_decimal']
                
                # Allow tolerance due to rounding in table (0.0001 for small values, 0.0001% for larger)
                tolerance = max(0.0001, expected_smm * 0.01)  # 1% relative or 0.0001 absolute
                self.assertAlmostEqual(
                    computed_smm, expected_smm, delta=tolerance,
                    msg=f"CPR {entry['cpr_pct']}% -> SMM: expected {expected_smm:.6f}, got {computed_smm:.6f}"
                )
    
    def test_smm_to_cpr_matches_table(self):
        """Verify smm_to_cpr against conversion table."""
        for entry in PREPAY_CONVERSION_TABLE:
            with self.subTest(smm_pct=entry['smm_pct'], expected_cpr_pct=entry['cpr_pct']):
                # smm_to_cpr takes SMM as decimal, returns CPR as percentage
                computed_cpr = smm_to_cpr(entry['smm_decimal'])
                expected_cpr = entry['cpr_pct']
                
                self.assertAlmostEqual(
                    computed_cpr, expected_cpr, places=DECIMAL_PLACES_FOR_PERCENT,
                    msg=f"SMM {entry['smm_pct']}% -> CPR: expected {expected_cpr:.1f}%, got {computed_cpr:.1f}%"
                )
    
    def test_round_trip_cpr_smm(self):
        """Test round-trip conversion: CPR -> SMM -> CPR."""
        test_cprs = [0.6, 1.2, 3.0, 6.0, 12.0, 30.0, 60.0]
        
        for cpr in test_cprs:
            with self.subTest(cpr=cpr):
                smm = cpr_to_smm(cpr)
                round_trip_cpr = smm_to_cpr(smm)
                
                self.assertAlmostEqual(
                    round_trip_cpr, cpr, places=DECIMAL_PLACES_FOR_PERCENT,
                    msg=f"Round-trip CPR {cpr}% -> SMM -> CPR: expected {cpr:.1f}%, got {round_trip_cpr:.1f}%"
                )
    
    def test_round_trip_smm_cpr(self):
        """Test round-trip conversion: SMM -> CPR -> SMM."""
        test_smms = [0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05]
        
        for smm in test_smms:
            with self.subTest(smm=smm):
                cpr = smm_to_cpr(smm)
                round_trip_smm = cpr_to_smm(cpr)
                
                self.assertAlmostEqual(
                    round_trip_smm, smm, places=DECIMAL_PLACES_FOR_ASSERTIONS,
                    msg=f"Round-trip SMM {smm:.6f} -> CPR -> SMM: expected {smm:.6f}, got {round_trip_smm:.6f}"
                )


class TestB2VectorizedConversions(unittest.TestCase):
    """Test vectorized CPR <-> SMM conversion functions."""
    
    def test_cpr_to_smm_vector_matches_scalar(self):
        """Verify vectorized function matches scalar function."""
        test_cprs = [0.6, 1.2, 3.0, 6.0, 12.0, 30.0, 60.0]
        cpr_array = np.array(test_cprs)
        
        # Vectorized conversion
        smm_vector = cpr_to_smm_vector(cpr_array)
        
        # Scalar conversions
        for i, cpr in enumerate(test_cprs):
            with self.subTest(cpr=cpr):
                smm_scalar = cpr_to_smm(cpr)
                self.assertAlmostEqual(
                    smm_vector[i], smm_scalar, places=DECIMAL_PLACES_FOR_ASSERTIONS,
                    msg=f"Vectorized CPR {cpr}% -> SMM: expected {smm_scalar:.6f}, got {smm_vector[i]:.6f}"
                )
    
    def test_smm_to_cpr_vector_matches_scalar(self):
        """Verify vectorized function matches scalar function."""
        test_smms = [0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05]
        smm_array = np.array(test_smms)
        
        # Vectorized conversion
        cpr_vector = smm_to_cpr_vector(smm_array)
        
        # Scalar conversions
        for i, smm in enumerate(test_smms):
            with self.subTest(smm=smm):
                cpr_scalar = smm_to_cpr(smm)
                self.assertAlmostEqual(
                    cpr_vector[i], cpr_scalar, places=DECIMAL_PLACES_FOR_PERCENT,
                    msg=f"Vectorized SMM {smm:.6f} -> CPR: expected {cpr_scalar:.1f}%, got {cpr_vector[i]:.1f}%"
                )
    
    def test_vectorized_round_trip(self):
        """Test round-trip with vectorized functions."""
        test_cprs = np.array([0.6, 1.2, 3.0, 6.0, 12.0, 30.0, 60.0])
        
        smm_vector = cpr_to_smm_vector(test_cprs)
        round_trip_cpr = smm_to_cpr_vector(smm_vector)
        
        np.testing.assert_array_almost_equal(
            round_trip_cpr, test_cprs, decimal=DECIMAL_PLACES_FOR_PERCENT,
            err_msg="Vectorized round-trip CPR -> SMM -> CPR failed"
        )
    
    def test_vectorized_conversion_table(self):
        """Test vectorized functions against conversion table.
        
        Note: Table values are rounded, so we use element-wise comparison with tolerance.
        """
        # Extract CPR and SMM from table
        cpr_values = np.array([entry['cpr_pct'] for entry in PREPAY_CONVERSION_TABLE])
        smm_values = np.array([entry['smm_decimal'] for entry in PREPAY_CONVERSION_TABLE])
        
        # Test CPR -> SMM vectorized (with tolerance for rounding)
        computed_smm = cpr_to_smm_vector(cpr_values)
        for i, (computed, expected) in enumerate(zip(computed_smm, smm_values)):
            tolerance = max(0.0001, expected * 0.01)  # 1% relative or 0.0001 absolute
            self.assertAlmostEqual(
                computed, expected, delta=tolerance,
                msg=f"Vectorized CPR {cpr_values[i]}% -> SMM: expected {expected:.6f}, got {computed:.6f}"
            )
        
        # Test SMM -> CPR vectorized (with tolerance for rounding)
        computed_cpr = smm_to_cpr_vector(smm_values)
        for i, (computed, expected) in enumerate(zip(computed_cpr, cpr_values)):
            self.assertAlmostEqual(
                computed, expected, places=DECIMAL_PLACES_FOR_PERCENT,
                msg=f"Vectorized SMM {smm_values[i]:.6f} -> CPR: expected {expected:.1f}%, got {computed:.1f}%"
            )


class TestB2PsaConversions(unittest.TestCase):
    """Test PSA <-> CPR conversions."""
    
    def test_psa_to_cpr_ramp_period(self):
        """Test PSA to CPR conversion during ramp period (months 1-30)."""
        # At 100% PSA: CPR = 0.2% * month
        test_cases = [
            (100, 1, 0.2),
            (100, 15, 3.0),
            (100, 30, 6.0),
            (150, 1, 0.3),  # 0.2 * 1 * 1.5
            (150, 15, 4.5),  # 0.2 * 15 * 1.5
            (150, 30, 9.0),  # 0.2 * 30 * 1.5
            (50, 1, 0.1),   # 0.2 * 1 * 0.5
            (50, 15, 1.5),  # 0.2 * 15 * 0.5
            (50, 30, 3.0),  # 0.2 * 30 * 0.5
        ]
        
        for psa_speed, month, expected_cpr in test_cases:
            with self.subTest(psa_speed=psa_speed, month=month, expected_cpr=expected_cpr):
                computed_cpr = psa_to_cpr(psa_speed, month)
                self.assertAlmostEqual(
                    computed_cpr, expected_cpr, places=DECIMAL_PLACES_FOR_PERCENT,
                    msg=f"PSA {psa_speed}% at month {month}: expected {expected_cpr}%, got {computed_cpr:.1f}%"
                )
    
    def test_psa_to_cpr_plateau_period(self):
        """Test PSA to CPR conversion during plateau period (months 31+)."""
        # At 100% PSA: CPR = 6.0% for months 31+
        test_cases = [
            (100, 31, 6.0),
            (100, 60, 6.0),
            (100, 360, 6.0),
            (150, 31, 9.0),  # 6.0 * 1.5
            (150, 60, 9.0),
            (200, 31, 12.0),  # 6.0 * 2.0
            (50, 31, 3.0),   # 6.0 * 0.5
        ]
        
        for psa_speed, month, expected_cpr in test_cases:
            with self.subTest(psa_speed=psa_speed, month=month, expected_cpr=expected_cpr):
                computed_cpr = psa_to_cpr(psa_speed, month)
                self.assertAlmostEqual(
                    computed_cpr, expected_cpr, places=DECIMAL_PLACES_FOR_PERCENT,
                    msg=f"PSA {psa_speed}% at month {month}: expected {expected_cpr}%, got {computed_cpr:.1f}%"
                )
    
    def test_cpr_to_psa_ramp_period(self):
        """Test CPR to PSA conversion during ramp period (months 1-30)."""
        # Inverse: PSA = CPR * 500 / month
        test_cases = [
            (0.2, 1, 100.0),   # 0.2 * 500 / 1
            (3.0, 15, 100.0),  # 3.0 * 500 / 15
            (6.0, 30, 100.0),  # 6.0 * 500 / 30
            (0.3, 1, 150.0),   # 0.3 * 500 / 1
            (4.5, 15, 150.0),  # 4.5 * 500 / 15
            (9.0, 30, 150.0),  # 9.0 * 500 / 30
        ]
        
        for cpr, month, expected_psa in test_cases:
            with self.subTest(cpr=cpr, month=month, expected_psa=expected_psa):
                computed_psa = cpr_to_psa(cpr, month)
                self.assertAlmostEqual(
                    computed_psa, expected_psa, places=1,
                    msg=f"CPR {cpr}% at month {month} -> PSA: expected {expected_psa:.1f}%, got {computed_psa:.1f}%"
                )
    
    def test_cpr_to_psa_plateau_period(self):
        """Test CPR to PSA conversion during plateau period (months 31+)."""
        # Inverse: PSA = CPR * 100 / 6
        test_cases = [
            (6.0, 31, 100.0),   # 6.0 * 100 / 6
            (6.0, 60, 100.0),
            (9.0, 31, 150.0),   # 9.0 * 100 / 6
            (12.0, 31, 200.0),  # 12.0 * 100 / 6
            (3.0, 31, 50.0),    # 3.0 * 100 / 6
        ]
        
        for cpr, month, expected_psa in test_cases:
            with self.subTest(cpr=cpr, month=month, expected_psa=expected_psa):
                computed_psa = cpr_to_psa(cpr, month)
                self.assertAlmostEqual(
                    computed_psa, expected_psa, places=1,
                    msg=f"CPR {cpr}% at month {month} -> PSA: expected {expected_psa:.1f}%, got {computed_psa:.1f}%"
                )
    
    def test_cpr_to_psa_matches_table(self):
        """Verify CPR to PSA conversion at age 30+ against conversion table.
        
        Note: Table uses plateau formula (PSA = CPR * 100 / 6) for age 30+.
        The function cpr_to_psa uses effective_month = min(month, 30), so both
        month 30 and 31 use the ramp formula with month=30. Table values may have
        rounding differences, so we verify the formula matches rather than exact values.
        """
        for entry in PREPAY_CONVERSION_TABLE:
            with self.subTest(cpr_pct=entry['cpr_pct'], expected_psa30=entry['psa30']):
                # At age 30+, table uses plateau formula: PSA = CPR * 100 / 6
                # Function uses ramp formula: PSA = CPR * 500 / 30 (for month 30)
                # These are equivalent: CPR * 500 / 30 = CPR * 100 / 6
                computed_psa = cpr_to_psa(entry['cpr_pct'], month=30)
                expected_psa = entry['psa30']
                
                # Allow 1 unit tolerance due to rounding differences in table
                # (table may round CPR before converting to PSA)
                self.assertAlmostEqual(
                    computed_psa, expected_psa, delta=1.0,
                    msg=f"CPR {entry['cpr_pct']}% at month 30 -> PSA: expected {expected_psa:.0f}, got {computed_psa:.0f}"
                )
    
    def test_round_trip_psa_cpr(self):
        """Test round-trip conversion: PSA -> CPR -> PSA."""
        test_cases = [
            (100, 1), (100, 15), (100, 30), (100, 60),
            (150, 1), (150, 15), (150, 30), (150, 60),
            (200, 1), (200, 15), (200, 30), (200, 60),
        ]
        
        for psa_speed, month in test_cases:
            with self.subTest(psa_speed=psa_speed, month=month):
                cpr = psa_to_cpr(psa_speed, month)
                round_trip_psa = cpr_to_psa(cpr, month)
                
                self.assertAlmostEqual(
                    round_trip_psa, psa_speed, places=1,
                    msg=f"Round-trip PSA {psa_speed}% at month {month} -> CPR -> PSA: expected {psa_speed:.1f}%, got {round_trip_psa:.1f}%"
                )


class TestB2PsaCurveGeneration(unittest.TestCase):
    """Test PSA curve generation."""
    
    def test_generate_psa_curve_100_percent(self):
        """Test 100% PSA curve generation."""
        term = 360
        curve = generate_psa_curve(100, term)
        
        # Verify length
        self.assertEqual(len(curve), term + 1)
        
        # Verify ramp period
        self.assertAlmostEqual(curve[1], 0.2, places=1)   # Month 1: 0.2%
        self.assertAlmostEqual(curve[15], 3.0, places=1)  # Month 15: 3.0%
        self.assertAlmostEqual(curve[30], 6.0, places=1)   # Month 30: 6.0%
        
        # Verify plateau period
        self.assertAlmostEqual(curve[31], 6.0, places=1)   # Month 31: 6.0%
        self.assertAlmostEqual(curve[60], 6.0, places=1)   # Month 60: 6.0%
        self.assertAlmostEqual(curve[360], 6.0, places=1) # Month 360: 6.0%
    
    def test_generate_psa_curve_150_percent(self):
        """Test 150% PSA curve generation."""
        term = 360
        curve = generate_psa_curve(150, term)
        
        # Verify ramp period
        self.assertAlmostEqual(curve[1], 0.3, places=1)   # Month 1: 0.2% * 1.5
        self.assertAlmostEqual(curve[15], 4.5, places=1)  # Month 15: 3.0% * 1.5
        self.assertAlmostEqual(curve[30], 9.0, places=1)  # Month 30: 6.0% * 1.5
        
        # Verify plateau period
        self.assertAlmostEqual(curve[31], 9.0, places=1)   # Month 31: 6.0% * 1.5
        self.assertAlmostEqual(curve[60], 9.0, places=1)  # Month 60: 6.0% * 1.5
    
    def test_generate_psa_curve_matches_psa_to_cpr(self):
        """Verify curve generation matches individual PSA to CPR calls."""
        term = 360
        psa_speed = 100
        curve = generate_psa_curve(psa_speed, term)
        
        # Check several months
        test_months = [1, 15, 30, 31, 60, 120, 360]
        for month in test_months:
            with self.subTest(month=month):
                expected_cpr = psa_to_cpr(psa_speed, month)
                self.assertAlmostEqual(
                    curve[month], expected_cpr, places=DECIMAL_PLACES_FOR_PERCENT,
                    msg=f"Curve month {month}: expected {expected_cpr}%, got {curve[month]:.1f}%"
                )


class TestB2FullConversionChains(unittest.TestCase):
    """Test full conversion chains: SMM <-> CPR <-> PSA."""
    
    def test_smm_to_cpr_to_psa_chain(self):
        """Test conversion chain: SMM -> CPR -> PSA."""
        # Use conversion table entries
        for entry in PREPAY_CONVERSION_TABLE[:20]:  # Test first 20 entries
            with self.subTest(smm_pct=entry['smm_pct']):
                # SMM -> CPR
                cpr = smm_to_cpr(entry['smm_decimal'])
                self.assertAlmostEqual(cpr, entry['cpr_pct'], places=DECIMAL_PLACES_FOR_PERCENT)
                
                # CPR -> PSA (at age 30+)
                psa = cpr_to_psa(cpr, month=30)
                self.assertAlmostEqual(psa, entry['psa30'], places=0)
    
    def test_psa_to_cpr_to_smm_chain(self):
        """Test conversion chain: PSA -> CPR -> SMM."""
        # Test various PSA speeds at month 30+
        test_cases = [
            (100, 30, 6.0),   # 100% PSA -> 6% CPR
            (150, 30, 9.0),   # 150% PSA -> 9% CPR
            (200, 30, 12.0),  # 200% PSA -> 12% CPR
        ]
        
        for psa_speed, month, expected_cpr in test_cases:
            with self.subTest(psa_speed=psa_speed, month=month):
                # PSA -> CPR
                cpr = psa_to_cpr(psa_speed, month)
                self.assertAlmostEqual(cpr, expected_cpr, places=DECIMAL_PLACES_FOR_PERCENT)
                
                # CPR -> SMM (compute expected from CPR)
                smm = cpr_to_smm(cpr)
                expected_smm = cpr_to_smm(expected_cpr)
                self.assertAlmostEqual(smm, expected_smm, places=DECIMAL_PLACES_FOR_ASSERTIONS)
    
    def test_round_trip_smm_psa(self):
        """Test round-trip conversion: SMM -> CPR -> PSA -> CPR -> SMM."""
        test_smms = [0.0005, 0.001, 0.0025, 0.005, 0.01]
        
        for smm in test_smms:
            with self.subTest(smm=smm):
                # SMM -> CPR -> PSA (at age 30+)
                cpr = smm_to_cpr(smm)
                psa = cpr_to_psa(cpr, month=30)
                
                # PSA -> CPR -> SMM
                round_trip_cpr = psa_to_cpr(psa, month=30)
                round_trip_smm = cpr_to_smm(round_trip_cpr)
                
                self.assertAlmostEqual(
                    round_trip_smm, smm, places=DECIMAL_PLACES_FOR_ASSERTIONS,
                    msg=f"Round-trip SMM {smm:.6f} -> CPR -> PSA -> CPR -> SMM failed"
                )
    
    def test_psa_to_smm_via_conversion_table(self):
        """Test PSA to SMM conversion using 1m_PSAtoSMM_conversion.csv data."""
        if not PSA_TO_SMM_DATA:
            self.skipTest("PSA to SMM conversion data not loaded")
        
        # Test a sample of entries
        for entry in PSA_TO_SMM_DATA[:50]:  # Test first 50 entries
            with self.subTest(month=entry['month'], psa_speed=entry['psa_speed']):
                # PSA -> CPR -> SMM
                cpr = psa_to_cpr(entry['psa_speed'], entry['month'])
                computed_smm = cpr_to_smm(cpr)
                
                # Compare with table (allowing for rounding differences)
                expected_smm = entry['smm_decimal']
                # Allow 0.01% tolerance due to rounding in table
                self.assertAlmostEqual(
                    computed_smm, expected_smm, places=4,
                    msg=f"PSA {entry['psa_speed']}% at month {entry['month']} -> SMM: "
                        f"expected {expected_smm:.6f}, got {computed_smm:.6f}"
                )


if __name__ == '__main__':
    unittest.main()
