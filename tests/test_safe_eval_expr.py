"""Tests for the IR expression sandbox (``_safe_eval_expr``) and Phase 1d.3
loan-iteration extensions.

Two-part scope:

1. Original ``_safe_eval_expr`` semantics — arithmetic, identifier lookup,
   whitelisted function calls (min / max / abs). Pinned here so the
   Phase 1d.3 expansion doesn't regress the legacy contract.

2. Phase 1d.3 expansion — comparisons, boolean operators, conditional
   expressions, list / generator comprehensions, attribute access on
   ``LoanProxy`` targets, subscripting on ``_LoanArrayProxy`` targets,
   plus the new whitelisted functions (len, sum, any, all). Sandbox
   guarantees: no dunder access, no nested comprehensions, no attribute
   access on non-LoanProxy targets.

The Phase 1d.3 extensions exist so calculation expressions and trigger
thresholds can reference per-loan cashflow data (``ExecutionContext.constituents``)
without giving up the AST sandbox guarantees.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from bma_standard_formulas.deals.runtime import (
    LoanProxy,
    _LoanArrayProxy,
    _safe_eval_expr,
)
from bma_standard_formulas.engine.loan import (
    Loan,
    actual_cashflow_from_loan,
    scheduled_cashflow_from_loan,
)
from bma_standard_formulas.formulas import generate_smm_curve_from_psa


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_actual_cashflow(loan_id: int = 1, balance: float = 1_000_000.0):
    loan = Loan(
        loan_id=loan_id,
        origination_date=date(2024, 1, 1),
        asof_date=date(2024, 1, 1),
        original_balance=balance,
        current_balance=balance,
        rate_margin=6.0,
        original_term=360,
        remaining_term=360,
        group_id=None,
    )
    sched = scheduled_cashflow_from_loan(loan)
    smm = generate_smm_curve_from_psa(100.0, loan.original_term)
    n = loan.original_term + 1
    actual = actual_cashflow_from_loan(
        loan=loan,
        scheduled_cf=sched,
        smm_curve=smm,
        mdr_curve=np.zeros(n),
        severity_curve=np.zeros(n),
    )
    return actual


# ---------------------------------------------------------------------------
# 1. Legacy contract — pinned so Phase 1d.3 expansion is backward compatible
# ---------------------------------------------------------------------------


class TestArithmetic:
    def test_constant_evaluates(self):
        assert _safe_eval_expr("3.14", {}) == pytest.approx(3.14)

    def test_identifier_lookup(self):
        assert _safe_eval_expr("x", {"x": 42.0}) == pytest.approx(42.0)

    def test_missing_identifier_returns_zero(self):
        """Legacy behavior: missing names default to 0.0 silently."""
        assert _safe_eval_expr("missing", {}) == 0.0

    def test_addition_subtraction(self):
        assert _safe_eval_expr("a + b - c", {"a": 10.0, "b": 5.0, "c": 3.0}) == 12.0

    def test_multiplication_division(self):
        assert _safe_eval_expr("a * b / c", {"a": 6.0, "b": 4.0, "c": 2.0}) == 12.0

    def test_power_and_modulo(self):
        assert _safe_eval_expr("2 ** 3", {}) == 8.0
        assert _safe_eval_expr("10 % 3", {}) == 1.0

    def test_unary_negate(self):
        assert _safe_eval_expr("-x", {"x": 5.0}) == -5.0

    def test_unary_plus(self):
        assert _safe_eval_expr("+x", {"x": 5.0}) == 5.0


class TestWhitelistedFunctions:
    def test_min_max_abs(self):
        assert _safe_eval_expr("min(3, 1, 2)", {}) == 1.0
        assert _safe_eval_expr("max(3, 1, 2)", {}) == 3.0
        assert _safe_eval_expr("abs(-7)", {}) == 7.0

    def test_unsupported_function_rejected(self):
        with pytest.raises(ValueError, match="Unsupported function"):
            _safe_eval_expr("eval('1+1')", {})

    def test_attribute_access_without_loanproxy_rejected(self):
        """Plain dict/object attribute access is not allowed — sandbox escape."""
        class Sneaky:
            x = 42
        with pytest.raises(ValueError, match="Attribute access only allowed"):
            _safe_eval_expr("obj.x", {"obj": Sneaky()})


# ---------------------------------------------------------------------------
# 2. Phase 1d.3: comparisons, boolean ops, conditional expressions
# ---------------------------------------------------------------------------


class TestCompareOps:
    def test_simple_comparisons(self):
        assert _safe_eval_expr("1 < 2", {}) == 1.0
        assert _safe_eval_expr("1 > 2", {}) == 0.0
        assert _safe_eval_expr("1 == 1", {}) == 1.0
        assert _safe_eval_expr("1 != 2", {}) == 1.0
        assert _safe_eval_expr("2 <= 2", {}) == 1.0
        assert _safe_eval_expr("2 >= 3", {}) == 0.0

    def test_chained_comparison(self):
        """Python's `a < b < c` is one Compare node — test it works."""
        assert _safe_eval_expr("1 < 2 < 3", {}) == 1.0
        assert _safe_eval_expr("1 < 2 < 1", {}) == 0.0

    def test_comparison_with_identifiers(self):
        ctx = {"x": 5.0, "y": 10.0}
        assert _safe_eval_expr("x < y", ctx) == 1.0
        assert _safe_eval_expr("x >= y", ctx) == 0.0


