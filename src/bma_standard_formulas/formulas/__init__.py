# Requires Python 3.12+
"""
BMA Standard Formulas — mathematical implementations of the BMA
Uniform Practices/Standard Formulas document (February 1, 1999).

Modules:
    scheduled_payments  B.1: balance factor, payment factor, amortization
    payment_models      B.2–B.4, C: SMM/CPR/PSA/ABS/CDR/MDR/SDA conversions
                        and historical speed recovery
    cashflows           C.3: scheduled and actual cashflow runners and
                        frozen result dataclasses
    examples            Reference examples from the BMA document

Usage::

    from bma_standard_formulas.formulas import (
        psa_to_cpr,
        generate_psa_curve,
        run_bma_scheduled_cashflow,
        BMAScheduledCashflow,
    )
"""

# B.1 Scheduled payments
from bma_standard_formulas.formulas.scheduled_payments import (
    sch_balance_factor_fixed_rate,
    sch_payment_factor_fixed_rate,
    sch_am_factor_fixed_rate,
    sch_payment_factor,
    am_factor,
    sch_payment_factor_vector,
    sch_balance_factors,
    sch_ending_balance_factor,
)

# B.2–B.4, C: Payment models
from bma_standard_formulas.formulas.payment_models import (
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
    smm_to_abs,
    generate_smm_curve_from_abs,
    historical_abs,
    cdr_to_mdr,
    cdr_to_mdr_vector,
    sda_to_cdr,
    generate_sda_curve,
)

# C.3: Cashflow runners and result dataclasses
from bma_standard_formulas.formulas.cashflows import (
    BMAScheduledCashflow,
    BMAActualCashflow,
    CashFlowPair,
    CashFlowPairValidationError,
    FieldKind,
    PortfolioModeError,
    run_bma_scheduled_cashflow,
    run_bma_actual_cashflow,
    compare_arrays,
)

# Reference examples
from bma_standard_formulas.formulas.examples import (
    PrepayType,
    DefaultType,
    OriginationParams,
    CurrentState,
    CashFlowAssumptions,
    PeriodCashFlows,
    BMAExample,
)

__all__ = [
    # B.1
    "sch_balance_factor_fixed_rate",
    "sch_payment_factor_fixed_rate",
    "sch_am_factor_fixed_rate",
    "sch_payment_factor",
    "am_factor",
    "sch_payment_factor_vector",
    "sch_balance_factors",
    "sch_ending_balance_factor",
    # B.2–B.4, C
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
    "smm_to_abs",
    "generate_smm_curve_from_abs",
    "historical_abs",
    "cdr_to_mdr",
    "cdr_to_mdr_vector",
    "sda_to_cdr",
    "generate_sda_curve",
    # C.3
    "BMAScheduledCashflow",
    "BMAActualCashflow",
    "CashFlowPair",
    "CashFlowPairValidationError",
    "FieldKind",
    "PortfolioModeError",
    "run_bma_scheduled_cashflow",
    "run_bma_actual_cashflow",
    "compare_arrays",
    # Examples
    "PrepayType",
    "DefaultType",
    "OriginationParams",
    "CurrentState",
    "CashFlowAssumptions",
    "PeriodCashFlows",
    "BMAExample",
]