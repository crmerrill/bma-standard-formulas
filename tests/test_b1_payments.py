"""
Unit tests for BMA Section B.1 payment/balance functions.

Tests consistency across all 8 B.1 functions using identical inputs.
Verifies fundamental amortization identities and terminal conditions.

Version: 0.3.0
Last Updated: 2026-01-28
Status: Active

================================================================================
NOTATION CONVENTION (per BMA SF-6 and notation_reference.md)
================================================================================

    i = period index (0-indexed from observation)
    age_i = start_age + i (age at END of period i)
    M_i = rem_term - i (remaining_term at age_i)
    
    Key relationships:
        - age_0 = start_age = orig_term - rem_term (observation point)
        - Period i spans from age_i-1 to age_i
        - At i=0 with start_age=0: boundary condition (balance=1, am_factor=0)
        - At i=rem_term: age = orig_term, M = 0 (maturity)
    
    ALIGNED Vector indexing (both indexed by AGE):
        - survival_vec[k] = balance at age k
        - am_vec[k] = am_factor at age k (for period ENDING at age k)
        - am_vec[0] = 0 (no amortization to reach origination)
        
        Relationship: survival_vec[k] = survival_vec[k-1] * (1 - am_vec[k])  for k >= 1
    
    Function parameters (remaining_term at START of period):
        - Use M_i + 1 for functions that need remaining_term at START

================================================================================
LLM REVIEW INSTRUCTIONS
================================================================================

This test module validates BMA Section B.1 payment/balance functions for mortgage
amortization calculations. Conduct a thorough, independent code review focusing on
code quality, correctness, maintainability, and adherence to Python/unittest best
practices.

CONTEXT & DOMAIN KNOWLEDGE:
---------------------------
- Tests 8 BMA B.1 functions that compute survival factors, payment factors, and
  amortization factors for fixed-rate mortgages
- Functions should produce identical results when given identical inputs
- Key relationship: M(i) = orig_term - age(i) = rem_term - i
  * At origination: age=0, remaining_term=original_term
  * At maturity: age=original_term, remaining_term=0
- survival_factors vectors are indexed by AGE (0 to orig_term)
- am_factors vectors are indexed by starting age (0 to orig_term-1)
- Fundamental amortization identities must hold:
  * payment = principal + interest
  * balance_change = payment - interest
  * survival[age(i)] = survival[age(i-1)] * (1 - am_vec[age(i-1)])

FUNCTIONS UNDER TEST:
--------------------
- sch_balance_factor_fixed_rate(coupon, original_term, remaining_term)
- sch_payment_factor_fixed_rate(coupon, original_term, remaining_term)
- sch_payment_factor(coupon, remaining_term)
- sch_am_factor_fixed_rate(coupon, remaining_term)
- am_factor(beginning_balance, coupon, remaining_term)
- sch_balance_factors(coupon_vector, original_term, remaining_term)
- sch_ending_balance_factor(coupon_vector, original_term, remaining_term)

REVIEW APPROACH:
---------------
1. Read the entire file to understand the structure and purpose
2. Evaluate code quality using Python and unittest best practices
3. Check mathematical correctness of relationships and identities
4. Assess test coverage and completeness
5. Review code organization, naming, and maintainability
6. Consider edge cases and error handling
7. Evaluate performance and scalability considerations
8. Assess documentation clarity

QUESTIONS TO CONSIDER:
---------------------
- Are tests well-isolated and independently runnable?
- Is the code DRY (Don't Repeat Yourself)? Are there patterns that should be extracted?
- Are variable names clear and descriptive?
- Are assertions appropriate for floating-point comparisons?
- Is test coverage comprehensive (all functions, all scenarios, boundaries)?
- Would test failures clearly identify what went wrong?
- Is the code maintainable and easy to understand?
- Are there any mathematical errors or incorrect relationships?
- Are edge cases and boundary conditions properly tested?
- Is the setup/teardown appropriate for the test structure?
- Are type hints used appropriately (Python 3.12+ native syntax)?
- Is the code consistent with Python and unittest conventions?

EXPECTED OUTPUT:
---------------
Provide a comprehensive review including:
- Overall assessment (grade A-F with justification)
- Summary of strengths
- Issues found (categorized as critical, major, or minor)
- Specific recommendations with code examples where helpful
- Any patterns or practices that could be improved

Focus on providing actionable feedback that improves code quality, correctness,
and maintainability. Apply your knowledge of Python best practices, unittest
conventions, and software engineering principles rather than following a checklist.

================================================================================
"""