class TestBoolOps:
    def test_and_short_circuits(self):
        # The `b > 0` branch should never evaluate b/0 because the first
        # operand is False. We test by ensuring a divide-by-zero would
        # have surfaced if both branches evaluated.
        assert _safe_eval_expr("False and (1 / 0)", {}) == 0.0

    def test_or_short_circuits(self):
        assert _safe_eval_expr("True or (1 / 0)", {}) == 1.0

    def test_not_operator(self):
        assert _safe_eval_expr("not (1 < 0)", {}) == 1.0
        assert _safe_eval_expr("not (1 > 0)", {}) == 0.0


class TestIfExp:
    def test_ternary_conditional(self):
        assert _safe_eval_expr("100 if x > 0 else 0", {"x": 5.0}) == 100.0
        assert _safe_eval_expr("100 if x > 0 else 0", {"x": -5.0}) == 0.0


# ---------------------------------------------------------------------------
# 3. Phase 1d.3: LoanProxy whitelist semantics
# ---------------------------------------------------------------------------


class TestLoanProxy:
    def test_whitelisted_scalar_attributes(self):
        cf = _build_actual_cashflow(loan_id=42, balance=750_000.0)
        proxy = LoanProxy(cf)
        assert proxy.loan_id == 42
        assert proxy.original_balance == pytest.approx(750_000.0)
        assert proxy.original_term == 360

    def test_whitelisted_array_attribute_returns_proxy(self):
        cf = _build_actual_cashflow()
        proxy = LoanProxy(cf)
        arr = proxy.perf_bal
        assert isinstance(arr, _LoanArrayProxy)

    def test_array_proxy_supports_subscripting(self):
        cf = _build_actual_cashflow(balance=1_000_000.0)
        proxy = LoanProxy(cf)
        # Period 0 perf_bal == initial balance.
        assert proxy.perf_bal[0] == pytest.approx(1_000_000.0)

    def test_array_proxy_returns_zero_for_out_of_bounds(self):
        cf = _build_actual_cashflow()
        proxy = LoanProxy(cf)
        # Out-of-bounds: defensive default rather than IndexError.
        assert proxy.perf_bal[9999] == 0.0
        assert proxy.perf_bal[-1] == 0.0  # negative also rejected

    def test_array_proxy_rejects_non_numeric_index(self):
        cf = _build_actual_cashflow()
        proxy = LoanProxy(cf)
        with pytest.raises(ValueError, match="numeric"):
            proxy.perf_bal["not_a_number"]

    def test_proxy_getattr_rejects_arbitrary_attribute(self):
        cf = _build_actual_cashflow()
        proxy = LoanProxy(cf)
        with pytest.raises(ValueError, match="not exposed"):
            proxy.some_random_attr

    def test_dunder_access_blocked_at_ast_level(self):
        """Sandbox safety: ``__class__`` / ``__dict__`` etc. resolve via
        Python MRO and bypass ``__getattr__``. The AST walker enforces
        the whitelist at the expression level, so an IR expression
        cannot reach dunder attrs even though direct Python access
        would succeed.
        """
        cf = _build_actual_cashflow()
        ctx = {"l": LoanProxy(cf)}
        with pytest.raises(ValueError, match="not exposed"):
            _safe_eval_expr("l.__class__", ctx)
        with pytest.raises(ValueError, match="not exposed"):
            _safe_eval_expr("l.__doc__", ctx)
        with pytest.raises(ValueError, match="not exposed"):
            _safe_eval_expr("l.__init__", ctx)

    def test_arbitrary_attribute_blocked_at_ast_level(self):
        cf = _build_actual_cashflow()
        ctx = {"l": LoanProxy(cf)}
        with pytest.raises(ValueError, match="not exposed"):
            _safe_eval_expr("l.totally_made_up_field", ctx)


