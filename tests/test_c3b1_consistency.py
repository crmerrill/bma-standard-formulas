"""
Unit tests for consistency between BMA Section C.3 and Section B.1 functions.

Tests that the high-level C.3 cashflow generation functions produce identical results
to the low-level B.1 payment/balance formulas when there are no prepayments
or defaults (0% CPR, 0% CDR).

This is a critical consistency check ensuring that:
- C.3 survival factors match B.1 survival factors
- C.3 scheduled payments match B.1 payment factors
- C.3 principal payments match B.1 amortization factors
- With 0% CPR/0% CDR, actual cashflows match scheduled cashflows

Version: 0.1.0
Last Updated: 2026-01-29
Status: Active

================================================================================
TEST APPROACH:
================================================================================
For each test scenario:
1. Generate C.3 scheduled cashflow (run_bma_scheduled_cashflow)
2. Generate C.3 actual cashflow with 0% CPR/0% CDR (run_bma_actual_cashflow)
3. Compute B.1 formulas directly (survival factors, payment factors, am factors)
4. Cross-reference all results to ensure consistency

================================================================================
TEST EXECUTION ORDER:
================================================================================
This module depends on:
- test_bma_reference_b1_payments.py (B.1 functions)
- test_bma_reference_c3_cashflows.py (C.3 functions)

Test execution order is controlled by test_suite_bma_compliance.py's load_tests protocol.
When running all tests via the test suite, prerequisites will run first.

To run this module alone, ensure prerequisites pass first:
    python -m unittest tests.laminarcf.bma_compliance.tests.test_bma_reference_b1_payments
    python -m unittest tests.laminarcf.bma_compliance.tests.test_bma_reference_c3_cashflows
    python -m unittest tests.laminarcf.bma_compliance.tests.test_bma_reference_c3b1_consistency

Or run all tests together (recommended):
    python -m unittest tests.laminarcf.bma_compliance.tests.test_suite_bma_compliance

================================================================================
"""

import unittest
import numpy as np
from bma_standard_formulas.scheduled_payments import (
    sch_balance_factor_fixed_rate,
    sch_payment_factor_fixed_rate,
    sch_payment_factor,
    sch_am_factor_fixed_rate,
    sch_balance_factors,
)
from bma_standard_formulas.cashflows import (
    run_bma_scheduled_cashflow,
    run_bma_actual_cashflow,
)

# =============================================================================
# Test Parameters
# =============================================================================

ORIGINAL_BALANCE: float = 1.0  # Normalized balance for factor comparisons
DECIMAL_PLACES_FOR_ASSERTIONS: int = 10  # Precision for floating-point comparisons

# Test scenarios - same as test_bma_reference_b1_payments.py
TEST_SCENARIOS: list[dict[str, int | float]] = []


# =============================================================================
# Module Setup/Teardown
# =============================================================================

def setUpModule():
    """Pre-compute all test scenarios.
    
    Uses the same test parameter generation logic as test_bma_reference_b1_payments.py
    to ensure consistency across test modules.
    """
    # Test parameter constants (same as B.1 test module)
    coupons = [9.5, 9.0, 8.0]  # Annual rates as percentages (e.g., 9.5 for 9.5%)
    terms = {
        36:  [36, 27, 18, 9, 1],
        60:  [60, 45, 30, 15, 1],
        120: [120, 90, 60, 30, 1],
        180: [180, 135, 90, 45, 1],
        360: [360, 270, 180, 90, 1],
    }
    # Keys are original terms, values are remaining terms to test for each original term
    
    # Build all test scenarios
    for coupon in coupons:
        for orig_term, rem_term_list in terms.items():
            for rem_term in rem_term_list:
                age = orig_term - rem_term
                TEST_SCENARIOS.append({
                    'coupon': coupon,
                    'orig_term': orig_term,
                    'rem_term': rem_term,
                    'age': age,
                })
    
    # Validate that scenarios were created
    if not TEST_SCENARIOS:
        raise RuntimeError("setUpModule failed: No test scenarios were created")


def tearDownModule():
    """Clean up module-level data."""
    pass


# =============================================================================
# Test Classes
# =============================================================================

