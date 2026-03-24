"""
Comprehensive tests for portfolio-level features (Tier 2).

Covers:
  - PortfolioMode enum and LCD coercion
  - CashFlowPair validation and scale_by
  - PortfolioCashflow operators (add, subtract, multiply, divide)
  - Lazy evaluation and cache invalidation
  - Cross-collateralization modes (NONE, FULL, GROUP)
  - Version history and rewind
  - Waterfall outputs (pt_principal, pt_interest, etc.)
  - FieldKind registry
  - Advance reimbursement (leaf and portfolio level)
"""

import unittest
import numpy as np

from bma_standard_formulas.formulas import (
    BMAScheduledCashflow,
    BMAActualCashflow,
    CashFlowPair,
    CashFlowPairValidationError,
    FieldKind,
    PortfolioModeError,
    run_bma_scheduled_cashflow,
    run_bma_actual_cashflow,
    generate_smm_curve_from_psa,
    generate_sda_curve,
    cdr_to_mdr_vector,
)
from bma_standard_formulas.engine import (
    PortfolioCashflow,
    PortfolioMode,
    PortfolioOp,
    CrossCollateralMode,
    PortfolioEvent,
    apply_waterfall,
)
from bma_standard_formulas.formulas.cashflows import fields_by_kind


# ---------------------------------------------------------------------------
# Helpers: build leaf cashflows for tests
# ---------------------------------------------------------------------------

def _make_scheduled(loan_id: int = 1, balance: float = 100_000.0, rate: float = 0.06,
                    term: int = 360, remaining: int = 360) -> BMAScheduledCashflow:
    return run_bma_scheduled_cashflow(
        original_balance=balance,
        current_balance=balance,
        coupon_vector=rate * 100,
        original_term=term,
        remaining_term=remaining,
        loan_id=loan_id,
    )


def _make_actual(scheduled: BMAScheduledCashflow,
                 psa: float = 100, sda: float = 100) -> BMAActualCashflow:
    n = len(scheduled.period) - 1
    smm = generate_smm_curve_from_psa(psa, n)
    cdr = generate_sda_curve(sda, n)
    mdr = cdr_to_mdr_vector(cdr)
    severity = np.full(n + 1, 0.35)
    return run_bma_actual_cashflow(
        scheduled_cf=scheduled,
        smm_curve=smm,
        mdr_curve=mdr,
        severity_curve=severity,
    )


def _make_pair(loan_id: int = 1, balance: float = 100_000.0,
               psa: float = 100, sda: float = 100) -> CashFlowPair:
    s = _make_scheduled(loan_id=loan_id, balance=balance)
    a = _make_actual(s, psa=psa, sda=sda)
    return CashFlowPair(scheduled=s, actual=a)


# ---------------------------------------------------------------------------
# FieldKind Registry
# ---------------------------------------------------------------------------

class TestFieldKind(unittest.TestCase):

    def test_scheduled_fields_have_kind(self):
        """Every BMAScheduledCashflow field should have a FieldKind annotation."""
        from dataclasses import fields as dc_fields
        for f in dc_fields(BMAScheduledCashflow):
            kind = f.metadata.get("kind")
            self.assertIsNotNone(kind, f"Field {f.name!r} has no FieldKind metadata")
            self.assertIsInstance(kind, FieldKind)

    def test_actual_fields_have_kind(self):
        """Every BMAActualCashflow field should have a FieldKind annotation."""
        from dataclasses import fields as dc_fields
        for f in dc_fields(BMAActualCashflow):
            kind = f.metadata.get("kind")
            self.assertIsNotNone(kind, f"Field {f.name!r} has no FieldKind metadata")
            self.assertIsInstance(kind, FieldKind)

    def test_fields_by_kind_returns_correct_subset(self):
        flows = fields_by_kind(BMAScheduledCashflow, FieldKind.FLOW)
        flow_names = {f.name for f in flows}
        self.assertIn("scheduled_payment", flow_names)
        self.assertIn("principal_paid", flow_names)
        self.assertNotIn("ending_balance", flow_names)

    def test_period_is_meta(self):
        """period is a sequence index, not derived from flows — should be META."""
        from dataclasses import fields as dc_fields
        for cls in (BMAScheduledCashflow, BMAActualCashflow):
            for f in dc_fields(cls):
                if f.name == "period":
                    self.assertEqual(f.metadata["kind"], FieldKind.META,
                                     f"period should be META on {cls.__name__}")


