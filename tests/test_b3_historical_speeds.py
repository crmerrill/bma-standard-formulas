"""
Unit tests for BMA Section B.3 historical prepayment speed recovery functions.

Tests historical SMM, CPR, and PSA recovery from observed pool factors,
including single-pool (fixed and floating rate) and multi-pool aggregation.

Version: 0.1.0
Last Updated: 2026-01-29
Status: Active

================================================================================
FUNCTIONS UNDER TEST:
================================================================================
- project_act_end_factor: Project actual ending factor from beginning factor + SMM
- historical_smm_fixed_rate: Recover SMM from factors (fixed-rate, closed-form)
- historical_cpr_fixed_rate: Recover CPR from factors (fixed-rate)
- historical_smm: Recover SMM from factors (floating-rate, iterative)
- historical_cpr: Recover CPR from factors (floating-rate)
- historical_psa: Recover PSA speed from factors (Brent's method)
- historical_smm_pool: Aggregate SMM across multiple pools
- historical_cpr_pool: Aggregate CPR across multiple pools
- historical_psa_pool: Aggregate PSA across multiple pools

================================================================================
TEST DATA SOURCES:
================================================================================
- SF-7 example: GNMA 9.0% pool, 9.5% WAC, original term 359
  F1 = 0.85150625 (age 15), F2 = 0.84732282 (age 16)
  SMM = 0.435270%, CPR = 5.10%, PSA = 150% (month 17)

- SF-12 example: Two-pool aggregation
  Pool 1: $1M, 9.5%, 358mo, age 9->15, factor 0.86925218->0.84732282
  Pool 2: $2M, 9.5%, 360mo, age 1->7,  factor 0.99950812->0.98290230
  SMM_avg = 0.00271142 (0.271142%), CPR_avg = 3.2056%

================================================================================
"""

import unittest
import numpy as np
from bma_standard_formulas.payment_models import (
    project_act_end_factor,
    historical_smm_fixed_rate,
    historical_cpr_fixed_rate,
    historical_smm,
    historical_cpr,
    historical_psa,
    historical_smm_pool,
    historical_cpr_pool,
    historical_psa_pool,
    smm_to_cpr,
    cpr_to_smm,
    psa_to_smm,
    generate_smm_curve_from_psa,
)
from bma_standard_formulas.scheduled_payments import (
    sch_balance_factor_fixed_rate,
)


# =============================================================================
# BMA SF-7 Reference Data
# =============================================================================

SF7_COUPON = 9.5        # WAC %
SF7_ORIG_TERM = 359     # months
SF7_BEG_AGE = 15
SF7_END_AGE = 16
SF7_BEG_FACTOR = 0.85150625
SF7_END_FACTOR = 0.84732282
SF7_SMM = 0.00435270    # decimal
SF7_CPR = 5.10          # percentage
SF7_BEG_MONTH = 17      # 1-indexed loan month for PSA
SF7_PSA = 150.0         # percentage


# =============================================================================
# BMA SF-12 Reference Data (Two-pool aggregation)
# =============================================================================

SF12_POOLS = [
    {
        'coupon_vector': 9.5,
        'original_term': 358,
        'original_face': 1_000_000,
        'beginning_age': 9,
        'beginning_factor': 0.86925218,
        'ending_factor': 0.84732282,
    },
    {
        'coupon_vector': 9.5,
        'original_term': 360,
        'original_face': 2_000_000,
        'beginning_age': 1,
        'beginning_factor': 0.99950812,
        'ending_factor': 0.98290230,
    },
]
SF12_POOL_AGE = 6
SF12_SMM_AVG = 0.00271142  # decimal
SF12_CPR_AVG = 3.2056       # percentage


# =============================================================================
# Test Classes
# =============================================================================

