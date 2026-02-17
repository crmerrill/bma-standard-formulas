"""
Comprehensive verification of all library functions against BMA examples.

Tests every public function in scheduled_payments, payment_models, and cashflows
against every example in BMA_EXAMPLES. Cross-verifies modules against each other.

Version: 0.2.0
Last Updated: 2026-02-16
Status: Active
"""

import unittest
import numpy as np

from bma_standard_formulas.examples import (
    BMA_EXAMPLES, BMAExample, PeriodCashFlows, PrepayType, DefaultType,
    SF12_POOL1, SF12_POOL2,
)
from bma_standard_formulas.scheduled_payments import (
    sch_balance_factor_fixed_rate,
    sch_payment_factor_fixed_rate,
    sch_am_factor_fixed_rate,
    sch_payment_factor,
    am_factor,
    sch_payment_factor_vector,
    sch_balance_factors,
    sch_ending_balance_factor,
)
from bma_standard_formulas.payment_models import (
    smm_from_factors,
    smm_to_cpr,
    cpr_to_smm,
    smm_to_cpr_vector,
    cpr_to_smm_vector,
    psa_to_cpr,
    cpr_to_psa,
    psa_to_smm,
    generate_psa_curve,
    generate_smm_curve_from_psa,
    project_act_end_factor,
    historical_smm_fixed_rate,
    historical_cpr_fixed_rate,
    historical_smm,
    historical_cpr,
    historical_psa,
    historical_smm_pool,
    historical_cpr_pool,
    historical_psa_pool,
    cdr_to_mdr,
    cdr_to_mdr_vector,
    sda_to_cdr,
    generate_sda_curve,
)
from bma_standard_formulas.cashflows import (
    Loan,
    scheduled_cashflow_from_loan,
    actual_cashflow_from_loan,
)


# =============================================================================
# Helpers
# =============================================================================

def _cf(ex):
    if not ex.cashflows:
        return None
    return next(iter(ex.cashflows.values()))


def _window(ex):
    if not ex.cashflows:
        return 0
    return next(iter(ex.cashflows.keys()))[1]


def _rem_beg(ex):
    """Remaining term at beginning of observation window.

    BMA Section D.2, SF-40: "If the age as calculated above is greater than
    the original maturity minus the current WAM, then CAGE should be defined
    as the original maturity minus the current WAM."  Equivalently,
    remaining_term = max(current_WAM, original_maturity - CAGE).
    """
    return max(int(ex.current.remaining_term),
               int(ex.origination.original_term) - int(ex.current.loan_age))


def _rem_end(ex):
    """Remaining term at end of observation window."""
    return _rem_beg(ex) - _window(ex)


def _oterm(ex):
    return int(ex.origination.original_term)


def _coupon(ex):
    return ex.origination.gross_coupon


def _is_factor_bal(cf):
    """True if bal1 is a balance factor (0-2), not dollar amounts."""
    return 0 < cf.bal1 < 2.0


def _has_single_period_flows(ex):
    """True if example has single-period cashflow with smm > 0 and asof > 0."""
    cf = _cf(ex)
    return (cf is not None and _window(ex) == 1
            and cf.asof_period > 0 and cf.smm > 0)


def _build_loan(ex):
    oterm = _oterm(ex)
    # BMA D.2 SF-40: use the D.2-adjusted remaining term for amortization
    rem = _rem_beg(ex)
    return Loan(
        origination_date=ex.origination.origination_date or '2000-01-01',
        asof_date=ex.current.asof_date or '2000-01-01',
        original_balance=ex.origination.original_balance,
        current_balance=ex.current.current_balance,
        rate_margin=_coupon(ex),
        rate_index=None,
        servicing_fee=ex.assumptions.servicing_fee,
        original_term=oterm,
        remaining_term=rem,
    )


def _build_sf12_pools():
    pools = []
    for ex in [SF12_POOL1, SF12_POOL2]:
        cf = _cf(ex)
        pools.append({
            'coupon_vector': _coupon(ex),
            'original_term': _oterm(ex),
            'original_face': ex.origination.original_balance,
            'beginning_age': int(ex.current.loan_age),
            'beginning_factor': ex.current.current_factor,
            'ending_factor': cf.surv_fac2,
        })
    return pools


# =============================================================================
# scheduled_payments.py — all 8 public functions
# =============================================================================