# ---------------------------------------------------------------------------
# CashFlowPair
# ---------------------------------------------------------------------------

class TestCashFlowPair(unittest.TestCase):

    def test_valid_pair_construction(self):
        pair = _make_pair(loan_id=42)
        self.assertEqual(pair.scheduled.loan_id, 42)
        self.assertEqual(pair.actual.loan_id, 42)

    def test_loan_id_mismatch_raises(self):
        s = _make_scheduled(loan_id=1)
        a = _make_actual(_make_scheduled(loan_id=2))
        with self.assertRaises(CashFlowPairValidationError):
            CashFlowPair(scheduled=s, actual=a)

    def test_original_term_mismatch_raises(self):
        s1 = _make_scheduled(loan_id=1, term=360, remaining=360)
        s2 = _make_scheduled(loan_id=1, term=180, remaining=180)
        a2 = _make_actual(s2)
        with self.assertRaises(CashFlowPairValidationError):
            CashFlowPair(scheduled=s1, actual=a2)

    def test_scale_by(self):
        pair = _make_pair(loan_id=1, balance=100_000)
        scaled = pair.scale_by(2.0)
        np.testing.assert_allclose(
            scaled.scheduled.ending_balance,
            pair.scheduled.ending_balance * 2.0,
        )
        np.testing.assert_allclose(
            scaled.actual.perf_bal,
            pair.actual.perf_bal * 2.0,
            rtol=1e-10,
        )


# ---------------------------------------------------------------------------
# PortfolioMode and LCD Coercion
# ---------------------------------------------------------------------------

class TestPortfolioMode(unittest.TestCase):

    def test_scheduled_plus_scheduled(self):
        s1 = _make_scheduled(loan_id=1)
        s2 = _make_scheduled(loan_id=2)
        p = s1 + s2
        self.assertIsInstance(p, PortfolioCashflow)
        self.assertEqual(p.mode, PortfolioMode.SCHEDULED_ONLY)

    def test_actual_plus_actual(self):
        s1 = _make_scheduled(loan_id=1)
        s2 = _make_scheduled(loan_id=2)
        a1 = _make_actual(s1)
        a2 = _make_actual(s2)
        p = a1 + a2
        self.assertEqual(p.mode, PortfolioMode.ACTUAL_ONLY)

    def test_actual_plus_scheduled_raises(self):
        s = _make_scheduled(loan_id=1)
        a = _make_actual(_make_scheduled(loan_id=2))
        p = PortfolioCashflow([a], mode=PortfolioMode.ACTUAL_ONLY)
        with self.assertRaises(PortfolioModeError):
            p + s

    def test_invalid_mode_string_raises(self):
        with self.assertRaises(ValueError):
            PortfolioCashflow([], mode="bogus")

    def test_lcd_paired_plus_actual_becomes_actual_only(self):
        pair = _make_pair(loan_id=1)
        a = _make_actual(_make_scheduled(loan_id=2))
        p = PortfolioCashflow([pair], mode=PortfolioMode.PAIRED)
        p += a
        self.assertEqual(p.mode, PortfolioMode.ACTUAL_ONLY)


# ---------------------------------------------------------------------------
# Operator Semantics
# ---------------------------------------------------------------------------