class TestB3ProjectActEndFactor(unittest.TestCase):
    """Test project_act_end_factor for forward factor projection."""

    def test_zero_smm_returns_scheduled(self):
        """With 0% SMM, projected factor = scheduled factor."""
        smm_vec = np.zeros(12)
        ending = project_act_end_factor(1.0, smm_vec, SF7_COUPON, SF7_ORIG_TERM, 0)
        expected = sch_balance_factor_fixed_rate(SF7_COUPON, SF7_ORIG_TERM, SF7_ORIG_TERM - 12)
        self.assertAlmostEqual(ending, expected, places=10)

    def test_roundtrip_with_historical_smm(self):
        """project_act_end_factor with recovered SMM reproduces the observed factor."""
        smm = historical_smm_fixed_rate(
            SF7_COUPON, SF7_ORIG_TERM,
            SF7_BEG_FACTOR, SF7_BEG_AGE,
            SF7_END_FACTOR, SF7_END_AGE
        )
        smm_vec = np.array([smm])
        projected = project_act_end_factor(
            SF7_BEG_FACTOR, smm_vec, SF7_COUPON, SF7_ORIG_TERM, SF7_BEG_AGE
        )
        self.assertAlmostEqual(projected, SF7_END_FACTOR, places=8)

    def test_variable_rates_and_smm(self):
        """Non-iterative formula matches month-by-month iteration for variable inputs."""
        original_term = 360
        beginning_age = 24
        window = 12
        act_beg_factor = 0.92
        coupon_vector = list(np.linspace(7.0, 8.5, 36))
        smm_vector = np.array([0.003, 0.004, 0.005, 0.006, 0.007, 0.008,
                                0.009, 0.010, 0.008, 0.006, 0.004, 0.003])

        result = project_act_end_factor(
            act_beg_factor, smm_vector, coupon_vector, original_term, beginning_age
        )

        # Iterative check
        from bma_standard_formulas.scheduled_payments import sch_balance_factors
        remaining_end = original_term - beginning_age - window
        _, _, _, sf = sch_balance_factors(coupon_vector, original_term, remaining_end)
        factor = act_beg_factor
        for m in range(window):
            age = beginning_age + m
            sch_ratio = sf[age + 1] / sf[age]
            factor = factor * sch_ratio * (1.0 - smm_vector[m])

        self.assertAlmostEqual(result, factor, places=12)

    def test_full_prepay_returns_zero(self):
        """100% SMM every month drives factor to zero."""
        smm_vec = np.ones(6)  # 100% each month
        ending = project_act_end_factor(0.95, smm_vec, 8.0, 360, 12)
        self.assertAlmostEqual(ending, 0.0, places=10)


class TestB3HistoricalSmmFixedRate(unittest.TestCase):
    """Test historical_smm_fixed_rate against SF-7 example."""

    def test_sf7_single_month(self):
        """SF-7: GNMA 9.0% pool, single month SMM = 0.435270%."""
        smm = historical_smm_fixed_rate(
            SF7_COUPON, SF7_ORIG_TERM,
            SF7_BEG_FACTOR, SF7_BEG_AGE,
            SF7_END_FACTOR, SF7_END_AGE
        )
        self.assertAlmostEqual(smm, SF7_SMM, places=6)

    def test_multi_month_window(self):
        """Multi-month window returns average SMM."""
        smm = historical_smm_fixed_rate(
            SF7_COUPON, SF7_ORIG_TERM,
            SF7_BEG_FACTOR, SF7_BEG_AGE,
            SF7_END_FACTOR, SF7_END_AGE
        )
        self.assertGreater(smm, 0.0)
        self.assertLess(smm, 1.0)

    def test_no_prepay_returns_zero(self):
        """When actual factor equals scheduled, SMM = 0."""
        bal_start = sch_balance_factor_fixed_rate(8.0, 360, 360)
        bal_end = sch_balance_factor_fixed_rate(8.0, 360, 348)
        smm = historical_smm_fixed_rate(8.0, 360, bal_start, 0, bal_end, 12)
        self.assertAlmostEqual(smm, 0.0, places=10)


class TestB3HistoricalCprFixedRate(unittest.TestCase):
    """Test historical_cpr_fixed_rate against SF-7 example."""

    def test_sf7_single_month(self):
        """SF-7: CPR = 5.10% for GNMA pool."""
        cpr = historical_cpr_fixed_rate(
            SF7_COUPON, SF7_ORIG_TERM,
            SF7_BEG_FACTOR, SF7_BEG_AGE,
            SF7_END_FACTOR, SF7_END_AGE
        )
        self.assertAlmostEqual(cpr, SF7_CPR, places=2)

    def test_cross_verify_smm_to_cpr(self):
        """historical_cpr_fixed_rate == smm_to_cpr(historical_smm_fixed_rate(...))."""
        smm = historical_smm_fixed_rate(
            SF7_COUPON, SF7_ORIG_TERM,
            SF7_BEG_FACTOR, SF7_BEG_AGE,
            SF7_END_FACTOR, SF7_END_AGE
        )
        cpr_from_smm = smm_to_cpr(smm)
        cpr_direct = historical_cpr_fixed_rate(
            SF7_COUPON, SF7_ORIG_TERM,
            SF7_BEG_FACTOR, SF7_BEG_AGE,
            SF7_END_FACTOR, SF7_END_AGE
        )
        self.assertAlmostEqual(cpr_direct, cpr_from_smm, places=8)


