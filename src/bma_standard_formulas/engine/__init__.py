# Requires Python 3.12+
"""
BMA cashflow engine — application layer built on the BMA formulas.

Modules:
    loan                Loan dataclass, rate vector construction, per-loan
                        cashflow wrappers, and portfolio runner functions
    portfolio           PortfolioCashflow aggregation container and trust
                        waterfall (apply_waterfall)
    tape                TapeSchema and read_loan_tape: CSV/DataFrame → list[Loan]
    rate_index          RateIndex: dated market rate curve for floating-rate loans
    cashflow_persistence  Parquet I/O for cashflow objects

Usage::

    from bma_standard_formulas.engine import (
        Loan,
        TapeSchema,
        read_loan_tape,
        run_scheduled_portfolio,
        PortfolioCashflow,
    )
"""

# Loan data model and cashflow wrappers
from bma_standard_formulas.engine.loan import (
    Loan,
    build_rate_vector,
    scheduled_cashflow_from_loan,
    actual_cashflow_from_loan,
    run_scheduled_portfolio,
    run_actual_portfolio,
    run_paired_portfolio,
)

# Portfolio aggregation and waterfall
from bma_standard_formulas.engine.portfolio import (
    PortfolioCashflow,
    PortfolioMode,
    PortfolioOp,
    CrossCollateralMode,
    PortfolioEvent,
    apply_waterfall,
)

# Tape reader
from bma_standard_formulas.engine.tape import (
    TapeSchema,
    FieldSpec,
    TapeReadError,
    read_loan_tape,
    loans_to_dataframe,
)

# Market rate index
from bma_standard_formulas.engine.rate_index import RateIndex

# Cashflow persistence
from bma_standard_formulas.engine.cashflow_persistence import (
    write_cashflow,
    read_scheduled,
    read_actual,
    read_cashflows,
    SCHEDULED_SCHEMA,
    ACTUAL_SCHEMA,
    SchemaValidationError,
)

__all__ = [
    # Loan
    "Loan",
    "build_rate_vector",
    "scheduled_cashflow_from_loan",
    "actual_cashflow_from_loan",
    "run_scheduled_portfolio",
    "run_actual_portfolio",
    "run_paired_portfolio",
    # Portfolio
    "PortfolioCashflow",
    "PortfolioMode",
    "PortfolioOp",
    "CrossCollateralMode",
    "PortfolioEvent",
    "apply_waterfall",
    # Tape
    "TapeSchema",
    "FieldSpec",
    "TapeReadError",
    "read_loan_tape",
    "loans_to_dataframe",
    # Rate index
    "RateIndex",
    # Persistence
    "write_cashflow",
    "read_scheduled",
    "read_actual",
    "read_cashflows",
    "SCHEDULED_SCHEMA",
    "ACTUAL_SCHEMA",
    "SchemaValidationError",
]