class TestPortfolioOperators(unittest.TestCase):

    def test_portfolio_plus_cf_mutates(self):
        s1 = _make_scheduled(loan_id=1)
        s2 = _make_scheduled(loan_id=2)
        p = PortfolioCashflow([s1], mode=PortfolioMode.SCHEDULED_ONLY)
        p_id = id(p)
        result = p + s2
        self.assertEqual(id(result), p_id, "portfolio + cf should return same object")
        self.assertEqual(p.n_constituents, 2)

    def test_portfolio_plus_portfolio_returns_new(self):
        s1 = _make_scheduled(loan_id=1)
        s2 = _make_scheduled(loan_id=2)
        p1 = PortfolioCashflow([s1], mode=PortfolioMode.SCHEDULED_ONLY)
        p2 = PortfolioCashflow([s2], mode=PortfolioMode.SCHEDULED_ONLY)
        p1_count_before = p1.n_constituents
        p3 = p1 + p2
        self.assertIsNot(p3, p1)
        self.assertIsNot(p3, p2)
        self.assertEqual(p3.n_constituents, 2)
        self.assertEqual(p1.n_constituents, p1_count_before, "p1 should not be mutated")

    def test_portfolio_minus_cf_removes(self):
        s1 = _make_scheduled(loan_id=1)
        s2 = _make_scheduled(loan_id=2)
        p = PortfolioCashflow([s1, s2], mode=PortfolioMode.SCHEDULED_ONLY)
        p -= s1
        self.assertEqual(p.n_constituents, 1)

    def test_portfolio_minus_missing_cf_raises(self):
        s1 = _make_scheduled(loan_id=1)
        s_other = _make_scheduled(loan_id=99)
        p = PortfolioCashflow([s1], mode=PortfolioMode.SCHEDULED_ONLY)
        with self.assertRaises(ValueError):
            p - s_other

    def test_portfolio_mul_returns_new(self):
        s1 = _make_scheduled(loan_id=1)
        p = PortfolioCashflow([s1], mode=PortfolioMode.SCHEDULED_ONLY)
        p2 = p * 2.0
        self.assertIsNot(p2, p)

    def test_rmul(self):
        s1 = _make_scheduled(loan_id=1)
        p = PortfolioCashflow([s1], mode=PortfolioMode.SCHEDULED_ONLY)
        p2 = 2.0 * p
        self.assertIsInstance(p2, PortfolioCashflow)

    def test_imul_mutates(self):
        s1 = _make_scheduled(loan_id=1)
        p = PortfolioCashflow([s1], mode=PortfolioMode.SCHEDULED_ONLY)
        p_id = id(p)
        p *= 2.0
        self.assertEqual(id(p), p_id)

    def test_div_by_zero_raises(self):
        s1 = _make_scheduled(loan_id=1)
        p = PortfolioCashflow([s1], mode=PortfolioMode.SCHEDULED_ONLY)
        with self.assertRaises(ValueError):
            p / 0


# ---------------------------------------------------------------------------
# Lazy Evaluation and Cache
# ---------------------------------------------------------------------------

class TestLazyEval(unittest.TestCase):

    def test_cache_populated_on_access(self):
        s1 = _make_scheduled(loan_id=1)
        s2 = _make_scheduled(loan_id=2)
        p = s1 + s2
        self.assertNotIn("_scheduled", p._committed)
        _ = p.scheduled
        self.assertIn("_scheduled", p._committed)

    def test_cache_cleared_on_mutation(self):
        s1 = _make_scheduled(loan_id=1)
        s2 = _make_scheduled(loan_id=2)
        p = s1 + s2
        _ = p.scheduled  # populate cache
        self.assertIn("_scheduled", p._committed)
        p += _make_scheduled(loan_id=3)
        self.assertNotIn("_scheduled", p._committed)


# ---------------------------------------------------------------------------
# Single-Asset Round Trip
# ---------------------------------------------------------------------------

class TestSingleAssetRoundTrip(unittest.TestCase):

    def test_scheduled_single_asset(self):
        """A portfolio with one scheduled CF should match the original exactly."""
        s = _make_scheduled(loan_id=1)
        p = PortfolioCashflow([s], mode=PortfolioMode.SCHEDULED_ONLY)
        agg = p.scheduled
        np.testing.assert_allclose(agg.ending_balance, s.ending_balance)
        np.testing.assert_allclose(agg.interest_billed, s.interest_billed)
        np.testing.assert_allclose(agg.gross_rate, s.gross_rate, atol=1e-12)

    def test_actual_single_asset(self):
        """A portfolio with one actual CF should match the original exactly."""
        s = _make_scheduled(loan_id=1)
        a = _make_actual(s)
        p = PortfolioCashflow([a], mode=PortfolioMode.ACTUAL_ONLY)
        pool = p.pool
        np.testing.assert_allclose(pool.perf_bal, a.perf_bal)
        np.testing.assert_allclose(pool.mdr, a.mdr, atol=1e-12)
        np.testing.assert_allclose(pool.smm, a.smm, atol=1e-12)


# ---------------------------------------------------------------------------
# Waterfall Outputs
# ---------------------------------------------------------------------------