class TestScheduledPayments(unittest.TestCase):

    def test_sch_balance_factor_fixed_rate(self):
        """bal1 and bal2 match sch_balance_factor_fixed_rate."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.bal1 == 0 or not _is_factor_bal(cf):
                    continue
                bal1 = sch_balance_factor_fixed_rate(_coupon(ex), _oterm(ex), _rem_beg(ex))
                bal2 = sch_balance_factor_fixed_rate(_coupon(ex), _oterm(ex), _rem_end(ex))
                self.assertAlmostEqual(bal1, cf.bal1, places=5)
                self.assertAlmostEqual(bal2, cf.bal2, places=5)

    def test_sch_ending_balance_factor_consistency(self):
        """sch_ending_balance_factor matches sch_balance_factor_fixed_rate."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.bal1 == 0 or not _is_factor_bal(cf):
                    continue
                fixed = sch_balance_factor_fixed_rate(_coupon(ex), _oterm(ex), _rem_beg(ex))
                general = sch_ending_balance_factor([_coupon(ex)], _oterm(ex), _rem_beg(ex))
                self.assertAlmostEqual(fixed, general, places=10)

    def test_sch_balance_factors_vector(self):
        """Vector survival factors match scalar at beg/end ages."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.bal1 == 0 or not _is_factor_bal(cf):
                    continue
                oterm = _oterm(ex)
                beg_age = oterm - _rem_beg(ex)
                end_age = oterm - _rem_end(ex)
                _, _, _, survival = sch_balance_factors([_coupon(ex)], oterm, _rem_end(ex))
                self.assertAlmostEqual(survival[beg_age], cf.bal1, places=5)
                self.assertAlmostEqual(survival[end_age], cf.bal2, places=5)

    def test_surv_fac2_sched_identity(self):
        """surv_fac2_sched == surv_fac1 * (bal2/bal1)."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.bal1 == 0 or cf.surv_fac2_sched == 0:
                    continue
                expected = cf.surv_fac1 * (cf.bal2 / cf.bal1)
                self.assertAlmostEqual(expected, cf.surv_fac2_sched, places=5)

    def test_sch_am_factor_fixed_rate(self):
        """sch_am_factor == 1 - bal2/bal1 for single-month examples."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.bal1 == 0 or not _is_factor_bal(cf):
                    continue
                if _window(ex) != 1:
                    continue
                computed = sch_am_factor_fixed_rate(_coupon(ex), _oterm(ex), _rem_beg(ex))
                expected = 1.0 - cf.bal2 / cf.bal1
                self.assertAlmostEqual(computed, expected, places=8)

    def test_am_factor_matches_sch_am_factor(self):
        """am_factor(bal, coupon, rem) == sch_am_factor_fixed_rate."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.bal1 == 0 or not _is_factor_bal(cf):
                    continue
                if _window(ex) != 1:
                    continue
                from_fixed = sch_am_factor_fixed_rate(_coupon(ex), _oterm(ex), _rem_beg(ex))
                from_general = am_factor(cf.bal1, _coupon(ex), _rem_beg(ex))
                self.assertAlmostEqual(from_fixed, from_general, places=8)

    def test_sch_payment_factor_fixed_rate_decomposition(self):
        """Payment = principal + interest (as fractions of par)."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.bal1 == 0 or not _is_factor_bal(cf):
                    continue
                if _window(ex) != 1:
                    continue
                pmt = sch_payment_factor_fixed_rate(_coupon(ex), _oterm(ex), _rem_beg(ex))
                r = _coupon(ex) / 1200.0
                principal_frac = cf.bal1 - cf.bal2  # as fraction of par
                interest_frac = cf.bal1 * r          # as fraction of par
                self.assertAlmostEqual(pmt, principal_frac + interest_frac, places=6)

    def test_sch_payment_factor_general(self):
        """sch_payment_factor(coupon, rem) == r + am_factor (annuity decomposition)."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.bal1 == 0 or not _is_factor_bal(cf):
                    continue
                if _window(ex) != 1:
                    continue
                r = _coupon(ex) / 1200.0
                rem = _rem_beg(ex)
                # sch_payment_factor with default bal=1.0 returns AF (annuity factor)
                af_val = sch_payment_factor(_coupon(ex), rem)
                am_val = am_factor(cf.bal1, _coupon(ex), rem)
                # AF = r + am_factor (payment = interest + principal per dollar of balance)
                self.assertAlmostEqual(af_val, r + am_val, places=10)

    def test_sch_payment_factor_vector_consistency(self):
        """Vector payment factors at end_age match scalar annuity factor."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.bal1 == 0 or not _is_factor_bal(cf):
                    continue
                if _window(ex) != 1:
                    continue
                oterm = _oterm(ex)
                end_age = oterm - _rem_end(ex)
                # sch_payment_factor_vector returns (periods, rates, payment_factors)
                periods, rates, pf_vec = sch_payment_factor_vector(
                    [_coupon(ex)], oterm, _rem_end(ex)
                )
                # pf_vec[end_age] is the annuity factor AF for that period
                # It should match sch_payment_factor(coupon, rem_beg) with default bal=1.0
                scalar_af = sch_payment_factor(_coupon(ex), _rem_beg(ex))
                self.assertAlmostEqual(pf_vec[end_age], scalar_af, places=8)


# =============================================================================
# payment_models.py — speed recovery
# =============================================================================

class TestSpeedRecovery(unittest.TestCase):

    def test_smm_from_factors(self):
        """smm_from_factors with bal1/bal2 matches cf.smm."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.smm == 0 or not _is_factor_bal(cf):
                    continue
                computed = smm_from_factors(
                    cf.surv_fac1, cf.surv_fac2, cf.bal1, cf.bal2, _window(ex)
                )
                self.assertAlmostEqual(computed, cf.smm, places=6)

    def test_historical_smm_fixed_rate(self):
        """historical_smm_fixed_rate matches cf.smm."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.smm == 0 or name == "SF12":
                    continue
                oterm = _oterm(ex)
                beg_age = oterm - _rem_beg(ex)
                end_age = oterm - _rem_end(ex)
                computed = historical_smm_fixed_rate(
                    _coupon(ex), oterm,
                    cf.surv_fac1, beg_age, cf.surv_fac2, end_age,
                )
                self.assertAlmostEqual(computed, cf.smm, places=6)

    def test_historical_smm_floating_matches_fixed(self):
        """historical_smm with constant coupon matches fixed-rate version."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.smm == 0 or name == "SF12":
                    continue
                oterm = _oterm(ex)
                beg_age = oterm - _rem_beg(ex)
                end_age = oterm - _rem_end(ex)
                from_fixed = historical_smm_fixed_rate(
                    _coupon(ex), oterm,
                    cf.surv_fac1, beg_age, cf.surv_fac2, end_age,
                )
                from_floating = historical_smm(
                    [_coupon(ex)], oterm,
                    cf.surv_fac1, beg_age, cf.surv_fac2, end_age,
                )
                self.assertAlmostEqual(from_fixed, from_floating, places=10)

    def test_historical_cpr_fixed_rate(self):
        """historical_cpr_fixed_rate matches cf.cpr."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.cpr == 0 or name == "SF12":
                    continue
                oterm = _oterm(ex)
                beg_age = oterm - _rem_beg(ex)
                end_age = oterm - _rem_end(ex)
                computed = historical_cpr_fixed_rate(
                    _coupon(ex), oterm,
                    cf.surv_fac1, beg_age, cf.surv_fac2, end_age,
                )
                self.assertAlmostEqual(computed, cf.cpr, places=2)

    def test_historical_cpr_floating_matches_fixed(self):
        """historical_cpr with constant coupon matches fixed-rate version."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.cpr == 0 or name == "SF12":
                    continue
                oterm = _oterm(ex)
                beg_age = oterm - _rem_beg(ex)
                end_age = oterm - _rem_end(ex)
                from_fixed = historical_cpr_fixed_rate(
                    _coupon(ex), oterm,
                    cf.surv_fac1, beg_age, cf.surv_fac2, end_age,
                )
                from_floating = historical_cpr(
                    [_coupon(ex)], oterm,
                    cf.surv_fac1, beg_age, cf.surv_fac2, end_age,
                )
                self.assertAlmostEqual(from_fixed, from_floating, places=10)

    def test_historical_psa_recovery(self):
        """historical_psa close to cf.psa (BMA rounds PSA)."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.psa == 0 or cf.smm == 0 or name == "SF12":
                    continue
                if _window(ex) != 1:
                    continue
                oterm = _oterm(ex)
                beg_age = oterm - _rem_beg(ex)
                end_age = oterm - _rem_end(ex)
                beg_month = cf.asof_period
                computed = historical_psa(
                    _coupon(ex), oterm,
                    cf.surv_fac1, beg_age, cf.surv_fac2, end_age,
                    beginning_month=beg_month,
                )
                self.assertAlmostEqual(computed, cf.psa, delta=2.0)

    def test_project_act_end_factor_roundtrip(self):
        """Recover SMM then project forward reproduces surv_fac2."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.smm == 0 or name == "SF12":
                    continue
                oterm = _oterm(ex)
                beg_age = oterm - _rem_beg(ex)
                window = _window(ex)
                smm = historical_smm_fixed_rate(
                    _coupon(ex), oterm,
                    cf.surv_fac1, beg_age,
                    cf.surv_fac2, beg_age + window,
                )
                smm_vec = np.full(window, smm)
                projected = project_act_end_factor(
                    cf.surv_fac1, smm_vec, _coupon(ex), oterm, beg_age,
                )
                self.assertAlmostEqual(projected, cf.surv_fac2, places=8)

    def test_sf12_pool_smm(self):
        """historical_smm_pool for SF12 combined matches cf.smm."""
        cf = _cf(BMA_EXAMPLES["SF12"])
        computed = historical_smm_pool(_build_sf12_pools(), _window(BMA_EXAMPLES["SF12"]))
        self.assertAlmostEqual(computed, cf.smm, places=5)

    def test_sf12_pool_cpr(self):
        """historical_cpr_pool for SF12 combined matches cf.cpr."""
        cf = _cf(BMA_EXAMPLES["SF12"])
        computed = historical_cpr_pool(_build_sf12_pools(), _window(BMA_EXAMPLES["SF12"]))
        self.assertAlmostEqual(computed, cf.cpr, places=2)

    def test_sf12_pool_psa(self):
        """historical_psa_pool for SF12 combined returns positive value."""
        computed = historical_psa_pool(_build_sf12_pools(), _window(BMA_EXAMPLES["SF12"]))
        self.assertGreater(computed, 0)