# ---------------------------------------------------------------------------
# 4. Phase 1d.3: comprehensions over loans
# ---------------------------------------------------------------------------


class TestLoanComprehensions:
    @pytest.fixture
    def loans_ctx(self):
        cfs = [_build_actual_cashflow(loan_id=i, balance=1_000_000.0) for i in (1, 2, 3)]
        return {"loans": [LoanProxy(cf) for cf in cfs], "i": 1.0}

    def test_count_via_len(self, loans_ctx):
        result = _safe_eval_expr("len(loans)", loans_ctx)
        assert result == 3.0

    def test_filtered_count(self, loans_ctx):
        # All loans have perf_bal[1] > 0, so filtered count == total.
        result = _safe_eval_expr(
            "len([l for l in loans if l.perf_bal[i] > 0])", loans_ctx,
        )
        assert result == 3.0

    def test_sum_over_attribute(self, loans_ctx):
        # Sum of period-1 perf_bal across all loans equals sum of starting
        # balances minus first scheduled amortization.
        result = _safe_eval_expr(
            "sum(l.perf_bal[i] for l in loans)", loans_ctx,
        )
        # Each loan's period-1 perf_bal is approximately 999,500ish (after
        # one period of amortization at ~6% on $1M).
        assert result > 2_990_000.0
        assert result < 3_000_000.0

    def test_filter_with_compound_condition(self):
        cfs = [_build_actual_cashflow(loan_id=i, balance=1_000_000.0) for i in (1, 2, 3)]
        ctx = {
            "loans": [LoanProxy(cf) for cf in cfs],
            "i": 1.0,
            "threshold": 500_000.0,
        }
        # All loans have perf_bal > threshold, so filter passes all.
        result = _safe_eval_expr(
            "len([l for l in loans if l.perf_bal[i] > threshold and l.original_balance == 1000000])",
            ctx,
        )
        assert result == 3.0

    def test_balance_weighted_average(self, loans_ctx):
        """Balance-weighted average of the gross_rate (a RATIO field).

        sum(l.original_balance * l.gross_rate[i] for l in loans) /
            sum(l.original_balance for l in loans)
        """
        result = _safe_eval_expr(
            "sum(l.original_balance * l.gross_rate[i] for l in loans) / "
            "sum(l.original_balance for l in loans)",
            loans_ctx,
        )
        # All loans have the same coupon (6%); weighted-average == 6%.
        # gross_rate is annualized so the value is ~0.06 (decimal).
        assert result == pytest.approx(0.06, abs=1e-6)

    def test_any_short_circuits(self, loans_ctx):
        # any() is whitelisted; expression must evaluate to a truthy value.
        # `any(l.perf_bal[i] > 0 for l in loans)` should yield True == 1.0.
        result = _safe_eval_expr(
            "any(l.perf_bal[i] > 0 for l in loans)", loans_ctx,
        )
        assert result == 1.0

    def test_all_with_filter(self, loans_ctx):
        result = _safe_eval_expr(
            "all(l.perf_bal[i] > 0 for l in loans)", loans_ctx,
        )
        assert result == 1.0

    def test_empty_loans_zero_count(self):
        result = _safe_eval_expr("len(loans)", {"loans": []})
        assert result == 0.0

    def test_empty_loans_zero_sum(self):
        result = _safe_eval_expr(
            "sum(l.perf_bal[i] for l in loans)",
            {"loans": [], "i": 1.0},
        )
        assert result == 0.0

    def test_empty_loans_sum_filtered(self):
        # all() on an empty iterable is True; len() of empty list is 0.
        assert _safe_eval_expr("all(l.perf_bal[i] > 0 for l in loans)", {"loans": [], "i": 1.0}) == 1.0
        assert _safe_eval_expr("any(l.perf_bal[i] > 0 for l in loans)", {"loans": [], "i": 1.0}) == 0.0