class TestB1C3SurvivalFactorConsistency(unittest.TestCase):
    """Test that B.1 survival factors match C.3 scheduled cashflow survival factors."""
    
    
    def test_survival_factor_matches_scheduled_cashflow(self):
        """B.1 survival factors should match C.3 scheduled cashflow survival factors."""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            rem_term = int(scenario['rem_term'])
            age = int(scenario['age'])
            
            # Generate scheduled cashflow
            # current_balance should be the balance at the starting age (age = orig_term - rem_term)
            # This is the balance when rem_term months remain
            starting_balance = sch_balance_factor_fixed_rate(coupon, orig_term, rem_term) * ORIGINAL_BALANCE
            scheduled = run_bma_scheduled_cashflow(
                original_balance=ORIGINAL_BALANCE,
                current_balance=starting_balance,
                coupon=coupon / 100.0,  # Convert percentage to decimal
                original_term=orig_term,
                remaining_term=rem_term,
            )
            
            # Compare survival factors for each period
            for i in range(rem_term + 1):
                age_i = age + i
                M_i = rem_term - i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age_i=age_i, M_i=M_i):
                    # B.1 survival factor
                    b1_survival = sch_balance_factor_fixed_rate(coupon, orig_term, M_i)
                    
                    # C.3 survival factor from scheduled cashflow
                    # survival_factor = pool_factor / amortized_balance_fraction
                    # With no prepays, pool_factor = amortized_balance_fraction, so survival_factor = 1.0
                    # But we should check pool_factor matches the survival factor concept
                    c3_pool_factor = scheduled.pool_factor[i]
                    c3_amortized_bal = scheduled.amortized_balance_fraction[i]
                    
                    # For scheduled (no prepays), survival_factor should be 1.0
                    # and pool_factor should equal amortized_balance_fraction
                    # The B.1 survival factor represents BAL(M_i) / BAL(M_0)
                    # which equals ending_balance[i] / original_balance
                    c3_survival_equivalent = scheduled.ending_balance[i] / ORIGINAL_BALANCE
                    
                    self.assertAlmostEqual(
                        b1_survival, c3_survival_equivalent, places=DECIMAL_PLACES_FOR_ASSERTIONS,
                        msg=f"Survival factor mismatch at period {i}: B.1={b1_survival:.10f}, C.3={c3_survival_equivalent:.10f}"
                    )
                    
                    # With no prepays, pool_factor should equal amortized_balance_fraction
                    self.assertAlmostEqual(
                        c3_pool_factor, c3_amortized_bal, places=DECIMAL_PLACES_FOR_ASSERTIONS,
                        msg=f"Pool factor should equal amortized balance (no prepays) at period {i}"
                    )


class TestB1C3PaymentFactorConsistency(unittest.TestCase):
    """Test that B.1 payment factors match C.3 scheduled cashflow payments."""
    
    
    def test_payment_factor_matches_scheduled_payment(self):
        """B.1 payment factors should match C.3 scheduled payments."""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            rem_term = int(scenario['rem_term'])
            
            # Generate scheduled cashflow
            # current_balance should be the balance at the starting age (age = orig_term - rem_term)
            # This is the balance when rem_term months remain
            starting_balance = sch_balance_factor_fixed_rate(coupon, orig_term, rem_term) * ORIGINAL_BALANCE
            scheduled = run_bma_scheduled_cashflow(
                original_balance=ORIGINAL_BALANCE,
                current_balance=starting_balance,
                coupon=coupon / 100.0,  # Convert percentage to decimal
                original_term=orig_term,
                remaining_term=rem_term,
            )
            
            # Compare payment factors for each period
            for i in range(1, rem_term + 1):  # Skip period 0 (no payment)
                M_i = rem_term - i + 1  # Remaining term at START of period i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, M_i=M_i):
                    # C.3 scheduled payment (as dollar amount)
                    c3_scheduled_payment = scheduled.scheduled_payment[i]
                    c3_beginning_balance = scheduled.beginning_balance[i]
                    
                    # Payment factor should equal payment / beginning_balance
                    # Use general payment factor (AF(M)) which is normalized to current balance
                    if c3_beginning_balance > 0:
                        c3_payment_factor = c3_scheduled_payment / c3_beginning_balance
                        b1_payment_factor = sch_payment_factor(coupon, M_i)  # AF(M) - payment factor per dollar of current balance
                        
                        self.assertAlmostEqual(
                            b1_payment_factor, c3_payment_factor, places=DECIMAL_PLACES_FOR_ASSERTIONS,
                            msg=f"Payment factor mismatch at period {i}: B.1={b1_payment_factor:.10f}, C.3={c3_payment_factor:.10f}"
                        )