# =============================================================================
# payment_models.py — all conversions
# =============================================================================

class TestConversions(unittest.TestCase):

    def test_smm_cpr_roundtrip(self):
        """smm_to_cpr(smm) == cf.cpr and cpr_to_smm(cpr) == cf.smm."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.smm == 0:
                    continue
                self.assertAlmostEqual(smm_to_cpr(cf.smm), cf.cpr, places=3)
                self.assertAlmostEqual(cpr_to_smm(cf.cpr), cf.smm, places=7)

    def test_smm_cpr_vector_consistency(self):
        """Vector smm_to_cpr/cpr_to_smm match scalar versions."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.smm == 0:
                    continue
                self.assertAlmostEqual(
                    smm_to_cpr_vector(np.array([cf.smm]))[0],
                    smm_to_cpr(cf.smm), places=10,
                )
                self.assertAlmostEqual(
                    cpr_to_smm_vector(np.array([cf.cpr]))[0],
                    cpr_to_smm(cf.cpr), places=10,
                )

    def test_psa_to_cpr_forward(self):
        """psa_to_cpr(psa, month) close to cf.cpr for single-month."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.psa == 0 or cf.cpr == 0:
                    continue
                if _window(ex) != 1:
                    continue
                # Use back-calculated PSA (from recovery) for precision,
                # since BMA rounds the stated PSA
                oterm = _oterm(ex)
                beg_age = oterm - _rem_beg(ex)
                month = cf.asof_period
                try:
                    exact_psa = historical_psa(
                        _coupon(ex), oterm,
                        cf.surv_fac1, beg_age,
                        cf.surv_fac2, beg_age + 1,
                        beginning_month=month,
                    )
                    computed_cpr = psa_to_cpr(exact_psa, month)
                    self.assertAlmostEqual(computed_cpr, cf.cpr, places=2)
                except ValueError:
                    pass

    def test_psa_to_smm_forward(self):
        """psa_to_smm(psa, month) close to cf.smm for single-month."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.psa == 0 or cf.smm == 0:
                    continue
                if _window(ex) != 1:
                    continue
                oterm = _oterm(ex)
                beg_age = oterm - _rem_beg(ex)
                month = cf.asof_period
                try:
                    exact_psa = historical_psa(
                        _coupon(ex), oterm,
                        cf.surv_fac1, beg_age,
                        cf.surv_fac2, beg_age + 1,
                        beginning_month=month,
                    )
                    computed_smm = psa_to_smm(exact_psa, month)
                    self.assertAlmostEqual(computed_smm, cf.smm, places=6)
                except ValueError:
                    pass

    def test_cpr_to_psa_backward(self):
        """cpr_to_psa(cpr, month) close to cf.psa for single-month."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.psa == 0 or cf.cpr == 0:
                    continue
                if _window(ex) != 1:
                    continue
                month = cf.asof_period
                computed = cpr_to_psa(cf.cpr, month)
                self.assertAlmostEqual(computed, cf.psa, delta=2.0)

    def test_psa_curve_at_month(self):
        """generate_psa_curve and generate_smm_curve at example's month."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.psa == 0 or cf.cpr == 0:
                    continue
                if _window(ex) != 1:
                    continue
                oterm = _oterm(ex)
                month = cf.asof_period
                # Use back-calculated PSA for curve check
                beg_age = oterm - _rem_beg(ex)
                try:
                    exact_psa = historical_psa(
                        _coupon(ex), oterm,
                        cf.surv_fac1, beg_age,
                        cf.surv_fac2, beg_age + 1,
                        beginning_month=month,
                    )
                    cpr_curve = generate_psa_curve(exact_psa, oterm)
                    self.assertAlmostEqual(cpr_curve[month], cf.cpr, places=2)
                    smm_curve = generate_smm_curve_from_psa(exact_psa, oterm)
                    self.assertAlmostEqual(smm_curve[month], cf.smm, places=6)
                except ValueError:
                    pass

    def test_cdr_mdr_for_sf23(self):
        """cdr_to_mdr for SF23 constant 1% MDR."""
        ex = BMA_EXAMPLES.get("SF23")
        if ex is None:
            return
        mdr_dec = ex.assumptions.default_speed / 100.0
        cdr = 100.0 * (1.0 - (1.0 - mdr_dec) ** 12.0)
        recovered = cdr_to_mdr(cdr)
        self.assertAlmostEqual(recovered, mdr_dec, places=8)
        vec = cdr_to_mdr_vector(np.array([cdr]))
        self.assertAlmostEqual(vec[0], recovered, places=10)

    def test_sda_curve_for_sf31(self):
        """sda_to_cdr and generate_sda_curve for SF31 (100% SDA)."""
        ex = BMA_EXAMPLES.get("SF31")
        if ex is None:
            return
        speed = ex.assumptions.default_speed
        oterm = _oterm(ex)
        curve = generate_sda_curve(speed, oterm)
        for month in [1, 15, 30, 45, 60, 90, 120, 200]:
            with self.subTest(month=month):
                scalar = sda_to_cdr(speed, month, term=oterm)
                self.assertAlmostEqual(curve[month], scalar, places=10)


