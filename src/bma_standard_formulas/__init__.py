# Requires Python 3.12+
"""
BMA Standard Formulas — mortgage cash flows, prepayments, and defaults.

Reference: BMA "Uniform Practices/Standard Formulas" (02/01/99).

Sub-packages
------------
bma_standard_formulas.formulas
    Mathematical implementations of the BMA standard: scheduled payment
    factors (B.1), prepayment and default speed models (B.2–B.4, C),
    cashflow runners and result dataclasses (C.3), and reference examples.

bma_standard_formulas.engine
    Application layer built on the formulas: Loan dataclass, TapeSchema for
    reading collateral tapes, PortfolioCashflow aggregation, RateIndex for
    floating-rate loans, and Parquet cashflow persistence.

Usage::

    # BMA math
    from bma_standard_formulas.formulas import psa_to_cpr, run_bma_scheduled_cashflow

    # Application layer
    from bma_standard_formulas.engine import Loan, read_loan_tape, run_scheduled_portfolio
"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("bma-standard-formulas")
except PackageNotFoundError:
    __version__ = "unknown"