class TestWaterfall(unittest.TestCase):

    def test_waterfall_produces_all_fields(self):
        s = _make_scheduled(loan_id=1)
        a = _make_actual(s)
        p = PortfolioCashflow([a], mode=PortfolioMode.ACTUAL_ONLY)
        for attr in ("pt_principal", "pt_interest", "pt_cashflow",
                      "gross_cashflow", "svc_cashflow", "svc_paid",
                      "svc_shortfall", "adv_reimbursed_prin",
                      "adv_reimbursed_int", "adv_unrecoverable"):
            arr = getattr(p, attr)
            self.assertIsInstance(arr, np.ndarray, f"{attr} should be ndarray")

    def test_pt_cashflow_equals_principal_plus_interest(self):
        s = _make_scheduled(loan_id=1)
        a = _make_actual(s)
        p = PortfolioCashflow([a], mode=PortfolioMode.ACTUAL_ONLY)
        np.testing.assert_allclose(p.pt_cashflow, p.pt_principal + p.pt_interest)

    def test_apply_waterfall_convenience(self):
        s = _make_scheduled(loan_id=1)
        a = _make_actual(s)
        p = apply_waterfall(a)
        self.assertIsInstance(p, PortfolioCashflow)
        self.assertEqual(p.mode, PortfolioMode.ACTUAL_ONLY)
        self.assertIsInstance(p.pt_cashflow, np.ndarray)


# ---------------------------------------------------------------------------
# Cross-Collateralization
# ---------------------------------------------------------------------------

class TestCrossCollateral(unittest.TestCase):

    def test_group_mode_raises(self):
        s = _make_scheduled(loan_id=1)
        a = _make_actual(s)
        p = PortfolioCashflow(
            [a], mode=PortfolioMode.ACTUAL_ONLY,
            cross_collateral_mode=CrossCollateralMode.GROUP,
        )
        with self.assertRaises(NotImplementedError):
            _ = p.pt_principal

    def test_full_mode_runs(self):
        s = _make_scheduled(loan_id=1)
        a = _make_actual(s)
        p = PortfolioCashflow(
            [a], mode=PortfolioMode.ACTUAL_ONLY,
            cross_collateral_mode=CrossCollateralMode.FULL,
            cross_collateral_cap=0.5,
        )
        self.assertIsInstance(p.pt_cashflow, np.ndarray)


# ---------------------------------------------------------------------------
# Version History and Rewind
# ---------------------------------------------------------------------------

class TestVersionHistory(unittest.TestCase):

    def test_history_grows_on_add(self):
        s1 = _make_scheduled(loan_id=1)
        s2 = _make_scheduled(loan_id=2)
        p = PortfolioCashflow([s1], mode=PortfolioMode.SCHEDULED_ONLY)
        self.assertEqual(len(p._history), 1)
        p += s2
        self.assertEqual(len(p._history), 2)
        self.assertEqual(p._history[-1].op, PortfolioOp.ADD)

    def test_history_records_scale(self):
        s = _make_scheduled(loan_id=1)
        p = PortfolioCashflow([s], mode=PortfolioMode.SCHEDULED_ONLY)
        p *= 2.0
        self.assertEqual(p._history[-1].op, PortfolioOp.SCALE)
        self.assertEqual(p._history[-1].scalar, 2.0)

    def test_rewind_to_earlier_version(self):
        s1 = _make_scheduled(loan_id=1)
        s2 = _make_scheduled(loan_id=2)
        s3 = _make_scheduled(loan_id=3)
        p = PortfolioCashflow([s1], mode=PortfolioMode.SCHEDULED_ONLY)
        p += s2
        p += s3
        self.assertEqual(p.n_constituents, 3)
        store = {s1.cf_id: s1, s2.cf_id: s2, s3.cf_id: s3}
        p_v2 = p.rewind(2, store=store)
        self.assertEqual(p_v2.n_constituents, 2)
        self.assertEqual(p.n_constituents, 3, "Original should be unchanged")

    def test_rewind_store_with_subtract(self):
        s1 = _make_scheduled(loan_id=1)
        s2 = _make_scheduled(loan_id=2)
        p = PortfolioCashflow([s1, s2], mode=PortfolioMode.SCHEDULED_ONLY)
        p -= s2
        store = {s1.cf_id: s1, s2.cf_id: s2}
        p_v2 = p.rewind(2, store=store)
        self.assertEqual(p_v2.n_constituents, 2)


# ---------------------------------------------------------------------------
# Advance Reimbursement
# ---------------------------------------------------------------------------