# =============================================================================
# cashflows.py — Loan properties
# =============================================================================

class TestLoanProperties(unittest.TestCase):

    def test_loan_age(self):
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                if ex.cashflows_file:
                    continue
                try:
                    loan = _build_loan(ex)
                except (ValueError, TypeError):
                    continue
                self.assertEqual(loan.age, _oterm(ex) - _rem_beg(ex))

    def test_loan_coupon_percent(self):
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                try:
                    loan = _build_loan(ex)
                except (ValueError, TypeError):
                    continue
                self.assertAlmostEqual(loan.coupon_percent, _coupon(ex), places=10)

    def test_loan_is_fixed_rate(self):
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                try:
                    loan = _build_loan(ex)
                except (ValueError, TypeError):
                    continue
                self.assertTrue(loan.is_fixed_rate())

    def test_loan_coupon_decimal(self):
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                try:
                    loan = _build_loan(ex)
                except (ValueError, TypeError):
                    continue
                if loan.remaining_term <= 0:
                    continue
                self.assertAlmostEqual(
                    loan.coupon_decimal_for_cashflow()[0],
                    _coupon(ex) / 100.0, places=10,
                )

    def test_loan_servicing_fee_decimal(self):
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                try:
                    loan = _build_loan(ex)
                except (ValueError, TypeError):
                    continue
                self.assertAlmostEqual(
                    loan.servicing_fee_decimal(),
                    ex.assumptions.servicing_fee / 100.0, places=10,
                )

    def test_loan_get_coupon_vector(self):
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                try:
                    loan = _build_loan(ex)
                except (ValueError, TypeError):
                    continue
                if loan.remaining_term <= 0:
                    continue
                vec = loan.get_coupon_vector(3)
                for v in vec:
                    self.assertAlmostEqual(v, _coupon(ex), places=10)