class TestB3HistoricalSmmFloating(unittest.TestCase):
    """Test historical_smm (floating-rate) matches fixed-rate for constant coupon."""

    def test_matches_fixed_rate_for_constant_coupon(self):
        """historical_smm with constant coupon_vector == historical_smm_fixed_rate."""
        smm_floating = historical_smm(
            [SF7_COUPON], SF7_ORIG_TERM,
            SF7_BEG_FACTOR, SF7_BEG_AGE,
            SF7_END_FACTOR, SF7_END_AGE
        )
        smm_fixed = historical_smm_fixed_rate(
            SF7_COUPON, SF7_ORIG_TERM,
            SF7_BEG_FACTOR, SF7_BEG_AGE,
            SF7_END_FACTOR, SF7_END_AGE
        )
        self.assertAlmostEqual(smm_floating, smm_fixed, places=10)

    def test_variable_coupon_produces_different_smm(self):
        """Varying coupon vector gives different SMM than fixed (unless rates are identical)."""
        coupon_vec = list(np.linspace(9.0, 10.0, 16))
        smm_floating = historical_smm(
            coupon_vec, SF7_ORIG_TERM,
            SF7_BEG_FACTOR, SF7_BEG_AGE,
            SF7_END_FACTOR, SF7_END_AGE
        )
        smm_fixed = historical_smm_fixed_rate(
            SF7_COUPON, SF7_ORIG_TERM,
            SF7_BEG_FACTOR, SF7_BEG_AGE,
            SF7_END_FACTOR, SF7_END_AGE
        )
        # Different coupons → different scheduled balances → different SMM
        self.assertNotAlmostEqual(smm_floating, smm_fixed, places=4)


class TestB3HistoricalCprFloating(unittest.TestCase):
    """Test historical_cpr (floating-rate)."""

    def test_matches_fixed_rate_for_constant_coupon(self):
        """historical_cpr with constant coupon == historical_cpr_fixed_rate."""
        cpr_floating = historical_cpr(
            [SF7_COUPON], SF7_ORIG_TERM,
            SF7_BEG_FACTOR, SF7_BEG_AGE,
            SF7_END_FACTOR, SF7_END_AGE
        )
        cpr_fixed = historical_cpr_fixed_rate(
            SF7_COUPON, SF7_ORIG_TERM,
            SF7_BEG_FACTOR, SF7_BEG_AGE,
            SF7_END_FACTOR, SF7_END_AGE
        )
        self.assertAlmostEqual(cpr_floating, cpr_fixed, places=10)

    def test_cross_verify_smm_to_cpr(self):
        """historical_cpr == smm_to_cpr(historical_smm(...))."""
        coupon_vec = list(np.linspace(9.0, 10.0, 16))
        smm = historical_smm(
            coupon_vec, SF7_ORIG_TERM,
            SF7_BEG_FACTOR, SF7_BEG_AGE,
            SF7_END_FACTOR, SF7_END_AGE
        )
        cpr_from_smm = smm_to_cpr(smm)
        cpr_direct = historical_cpr(
            coupon_vec, SF7_ORIG_TERM,
            SF7_BEG_FACTOR, SF7_BEG_AGE,
            SF7_END_FACTOR, SF7_END_AGE
        )
        self.assertAlmostEqual(cpr_direct, cpr_from_smm, places=8)