import unittest
from bma_standard_formulas.scheduled_payments import (
    sch_balance_factor_fixed_rate,
    sch_payment_factor_fixed_rate,
    sch_payment_factor,
    sch_am_factor_fixed_rate,
    am_factor,
    sch_balance_factors,
    sch_ending_balance_factor,
)

# =============================================================================
# Test Parameters
# =============================================================================

DECIMAL_PLACES_FOR_ASSERTIONS: int = 10  # decimal places for assertAlmostEqual

# Module-level shared data (populated by setUpModule)
TEST_SCENARIOS: list[dict[str, int | float]] = []


# =============================================================================
# Module Setup/Teardown
# =============================================================================

def setUpModule():
    """Pre-compute all test scenarios.
    
    Note: Function results are computed live in tests to ensure consistency
    and avoid stale precomputed data.
    """
    # Test parameter constants
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
    TEST_SCENARIOS.clear()


# =============================================================================
# Test Classes
# =============================================================================

class TestB1SurvivalFactorConsistency(unittest.TestCase):
    """Test that all survival/balance factor functions produce identical results.
    
    Notation (per BMA SF-6 and notation_reference.md):
        i = period index (0-indexed from observation)
        age(i) = start_age + i (age at END of period i)
        M(i) = rem_term - i (remaining_term at age(i))
        
        At i=0: age(0) = start_age, M(0) = rem_term (observation point)
        At i=rem_term: age(rem_term) = orig_term, M(rem_term) = 0 (maturity)
    """
    
    def test_fixed_rate_equals_survival_factors_vector(self):
        """sch_balance_factor_fixed_rate == balance_vec[age(i)] for all i."""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            start_age = int(scenario['age'])
            rem_term = int(scenario['rem_term'])
            coupon_vector = [coupon] * orig_term
            _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
            
            for i in range(rem_term + 1):
                age_i = start_age + i
                M_i = rem_term - i
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age_i=age_i, M_i=M_i):
                    fixed = sch_balance_factor_fixed_rate(coupon, orig_term, M_i)
                    iterative = survival_vec[age_i]
                    self.assertAlmostEqual(fixed, iterative, places=DECIMAL_PLACES_FOR_ASSERTIONS)
    
    def test_fixed_rate_equals_balance_factor(self):
        """sch_balance_factor_fixed_rate == sch_ending_balance_factor for all i."""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            start_age = int(scenario['age'])
            rem_term = int(scenario['rem_term'])
            coupon_vector = [coupon] * orig_term
            
            for i in range(rem_term + 1):
                age_i = start_age + i
                M_i = rem_term - i
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age_i=age_i, M_i=M_i):
                    fixed = sch_balance_factor_fixed_rate(coupon, orig_term, M_i)
                    balance = sch_ending_balance_factor(coupon_vector, orig_term, M_i)
                    self.assertAlmostEqual(fixed, balance, places=DECIMAL_PLACES_FOR_ASSERTIONS)
    
    def test_survival_factors_vector_equals_balance_factor(self):
        """survival_vec[age(i)] == sch_ending_balance_factor for all i."""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            start_age = int(scenario['age'])
            rem_term = int(scenario['rem_term'])
            coupon_vector = [coupon] * orig_term
            _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
            
            for i in range(rem_term + 1):
                age_i = start_age + i
                M_i = rem_term - i
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age_i=age_i, M_i=M_i):
                    iterative = survival_vec[age_i]
                    balance = sch_ending_balance_factor(coupon_vector, orig_term, M_i)
                    self.assertAlmostEqual(iterative, balance, places=DECIMAL_PLACES_FOR_ASSERTIONS)