# =============================================================================
# cashflows.py — scheduled + actual cashflow
# =============================================================================

class TestCashflowModule(unittest.TestCase):

    def test_scheduled_cashflow(self):
        """Scheduled cashflow identities at period 1."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                if not _has_single_period_flows(ex):
                    continue
                loan = _build_loan(ex)
                sch = scheduled_cashflow_from_loan(loan)
                i = 1
                coupon_dec = _coupon(ex) / 100.0
                self.assertAlmostEqual(
                    sch.beginning_balance[i], ex.current.current_balance, places=6,
                )
                self.assertAlmostEqual(
                    sch.interest_billed[i],
                    sch.beginning_balance[i] * coupon_dec / 12.0, places=8,
                )
                self.assertAlmostEqual(
                    sch.principal_paid[i] + sch.interest_paid[i],
                    sch.scheduled_payment[i], places=8,
                )
                self.assertAlmostEqual(
                    sch.ending_balance[i],
                    sch.beginning_balance[i] - sch.principal_paid[i], places=8,
                )

    def test_actual_cashflow(self):
        """Actual cashflow fields at period 1 match example values."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                if not _has_single_period_flows(ex):
                    continue
                cf = _cf(ex)
                loan = _build_loan(ex)
                sch = scheduled_cashflow_from_loan(loan)
                rem = loan.remaining_term
                act = actual_cashflow_from_loan(
                    loan, sch,
                    np.full(rem + 1, cf.smm),
                    np.full(rem + 1, cf.mdr),
                    np.full(rem + 1, ex.assumptions.loss_severity),
                    severity_lag=ex.assumptions.recovery_months,
                    months_to_liquidation=ex.assumptions.recovery_months,
                )
                i = 1
                orig = ex.origination.original_balance
                # perf_bal start matches surv_fac1
                self.assertAlmostEqual(
                    act.perf_bal[0] / orig, cf.surv_fac1, places=6,
                )
                # perf_bal end matches surv_fac2
                self.assertAlmostEqual(
                    act.perf_bal[i] / orig, cf.surv_fac2, places=5,
                )
                # act_am matches sch_am
                self.assertAlmostEqual(
                    act.act_am[i] / orig, cf.sch_am, places=5,
                )
                # vol_prepay
                self.assertAlmostEqual(
                    act.vol_prepay[i] / orig, cf.vol_prepay, places=5,
                )
                # gross interest (act_int = gross when no defaults)
                self.assertAlmostEqual(
                    act.act_int[i] / orig, cf.gross_int, places=4,
                )
                # smm and mdr
                self.assertAlmostEqual(act.smm[i], cf.smm, places=7)
                self.assertAlmostEqual(act.mdr[i], cf.mdr, places=7)
                # defaults are zero
                self.assertAlmostEqual(act.new_def[i], 0.0, places=8)
                self.assertAlmostEqual(act.lost_int[i], 0.0, places=8)