# ---------------------------------------------------------------------------
# 5. Phase 1d.3: sandbox guards
# ---------------------------------------------------------------------------


class TestSandboxGuards:
    def test_nested_comprehensions_rejected(self):
        cf = _build_actual_cashflow()
        ctx = {"loans": [LoanProxy(cf)], "i": 1.0}
        # Multi-generator (nested loop) comprehension is rejected.
        with pytest.raises(ValueError, match="Nested"):
            _safe_eval_expr(
                "len([l for l in loans for x in l.perf_bal])",
                ctx,
            )

    def test_subscript_only_on_loan_array_proxy(self):
        # Direct subscripting on a non-array context value is rejected.
        with pytest.raises(ValueError, match="Subscripting only allowed"):
            _safe_eval_expr("x[0]", {"x": 5.0})

    def test_attribute_only_on_loan_proxy(self):
        # Attribute access on a non-LoanProxy is rejected.
        class Foo:
            bar = 1
        with pytest.raises(ValueError, match="Attribute access only allowed"):
            _safe_eval_expr("obj.bar", {"obj": Foo()})

    def test_top_level_must_be_numeric(self):
        # An expression returning a non-numeric value (raw list) at the top
        # level is rejected by the outer wrapper.
        cf = _build_actual_cashflow()
        ctx = {"loans": [LoanProxy(cf)], "i": 1.0}
        with pytest.raises(ValueError, match="Expression result must be numeric"):
            _safe_eval_expr("[l for l in loans]", ctx)

    def test_unsupported_node_rejected(self):
        # Lambda is not whitelisted.
        with pytest.raises(ValueError, match="Unsupported expression node"):
            _safe_eval_expr("lambda x: x + 1", {})

    def test_string_constant_allowed_in_comparison(self):
        # Phase 9: string constants are now allowed so condition_expr can compare
        # deal_state strings (e.g. deal_state == "EARLY_AMORTIZATION").
        # A bare string literal as the outermost expression is rejected at the
        # numeric coercion step (not at the constant step).
        ctx = {"deal_state": "EARLY_AMORTIZATION"}
        result = _safe_eval_expr('deal_state == "EARLY_AMORTIZATION"', ctx)
        assert result == pytest.approx(1.0)
        result_no = _safe_eval_expr('deal_state == "REVOLVING"', ctx)
        assert result_no == pytest.approx(0.0)

    def test_bare_string_expression_still_rejected(self):
        # A bare string literal as the outermost expression produces a string
        # value which cannot be coerced to float; the coercion step rejects it.
        with pytest.raises(ValueError, match="Expression result must be numeric"):
            _safe_eval_expr("'hello'", {})


# ---------------------------------------------------------------------------
# 6. Phase 1d.3: bool result coercion to float at outer level
# ---------------------------------------------------------------------------


class TestBoolResultCoercion:
    def test_true_coerces_to_one(self):
        assert _safe_eval_expr("1 < 2", {}) == 1.0

    def test_false_coerces_to_zero(self):
        assert _safe_eval_expr("1 > 2", {}) == 0.0

    def test_complex_bool_returns_float(self):
        assert _safe_eval_expr("(1 < 2) and (3 > 1)", {}) == 1.0