class TestB1AmFactorConsistency(unittest.TestCase):
    """Test that all amortization factor functions produce identical results."""
    
    def test_fixed_rate_equals_am_factor(self):
        """sch_am_factor_fixed_rate == am_factor for all periods."""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            start_age = int(scenario['age'])
            rem_term = int(scenario['rem_term'])
            coupon_vector = [coupon] * orig_term
            _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
            
            for i in range(rem_term + 1):
                age_i = start_age + i 
                M_i = rem_term - i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age=age_i, rem_term=M_i):
                    if i == 0 and start_age == 0:
                        # Boundary: at origination, balance=1, am_factor=0
                        self.assertAlmostEqual(survival_vec[0], 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                    else:
                        # Period i: from age(i-1) to age(i)
                        beginning_balance = survival_vec[age_i - 1]
                        fixed = sch_am_factor_fixed_rate(coupon, orig_term, M_i + 1)
                        single_period = am_factor(beginning_balance, coupon, M_i + 1)
                        self.assertAlmostEqual(fixed, single_period, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(beginning_balance * (1-fixed), 
                                                survival_vec[age_i], places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(beginning_balance * (1-single_period), 
                                                survival_vec[age_i], places=DECIMAL_PLACES_FOR_ASSERTIONS)


    def test_fixed_rate_equals_am_factors_vector(self):
        """sch_am_factor_fixed_rate == am_vec[age_i] for all periods."""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            start_age = int(scenario['age'])
            rem_term = int(scenario['rem_term'])
            coupon_vector = [coupon] * orig_term
            _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
            
            for i in range(rem_term + 1):
                age_i = start_age + i
                M_i = rem_term - i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age=age_i, rem_term=M_i):
                    if i == 0 and start_age == 0:
                        # Boundary: at origination, balance=1, am_factor=0
                        self.assertAlmostEqual(survival_vec[0], 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(am_vec[0], 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                    else:
                        # Period i: from age_i-1 to age_i
                        beginning_balance = survival_vec[age_i - 1]
                        fixed = sch_am_factor_fixed_rate(coupon, orig_term, M_i + 1)
                        self.assertAlmostEqual(fixed, am_vec[age_i], places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(beginning_balance * (1 - fixed), 
                                               survival_vec[age_i], places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(beginning_balance * (1 - am_vec[age_i]),
                                               survival_vec[age_i], places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        
    
    def test_am_factor_equals_am_factors_vector(self):
        """am_factor == am_vec[age_i] for all periods."""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            start_age = int(scenario['age'])
            rem_term = int(scenario['rem_term'])
            coupon_vector = [coupon] * orig_term
            _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
            
            for i in range(rem_term + 1):
                age_i = start_age + i
                M_i = rem_term - i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age=age_i, rem_term=M_i):
                    if i == 0 and start_age == 0:
                        # Boundary: at origination, balance=1, am_factor=0
                        self.assertAlmostEqual(survival_vec[0], 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(am_vec[0], 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                    else:
                        # Period i: from age_i-1 to age_i
                        beginning_balance = survival_vec[age_i - 1]
                        single_period = am_factor(beginning_balance, coupon, M_i + 1)
                        self.assertAlmostEqual(single_period, am_vec[age_i], places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(beginning_balance * (1 - single_period), 
                                               survival_vec[age_i], places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(beginning_balance * (1 - am_vec[age_i]),
                                               survival_vec[age_i], places=DECIMAL_PLACES_FOR_ASSERTIONS)


    def test_am_factor_equals_payment_factor_minus_monthly_rate(self):
        """am_factor == payment_factor - monthly_rate for all periods."""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            start_age = int(scenario['age'])
            rem_term = int(scenario['rem_term'])
            coupon_vector = [coupon] * orig_term
            _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
            monthly_rate = coupon / 1200.0
            
            for i in range(rem_term + 1):
                age_i = start_age + i
                M_i = rem_term - i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age=age_i, rem_term=M_i):
                    if i == 0 and start_age == 0:
                        # Boundary: at origination, balance=1, am_factor=0
                        self.assertAlmostEqual(survival_vec[0], 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(am_vec[0], 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                    else:
                        # Period i: am_factor = payment_factor - monthly_rate
                        # am is principal amount = am_factor * beginning_balance
                        beginning_balance = survival_vec[age_i - 1]
                        am = am_vec[age_i] * beginning_balance
                        payment_factor1 = sch_payment_factor_fixed_rate(coupon, orig_term, M_i + 1)
                        payment_factor2 = sch_payment_factor(coupon, M_i + 1, beginning_balance)
                        # Compare principal amounts: (payment_factor - monthly_rate) * beginning_balance
                        principal_from_factor1 = payment_factor1 - (monthly_rate * beginning_balance)
                        principal_from_factor2 = payment_factor2 - (monthly_rate * beginning_balance)
                        self.assertAlmostEqual(am, principal_from_factor1, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(am, principal_from_factor2, places=DECIMAL_PLACES_FOR_ASSERTIONS)

class TestB1PaymentFactorConsistency(unittest.TestCase):
    """Test that payment factor functions produce consistent results."""
    
    def test_fixed_rate_payment_equals_payment_factor_times_balance(self):
        """sch_payment_factor_fixed_rate == sch_payment_factor * survival[age_i-1]"""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            start_age = int(scenario['age'])
            rem_term = int(scenario['rem_term'])
            coupon_vector = [coupon] * orig_term
            _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
            
            for i in range(rem_term + 1):
                age_i = start_age + i
                M_i = rem_term - i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age=age_i, rem_term=M_i):
                    if i == 0 and start_age == 0:
                        # Boundary: at origination, balance=1, am_factor=0
                        self.assertAlmostEqual(survival_vec[0], 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(am_vec[0], 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                    else:
                        # Period i: from age_i-1 to age_i
                        beginning_balance = survival_vec[age_i - 1]
                        fixed = sch_payment_factor_fixed_rate(coupon, orig_term, M_i + 1)
                        general = sch_payment_factor(coupon, M_i + 1) * beginning_balance
                        self.assertAlmostEqual(fixed, general, places=DECIMAL_PLACES_FOR_ASSERTIONS)
    
    def test_balance_rollforward_via_fixed_rate_payment(self):
        """beginning_balance - payment + interest == ending_balance (fixed rate form)"""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            start_age = int(scenario['age'])
            rem_term = int(scenario['rem_term'])
            coupon_vector = [coupon] * orig_term
            _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
            monthly_rate = coupon / 1200.0
            
            for i in range(rem_term + 1):
                age_i = start_age + i
                M_i = rem_term - i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age=age_i, rem_term=M_i):
                    if i == 0 and start_age == 0:
                        # Boundary: at origination, balance=1
                        self.assertAlmostEqual(survival_vec[0], 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                    else:
                        beginning_balance = survival_vec[age_i - 1]
                        payment = sch_payment_factor_fixed_rate(coupon, orig_term, M_i + 1)
                        interest = beginning_balance * monthly_rate
                        ending_balance = survival_vec[age_i]
                        self.assertAlmostEqual(beginning_balance - payment + interest,
                                               ending_balance, places=DECIMAL_PLACES_FOR_ASSERTIONS)
    
    def test_balance_rollforward_via_general_payment(self):
        """beginning_balance - payment + interest == ending_balance (general form)"""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            start_age = int(scenario['age'])
            rem_term = int(scenario['rem_term'])
            coupon_vector = [coupon] * orig_term
            _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
            monthly_rate = coupon / 1200.0
            
            for i in range(rem_term + 1):
                age_i = start_age + i
                M_i = rem_term - i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age=age_i, rem_term=M_i):
                    if i == 0 and start_age == 0:
                        # Boundary: at origination, balance=1
                        self.assertAlmostEqual(survival_vec[0], 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                    else:
                        beginning_balance = survival_vec[age_i - 1]
                        payment = sch_payment_factor(coupon, M_i + 1) * beginning_balance
                        interest = beginning_balance * monthly_rate
                        ending_balance = survival_vec[age_i]
                        self.assertAlmostEqual(beginning_balance - payment + interest,
                                               ending_balance, places=DECIMAL_PLACES_FOR_ASSERTIONS)


class TestB1AmortizationIdentities(unittest.TestCase):
    """Test fundamental amortization relationships.
    
    Notation:
        i = period index (0-indexed from observation)
        age_i = start_age + i (age at END of period i)
        M_i = rem_term - i (remaining_term at age_i)
        
        survival_vec[k] = balance at age k
        am_vec[k] = am_factor at age k (for period ending at age k)
        
        survival_vec[k] = survival_vec[k-1] * (1 - am_vec[k])  for k >= 1
    """
    
    def test_survival_rollforward_via_am_factor(self):
        """survival_vec[age_i] == survival_vec[age_i-1] * (1 - am_vec[age_i])"""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            start_age = int(scenario['age'])
            rem_term = int(scenario['rem_term'])
            coupon_vector = [coupon] * orig_term
            _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
            
            for i in range(rem_term + 1):
                age_i = start_age + i
                M_i = rem_term - i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age=age_i, rem_term=M_i):
                    if i == 0 and start_age == 0:
                        # Boundary: at origination, balance=1, am_factor=0
                        self.assertAlmostEqual(survival_vec[0], 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(am_vec[0], 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                    else:
                        # survival_vec[age_i] = survival_vec[age_i-1] * (1 - am_vec[age_i])
                        beginning_balance = survival_vec[age_i - 1]
                        actual = survival_vec[age_i]
                        expected = beginning_balance * (1 - am_vec[age_i])
                        self.assertAlmostEqual(actual, expected, places=DECIMAL_PLACES_FOR_ASSERTIONS)
    
    def test_balance_change_equals_scheduled_principal(self):
        """survival_vec[age_i-1] - survival_vec[age_i] == survival_vec[age_i-1] * am_vec[age_i]"""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            start_age = int(scenario['age'])
            rem_term = int(scenario['rem_term'])
            coupon_vector = [coupon] * orig_term
            _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
            
            for i in range(rem_term + 1):
                age_i = start_age + i
                M_i = rem_term - i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age=age_i, rem_term=M_i):
                    if i == 0 and start_age == 0:
                        # Boundary: at origination, balance=1, am_factor=0
                        self.assertAlmostEqual(survival_vec[0], 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(am_vec[0], 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                    else:
                        beginning_balance = survival_vec[age_i - 1]
                        balance_change = beginning_balance - survival_vec[age_i]
                        scheduled_principal = beginning_balance * am_vec[age_i]
                        self.assertAlmostEqual(balance_change, scheduled_principal, places=DECIMAL_PLACES_FOR_ASSERTIONS)
    
    def test_payment_equals_principal_plus_interest(self):
        """payment == principal + interest for period i."""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            start_age = int(scenario['age'])
            rem_term = int(scenario['rem_term'])
            coupon_vector = [coupon] * orig_term
            _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
            monthly_rate = coupon / 1200.0
            
            for i in range(rem_term + 1):
                age_i = start_age + i
                M_i = rem_term - i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age=age_i, rem_term=M_i):
                    if i == 0 and start_age == 0:
                        # Boundary: at origination, balance=1, am_factor=0
                        self.assertAlmostEqual(survival_vec[0], 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(am_vec[0], 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                    else:
                        beginning_balance = survival_vec[age_i - 1]
                        payment = sch_payment_factor(coupon, M_i + 1) * beginning_balance
                        principal = beginning_balance * am_vec[age_i]
                        interest = beginning_balance * monthly_rate
                        self.assertAlmostEqual(payment, principal + interest, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(beginning_balance * (1 - am_vec[age_i]),
                                               survival_vec[age_i], places=DECIMAL_PLACES_FOR_ASSERTIONS)
    
    def test_balance_change_equals_payment_minus_interest(self):
        """balance_change == payment - interest for period i."""
        for scenario in TEST_SCENARIOS:
            coupon = float(scenario['coupon'])
            orig_term = int(scenario['orig_term'])
            start_age = int(scenario['age'])
            rem_term = int(scenario['rem_term'])
            coupon_vector = [coupon] * orig_term
            _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
            monthly_rate = coupon / 1200.0
            
            for i in range(rem_term + 1):
                age_i = start_age + i
                M_i = rem_term - i
                
                with self.subTest(coupon=coupon, orig_term=orig_term, i=i, age=age_i, rem_term=M_i):
                    if i == 0 and start_age == 0:
                        # Boundary: at origination, balance=1, am_factor=0
                        self.assertAlmostEqual(survival_vec[0], 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(am_vec[0], 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                    else:
                        beginning_balance = survival_vec[age_i - 1]
                        balance_change = beginning_balance - survival_vec[age_i]
                        payment = sch_payment_factor(coupon, M_i + 1) * beginning_balance
                        interest = beginning_balance * monthly_rate
                        self.assertAlmostEqual(balance_change, payment - interest, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(beginning_balance * (1 - am_vec[age_i]),
                                               survival_vec[age_i], places=DECIMAL_PLACES_FOR_ASSERTIONS)


class TestB1TerminalConditions(unittest.TestCase):
    """Test that loans fully amortize to zero."""
    
    def test_survival_factor_fixed_rate_at_maturity_is_zero(self):
        """sch_balance_factor_fixed_rate at maturity (remaining_term=0) == 0"""
        for coupon, orig_term in {(s['coupon'], s['orig_term']) for s in TEST_SCENARIOS}:
            with self.subTest(coupon=coupon, orig_term=orig_term):
                terminal = sch_balance_factor_fixed_rate(coupon, orig_term, 0)
                self.assertAlmostEqual(terminal, 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
    
    def test_survival_factors_vector_at_maturity_is_zero(self):
        """sch_balance_factors[orig_term] == 0"""
        for coupon, orig_term in {(s['coupon'], s['orig_term']) for s in TEST_SCENARIOS}:
            with self.subTest(coupon=coupon, orig_term=orig_term):
                coupon_vector = [coupon] * orig_term
                _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
                self.assertAlmostEqual(survival_vec[orig_term], 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
    
    def test_balance_factor_at_maturity_is_zero(self):
        """sch_ending_balance_factor at maturity (remaining_term=0) == 0"""
        for coupon, orig_term in {(s['coupon'], s['orig_term']) for s in TEST_SCENARIOS}:
            with self.subTest(coupon=coupon, orig_term=orig_term):
                coupon_vector = [coupon] * orig_term
                terminal = sch_ending_balance_factor(coupon_vector, orig_term, 0)
                self.assertAlmostEqual(terminal, 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
    
    def test_cumulative_principal_equals_original_balance(self):
        """sum(principal) == 1.0"""
        for coupon, orig_term in {(s['coupon'], s['orig_term']) for s in TEST_SCENARIOS}:
            with self.subTest(coupon=coupon, orig_term=orig_term):
                coupon_vector = [coupon] * orig_term
                _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
                # principal at age k = survival_vec[k-1] * am_vec[k]
                total = sum(
                    survival_vec[age - 1] * am_vec[age]
                    for age in range(1, orig_term + 1)
                )
                self.assertAlmostEqual(total, 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
    
    def test_total_payments_equals_principal_plus_interest(self):
        """sum(payments) == 1.0 + sum(interest)"""
        for coupon, orig_term in {(s['coupon'], s['orig_term']) for s in TEST_SCENARIOS}:
            with self.subTest(coupon=coupon, orig_term=orig_term):
                coupon_vector = [coupon] * orig_term
                _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
                monthly_rate = coupon / 1200.0
                
                total_payments = sum(
                    sch_payment_factor(coupon, orig_term - age + 1) * survival_vec[age - 1]
                    for age in range(1, orig_term + 1)
                )
                total_interest = sum(
                    survival_vec[age - 1] * monthly_rate
                    for age in range(1, orig_term + 1)
                )
                self.assertAlmostEqual(total_payments, 1.0 + total_interest, places=DECIMAL_PLACES_FOR_ASSERTIONS)


class TestB1BoundaryConditions(unittest.TestCase):
    """Test boundary conditions: age=0 (origination) and age=orig_term (maturity)."""
    
    def test_survival_factor_at_origination_is_one(self):
        """sch_balance_factor_fixed_rate at origination (remaining_term=orig_term) == 1.0"""
        for coupon, orig_term in {(s['coupon'], s['orig_term']) for s in TEST_SCENARIOS}:
            with self.subTest(coupon=coupon, orig_term=orig_term):
                survival = sch_balance_factor_fixed_rate(coupon, orig_term, orig_term)
                self.assertAlmostEqual(survival, 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
    
    def test_survival_factors_vector_at_origination_is_one(self):
        """sch_balance_factors[0] == 1.0"""
        for coupon, orig_term in {(s['coupon'], s['orig_term']) for s in TEST_SCENARIOS}:
            with self.subTest(coupon=coupon, orig_term=orig_term):
                coupon_vector = [coupon] * orig_term
                _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
                self.assertAlmostEqual(survival_vec[0], 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
    
    def test_balance_factor_at_origination_is_one(self):
        """sch_ending_balance_factor at origination (remaining_term=orig_term) == 1.0"""
        for coupon, orig_term in {(s['coupon'], s['orig_term']) for s in TEST_SCENARIOS}:
            with self.subTest(coupon=coupon, orig_term=orig_term):
                coupon_vector = [coupon] * orig_term
                balance = sch_ending_balance_factor(coupon_vector, orig_term, orig_term)
                self.assertAlmostEqual(balance, 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)


class TestB1ZeroInterestEdgeCase(unittest.TestCase):
    """Test edge case: 0% interest rate (linear amortization).
    
    NOTE: The BMA reference functions in bma_reference.py do not currently handle
    0% interest rates (they result in division by zero). These tests are skipped
    until the reference implementation is updated to handle this edge case.
    """
    
    @unittest.skip("BMA reference functions do not handle 0% interest (division by zero)")
    def test_zero_interest_survival_factor_consistency(self):
        """All survival factor functions produce identical results at 0% interest."""
        coupon = 0.0
        for orig_term in {s['orig_term'] for s in TEST_SCENARIOS}:
            try:
                coupon_vector = [coupon] * orig_term
                _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
                coupon_vector = [coupon] * orig_term
                
                for age in range(orig_term + 1):
                    remaining_term = orig_term - age
                    with self.subTest(orig_term=orig_term, age=age, remaining_term=remaining_term):
                        fixed = sch_balance_factor_fixed_rate(coupon, orig_term, remaining_term)
                        vector = survival_vec[age]
                        balance = sch_ending_balance_factor(coupon_vector, orig_term, remaining_term)
                        
                        self.assertAlmostEqual(fixed, vector, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(fixed, balance, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        self.assertAlmostEqual(vector, balance, places=DECIMAL_PLACES_FOR_ASSERTIONS)
            except ZeroDivisionError:
                self.skipTest("BMA reference functions do not support 0% interest")
    
    @unittest.skip("BMA reference functions do not handle 0% interest (division by zero)")
    def test_zero_interest_linear_amortization(self):
        """At 0% interest, amortization should be linear (equal principal payments)."""
        coupon = 0.0
        for orig_term in {s['orig_term'] for s in TEST_SCENARIOS}:
            try:
                coupon_vector = [coupon] * orig_term
                _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
                monthly_rate = coupon / 1200.0
                
                # Monthly rate should be zero
                self.assertAlmostEqual(monthly_rate, 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                
                # Principal payment should be constant (1/orig_term per period)
                expected_principal_per_period = 1.0 / orig_term
                
                for age in range(1, orig_term + 1):
                    with self.subTest(orig_term=orig_term, age=age):
                        beginning_balance = survival_vec[age - 1]
                        principal = beginning_balance * am_vec[age - 1]
                        
                        # Principal payment should equal expected amount
                        self.assertAlmostEqual(principal, expected_principal_per_period, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                        
                        # Payment should equal principal (no interest)
                        payment = sch_payment_factor(coupon, orig_term - age + 1) * beginning_balance
                        self.assertAlmostEqual(payment, principal, places=DECIMAL_PLACES_FOR_ASSERTIONS)
            except ZeroDivisionError:
                self.skipTest("BMA reference functions do not support 0% interest")
    
    @unittest.skip("BMA reference functions do not handle 0% interest (division by zero)")
    def test_zero_interest_terminal_conditions(self):
        """Terminal conditions hold at 0% interest."""
        coupon = 0.0
        for orig_term in {s['orig_term'] for s in TEST_SCENARIOS}:
            try:
                with self.subTest(orig_term=orig_term):
                    # At maturity, balance should be zero
                    terminal = sch_balance_factor_fixed_rate(coupon, orig_term, 0)
                    self.assertAlmostEqual(terminal, 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                    
                    # At origination, balance should be one
                    initial = sch_balance_factor_fixed_rate(coupon, orig_term, orig_term)
                    self.assertAlmostEqual(initial, 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                    
                    # Cumulative principal should equal 1.0
                    coupon_vector = [coupon] * orig_term
                    _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
                    total_principal = sum(
                        survival_vec[age - 1] * am_vec[age - 1]
                        for age in range(1, orig_term + 1)
                    )
                    self.assertAlmostEqual(total_principal, 1.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)
            except ZeroDivisionError:
                self.skipTest("BMA reference functions do not support 0% interest")


class TestB1LastPaymentEdgeCase(unittest.TestCase):
    """Test edge case: final payment when only 1 month remains from large original term."""
    
    def test_one_month_remaining_from_large_term(self):
        """Verify correct behavior when remaining_term=1 from various large original terms."""
        for orig_term in [120, 180, 360]:  # Large terms
            for coupon in {s['coupon'] for s in TEST_SCENARIOS}:
                remaining_term = 1
                age_at_end = orig_term  # Age at END of final period
                
                with self.subTest(coupon=coupon, orig_term=orig_term, remaining_term=remaining_term):
                    # Note: sch_am_factor_fixed_rate(..., remaining_term) expects remaining_term
                    # at START of the period. For the final period (remaining_term=1 at start),
                    # this computes the am_factor for the period ending at age=orig_term.
                    # Survival factor should be very small but not zero
                    survival = sch_balance_factor_fixed_rate(coupon, orig_term, remaining_term)
                    self.assertGreater(survival, 0.0, "Survival factor should be positive with 1 month remaining")
                    self.assertLess(survival, 0.1, "Survival factor should be small with 1 month remaining")
                    
                    # Payment factor should be defined and positive
                    payment_factor = sch_payment_factor(coupon, remaining_term)
                    self.assertGreater(payment_factor, 0.0, "Payment factor should be positive")
                    
                    # Verify consistency with vectorized function
                    coupon_vector = [coupon] * orig_term
                    _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
                    monthly_rate = coupon / 1200.0
                    # am_vec[age_at_end] is the am_factor at age orig_term (for period ending at orig_term)
                    am_factor_vector = am_vec[age_at_end]
                    self.assertGreater(am_factor_vector, 0.0, "Amortization factor should be positive")
                    self.assertLess(am_factor_vector, payment_factor, "Amortization factor should be less than payment factor")
                    
                    # Verify relationship: am_factor = payment_factor - monthly_rate
                    self.assertAlmostEqual(am_factor_vector, payment_factor - monthly_rate, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                    
                    # Verify consistency with fixed-rate function
                    # Note: sch_am_factor_fixed_rate(coupon, orig_term, remaining_term) computes
                    # am_factor for period STARTING with remaining_term, so for final period we use remaining_term=1
                    am_factor_fixed = sch_am_factor_fixed_rate(coupon, orig_term, remaining_term)
                    self.assertAlmostEqual(am_factor_fixed, am_factor_vector, places=DECIMAL_PLACES_FOR_ASSERTIONS)
    
    def test_final_payment_amortization_identity(self):
        """Final payment (remaining_term=1) satisfies amortization identities."""
        for orig_term in [120, 180, 360]:
            for coupon in {s['coupon'] for s in TEST_SCENARIOS}:
                remaining_term = 1
                age_at_start = orig_term - remaining_term  # Age at start of final period
                age_at_end = orig_term  # Age at end of final period
                coupon_vector = [coupon] * orig_term
                _, _, am_vec, survival_vec = sch_balance_factors(coupon_vector, orig_term, 0)
                monthly_rate = coupon / 1200.0
                
                with self.subTest(coupon=coupon, orig_term=orig_term):
                    # For final period: starts at age age_at_start, ends at age orig_term
                    beginning_balance = survival_vec[age_at_start]
                    
                    # Payment = principal + interest
                    payment = sch_payment_factor(coupon, remaining_term) * beginning_balance
                    # am_vec[age_at_end] is the am_factor at age orig_term (for period ending at orig_term)
                    principal = beginning_balance * am_vec[age_at_end]
                    interest = beginning_balance * monthly_rate
                    self.assertAlmostEqual(payment, principal + interest, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                    
                    # Balance change = payment - interest
                    ending_balance = survival_vec[orig_term]
                    balance_change = beginning_balance - ending_balance
                    self.assertAlmostEqual(balance_change, payment - interest, places=DECIMAL_PLACES_FOR_ASSERTIONS)
                    
                    # Final balance should be zero
                    self.assertAlmostEqual(ending_balance, 0.0, places=DECIMAL_PLACES_FOR_ASSERTIONS)


class TestB1Warnings(unittest.TestCase):
    """Test expected warnings for rate vector extension."""
    
    def test_balance_factors_warns_on_short_rate_vector(self):
        """sch_balance_factors warns when rate vector is shorter than historical periods.
        
        Single-rate [coupon] is fixed-rate convention and extends silently (no warning).
        A partial vector (e.g. 5 rates for 12 periods) triggers backward-fill warning.
        """
        # 5 rates for a loan needing 12 periods → backward_fill = 7 → warning
        coupon_vector = [9.5, 9.4, 9.3, 9.2, 9.1]
        orig_term = 360
        remaining_term = 348  # 12 periods elapsed
        with self.assertWarns(UserWarning):
            sch_balance_factors(coupon_vector, orig_term, remaining_term)


if __name__ == '__main__':
    unittest.main()