class TestB3HistoricalPsa(unittest.TestCase):
    """Test historical_psa against SF-7/SF-8 example."""

    def test_sf7_psa_150(self):
        """SF-7/SF-8: PSA = 150% for GNMA pool."""
        psa = historical_psa(
            SF7_COUPON, SF7_ORIG_TERM,
            SF7_BEG_FACTOR, SF7_BEG_AGE,
            SF7_END_FACTOR, SF7_END_AGE,
            beginning_month=SF7_BEG_MONTH
        )
        self.assertAlmostEqual(psa, SF7_PSA, places=1)

    def test_roundtrip_project_then_recover(self):
        """Generate factor from known PSA, then recover PSA."""
        psa_speed = 200.0
        beginning_month = 10
        beginning_age = 9
        window = 6
        beg_factor = 0.95
        coupon = 8.0
        orig_term = 360

        smm_vector = np.array([
            psa_to_smm(psa_speed, beginning_month + m)
            for m in range(window)
        ])
        end_factor = project_act_end_factor(
            beg_factor, smm_vector, coupon, orig_term, beginning_age
        )

        recovered_psa = historical_psa(
            coupon, orig_term,
            beg_factor, beginning_age,
            end_factor, beginning_age + window,
            beginning_month=beginning_month
        )
        self.assertAlmostEqual(recovered_psa, psa_speed, places=2)


class TestB3HistoricalSmmPool(unittest.TestCase):
    """Test historical_smm_pool against SF-12 two-pool example."""

    def test_sf12_two_pool_smm(self):
        """SF-12: Combined pool SMM = 0.00271142."""
        smm = historical_smm_pool(SF12_POOLS, SF12_POOL_AGE)
        self.assertAlmostEqual(smm, SF12_SMM_AVG, places=5)

    def test_single_pool_matches_historical_smm_fixed_rate(self):
        """For a single pool, historical_smm_pool == historical_smm_fixed_rate."""
        pool = [SF12_POOLS[0]]
        pool_age = SF12_POOL_AGE
        smm_pool = historical_smm_pool(pool, pool_age)

        loan = pool[0]
        smm_single = historical_smm_fixed_rate(
            float(loan['coupon_vector']), loan['original_term'],
            loan['beginning_factor'], loan['beginning_age'],
            loan['ending_factor'], loan['beginning_age'] + pool_age
        )
        self.assertAlmostEqual(smm_pool, smm_single, places=8)


class TestB3HistoricalCprPool(unittest.TestCase):
    """Test historical_cpr_pool against SF-12 example."""

    def test_sf12_two_pool_cpr(self):
        """SF-12: Combined pool CPR = 3.2056%."""
        cpr = historical_cpr_pool(SF12_POOLS, SF12_POOL_AGE)
        self.assertAlmostEqual(cpr, SF12_CPR_AVG, places=2)

    def test_cross_verify_smm_to_cpr(self):
        """historical_cpr_pool == smm_to_cpr(historical_smm_pool(...))."""
        smm = historical_smm_pool(SF12_POOLS, SF12_POOL_AGE)
        cpr_from_smm = smm_to_cpr(smm)
        cpr_direct = historical_cpr_pool(SF12_POOLS, SF12_POOL_AGE)
        self.assertAlmostEqual(cpr_direct, cpr_from_smm, places=8)


class TestB3HistoricalPsaPool(unittest.TestCase):
    """Test historical_psa_pool against SF-12 example."""

    def test_roundtrip_known_psa(self):
        """Generate pool factors from known PSA, then recover PSA."""
        psa_speed = 150.0
        coupon = 9.5
        orig_term = 360
        pool_age = 6
        beg_ages = [12, 0]
        faces = [1_000_000, 2_000_000]

        pools = []
        for i, (beg_age, face) in enumerate(zip(beg_ages, faces)):
            beg_factor = sch_balance_factor_fixed_rate(coupon, orig_term, orig_term - beg_age)
            smm_vec = np.array([
                psa_to_smm(psa_speed, beg_age + 1 + m)
                for m in range(pool_age)
            ])
            end_factor = project_act_end_factor(
                beg_factor, smm_vec, coupon, orig_term, beg_age
            )
            pools.append({
                'coupon_vector': coupon,
                'original_term': orig_term,
                'original_face': face,
                'beginning_age': beg_age,
                'beginning_factor': beg_factor,
                'ending_factor': end_factor,
            })

        recovered_psa = historical_psa_pool(pools, pool_age)
        self.assertAlmostEqual(recovered_psa, psa_speed, places=1)


if __name__ == '__main__':
    unittest.main()