# =============================================================================
# Cross-module consistency
# =============================================================================

class TestCrossModuleConsistency(unittest.TestCase):

    def test_scheduled_payments_vs_cashflows(self):
        """Scheduled survival ratio from cashflows.py matches scheduled_payments.py.

        BMA SF-4: The survival ratio BAL(Mn)/BAL(Mn-1) is invariant regardless
        of starting balance. The cashflow module starts from current_balance
        (includes prior prepayments), while cf.bal1/bal2 are from par. But
        the RATIO must agree.
        """
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                if not _has_single_period_flows(ex):
                    continue
                cf = _cf(ex)
                if cf.bal1 == 0 or not _is_factor_bal(cf):
                    continue
                loan = _build_loan(ex)
                sch = scheduled_cashflow_from_loan(loan)
                # Survival ratio from cashflows module
                cf_ratio = sch.pool_factor[1] / sch.pool_factor[0]
                # Survival ratio from scheduled_payments
                sp_ratio = cf.bal2 / cf.bal1
                self.assertAlmostEqual(cf_ratio, sp_ratio, places=8)

    def test_payment_models_vs_cashflows(self):
        """SMM recovered from cashflow output matches input SMM."""
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                if not _has_single_period_flows(ex):
                    continue
                cf = _cf(ex)
                loan = _build_loan(ex)
                sch = scheduled_cashflow_from_loan(loan)
                rem = loan.remaining_term
                act = actual_cashflow_from_loan(
                    loan, sch,
                    np.full(rem + 1, cf.smm),
                    np.full(rem + 1, cf.mdr),
                    np.full(rem + 1, ex.assumptions.loss_severity),
                    severity_lag=ex.assumptions.recovery_months,
                    months_to_liquidation=ex.assumptions.recovery_months,
                )
                orig = ex.origination.original_balance
                oterm = _oterm(ex)
                beg_age = oterm - _rem_beg(ex)
                fac_beg = act.perf_bal[0] / orig
                fac_end = act.perf_bal[1] / orig
                recovered_smm = historical_smm_fixed_rate(
                    _coupon(ex), oterm, fac_beg, beg_age, fac_end, beg_age + 1,
                )
                self.assertAlmostEqual(recovered_smm, cf.smm, places=5)
                projected = project_act_end_factor(
                    fac_beg, np.array([cf.smm]), _coupon(ex), oterm, beg_age,
                )
                self.assertAlmostEqual(projected, fac_end, places=5)