class TestB1C3AmortizationFactorConsistency(unittest.TestCase):
    """Test that B.1 amortization factors match C.3 scheduled principal payments."""
    
    
    def test_am_factor_matches_scheduled_principal(self):
        """B.1 amortization factors should match C.3 scheduled principal payments."""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            rem_term = int(scenario['rem_term'])
            
            # Generate scheduled cashflow
            # current_balance should be the balance at the starting age (age = orig_term - rem_term)
            # This is the balance when rem_term months remain
            starting_balance = sch_balance_factor_fixed_rate(coupon, orig_term, rem_term) * ORIGINAL_BALANCE
            scheduled = run_bma_scheduled_cashflow(
                original_balance=ORIGINAL_BALANCE,
                current_balance=starting_balance,
                coupon=coupon / 100.0,  # Convert percentage to decimal
                original_term=orig_term,
                remaining_term=rem_term,
            )
            
            # Compare amortization factors for each period
            for i in range(1, rem_term + 1):  # Skip period 0 (no amortization)
                M_i = rem_term - i + 1  # Remaining term at START of period i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, M_i=M_i):
                    # B.1 amortization factor
                    b1_am_factor = sch_am_factor_fixed_rate(coupon, orig_term, M_i)
                    
                    # C.3 scheduled principal payment
                    c3_principal_paid = scheduled.principal_paid[i]
                    c3_beginning_balance = scheduled.beginning_balance[i]
                    
                    # Amortization factor should equal principal / beginning_balance
                    if c3_beginning_balance > 0:
                        c3_am_factor = c3_principal_paid / c3_beginning_balance
                        
                        self.assertAlmostEqual(
                            b1_am_factor, c3_am_factor, places=DECIMAL_PLACES_FOR_ASSERTIONS,
                            msg=f"Amortization factor mismatch at period {i}: B.1={b1_am_factor:.10f}, C.3={c3_am_factor:.10f}"
                        )


class TestB1C3BalanceConsistency(unittest.TestCase):
    """Test that B.1 balance calculations match C.3 scheduled balances."""
    
    
    def test_balance_rollforward_consistency(self):
        """B.1 survival factors should match C.3 balance rollforward."""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            rem_term = int(scenario['rem_term'])
            
            # Generate scheduled cashflow
            # current_balance should be the balance at the starting age (age = orig_term - rem_term)
            # This is the balance when rem_term months remain
            starting_balance = sch_balance_factor_fixed_rate(coupon, orig_term, rem_term) * ORIGINAL_BALANCE
            scheduled = run_bma_scheduled_cashflow(
                original_balance=ORIGINAL_BALANCE,
                current_balance=starting_balance,
                coupon=coupon / 100.0,
                original_term=orig_term,
                remaining_term=rem_term,
            )
            
            # Compare balances using B.1 survival factors
            for i in range(rem_term + 1):
                M_i = rem_term - i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, M_i=M_i):
                    # B.1 survival factor gives balance as fraction of par
                    b1_balance = sch_balance_factor_fixed_rate(coupon, orig_term, M_i) * ORIGINAL_BALANCE
                    
                    # C.3 ending balance
                    c3_balance = scheduled.ending_balance[i]
                    
                    self.assertAlmostEqual(
                        b1_balance, c3_balance, places=DECIMAL_PLACES_FOR_ASSERTIONS,
                        msg=f"Balance mismatch at period {i}: B.1={b1_balance:.10f}, C.3={c3_balance:.10f}"
                    )


