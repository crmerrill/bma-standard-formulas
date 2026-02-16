# Requires Python 3.12+
"""
BMA Standard Formulas — mortgage cash flows, prepayments, and defaults.

Reference: BMA "Uniform Practices/Standard Formulas" (02/01/99).
"""

from __future__ import annotations

__version__ = "0.3.1"

# Scheduled payments (B.1)
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

# Payment models (B.2–B.4, C)
from bma_standard_formulas.payment_models import (
    smm_from_factors,
    smm_to_cpr,
    smm_to_cpr_vector,
    cpr_to_smm,
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
    abs_to_smm,
    historical_abs,
    cdr_to_mdr,
    cdr_to_mdr_vector,
    sda_to_cdr,
    generate_sda_curve,
)

# Cashflows (C.3) and Loan
from bma_standard_formulas.cashflows import (
    BMAScheduledCashflow,
    BMAActualCashflow,
    run_bma_scheduled_cashflow,
    run_bma_actual_cashflow,
    compare_arrays,
    Loan,
    scheduled_cashflow_from_loan,
    actual_cashflow_from_loan,
)

# Examples (optional; heavy dataclasses/enums)
from bma_standard_formulas.examples import (
    PrepayType,
    DefaultType,
    OriginationParams,
    CurrentState,
    CashFlowAssumptions,
    PeriodCashFlows,
    BMAExample,
)

__all__ = [
    "__version__",
    # Scheduled payments
    "sch_balance_factor_fixed_rate",
    "sch_payment_factor_fixed_rate",
    "sch_am_factor_fixed_rate",
    "sch_payment_factor",
    "am_factor",
    "sch_payment_factor_vector",
    "sch_balance_factors",
    "sch_ending_balance_factor",
    # Payment models
    "smm_from_factors",
    "smm_to_cpr",
    "smm_to_cpr_vector",
    "cpr_to_smm",
    "cpr_to_smm_vector",
    "psa_to_cpr",
    "cpr_to_psa",
    "psa_to_smm",
    "generate_psa_curve",
    "generate_smm_curve_from_psa",
    "project_act_end_factor",
    "historical_smm_fixed_rate",
    "historical_cpr_fixed_rate",
    "historical_smm",
    "historical_cpr",
    "historical_psa",
    "historical_smm_pool",
    "historical_cpr_pool",
    "historical_psa_pool",
    "abs_to_smm",
    "historical_abs",
    "cdr_to_mdr",
    "cdr_to_mdr_vector",
    "sda_to_cdr",
    "generate_sda_curve",
    # Cashflows
    "BMAScheduledCashflow",
    "BMAActualCashflow",
    "run_bma_scheduled_cashflow",
    "run_bma_actual_cashflow",
    "compare_arrays",
    "Loan",
    "scheduled_cashflow_from_loan",
    "actual_cashflow_from_loan",
    # Examples
    "PrepayType",
    "DefaultType",
    "OriginationParams",
    "CurrentState",
    "CashFlowAssumptions",
    "PeriodCashFlows",
    "BMAExample",
]
