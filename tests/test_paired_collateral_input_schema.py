"""Schema tests for PairedCollateralInput (Phase 1a + 1e).

Validates:
  - PAIRED mode is recognized as a CollateralInputMode discriminator.
  - PairedCollateralInput rejects non-PortfolioCashflow payloads.
  - PairedCollateralInput accepts PAIRED and ACTUAL_ONLY PortfolioMode
    values (Phase 1e: ACTUAL_ONLY supports the ldcma_to_paired adapter
    that routes legacy LDCMA fixtures through the PAIRED runtime branch
    for parity testing).
  - PairedCollateralInput rejects SCHEDULED_ONLY portfolios — the runtime
    requires actual cashflow data via portfolio.pool.
  - DealRunInput round-trips a valid PAIRED payload (the discriminated
    union resolves to PairedCollateralInput).

Note on serialization: PAIRED is in-process only — the wrapped
PortfolioCashflow holds numpy arrays and is not JSON-serializable. These
tests therefore exercise object construction and validation, not
JSON round-trip.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from bma_standard_formulas.deals.schemas.common import CollateralInputMode
from bma_standard_formulas.deals.schemas.input import (
    DealRunInput,
    PairedCollateralInput,
    PooledCollateralInput,
)
from bma_standard_formulas.engine import PortfolioCashflow
from bma_standard_formulas.engine.loan import (
    Loan,
    actual_cashflow_from_loan,
    scheduled_cashflow_from_loan,
)
from bma_standard_formulas.engine.portfolio import PortfolioMode
from bma_standard_formulas.formulas import generate_smm_curve_from_psa
from bma_standard_formulas.formulas.cashflows import CashFlowPair


def _build_paired_portfolio(group_id: str | None = "GROUP_1") -> PortfolioCashflow:
    """Build a one-loan PAIRED PortfolioCashflow for schema tests."""
    loan = Loan(
        loan_id=1,
        origination_date=date(2024, 1, 1),
        asof_date=date(2024, 1, 1),
        original_balance=1_000_000.0,
        current_balance=1_000_000.0,
        rate_margin=6.0,
        original_term=360,
        remaining_term=360,
        group_id=group_id,
    )
    sched = scheduled_cashflow_from_loan(loan)
    smm = generate_smm_curve_from_psa(0.0, loan.original_term)
    actual = actual_cashflow_from_loan(
        loan=loan,
        scheduled_cf=sched,
        smm_curve=smm,
        mdr_curve=np.zeros(loan.original_term + 1),
        severity_curve=np.zeros(loan.original_term + 1),
    )
    pair = CashFlowPair(scheduled=sched, actual=actual)
    return PortfolioCashflow([pair], mode=PortfolioMode.PAIRED)


def test_paired_mode_enum_value():
    assert CollateralInputMode.PAIRED.value == "PAIRED"


def test_paired_input_accepts_paired_portfolio():
    portfolio = _build_paired_portfolio()
    payload = PairedCollateralInput(portfolio=portfolio)
    assert payload.mode == CollateralInputMode.PAIRED
    assert payload.portfolio is portfolio


def test_paired_input_rejects_non_portfolio():
    """Schema rejects e.g. a raw dict or DataFrame with a clear error."""
    with pytest.raises(Exception) as exc_info:
        PairedCollateralInput(portfolio={"not": "a portfolio"})
    assert "PortfolioCashflow" in str(exc_info.value)


def test_paired_input_accepts_actual_only_portfolio():
    """ACTUAL_ONLY portfolios are accepted (Phase 1e).

    The ``ldcma_to_paired`` adapter produces ACTUAL_ONLY portfolios (LDCMA
    inputs have no scheduled stream). The runtime degrades gracefully —
    ``portfolio.scheduled`` raises and is caught, scheduled-stream
    consumers see ``None``, and the loans accessor still works.
    """
    loan = Loan(
        loan_id=1,
        origination_date=date(2024, 1, 1),
        asof_date=date(2024, 1, 1),
        original_balance=1_000_000.0,
        current_balance=1_000_000.0,
        rate_margin=6.0,
        original_term=360,
        remaining_term=360,
        group_id="GROUP_1",
    )
    sched = scheduled_cashflow_from_loan(loan)
    smm = generate_smm_curve_from_psa(0.0, loan.original_term)
    actual = actual_cashflow_from_loan(
        loan=loan,
        scheduled_cf=sched,
        smm_curve=smm,
        mdr_curve=np.zeros(loan.original_term + 1),
        severity_curve=np.zeros(loan.original_term + 1),
    )
    actual_only_portfolio = PortfolioCashflow([actual], mode=PortfolioMode.ACTUAL_ONLY)

    payload = PairedCollateralInput(portfolio=actual_only_portfolio)
    assert payload.mode == CollateralInputMode.PAIRED
    assert payload.portfolio.mode == PortfolioMode.ACTUAL_ONLY


def test_paired_input_rejects_scheduled_only_portfolio():
    """SCHEDULED_ONLY portfolios cannot be used because the runtime needs
    actual cashflow data via ``portfolio.pool``.
    """
    loan = Loan(
        loan_id=1,
        origination_date=date(2024, 1, 1),
        asof_date=date(2024, 1, 1),
        original_balance=1_000_000.0,
        current_balance=1_000_000.0,
        rate_margin=6.0,
        original_term=360,
        remaining_term=360,
        group_id="GROUP_1",
    )
    sched = scheduled_cashflow_from_loan(loan)
    scheduled_only_portfolio = PortfolioCashflow([sched], mode=PortfolioMode.SCHEDULED_ONLY)

    with pytest.raises(Exception) as exc_info:
        PairedCollateralInput(portfolio=scheduled_only_portfolio)
    assert "SCHEDULED_ONLY" in str(exc_info.value)


def test_deal_run_input_with_paired_collateral():
    """DealRunInput accepts a PAIRED collateral payload via the discriminated union."""
    portfolio = _build_paired_portfolio()
    run_input = DealRunInput(
        collateral=PairedCollateralInput(portfolio=portfolio),
        loan_count=1,
        original_collateral_balance=1_000_000.0,
    )
    assert isinstance(run_input.collateral, PairedCollateralInput)
    assert run_input.collateral.mode == CollateralInputMode.PAIRED


def test_other_modes_still_resolve_correctly():
    """The new PAIRED variant doesn't disturb the other discriminated-union variants."""
    pooled_payload = {
        "mode": "POOLED",
        "collateral": {
            "cfdate": [0, 1],
            "balance": [100.0, 90.0],
            "principal": [0.0, 10.0],
            "interest": [0.0, 1.0],
            "cashflow": [0.0, 11.0],
            "loss": [0.0, 0.0],
            "prepbal": [0.0, 0.0],
            "defbal": [0.0, 0.0],
            "recovery": [0.0, 0.0],
            "principal_sched": [0.0, 10.0],
            "principal_unsched": [0.0, 0.0],
            "cpr": [0.0, 0.0],
            "cdr": [0.0, 0.0],
            "sev": [0.0, 0.0],
            "dq": [0.0, 0.0],
            "surv_fac": [1.0, 1.0],
            "sched_coupon": [6.0, 6.0],
            "sched_netcoupon": [5.0, 5.0],
            "coupon": [6.0, 6.0],
            "effcoupon": [6.0, 6.0],
            "sched_balance": [100.0, 90.0],
            "discount_factor": [1.0, 1.0],
        },
    }
    run_input = DealRunInput.model_validate({
        "collateral": pooled_payload,
        "loan_count": 1,
        "original_collateral_balance": 100.0,
    })
    assert isinstance(run_input.collateral, PooledCollateralInput)
    assert run_input.collateral.mode == CollateralInputMode.POOLED