class TestAdvanceReimbursement(unittest.TestCase):

    def test_leaf_reimbursement_fields_populated(self):
        s = _make_scheduled(loan_id=1)
        a = _make_actual(s, psa=200, sda=200)
        # With defaults, there should be some advance activity
        self.assertTrue(np.any(a.adv_prin > 0) or np.any(a.adv_int > 0),
                        "Expected some advancing activity with SDA=200")

    def test_reimburse_advances_false(self):
        s = _make_scheduled(loan_id=1)
        smm = generate_smm_curve_from_psa(200, 360)
        cdr = generate_sda_curve(200, 360)
        mdr = cdr_to_mdr_vector(cdr)
        severity = np.full(361, 0.35)
        a = run_bma_actual_cashflow(
            scheduled_cf=s, smm_curve=smm, mdr_curve=mdr,
            severity_curve=severity, reimburse_advances=False,
        )
        np.testing.assert_array_equal(a.adv_reimbursed_prin, 0.0)
        np.testing.assert_array_equal(a.adv_reimbursed_int, 0.0)


# ---------------------------------------------------------------------------
# cf_id Uniqueness
# ---------------------------------------------------------------------------

class TestCfId(unittest.TestCase):

    def test_cf_ids_are_unique(self):
        s1 = _make_scheduled(loan_id=1)
        s2 = _make_scheduled(loan_id=2)
        a1 = _make_actual(s1)
        self.assertNotEqual(s1.cf_id, s2.cf_id)
        self.assertNotEqual(s1.cf_id, a1.cf_id)
        self.assertTrue(len(s1.cf_id) > 0, "cf_id should be a non-empty UUID string")

    def test_cf_id_new_on_scale(self):
        """Scaled CF gets a new cf_id (it's a new object, not the same cashflow)."""
        s = _make_scheduled(loan_id=1)
        scaled = s * 2.0
        self.assertNotEqual(scaled.cf_id, s.cf_id)
        self.assertTrue(len(scaled.cf_id) > 0)


# ---------------------------------------------------------------------------
# Flush and Committed-as-Constituent
# ---------------------------------------------------------------------------

class TestFlush(unittest.TestCase):

    def test_flush_clears_pending(self):
        s1 = _make_scheduled(loan_id=1)
        s2 = _make_scheduled(loan_id=2)
        p = s1 + s2
        _ = p.scheduled  # trigger aggregation
        p.flush()
        self.assertEqual(len(p._pending), 0)
        self.assertTrue(p._flushed)

    def test_post_flush_mutation(self):
        s1 = _make_scheduled(loan_id=1)
        s2 = _make_scheduled(loan_id=2)
        p = s1 + s2
        _ = p.scheduled
        p.flush()
        s3 = _make_scheduled(loan_id=3)
        p += s3
        self.assertFalse(p._flushed)
        self.assertEqual(p.n_constituents, 3)
        # Accessing .scheduled should aggregate 2 items: old aggregate + s3
        agg = p.scheduled
        self.assertEqual(len(agg.period), len(s1.period))


# ---------------------------------------------------------------------------
# Empty Portfolio
# ---------------------------------------------------------------------------

class TestEmptyPortfolio(unittest.TestCase):

    def test_empty_creates_zero_constituents(self):
        p = PortfolioCashflow.empty()
        self.assertEqual(p.n_constituents, 0)

    def test_sum_pattern(self):
        s1 = _make_scheduled(loan_id=1)
        s2 = _make_scheduled(loan_id=2)
        p = PortfolioCashflow.empty(mode=PortfolioMode.SCHEDULED_ONLY)
        p += s1
        p += s2
        self.assertEqual(p.n_constituents, 2)


# ---------------------------------------------------------------------------
# Event Log uses cf_id
# ---------------------------------------------------------------------------

class TestEventLog(unittest.TestCase):

    def test_history_stores_cf_id(self):
        s1 = _make_scheduled(loan_id=1)
        p = PortfolioCashflow([s1], mode=PortfolioMode.SCHEDULED_ONLY)
        self.assertEqual(p._history[0].cf_id, s1.cf_id)
        self.assertEqual(p._history[0].loan_id, 1)
        self.assertIsNone(p._history[0].meta.get("operands", None))

    def test_history_no_object_refs(self):
        s1 = _make_scheduled(loan_id=1)
        p = PortfolioCashflow([s1], mode=PortfolioMode.SCHEDULED_ONLY)
        self.assertFalse(hasattr(p._history[0], "operands"))


if __name__ == "__main__":
    unittest.main()
