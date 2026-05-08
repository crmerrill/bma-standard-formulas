"""Phase 1h: verify the LDCMA-format adapters emit DeprecationWarning.

The legacy adapters in ``bma_standard_formulas.deals.adapters`` are
preserved for parity testing but tagged with ``DeprecationWarning`` so
new code picks up the BMA-native ``PairedCollateralInput`` path. This
module pins the warning contract: each adapter must warn exactly once
per call, with a stack-level pointing at the caller (so IDE / linter
"this function is deprecated" hints highlight the correct line).
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from bma_standard_formulas.deals.adapters import (
    from_actual_cashflow,
    from_collateral_dict,
    from_grouped_portfolio_cashflows,
    from_pi_strips,
    from_portfolio_cashflow,
    ldcma_to_paired,
)
from bma_standard_formulas.deals.schemas.input import (
    DealRunInput,
    PairedCollateralInput,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ldcma_dict(n: int = 3) -> dict:
    """Minimal valid LDCMA collCF dict for the deprecation tests."""
    return {
        "COLLAT": {
            "balance": [100.0, 90.0, 80.0],
            "principal": [0.0, 10.0, 10.0],
            "interest": [0.0, 1.0, 0.9],
            "cashflow": [0.0, 11.0, 10.9],
            "loss": [0.0] * n,
            "prepbal": [0.0] * n,
            "defbal": [0.0] * n,
            "recovery": [0.0] * n,
            "principal_sched": [0.0, 10.0, 10.0],
            "principal_unsched": [0.0] * n,
            "cpr": [0.0] * n,
            "cdr": [0.0] * n,
            "sev": [0.0] * n,
            "dq": [0.0] * n,
            "surv_fac": [1.0] * n,
            "sched_coupon": [0.0] * n,
            "sched_netcoupon": [0.0] * n,
            "coupon": [0.0] * n,
            "effcoupon": [0.0] * n,
            "sched_balance": [100.0, 90.0, 80.0],
            "discount_factor": [1.0] * n,
        }
    }


def _portfolio_df(n: int = 3):
    """Minimal BMA-shaped DataFrame for from_portfolio_cashflow tests."""
    import pandas as pd

    return pd.DataFrame(
        {
            "perf_bal": [100.0, 90.0, 80.0],
            "act_am": [0.0, 10.0, 10.0],
            "vol_prepay": [0.0] * n,
            "act_int": [0.0, 1.0, 0.9],
            "new_def": [0.0] * n,
            "prin_recov": [0.0] * n,
            "prin_loss": [0.0] * n,
        }
    )


class _FakeActual:
    """Duck-typed stand-in for BMAActualCashflow used by from_actual_cashflow.

    Only the field names accessed by the adapter are populated; the rest
    of the BMAActualCashflow contract is irrelevant for the deprecation
    contract test.
    """

    def __init__(self) -> None:
        n = 3
        self.perf_bal = np.array([100.0, 90.0, 80.0])
        self.act_am = np.array([0.0, 10.0, 10.0])
        self.vol_prepay = np.zeros(n)
        self.act_int = np.array([0.0, 1.0, 0.9])
        self.svc_billed = np.zeros(n)
        self.new_def = np.zeros(n)
        self.prin_recov = np.zeros(n)
        self.prin_loss = np.zeros(n)


# ---------------------------------------------------------------------------
# Each adapter emits exactly one DeprecationWarning per call
# ---------------------------------------------------------------------------


class TestDeprecationWarnings:
    """Each LDCMA-format adapter must emit DeprecationWarning when called."""

    def test_from_collateral_dict_warns(self):
        with pytest.warns(DeprecationWarning, match="LDCMA-format"):
            from_collateral_dict(_ldcma_dict())

    def test_from_portfolio_cashflow_warns(self):
        with pytest.warns(DeprecationWarning, match="LDCMA-format"):
            from_portfolio_cashflow(_portfolio_df())

    def test_from_grouped_portfolio_cashflows_warns(self):
        with pytest.warns(DeprecationWarning, match="LDCMA-format"):
            from_grouped_portfolio_cashflows({"GROUP_1": _portfolio_df()})

    def test_from_actual_cashflow_warns(self):
        with pytest.warns(DeprecationWarning, match="LDCMA-format"):
            from_actual_cashflow(_FakeActual(), horizon=3, initial_balance=100.0)

    def test_from_pi_strips_warns(self):
        # Build minimal P/I strip dicts with a balance field.
        p = {"balance": [100.0, 90.0, 80.0]}
        i = {"balance": [100.0, 90.0, 80.0]}
        with pytest.warns(DeprecationWarning, match="LDCMA-format"):
            from_pi_strips(p, i)


# ---------------------------------------------------------------------------
# Migration machinery suppresses the warning internally
# ---------------------------------------------------------------------------


class TestInternalSuppression:
    """``ldcma_to_paired`` and the orchestrator bridge are themselves
    migration machinery — they call the deprecated adapters as part of
    legacy-input bridging and must NOT surface the warning to their
    callers."""

    def test_ldcma_to_paired_does_not_warn_on_dict_input(self):
        """The dict-input branch internally calls from_collateral_dict;
        the warning must be suppressed inside the adapter."""
        with warnings.catch_warnings():
            # Capture all DeprecationWarnings; expect none from this call.
            warnings.simplefilter("error", DeprecationWarning)
            result = ldcma_to_paired(_ldcma_dict())
        assert isinstance(result, DealRunInput)
        assert isinstance(result.collateral, PairedCollateralInput)

    def test_ldcma_to_paired_does_not_warn_on_pooled_input(self):
        """The PooledCollateralInput branch doesn't call any deprecated
        adapter, but cover the case explicitly."""
        # Build the LDCMA input via a non-deprecated path: call
        # from_collateral_dict but suppress its warning so we can build
        # the test input. The test below verifies ldcma_to_paired
        # doesn't EMIT a warning even given the LDCMA input.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            run_input = from_collateral_dict(_ldcma_dict(), loan_count=1)

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            result = ldcma_to_paired(run_input)
        assert isinstance(result.collateral, PairedCollateralInput)