class TestC3ScheduledActualConsistency(unittest.TestCase):
    """Test that C.3 scheduled and actual cashflows match with 0% CPR/0% CDR."""
    
    
    def test_scheduled_matches_actual_with_zero_prepays_defaults(self):
        """With 0% CPR and 0% CDR, actual cashflow should match scheduled cashflow."""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            rem_term = int(scenario['rem_term'])
            
            # Generate scheduled cashflow
            # current_balance should be the balance at the starting age (age = orig_term - rem_term)
            # This is the balance when rem_term months remain
            starting_balance = sch_balance_factor_fixed_rate(coupon, orig_term, rem_term) * ORIGINAL_BALANCE
            scheduled = run_bma_scheduled_cashflow(
                original_balance=ORIGINAL_BALANCE,
                current_balance=starting_balance,
                coupon=coupon / 100.0,
                original_term=orig_term,
                remaining_term=rem_term,
            )
            
            # Generate actual cashflow with 0% CPR and 0% CDR
            periods = rem_term + 1
            zero_smm_curve = np.zeros(periods)
            zero_mdr_curve = np.zeros(periods)
            zero_severity_curve = np.zeros(periods)
            
            actual = run_bma_actual_cashflow(
                scheduled_cf=scheduled,
                smm_curve=zero_smm_curve,
                mdr_curve=zero_mdr_curve,
                severity_curve=zero_severity_curve,
                severity_lag=12,
                coupon=coupon / 100.0,
            )
            
            # Compare key fields
            for i in range(periods):
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i):
                    # Performing balance should equal scheduled ending balance
                    self.assertAlmostEqual(
                        actual.perf_bal[i], scheduled.ending_balance[i], places=DECIMAL_PLACES_FOR_ASSERTIONS,
                        msg=f"Performing balance mismatch at period {i}"
                    )
                    
                    # No defaults or prepayments
                    self.assertAlmostEqual(
                        actual.new_def[i], 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS,
                        msg=f"New defaults should be zero at period {i}"
                    )
                    self.assertAlmostEqual(
                        actual.vol_prepay[i], 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS,
                        msg=f"Voluntary prepayments should be zero at period {i}"
                    )
                    self.assertAlmostEqual(
                        actual.fcl[i], 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS,
                        msg=f"Foreclosure should be zero at period {i}"
                    )
                    
                    # Actual amortization should equal scheduled principal paid
                    if i > 0:
                        self.assertAlmostEqual(
                            actual.act_am[i], scheduled.principal_paid[i], places=DECIMAL_PLACES_FOR_ASSERTIONS,
                            msg=f"Actual amortization mismatch at period {i}"
                        )
                        
                        # Expected interest should equal scheduled interest paid
                        self.assertAlmostEqual(
                            actual.exp_int[i], scheduled.interest_paid[i], places=DECIMAL_PLACES_FOR_ASSERTIONS,
                            msg=f"Expected interest mismatch at period {i}"
                        )
                        
                        # No lost interest
                        self.assertAlmostEqual(
                            actual.lost_int[i], 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS,
                            msg=f"Lost interest should be zero at period {i}"
                        )
                        
                        # Actual interest should equal expected interest
                        self.assertAlmostEqual(
                            actual.act_int[i], actual.exp_int[i], places=DECIMAL_PLACES_FOR_ASSERTIONS,
                            msg=f"Actual interest should equal expected interest at period {i}"
                        )


class TestB1C3VectorConsistency(unittest.TestCase):
    """Test that B.1 vectorized functions match C.3 cashflow arrays."""
    
    
    def test_survival_factors_vector_matches_scheduled_cashflow(self):
        """B.1 survival factors vector should match C.3 scheduled cashflow balances."""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            rem_term = int(scenario['rem_term'])
            age = int(scenario['age'])
            
            # Generate scheduled cashflow
            # current_balance should be the balance at the starting age (age = orig_term - rem_term)
            # This is the balance when rem_term months remain
            starting_balance = sch_balance_factor_fixed_rate(coupon, orig_term, rem_term) * ORIGINAL_BALANCE
            scheduled = run_bma_scheduled_cashflow(
                original_balance=ORIGINAL_BALANCE,
                current_balance=starting_balance,
                coupon=coupon / 100.0,
                original_term=orig_term,
                remaining_term=rem_term,
            )
            
            # Generate B.1 balance factors vector
            coupon_vector = [coupon] * orig_term
            _, _, am_vec, balance_vec = sch_balance_factors(coupon_vector, orig_term, 0)
            
            # Compare balance factors
            for i in range(rem_term + 1):
                age_i = age + i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age_i=age_i):
                    # B.1 survival factor from vector
                    b1_balance = balance_vec[age_i]
                    
                    # C.3 balance as fraction of original
                    c3_survival = scheduled.ending_balance[i] / ORIGINAL_BALANCE
                    
                    self.assertAlmostEqual(
                        b1_balance, c3_survival, places=DECIMAL_PLACES_FOR_ASSERTIONS,
                        msg=f"Survival factor vector mismatch at period {i}"
                    )
            
            # Compare amortization factors
            for i in range(1, rem_term + 1):
                age_i = age + i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age_i=age_i):
                    # B.1 amortization factor from vector
                    b1_am = am_vec[age_i]
                    
                    # C.3 amortization factor
                    if scheduled.beginning_balance[i] > 0:
                        c3_am = scheduled.principal_paid[i] / scheduled.beginning_balance[i]
                        
                        self.assertAlmostEqual(
                            b1_am, c3_am, places=DECIMAL_PLACES_FOR_ASSERTIONS,
                            msg=f"Amortization factor vector mismatch at period {i}"
                        )


if __name__ == '__main__':
    unittest.main()