# =============================================================================
# Identity checks on example data
# =============================================================================

class TestCashflowIdentities(unittest.TestCase):

    def test_tot_am_equals_sch_am_plus_vol_prepay(self):
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.sch_am <= 0:
                    continue
                self.assertAlmostEqual(cf.tot_am, cf.sch_am + cf.vol_prepay, places=4)

    def test_pt_cf_equals_pt_prin_plus_pt_int(self):
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.pt_cf == 0:
                    continue
                self.assertAlmostEqual(cf.pt_cf, cf.pt_prin + cf.pt_int, places=4)

    def test_net_int_equals_gross_int_minus_svc_fee(self):
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.gross_int == 0:
                    continue
                # For dollar-amount multi-month examples, use relative tolerance
                if cf.gross_int > 1.0:
                    self.assertAlmostEqual(
                        cf.net_int / cf.gross_int,
                        (cf.gross_int - cf.svc_fee) / cf.gross_int,
                        places=3,
                    )
                else:
                    self.assertAlmostEqual(cf.net_int, cf.gross_int - cf.svc_fee, places=5)

    def test_factor_change_equals_tot_am(self):
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.tot_am == 0 or cf.surv_fac1 == 0:
                    continue
                # Only for factor-based single-pool examples (surv_fac in 0-1 range)
                if cf.surv_fac1 > 1.1:
                    continue
                # SF12 combined: tot_am is in dollars, surv_fac is a factor — skip
                # SF56: different structure — skip
                if not _is_factor_bal(cf):
                    continue
                self.assertAlmostEqual(
                    cf.surv_fac1 - cf.surv_fac2, cf.tot_am, places=6,
                )

    def test_no_default_identities(self):
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.sch_am <= 0 or cf.mdr != 0:
                    continue
                self.assertAlmostEqual(cf.exp_am, cf.sch_am, places=6)
                self.assertAlmostEqual(cf.act_am, cf.sch_am, places=6)
                if cf.exp_int > 0:
                    self.assertAlmostEqual(cf.exp_int, cf.act_int, places=6)
                self.assertAlmostEqual(cf.lost_int, 0.0, places=8)

    def test_perf_bal_equals_surv_fac2_no_defaults(self):
        for name, ex in BMA_EXAMPLES.items():
            with self.subTest(example=name):
                cf = _cf(ex)
                if cf is None or cf.perf_bal == 0 or cf.mdr != 0:
                    continue
                if cf.surv_fac2 == 0:
                    continue
                # SF49_50/SF51: perf_bal=100 (dollars), surv_fac2=1.0 (factor)
                # These are at different scales; compare ratio instead
                if cf.perf_bal > 1.1 and cf.surv_fac2 <= 1.0:
                    ratio = cf.perf_bal / ex.origination.original_balance
                    self.assertAlmostEqual(ratio, cf.surv_fac2, places=6)
                else:
                    self.assertAlmostEqual(cf.perf_bal, cf.surv_fac2, places=6)


if __name__ == '__main__':
    unittest.main()
