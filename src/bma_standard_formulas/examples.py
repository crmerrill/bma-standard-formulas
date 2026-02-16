"""
BMA Standard Formulas - Example Loan Data

**Version**: 2.1.0
**Last Updated**: 2026-01-22
**Status**: Draft

Organized numerical examples from BMA "Uniform Practices/Standard Formulas" (02/01/99).
Variable names follow BMA C.3 (SF-17 to SF-18) standard terminology.

Structure:
  (1) OriginationParams - loan characteristics at birth
  (2) CurrentState - loan state at beginning of period (asof_date)
  (3) CashFlowAssumptions - prepay/default/servicing assumptions + end_date
  (4) PeriodCashFlows - computed results for single or aggregate periods
  
  cashflows is Dict[Tuple[int, int], PeriodCashFlows] where key is (asof_period, window_length)
  - Single period: (15, 1) = month 15, 1-month window
  - Aggregate: (15, 6) = as-of month 15, 6-month window (months 10-15)
"""

from dataclasses import dataclass
from typing import Optional, Dict, Tuple
from enum import Enum
import datetime as dt


# =============================================================================
# ENUMS
# =============================================================================

class PrepayType(Enum):
    """Prepayment rate types (SF-5)."""
    SMM = "SMM"
    CPR = "CPR"
    PSA = "PSA"


class DefaultType(Enum):
    """Default rate types (SF-19/20)."""
    MDR = "MDR"
    CDR = "CDR"
    SDA = "SDA"


# =============================================================================
# (1) ORIGINATION PARAMETERS - Loan characteristics at birth
# =============================================================================

@dataclass
class OriginationParams:
    """Static loan/pool characteristics at origination."""
    original_balance: float              # Original face amount ($) or 1.0 for normalized
    gross_coupon: float                  # WAC % (annual rate, e.g., 9.5 = 9.5%)
    original_term: float                 # M0 - original term in months (can be fractional for pools)
    origination_date: Optional[dt.date]  # Issue date (None if not specified)


# =============================================================================
# (2) CURRENT STATE - Loan state at beginning of calculation period
# =============================================================================

@dataclass
class CurrentState:
    """Loan/pool state at beginning of calculation period."""
    asof_date: Optional[dt.date]         # Beginning of period date (None if not specified)
    loan_age: float                      # WALA - loan age at start of window (months, can be fractional for pools)
    current_balance: float               # Performing balance at start of period
    current_factor: float                # Pool factor at this point in time
    remaining_term: float                # WAM - months remaining (can be fractional for pools)


# =============================================================================
# (3) CASH FLOW ASSUMPTIONS - Projection assumptions + end date
# =============================================================================

@dataclass
class CashFlowAssumptions:
    """Assumptions for cash flow projection from asof_period to end_period."""
    end_date: Optional[dt.date]          # End of period / settlement date (None if not specified)
    end_period: int                      # Loan age at end of window (required)
    prepay_type: PrepayType              # SMM, CPR, or PSA
    prepay_speed: float                  # Rate (% for SMM/CPR, multiple for PSA)
    default_type: DefaultType            # MDR, CDR, or SDA
    default_speed: float                 # Rate (% for MDR/CDR, multiple for SDA)
    servicing_fee: float                 # Annual % (0.50 = 50bps, agency standard)
    servicing_advance: bool = False      # True = servicer advances P&I on delinquent loans
    recovery_months: int = 12            # Months from default to recovery (typically 12)
    loss_severity: float = 0.20          # Loss as fraction of defaulted balance (0.20 = 20%)


# =============================================================================
# (4) PERIOD CASH FLOWS - Computed outputs for single or aggregate periods
# =============================================================================

@dataclass
class PeriodCashFlows:
    """
    Cash flow outputs for a single or aggregate period from BMA C.3 (SF-17 to SF-18).
    ALL fields must be filled for every example (use 0.0 if not applicable).
    Values shown with inline computation documentation.
    
    Note: CurrentState represents loan BEFORE calculation; PeriodCashFlows represents
    the output AFTER applying assumptions for the period(s).
    
    BMA Age Convention:
    - Age is 0-indexed from origination (age 0 = origination, age n = n months elapsed)
    - Window defined by [beg_period, asof_period] where both are ages
    - Example: age 9 to age 15 = 6-month window starting after month 9
    
    Temporal mapping:
    - beg_period/beg_date: Starting age/date of observation window (matches CurrentState.asof_date for the window)
    - asof_period/asof_date: Ending age/date of observation window (matches CashFlowAssumptions.end_date)
    - Single period: asof_period - beg_period = 1
    - Aggregate: asof_period - beg_period > 1
    
    For aggregates:
    - Balance/factor fields: values at starting and ending ages
    - Flow fields (interest, principal): SUMS over the window
    - Rate fields (smm, cpr): AVERAGES over the window
    """
    # === Period/Temporal Info ===
    # BMA age is 0-indexed: age 0 = origination, age n = n months after origination
    asof_date: Optional[dt.date]         # Calendar date at ending age (None if not specified)
    beg_date: Optional[dt.date] = None   # Calendar date at starting age (None = single period)
    asof_period: int = 0                 # Ending age (0-indexed months from origination)
    beg_period: Optional[int] = None     # Starting age (0-indexed); window = [beg_period, asof_period]
    loan_age: float = 0                  # WALA at ending age (can be fractional for pools)
    remaining_term: float = 0            # WAM at ending age (can be fractional for pools)
    
    @property
    def is_aggregate(self) -> bool:
        """True if this represents multiple periods (window_length > 1)."""
        if self.beg_period is None:
            return False
        return self.beg_period < self.asof_period - 1
    
    # === Balance & Factor Variables ===
    # BMA age convention: age is 0-indexed from origination
    # For window [beg_period, asof_period], e.g. age 9 to age 15:
    bal1: float = 0.0                    # BAL(beg_period): scheduled balance at starting age (no prepay)
    bal2: float = 0.0                    # BAL(asof_period): scheduled balance at ending age (no prepay)
    surv_fac1: float = 0.0               # F(beg_period): observed pool factor at starting age (F1, includes prepays)
    surv_fac2: float = 0.0               # F(asof_period): observed pool factor at ending age (F2, includes prepays)
    surv_fac2_sched: float = 0.0         # F_sched: = surv_fac1 × (bal2/bal1), expected if 0% prepay / -
    perf_bal: float = 0.0                # Performing balance at ending age (= surv_fac2 if no defaults)
    
    # === Amortization ===
    sch_am: float = 0.0                  # Scheduled amortization = ((bal1-bal2)/bal1) * surv_fac1
    exp_am: float = 0.0                  # Expected amortization (= sch_am for performing pool)
    act_am: float = 0.0                  # Actual amortization (= exp_am adjusted for defaults)
    tot_am: float = 0.0                  # Total amortization (= act_am + vol_prepay)
    
    # === Prepayment ===
    vol_prepay: float = 0.0              # Voluntary prepayments
    smm: float = 0.0                     # Single Monthly Mortality (decimal, 0-1)
    cpr: float = 0.0                     # Conditional Prepayment Rate (annual %)
    psa: float = 0.0                     # PSA speed (% of benchmark)
    
    # === Defaults ===
    new_def: float = 0.0                 # New defaults this period
    fcl: float = 0.0                     # Loans in foreclosure
    am_def: float = 0.0                  # Amortization from defaults
    mdr: float = 0.0                     # Monthly Default Rate (%)
    cdr: float = 0.0                     # Constant Default Rate (annual %)
    
    # === Interest ===
    gross_int: float = 0.0               # Gross mortgage interest
    svc_fee: float = 0.0                 # Servicing fee
    net_int: float = 0.0                 # Net interest (= gross_int - svc_fee)
    exp_int: float = 0.0                 # Expected interest
    lost_int: float = 0.0                # Interest lost to defaults
    act_int: float = 0.0                 # Actual interest received
    
    # === Pass-Through ===
    pt_prin: float = 0.0                 # Pass-through principal
    pt_int: float = 0.0                  # Pass-through interest (= net_int)
    pt_cf: float = 0.0                   # Total pass-through cash flow
    
    # === Recovery/Loss ===
    prin_recov: float = 0.0              # Principal recovery from defaults
    prin_loss: float = 0.0               # Principal loss
    adb: float = 0.0                     # Amortized default balance in recovery
    
    # === Yield/Duration (SF-49/50/51) ===
    price: float = 0.0                   # Clean price (% of par)
    yield_pct: float = 0.0               # Bond-equivalent yield (%)
    mortgage_yield: float = 0.0          # Mortgage yield (%)
    avg_life: float = 0.0                # Average life (years)
    duration: float = 0.0                # Macaulay duration (years)
    mod_duration: float = 0.0            # Modified duration (years)
    convexity: float = 0.0               # Cash-flow convexity (years^2)
    eff_duration: float = 0.0            # Effective duration (years)
    eff_convexity: float = 0.0           # Effective convexity (years^2)


# =============================================================================
# BMA EXAMPLE - Combines all four components
# =============================================================================

@dataclass
class BMAExample:
    """
    Sample loan/pool from BMA documentation with inputs and expected outputs.
    
    Coupons: annual percentages (9.5 = 9.5%)
    
    cashflows: Dict mapping (asof_period, window_length) to PeriodCashFlows.
               Key format: (asof_period, window_length)
               - Single period: (15, 1) = as-of month 15, 1-month window
               - Aggregate: (15, 6) = as-of month 15, 6-month window
               For very large multi-month examples (Cash Flow A/B), use
               cashflows_file to reference external CSV instead.
    """
    id: str
    description: str
    origination: OriginationParams
    current: CurrentState
    assumptions: CashFlowAssumptions
    cashflows: Optional[Dict[Tuple[int, int], PeriodCashFlows]] = None  # (asof, length) -> PeriodCashFlows
    cashflows_file: Optional[str] = None                                 # Path to multi-month CSV file
    
    @property
    def loan_age(self) -> int:
        """WALA - loan age in months = original_term - remaining_term."""
        return self.origination.original_term - self.current.remaining_term
    
    @property
    def net_coupon(self) -> float:
        """Net coupon = gross_coupon - servicing_fee."""
        return self.origination.gross_coupon - self.assumptions.servicing_fee
    
    @property
    def is_seasoned(self) -> bool:
        """BMA defines seasoned as loan age >= 30 months (SF-5)."""
        return self.loan_age >= 30
    
    @property
    def is_new(self) -> bool:
        """BMA defines new as loan age < 30 months (SF-5)."""
        return self.loan_age < 30


# =============================================================================
# EXAMPLES
# =============================================================================

# =============================================================================
# SF-4: Basic Pass-Through Cash Flow Example
# =============================================================================
SF4 = BMAExample(
    id="SF-4",
    description=(
        "A mortgage pass-through issued with a net coupon of 9.0%, "
        "a gross coupon of 9.5% and a term of 360 months. "
        "First month cash flow calculation (month 1)."
    ),
    
    # (1) ORIGINATION - loan at birth
    origination=OriginationParams(
        original_balance=1.0,                           # Normalized to par (inferred from BMA doc)
        gross_coupon=9.5,                               # Given in example
        original_term=360,                              # Given in example
        origination_date=None,                          # Not specified in example
    ),
    
    # (2) CURRENT STATE - beginning of period (before month 1 payment)
    current=CurrentState(
        asof_date=None,                                 # Not specified in example
        loan_age=0,                                     # WALA at start: 0 (new loan)
        current_balance=1.0,                            # = original_balance (new loan)
        current_factor=1.0,                               # New loan, full balance
        remaining_term=360,                             # Full term (before any payments)
    ),
    
    # (3) CASH FLOW ASSUMPTIONS
    assumptions=CashFlowAssumptions(
        end_date=None,                                  # Not specified in example
        end_period=1,                                   # Loan age at end: 1 (after month 1)
        prepay_type=PrepayType.SMM,                     # Given in example (vol_prepay as SMM)
        prepay_speed=0.00025022,                        # Given in example: vol_prepay amount = SMM * (1 - sch_am)
        default_type=DefaultType.MDR,                   # Not specified in example
        default_speed=0.0,                              # Not specified in example (no defaults)
        servicing_fee=0.50,                             # = 9.5% gross - 9.0% net (given in example)
        recovery_months=12,                             # Not specified (using agency standard)
        loss_severity=0.20,                             # Not specified (using agency standard)
    ),
    
    # (4) CASH FLOWS - computed outputs (ALL fields filled)
    # Key: (asof_period=1, window_length=1) = single period, month 1
    cashflows={(1, 1): PeriodCashFlows(
        # Period/Temporal Info
        asof_date=None,                                 # Not specified in example
        beg_date=None,                                  # Not specified in example
        asof_period=1,                                  # End of window: month 1
        beg_period=0,                                   # Beginning of window: end of month 0 (start of month 1)
        loan_age=1,                                     # After month 1: loan is 1 month old
        remaining_term=359,                             # After month 1: 360 - 1 = 359 remaining
        
        # Balances & Factors
        bal1=1.0,                                       # Scheduled balance at start (no prepay ever)
        bal2=1.0 - 0.00049188,                          # = bal1 - sch_am = 0.99950812 (scheduled, no prepay)
        surv_fac1=1.0,                                  # Actual factor at start (new loan, same as bal1)
        surv_fac2=1.0 - 0.00049188 - 0.00025022,        # = surv_fac1 - sch_am - vol_prepay = 0.9992579
        surv_fac2_sched=1.0 - 0.00049188,                # = bal2 (scheduled factor this period) = 0.99950812
        perf_bal=1.0 - 0.00049188 - 0.00025022,         # = surv_fac2 (no defaults)
        
        # Amortization
        sch_am=0.00049188,                              # = ((bal1-bal2)/bal1)*surv_fac1 = ((1.0-0.99950812)/1.0)*1.0
        exp_am=0.00049188,                              # = sch_am (expected = scheduled for performing)
        act_am=0.00049188,                              # = exp_am (no defaults)
        tot_am=0.00049188 + 0.00025022,                 # = act_am + vol_prepay = 0.0007421
        
        # Prepayment (rates in %, vol_prepay as factor)
        vol_prepay=0.00025022,                          # Given in example: = smm * surv_fac2_sched
        smm=0.0002503438,                               # = vol_prepay / surv_fac2_sched (decimal)
        cpr=0.29999534,                                 # = (1 - (1 - smm)^12) * 100
        psa=149.9976700,                                # = cpr / (6 * min(age,30)/30) = 0.29999534 / 0.2
        
        # Defaults (none in this example)
        new_def=0.0,                                    # Not specified (no defaults)
        fcl=0.0,                                        # Not specified (no defaults)
        am_def=0.0,                                     # Not specified (no defaults)
        mdr=0.0,                                        # Not specified (no defaults)
        cdr=0.0,                                        # Not specified (no defaults)
        
        # Interest
        gross_int=0.00791667,                           # Given: = 1.0 * (9.5/12/100) = 0.00791667
        svc_fee=0.00041667,                             # Given: = 1.0 * (0.5/12/100) = 0.00041667
        net_int=0.00750000,                             # = gross_int - svc_fee = 0.0075
        exp_int=0.00750000,                             # = net_int (no defaults)
        lost_int=0.0,                                   # Not specified (no defaults)
        act_int=0.00750000,                             # = exp_int (no defaults)
        
        # Pass-through
        pt_prin=0.00074210,                             # Given: = sch_am + vol_prepay = 0.0007421
        pt_int=0.00750000,                              # Given: = net_int = 0.0075
        pt_cf=0.00824210,                               # Given: = pt_prin + pt_int = 0.0082421
        
        # Recovery/Loss (none in this example)
        prin_recov=0.0,                                 # Not specified (no defaults)
        prin_loss=0.0,                                  # Not specified (no defaults)
        adb=0.0,                                        # Not specified (no defaults)
        
        #TODO: need to review the risk calculations here.
        # Yield/Duration (computed for 9.0% net, 360mo, at par, constant 0.025% SMM)
        # Projected 360 months with SMM=0.00025 constant each month
        price=100.0,                                    # At par (given)
        yield_pct=9.0,                                  # At par, yield = net coupon = 9.0%
        mortgage_yield=9.0,                             # IRR of monthly payments ≈ yield at par
        avg_life=21.03,                                 # Σ(t*prin_t)/Σ(prin_t) = 252.3mo/12 = 21.03 years
        duration=9.38,                                  # Macaulay: Σ(t*PV_t)/Price in years
        mod_duration=8.98,                              # = duration/(1+y/2) = 9.38/1.045
        convexity=136.2,                                # = Σ(t²*PV_t)/Price in years²
        eff_duration=0.0,                               # Requires ±rate shift repricing (not in SF-4)
        eff_convexity=0.0,                              # Requires ±rate shift repricing (not in SF-4)
    )},
)

# =============================================================================
# SF-7: Prepayment Rate Back-Calculation Example
# =============================================================================
SF7 = BMAExample(
    id="SF-7",
    description=(
        "Ginnie Mae I 9.0% pass-through issued 2/1/88. "
        "Back-calculating prepayment rates from observed factors for month 17."
    ),
    
    # (1) ORIGINATION
    origination=OriginationParams(
        original_balance=1.0,                           # Normalized to par
        gross_coupon=9.5,                               # GNMA I: 50bp servicing -> 9.0% net
        original_term=359,                              # Given in example (359mo remaining at issue)
        origination_date=dt.date(1988, 3, 1),           # Given in example
    ),
    
    # (2) CURRENT STATE - beginning of month 17
    current=CurrentState(
        asof_date=dt.date(1989, 6, 1),                  # Beginning of month 17
        loan_age=16,                                    # WALA at start: 16
        current_balance=0.85150625,                     # = current_factor (observed)
        current_factor=0.85150625,                        # Given in example (observed)
        remaining_term=344,                             # = 360 - 16 (before month 17 amortization)
    ),
    
    # (3) CASH FLOW ASSUMPTIONS
    assumptions=CashFlowAssumptions(
        end_date=dt.date(1989, 7, 1),                   # End of month 17
        end_period=17,                                  # Loan age at end: 17
        prepay_type=PrepayType.CPR,                     # Back-calculated as CPR
        prepay_speed=5.1000,                            # Given in example (back-calculated)
        default_type=DefaultType.MDR,                   # Not specified (no defaults)
        default_speed=0.0,                              # Not specified (no defaults)
        servicing_fee=0.50,                             # GNMA I standard
        recovery_months=12,                             # Agency standard
        loss_severity=0.20,                             # Agency standard
    ),
    
    # (4) CASH FLOWS - computed/observed outputs
    # Key: (asof_period=17, window_length=1) = single period, month 17
    cashflows={(17, 1): PeriodCashFlows(
        # Period/Temporal Info
        asof_date=dt.date(1989, 7, 1),                  # End of window: month 17
        beg_date=dt.date(1989, 6, 1),                   # Beginning of window: start of month 17
        asof_period=17,                                 # End period: month 17
        beg_period=16,                                  # Beginning period: end of month 16 (start of month 17)
        loan_age=17,                                    # After month 17: loan is 17 months old
        remaining_term=343,                             # After month 17: 360 - 17 = 343 remaining
        
        # Balances & Factors
        bal1=0.99213300,                                # Scheduled balance at month 17 start (no prepay ever)
        bal2=0.99157471,                                # Scheduled balance at month 17 end (no prepay ever)
        surv_fac1=0.85150625,                           # Actual factor at start (includes prior prepays)
        surv_fac2=0.84732282,                           # Actual factor at end (includes this month's prepay)
        surv_fac2_sched=0.85102709,                      # Scheduled factor (no prepay this period)
        perf_bal=0.84732282,                            # = surv_fac2 (no defaults)
        
        # Amortization
        sch_am=0.00047916,                              # = ((bal1-bal2)/bal1)*surv_fac1 = ((0.99213300-0.99157471)/0.99213300)*0.85150625
        exp_am=0.00047916,                              # Given in example (scheduled for performing)
        act_am=0.00047916,                              # = exp_am (no defaults)
        tot_am=0.00047916 + 0.00370427,                 # = act_am + vol_prepay = 0.00418343
        
        # Prepayment (rates in %, vol_prepay as factor, back-calculated from observed factors)
        vol_prepay=0.00370427,                          # Given: = surv_fac1 - surv_fac2 - sch_am
        smm=0.0043527000,                               # Given: = vol_prepay / surv_fac2_sched (decimal)
        cpr=5.10000000,                                 # Given: = (1 - (1 - smm)^12) * 100
        psa=150.0000000,                                # Given: = cpr / (6 * min(age,30)/30) = 5.1 / 3.4
        
        # Defaults (none in this example)
        new_def=0.0,                                    # Not specified
        fcl=0.0,                                        # Not specified
        am_def=0.0,                                     # Not specified
        mdr=0.0,                                        # Not specified
        cdr=0.0,                                        # Not specified
        
        # Interest
        gross_int=0.85150625 * 9.5 / 1200,              # = factor_begin * gross_coupon/1200 = 0.00674187
        svc_fee=0.85150625 * 0.5 / 1200,                # = factor_begin * svc_fee/1200 = 0.00035479
        net_int=0.85150625 * 9.0 / 1200,                # = factor_begin * net_coupon/1200 = 0.00638629
        exp_int=0.85150625 * 9.0 / 1200,                # = net_int (no defaults)
        lost_int=0.0,                                   # No defaults
        act_int=0.85150625 * 9.0 / 1200,                # = net_int (no defaults)
        
        # Pass-through
        pt_prin=0.85150625 - 0.84732282,                # = factor_begin - factor_end = 0.00418343
        pt_int=0.85150625 * 9.0 / 1200,                 # = net_int = 0.00638629
        pt_cf=0.85150625 - 0.84732282 + 0.85150625 * 9.0 / 1200,  # = pt_prin + pt_int
        
        # Recovery/Loss (none)
        prin_recov=0.0,                                 # No defaults
        prin_loss=0.0,                                  # No defaults
        adb=0.0,                                        # No defaults
        
        #TODO: need to review the risk calculations here.
        # Yield/Duration (not the focus of SF-7, using SF-49 values for similar loan)
        price=100.0,                                    # Assumed at par
        yield_pct=9.0,                                  # At par ≈ net coupon
        mortgage_yield=9.0,                             # At par ≈ net coupon
        avg_life=9.78,                                  # Similar to SF-49 (150% PSA)
        duration=5.73,                                  # Similar to SF-49
        mod_duration=5.48,                              # Similar to SF-49
        convexity=54.4,                                 # Similar to SF-49
        eff_duration=0.0,                               # Not computed
        eff_convexity=0.0,                              # Not computed
    )},
)

# =============================================================================
# SF-12: Multi-Pool Average Prepayment Rate Example
# Pool 1: GNMA I 9%, orig 4/1/88, $1M original
# =============================================================================
SF12_POOL1 = BMAExample(
    id="SF-12-P1",
    description="Pool 1 for SF-12: GNMA I 9%, orig 4/1/88, $1M original, 6-month observation",
    
    origination=OriginationParams(
        original_balance=1_000_000,                     # Given: $1M
        gross_coupon=9.5,                               # GNMA I: 50bp servicing
        original_term=358,                              # Given in example
        origination_date=dt.date(1988, 4, 1),           # Given in example
    ),
    
    current=CurrentState(
        asof_date=dt.date(1989, 1, 1),                  # 6 months before end
        loan_age=9,                                     # WALA at start: 9
        current_balance=1_000_000 * 0.86925218,         # = orig * factor_begin = 869,252.18
        current_factor=0.86925218,                        # Given: observed factor 6mo before end
        remaining_term=358 - 9,                         # = 349 months remaining
    ),
    
    assumptions=CashFlowAssumptions(
        end_date=dt.date(1989, 7, 1),                   # End of 6-month observation
        end_period=15,                                  # Loan age at end: 15 (9 + 6)
        prepay_type=PrepayType.CPR,                     # Back-calculated as CPR
        prepay_speed=4.35137207,                        # 6-month avg CPR (%) back-calculated below
        default_type=DefaultType.MDR,
        default_speed=0.0,
        servicing_fee=0.50,                             # GNMA I standard
        recovery_months=12,                             # Agency standard
        loss_severity=0.20,                             # Agency standard
    ),
    
    # (4) CASH FLOWS - Pool 1 contributes to combined calculation
    # Back-calculation: actual_surv = 0.84732282/0.86925218 = 0.97477215
    #                   sched_surv = bal2/bal1 = 0.99206679/0.99535309 = 0.99669836
    #                   prepay_surv = 0.97477215/0.99669836 = 0.97800117
    #                   SMM = (1 - 0.97800117^(1/6)) * 100 = 0.370054%, CPR = 4.3514%
    # Key: (asof_period=15, window_length=6) = 6-month aggregate, months 10-15
    cashflows={(15, 6): PeriodCashFlows(
        # Period/Temporal Info
        asof_date=dt.date(1989, 7, 1),                  # End of 6-month window
        beg_date=dt.date(1989, 1, 1),                   # Beginning of 6-month window
        asof_period=15,                                 # End period: month 15
        beg_period=9,                                   # Beginning period: end of month 9 (start of month 10)
        loan_age=15,                                    # After 6mo observation: 9 + 6 = 15
        remaining_term=343,                             # 358 - 15 = 343 remaining
        
        # Balances & Factors (scheduled balances at 9.5% gross, 358mo term)
        bal1=0.99535309,                                # Scheduled balance at age 9 (no prepay ever)
        bal2=0.99206679,                                # Scheduled balance at age 15 (no prepay ever)
        surv_fac1=0.86925218,                           # Actual factor at start (observed)
        surv_fac2=0.84732282,                           # Actual factor at end (observed after 6 months)
        surv_fac2_sched=0.86638222,                     # = surv_fac1 * (bal2/bal1)
        perf_bal=0.84732282,                            # = surv_fac2 (no defaults)
        
        # Amortization
        sch_am=0.00286996,                              # = surv_fac1 * (1 - bal2/bal1)
        exp_am=0.00286996,                              # = sch_am (no defaults)
        act_am=0.00286996,                              # = sch_am (no defaults)
        tot_am=0.02192936,                              # = surv_fac1 - surv_fac2 = 0.86925218 - 0.84732282
        
        # Prepayment (rates in %, 6-month average)
        vol_prepay=0.01905940,                          # = tot_am - sch_am
        smm=0.0037005390,                               # = 1 - prepay_surv^(1/6) (decimal)
        cpr=4.35137207,                                 # = (1 - (1 - smm)^12) * 100
        psa=0.00000000,                                 # N/A - would need age-weighted calc
        
        # Defaults
        new_def=0.00000000,                             # No defaults
        fcl=0.00000000,                                 # No defaults
        am_def=0.00000000,                              # No defaults
        mdr=0.00000000,                                 # No defaults
        cdr=0.00000000,                                 # No defaults
        
        # Interest (6-month sum using scheduled amort + prepay, (1-SMM)=0.9962994610/mo)
        # Balances: $869,252→$865,568→$861,896→$858,235→$854,586→$850,949
        gross_int=40853.86,                             # = sum(monthly_bal * 9.5%/12) for 6 months
        svc_fee=2150.20,                                # = sum(monthly_bal * 0.5%/12) for 6 months
        net_int=38703.65,                               # = sum(monthly_bal * 9.0%/12) for 6 months
        exp_int=38703.65,                               # = net_int (no defaults)
        lost_int=0.00000000,                            # No defaults
        act_int=38703.65,                               # = net_int (no defaults)
        
        # Pass-through (6-month totals, $ amounts)
        pt_prin=21929.36,                               # = $869,252.18 - $847,322.82
        pt_int=38703.65,                                # = net_int
        pt_cf=60633.01,                                 # = pt_prin + pt_int
        
        # Recovery/Loss
        prin_recov=0.00000000,                          # No defaults
        prin_loss=0.00000000,                           # No defaults
        adb=0.00000000,                                 # No defaults
        
        #TODO: need to review the risk calculations here.
        # Yield/Duration (assuming price=100 at par, CPR=4.34% constant)
        price=100.00000000,                             # Assumed: par
        yield_pct=9.00000000,                           # = net coupon at par
        mortgage_yield=9.00000000,                      # = yield for pass-through
        avg_life=7.65669116,                            # years = Σ(t×Prin_t)/Σ(Prin_t)/12
        duration=5.19877898,                            # Macaulay duration (years)
        mod_duration=4.97490811,                        # = Mac/(1+y/2) = 5.199/(1.045)
        convexity=40.61774731,                          # Cash-flow convexity
        eff_duration=5.16047787,                        # ≈ mod_duration (no OAS)
        eff_convexity=40.61983364,                      # ≈ convexity (no OAS)
    )},
)

# =============================================================================
# SF-12: Multi-Pool Average Prepayment Rate Example
# Pool 2: GNMA I 9%, orig 12/1/88, $2M original
# =============================================================================
SF12_POOL2 = BMAExample(
    id="SF-12-P2",
    description="Pool 2 for SF-12: GNMA I 9%, orig 12/1/88, $2M original, 6-month observation",
    
    # (1) ORIGINATION
    origination=OriginationParams(
        original_balance=2_000_000,                     # Given: $2M original face
        gross_coupon=9.5,                               # GNMA I: 50bp servicing -> 9.0% net
        original_term=360,                              # Given in example
        origination_date=dt.date(1988, 12, 1),          # Given in example
    ),
    
    # (2) CURRENT STATE - 6 months before observation end
    current=CurrentState(
        asof_date=dt.date(1989, 1, 1),                  # Start of 6-month observation
        loan_age=1,                                     # WALA at start: 1
        current_balance=2_000_000 * 0.99950812,         # = orig * factor_begin = 1,999,016.24
        current_factor=0.99950812,                        # Given: observed factor at start
        remaining_term=360 - 1,                         # = 359 months remaining
    ),
    
    # (3) CASH FLOW ASSUMPTIONS
    assumptions=CashFlowAssumptions(
        end_date=dt.date(1989, 7, 1),                   # End of 6-month observation
        end_period=7,                                   # Loan age at end: 7 (1 + 6)
        prepay_type=PrepayType.CPR,                     # Back-calculated as CPR
        prepay_speed=2.70539607,                        # 6-month avg CPR (%) back-calculated below
        default_type=DefaultType.MDR,                   # Not specified (no defaults)
        default_speed=0.0,                              # Not specified (no defaults)
        servicing_fee=0.50,                             # GNMA I standard
        recovery_months=12,                             # Agency standard
        loss_severity=0.20,                             # Agency standard
    ),
    
    # (4) CASH FLOWS - Pool 2 contributes to combined calculation
    # Back-calculation: actual_surv = 0.98290230/0.99950812 = 0.98339198
    #                   sched_surv = bal2/bal1 = 0.99647401/0.99950812 = 0.99696589
    #                   prepay_surv = 0.98339198/0.99696589 = 0.98638823
    #                   SMM = 1 - 0.98638823^(1/6) = 0.00228294 (decimal)
    # Key: (asof_period=7, window_length=6) = 6-month aggregate, months 2-7
    cashflows={(7, 6): PeriodCashFlows(
        # Period/Temporal Info
        asof_date=dt.date(1989, 7, 1),                  # End of 6-month window
        beg_date=dt.date(1989, 1, 1),                   # Beginning of 6-month window
        asof_period=7,                                  # End period: month 7
        beg_period=1,                                   # Beginning period: end of month 1 (start of month 2)
        loan_age=7,                                     # After 6mo observation: 1 + 6 = 7
        remaining_term=353,                             # 360 - 7 = 353 remaining
        
        # Balances & Factors (scheduled balances at 9.5% gross, 360mo term)
        bal1=0.99950812,                                # Scheduled balance at age 1 (no prepay ever)
        bal2=0.99647401,                                # Scheduled balance at age 7 (no prepay ever)
        surv_fac1=0.99950812,                           # Actual factor at start (observed)
        surv_fac2=0.98290230,                           # Actual factor at end (observed after 6 months)
        surv_fac2_sched=0.99647401,                     # = surv_fac1 * (bal2/bal1)
        perf_bal=0.98290230,                            # = surv_fac2 (no defaults)
        
        # Amortization
        sch_am=0.00303411,                              # = surv_fac1 * (1 - bal2/bal1)
        exp_am=0.00303411,                              # = sch_am (no defaults)
        act_am=0.00303411,                              # = sch_am (no defaults)
        tot_am=0.01660582,                              # = surv_fac1 - surv_fac2 = 0.99950812 - 0.98290230
        
        # Prepayment (rates in %, 6-month average)
        vol_prepay=0.01357171,                          # = tot_am - sch_am
        smm=0.0022829448,                               # = 1 - prepay_surv^(1/6) (decimal)
        cpr=2.70539607,                                 # = (1 - (1 - smm)^12) * 100
        psa=0.00000000,                                 # N/A - would need age-weighted calc
        
        # Defaults
        new_def=0.0,                                    # Not specified (no defaults)
        fcl=0.0,                                        # Not specified (no defaults)
        am_def=0.0,                                     # Not specified (no defaults)
        mdr=0.0,                                        # Not specified (no defaults)
        cdr=0.0,                                        # Not specified (no defaults)
        
        # Interest (6-month sum using scheduled amort + prepay, (1-SMM)=0.9977170552/mo)
        # Balances: $1,999,016→$1,993,463→$1,987,918→$1,982,379→$1,976,847→$1,971,322
        gross_int=94294.98,                             # = sum(monthly_bal * 9.5%/12) for 6 months
        svc_fee=4962.89,                                # = sum(monthly_bal * 0.5%/12) for 6 months
        net_int=89332.09,                               # = sum(monthly_bal * 9.0%/12) for 6 months
        exp_int=89332.09,                               # = net_int (no defaults)
        lost_int=0.00000000,                            # No defaults
        act_int=89332.09,                               # = net_int (no defaults)
        
        # Pass-through (6-month totals, $ amounts)
        pt_prin=33211.64,                               # = $1,999,016.24 - $1,965,804.60
        pt_int=89332.09,                                # = net_int
        pt_cf=122543.73,                                # = pt_prin + pt_int
        
        # Recovery/Loss
        prin_recov=0.0,                                 # Not specified (no defaults)
        prin_loss=0.0,                                  # Not specified (no defaults)
        adb=0.0,                                        # Not specified (no defaults)
        
        #TODO: need to review the risk calculations here.
        # Yield/Duration (assuming price=100 at par, CPR=2.70% constant)
        price=100.00000000,                             # Assumed: par
        yield_pct=9.00000000,                           # = net coupon at par
        mortgage_yield=9.00000000,                      # = yield for pass-through
        avg_life=9.70006184,                            # years = Σ(t×Prin_t)/Σ(Prin_t)/12
        duration=6.07364177,                            # Macaulay duration (years)
        mod_duration=5.81209739,                        # = Mac/(1+y/2) = 6.074/(1.045)
        convexity=55.99352845,                          # Cash-flow convexity
        eff_duration=6.02908108,                        # ≈ mod_duration (no OAS)
        eff_convexity=55.99757321,                      # ≈ convexity (no OAS)
    )},
)

# =============================================================================
# SF-12: Two-Pool 6-Month Average Prepayment Rate (Combined Result)
# =============================================================================
SF12 = BMAExample(
    id="SF-12",
    description="Two-pool 6-month average prepayment rate combining Pool 1 + Pool 2",
    
    # (1) ORIGINATION - combined pool characteristics
    origination=OriginationParams(
        original_balance=3_000_000,                     # = 1M + 2M = $3M combined
        gross_coupon=9.5,                               # Both pools same coupon (GNMA I)
        original_term=359.39388366,                     # WA OTerm = (P1_bal×358 + P2_bal×360) / total
        origination_date=None,                          # N/A for combined pool
    ),
    
    # (2) CURRENT STATE - start of 6-month observation
    current=CurrentState(
        asof_date=dt.date(1989, 1, 1),                  # Start of 6-month observation
        loan_age=3.42446536,                            # WALA = (P1_bal×9 + P2_bal×1) / total
        current_balance=869252.18 + 1999016.24,         # = P1 + P2 = 2,868,268.42
        current_factor=0.95608947,                        # = combined_current / combined_orig = 2,868,268.42 / 3,000,000
        remaining_term=355.96941829,                    # WAM = (P1_bal×349 + P2_bal×359) / total
    ),
    
    # (3) CASH FLOW ASSUMPTIONS
    assumptions=CashFlowAssumptions(
        end_date=dt.date(1989, 7, 1),                   # End of 6-month observation
        end_period=6,                                   # Observation period at end: 6 (combined pool)
        prepay_type=PrepayType.SMM,                     # Back-calculated as SMM
        prepay_speed=0.271142,                          # Given: back-calculated 6-month avg SMM
        default_type=DefaultType.MDR,                   # Not specified (no defaults)
        default_speed=0.0,                              # Not specified (no defaults)
        servicing_fee=0.50,                             # GNMA I standard
        recovery_months=12,                             # Agency standard
        loss_severity=0.20,                             # Agency standard
    ),
    
    # (4) CASH FLOWS - combined 6-month results
    # Key: (asof_period=6, window_length=6) = 6-month aggregate
    # Note: asof_period=6 is observation month count, not loan age (combined pool has mixed ages)
    cashflows={(6, 6): PeriodCashFlows(
        # Period/Temporal Info
        asof_date=dt.date(1989, 7, 1),                  # End of 6-month window
        beg_date=dt.date(1989, 1, 1),                   # Beginning of 6-month window
        asof_period=6,                                  # End period: observation month 6
        beg_period=0,                                   # Beginning period: observation month 0 (start)
        loan_age=9.40962514,                            # WALA at end = (P1_end×15 + P2_end×7) / total
        remaining_term=349.98796857,                    # WAM at end = (P1_end×343 + P2_end×353) / total
        
        # Balances & Factors
        bal1=2868268.42,                                # Combined starting balance = P1 + P2
        bal2=2859330.23,                                # Scheduled final balance (no prepay)
        surv_fac1=0.95608947,                           # = $2,868,268.42 / $3,000,000
        surv_fac2=0.93770914,                           # = $2,813,127.42 / $3,000,000
        surv_fac2_sched=0.95311008,                     # = $2,859,330.23 / $3,000,000
        perf_bal=0.93770914,                            # = surv_fac2 (no defaults)
        
        # Amortization ($ amounts, not factors)
        sch_am=9005.61,                                 # = P1_sch ($2,894.33) + P2_sch ($6,111.28)
        exp_am=9005.61,                                 # = sch_am (no defaults)
        act_am=9005.61,                                 # = sch_am (no defaults)
        tot_am=55141.00,                                # = P1_tot ($21,929.36) + P2_tot ($33,211.64) = pt_prin
        
        # Prepayment (back-calculated from observed balances)
        vol_prepay=46135.39,                            # = tot_am - sch_am = 55141.00 - 9005.61
        smm=0.0027114200,                               # Given: 6-month average SMM (decimal)
        cpr=3.20560000,                                 # Given: = (1-(1-SMM/100)^12)*100 = 3.2056%
        psa=212.0200000,                                # Given: back-calculated PSA multiple
        
        # Defaults
        new_def=0.0,                                    # Not specified (no defaults)
        fcl=0.0,                                        # Not specified (no defaults)
        am_def=0.0,                                     # Not specified (no defaults)
        mdr=0.0,                                        # Not specified (no defaults)
        cdr=0.0,                                        # Not specified (no defaults)
        
        # Interest (6-month sum = P1 + P2)
        gross_int=135148.84,                            # = P1 ($40,853.86) + P2 ($94,294.98)
        svc_fee=7113.09,                                # = P1 ($2,150.20) + P2 ($4,962.89)
        net_int=128035.74,                              # = P1 ($38,703.65) + P2 ($89,332.09)
        exp_int=128035.74,                              # = net_int (no defaults)
        lost_int=0.00,                                  # No defaults
        act_int=128035.74,                              # = net_int (no defaults)
        
        # Pass-through (6-month sum = P1 + P2)
        pt_prin=55141.00,                               # = P1 ($21,929.36) + P2 ($33,211.64)
        pt_int=128035.74,                               # = P1 ($38,703.65) + P2 ($89,332.09)
        pt_cf=183176.74,                                # = P1 ($60,633.01) + P2 ($122,543.73)
        
        # Recovery/Loss
        prin_recov=0.0,                                 # Not specified (no defaults)
        prin_loss=0.0,                                  # Not specified (no defaults)
        adb=0.0,                                        # Not specified (no defaults)
        
        # Yield/Duration (assuming price=100 at par, CPR=3.2056% constant forward)
        price=100.00000000,                             # Assumed: par
        yield_pct=9.00000000,                           # = net coupon at par
        mortgage_yield=9.00000000,                      # = yield for pass-through
        avg_life=14.57623125,                           # years = Σ(t×Prin_t)/Σ(Prin_t)/12
        duration=7.17441241,                            # Macaulay duration (years)
        mod_duration=6.86546643,                        # = Mac/(1+y/2) = 7.174/(1.045)
        convexity=90.03685708,                          # Cash-flow convexity
        eff_duration=6.83113909,                        # ≈ mod_duration (no OAS)
        eff_convexity=90.04586076,                      # ≈ convexity (no OAS)
    )},
)

# =============================================================================
# SF-23 to SF-30: CASH FLOW A - 1% SMM + 1% MDR (Full 360-month table)
# =============================================================================
SF23_CASHFLOW_A = BMAExample(
    id="SF-23",
    description=(
        "Cash Flow A: 1% SMM constant, 1% MDR constant, "
        "P&I advanced, 12mo recovery, 20% loss severity. "
        "Full 360-month cash flow table in bma_cashflow_a.csv."
    ),
    
    # (1) ORIGINATION
    origination=OriginationParams(
        original_balance=100_000_000,                   # Given: $100M
        gross_coupon=8.0,                               # Given: 8% WAC (gross coupon)
        original_term=360,                              # Given: 30-year
        origination_date=None,                          # Not specified
    ),
    
    # (2) CURRENT STATE - month 0 (before first payment)
    current=CurrentState(
        asof_date=None,                                 # Not specified
        loan_age=0,                                     # WALA at start: 0 (new loan)
        current_balance=100_000_000,                    # = original at month 0
        current_factor=1.0,                               # New loan
        remaining_term=360,                             # Full term
    ),
    
    # (3) CASH FLOW ASSUMPTIONS
    assumptions=CashFlowAssumptions(
        end_date=None,                                  # 360-month projection
        end_period=360,                                 # Loan age at end: 360 (full term)
        prepay_type=PrepayType.SMM,                     # Given: constant SMM
        prepay_speed=1.0,                               # Given: 1% SMM
        default_type=DefaultType.MDR,                   # Given: constant MDR
        default_speed=1.0,                              # Given: 1% MDR
        servicing_fee=0.50,                             # Agency standard (inferred: 8% gross - 7.5% net)
        servicing_advance=True,                         # Given: "P&I advanced" in example description
        recovery_months=12,                             # Given: 12 months
        loss_severity=0.20,                             # Given: 20%
    ),
    
    # (4) CASH FLOWS - Full table in CSV file
    cashflows=None,                                     # Multi-month example, see cashflows_file
    cashflows_file="fixtures/bma_cashflow_a.csv",       # 360-month cash flow table
)

# =============================================================================
# SF-31 to SF-38: CASH FLOW B - 150% PSA + 100% SDA (Full 360-month table)
# =============================================================================
SF31_CASHFLOW_B = BMAExample(
    id="SF-31",
    description=(
        "Cash Flow B: 150% PSA, 100% SDA, "
        "P&I advanced, 12mo recovery, 20% loss severity. "
        "Full 360-month cash flow table in bma_cashflow_b.csv."
    ),
    
    # (1) ORIGINATION
    origination=OriginationParams(
        original_balance=100_000_000,                   # Given: $100M
        gross_coupon=8.0,                               # Given: 8% WAC (gross coupon)
        original_term=360,                              # Given: 30-year
        origination_date=None,                          # Not specified
    ),
    
    # (2) CURRENT STATE - month 0 (before first payment)
    current=CurrentState(
        asof_date=None,                                 # Not specified
        loan_age=0,                                     # WALA at start: 0 (new loan)
        current_balance=100_000_000,                    # = original at month 0
        current_factor=1.0,                               # New loan
        remaining_term=360,                             # Full term
    ),
    
    # (3) CASH FLOW ASSUMPTIONS
    assumptions=CashFlowAssumptions(
        end_date=None,                                  # 360-month projection
        end_period=360,                                 # Loan age at end: 360 (full term)
        prepay_type=PrepayType.PSA,                     # Given: PSA model
        prepay_speed=150.0,                             # Given: 150% PSA
        default_type=DefaultType.SDA,                   # Given: SDA model
        default_speed=100.0,                            # Given: 100% SDA
        servicing_fee=0.50,                             # Agency standard (inferred: 8% gross - 7.5% net)
        servicing_advance=True,                         # Given: "P&I advanced" in example description
        recovery_months=12,                             # Given: 12 months
        loss_severity=0.20,                             # Given: 20%
    ),
    
    # (4) CASH FLOWS - Full table in CSV file
    cashflows=None,                                     # Multi-month example, see cashflows_file
    cashflows_file="fixtures/bma_cashflow_b.csv",       # 360-month cash flow table
)

# =============================================================================
# SF-42: FANNIE MAE POOL - WAM/WALA ADJUSTMENT EXAMPLE
# =============================================================================
SF42_FNMA = BMAExample(
    id="SF-42-FNMA",
    description=(
        "Fannie Mae pool issued July 1993. WAM/WALA not directly reported, "
        "must be inferred from pool type and elapsed time. "
        "Original WAM was 350mo, assumed orig term 360mo, 6mo elapsed → age=16."
    ),
    
    origination=OriginationParams(
        original_balance=1.0,                           # Normalized
        gross_coupon=8.0,                               # Not specified, assumed typical
        original_term=360,                              # Assumed standard 30-year
        origination_date=dt.date(1993, 7, 1),           # Given: issued July 1993
    ),
    
    current=CurrentState(
        asof_date=dt.date(1993, 9, 1),                  # September 1993
        loan_age=15,                                    # WALA at start: 15 (before month 16)
        current_balance=0.96891577,                     # = factor_begin
        current_factor=0.96891577,                        # Given: September 1993 factor
        remaining_term=341,                             # Given: WAM = 341 months
    ),
    
    assumptions=CashFlowAssumptions(
        end_date=dt.date(1993, 10, 1),                  # October 1993
        end_period=16,                                  # Loan age at end: 16
        prepay_type=PrepayType.PSA,
        prepay_speed=22.0,                              # Given: back-calculated PSA
        default_type=DefaultType.MDR,
        default_speed=0.0,
        servicing_fee=0.50,
        recovery_months=12,
        loss_severity=0.20,
    ),
    
    # (4) CASH FLOWS - back-calculated PSA from observed factors
    # Key: (asof_period=16, window_length=1) = single period, month 16
    cashflows={(16, 1): PeriodCashFlows(
        # Period/Temporal Info
        asof_date=dt.date(1993, 10, 1),                 # End of window: October 1993
        beg_date=dt.date(1993, 9, 1),                   # Beginning of window: September 1993
        asof_period=16,                                 # End period: month 16
        beg_period=15,                                  # Beginning period: end of month 15
        loan_age=16,                                    # Given: loan age for PSA calc
        remaining_term=344,                             # 360 - 16 = 344 remaining
        
        # Balances & Factors
        bal1=0.0,                                       # N/A - scheduled balance not focus of SF-42
        bal2=0.0,                                       # N/A - scheduled balance not focus of SF-42
        surv_fac1=0.96891577,                           # Actual factor at start (September 1993)
        surv_fac2=0.96783524,                           # Actual factor at end (October 1993)
        surv_fac2_sched=0.0,                             # N/A - not computed in example
        perf_bal=0.0,                                   # N/A - not computed in example
        
        # Amortization
        sch_am=0.0,                                     # N/A - not computed in example
        exp_am=0.0,                                     # N/A - not computed in example
        act_am=0.0,                                     # N/A - not computed in example
        tot_am=0.96891577 - 0.96783524,                 # = factor change = 0.00108053
        
        # Prepayment (back-calculated from observed factors)
        vol_prepay=0.96891577 - 0.96783524,             # = factor_begin - factor_end = 0.00108053
        smm=0.00000000,                                 # N/A - computed via PSA
        cpr=0.00000000,                                 # N/A - computed via PSA
        psa=22.0000000,                                 # Given: back-calculated PSA
        
        # Defaults
        new_def=0.0,                                    # Not specified (no defaults)
        fcl=0.0,                                        # Not specified (no defaults)
        am_def=0.0,                                     # Not specified (no defaults)
        mdr=0.0,                                        # Not specified (no defaults)
        cdr=0.0,                                        # Not specified (no defaults)
        
        # Interest
        gross_int=0.0,                                  # N/A - not focus of SF-42
        svc_fee=0.0,                                    # N/A - not focus of SF-42
        net_int=0.0,                                    # N/A - not focus of SF-42
        exp_int=0.0,                                    # N/A - not focus of SF-42
        lost_int=0.0,                                   # N/A - not focus of SF-42
        act_int=0.0,                                    # N/A - not focus of SF-42
        
        # Pass-through
        pt_prin=0.0,                                    # N/A - not focus of SF-42
        pt_int=0.0,                                     # N/A - not focus of SF-42
        pt_cf=0.0,                                      # N/A - not focus of SF-42
        
        # Recovery/Loss
        prin_recov=0.0,                                 # Not specified (no defaults)
        prin_loss=0.0,                                  # Not specified (no defaults)
        adb=0.0,                                        # Not specified (no defaults)
        
        # Yield/Duration
        price=0.0,                                      # N/A - not focus of SF-42
        yield_pct=0.0,                                  # N/A - not focus of SF-42
        mortgage_yield=0.0,                             # N/A - not focus of SF-42
        avg_life=0.0,                                   # N/A - not focus of SF-42
        duration=0.0,                                   # N/A - not focus of SF-42
        mod_duration=0.0,                               # N/A - not focus of SF-42
        convexity=0.0,                                  # N/A - not focus of SF-42
        eff_duration=0.0,                               # N/A - not focus of SF-42
        eff_convexity=0.0,                              # N/A - not focus of SF-42
    )},
)

# =============================================================================
# SF-42: GINNIE MAE POOL - WAM/WALA ADJUSTMENT EXAMPLE
# =============================================================================
SF42_GNMA = BMAExample(
    id="SF-42-GNMA",
    description=(
        "Ginnie Mae pool issued May 1993. WAM 359mo, WALA 1mo reported Oct 1993. "
        "Adjusted for 4-month reporting lag → effective age=5."
    ),
    
    origination=OriginationParams(
        original_balance=1.0,
        gross_coupon=7.5,                               # Given in example
        original_term=360,                              # Standard 30-year
        origination_date=dt.date(1993, 5, 1),           # Given: issued May 1993
    ),
    
    current=CurrentState(
        asof_date=dt.date(1993, 9, 1),                  # September 1993 factor date
        loan_age=4,                                     # WALA at start: 4 (before month 5)
        current_balance=0.970000,                       # = factor_begin
        current_factor=0.970000,                          # Given: September 1993 factor
        remaining_term=355,                             # = 359 - 4 (adjusted for reporting lag)
    ),
    
    assumptions=CashFlowAssumptions(
        end_date=dt.date(1993, 10, 1),                  # October 1993
        end_period=5,                                   # Loan age at end: 5 (adjusted for reporting lag)
        prepay_type=PrepayType.PSA,
        prepay_speed=1087.0,                            # Given: back-calculated PSA (very high!)
        default_type=DefaultType.MDR,
        default_speed=0.0,
        servicing_fee=0.50,
        recovery_months=12,
        loss_severity=0.20,
    ),
    
    # (4) CASH FLOWS - back-calculated PSA from observed factors
    # Key: (asof_period=5, window_length=1) = single period, month 5
    cashflows={(5, 1): PeriodCashFlows(
        # Period/Temporal Info
        asof_date=dt.date(1993, 10, 1),                 # End of window: October 1993
        beg_date=dt.date(1993, 9, 1),                   # Beginning of window: September 1993
        asof_period=5,                                  # End period: month 5 (adjusted for reporting lag)
        beg_period=4,                                   # Beginning period: end of month 4
        loan_age=5,                                     # Given: adjusted loan age (WALA + 4mo lag)
        remaining_term=355,                             # 360 - 5 = 355 remaining
        
        # Balances & Factors
        bal1=0.0,                                       # N/A - scheduled balance not focus of SF-42
        bal2=0.0,                                       # N/A - scheduled balance not focus of SF-42
        surv_fac1=0.970000,                             # Actual factor at start (September 1993)
        surv_fac2=0.960000,                             # Actual factor at end (October 1993)
        surv_fac2_sched=0.0,                             # N/A - not computed in example
        perf_bal=0.0,                                   # N/A - not computed in example
        
        # Amortization
        sch_am=0.0,                                     # N/A - not computed in example
        exp_am=0.0,                                     # N/A - not computed in example
        act_am=0.0,                                     # N/A - not computed in example
        tot_am=0.970000 - 0.960000,                     # = factor change = 0.01
        
        # Prepayment (back-calculated from observed factors)
        vol_prepay=0.970000 - 0.960000,                 # = factor_begin - factor_end = 0.01
        smm=0.00000000,                                 # N/A - computed via PSA
        cpr=0.00000000,                                 # N/A - computed via PSA
        psa=1087.000000,                                # Given: back-calculated PSA (very high!)
        
        # Defaults
        new_def=0.0,                                    # Not specified (no defaults)
        fcl=0.0,                                        # Not specified (no defaults)
        am_def=0.0,                                     # Not specified (no defaults)
        mdr=0.0,                                        # Not specified (no defaults)
        cdr=0.0,                                        # Not specified (no defaults)
        
        # Interest
        gross_int=0.0,                                  # N/A - not focus of SF-42
        svc_fee=0.0,                                    # N/A - not focus of SF-42
        net_int=0.0,                                    # N/A - not focus of SF-42
        exp_int=0.0,                                    # N/A - not focus of SF-42
        lost_int=0.0,                                   # N/A - not focus of SF-42
        act_int=0.0,                                    # N/A - not focus of SF-42
        
        # Pass-through
        pt_prin=0.0,                                    # N/A - not focus of SF-42
        pt_int=0.0,                                     # N/A - not focus of SF-42
        pt_cf=0.0,                                      # N/A - not focus of SF-42
        
        # Recovery/Loss
        prin_recov=0.0,                                 # Not specified (no defaults)
        prin_loss=0.0,                                  # Not specified (no defaults)
        adb=0.0,                                        # Not specified (no defaults)
        
        # Yield/Duration
        price=0.0,                                      # N/A - not focus of SF-42
        yield_pct=0.0,                                  # N/A - not focus of SF-42
        mortgage_yield=0.0,                             # N/A - not focus of SF-42
        avg_life=0.0,                                   # N/A - not focus of SF-42
        duration=0.0,                                   # N/A - not focus of SF-42
        mod_duration=0.0,                               # N/A - not focus of SF-42
        convexity=0.0,                                  # N/A - not focus of SF-42
        eff_duration=0.0,                               # N/A - not focus of SF-42
        eff_convexity=0.0,                              # N/A - not focus of SF-42
    )},
)


# =============================================================================
# SF-49/50: YIELD CALCULATION EXAMPLE - SETTLED ON ISSUE DATE
# =============================================================================
SF49_YIELD = BMAExample(
    id="SF-49",
    description=(
        "Ginnie Mae I 9.0% pass-through, 360mo term, 150% PSA, 14-day actual delay, "
        "settled on issue date at par. Full yield/duration example."
    ),
    
    origination=OriginationParams(
        original_balance=100.0,                         # Normalized to 100 (percent of par)
        gross_coupon=9.5,                               # GNMA I: 50bp servicing -> 9.0% net
        original_term=360,                              # Given: 30-year
        origination_date=None,                          # Settlement on issue date
    ),
    
    current=CurrentState(
        asof_date=None,                                 # Issue date
        loan_age=0,                                     # WALA at start: 0 (new issue)
        current_balance=100.0,                          # At par
        current_factor=1.0,                               # New issue
        remaining_term=360,                             # Full term
    ),
    
    assumptions=CashFlowAssumptions(
        end_date=None,                                  # Multi-period projection
        end_period=360,                                 # Full term projection
        prepay_type=PrepayType.PSA,                     # Given: PSA model
        prepay_speed=150.0,                             # Given: 150% PSA
        default_type=DefaultType.MDR,
        default_speed=0.0,                              # No defaults assumed
        servicing_fee=0.50,                             # GNMA I standard
        recovery_months=12,
        loss_severity=0.20,
    ),
    
    # (4) CASH FLOWS - at issue (month 0), plus yield/duration from BMA SF-50
    # Note: This is a pricing/yield example at settlement - month 0 values are pre-first-payment
    # Key: (asof_period=0, window_length=1) = snapshot at issue
    cashflows={(0, 1): PeriodCashFlows(
        # Period/Temporal Info
        asof_date=None,                                 # Issue date (not specified)
        beg_date=None,                                  # N/A for issue snapshot
        asof_period=0,                                  # At issue, before first payment
        beg_period=None,                                # N/A for issue snapshot (no prior period)
        loan_age=0,                                     # New loan
        remaining_term=360,                             # Full term at issue
        
        # Balances & Factors (at issue, period 0 = no payments yet)
        bal1=100.0,                                     # Scheduled balance at issue (no prepay ever)
        bal2=100.0,                                     # = bal1 (no payment yet at month 0)
        surv_fac1=1.0,                                  # Actual factor at issue (= bal1/100)
        surv_fac2=1.0,                                  # = surv_fac1 (no payment yet)
        surv_fac2_sched=1.0,                             # = surv_fac1 (no payment yet)
        perf_bal=100.0,                                 # = bal1 (at issue)
        
        # Amortization (none at month 0 - before first payment)
        sch_am=0.0,                                     # No payment yet at month 0
        exp_am=0.0,                                     # No payment yet at month 0
        act_am=0.0,                                     # No payment yet at month 0
        tot_am=0.0,                                     # No payment yet at month 0
        
        # Prepayment (none at month 0)
        vol_prepay=0.0,                                 # No prepay at month 0
        smm=0.00000000,                                 # No prepay at month 0
        cpr=0.00000000,                                 # No prepay at month 0
        psa=150.0000000,                                # Given: assumption for projection
        
        # Defaults (none at month 0)
        new_def=0.0,                                    # No defaults at month 0
        fcl=0.0,                                        # No foreclosures at month 0
        am_def=0.0,                                     # No amortized defaults at month 0
        mdr=0.0,                                        # No defaults at month 0
        cdr=0.0,                                        # No defaults at month 0
        
        # Interest (none collected at month 0 - before first payment)
        gross_int=0.0,                                  # No interest collected at month 0
        svc_fee=0.0,                                    # No servicing fee at month 0
        net_int=0.0,                                    # No net interest at month 0
        exp_int=0.0,                                    # No expected interest at month 0
        lost_int=0.0,                                   # No lost interest at month 0
        act_int=0.0,                                    # No actual interest at month 0
        
        # Pass-through (none at month 0)
        pt_prin=0.0,                                    # No principal pass-through at month 0
        pt_int=0.0,                                     # No interest pass-through at month 0
        pt_cf=0.0,                                      # No cash flow at month 0
        
        # Recovery/Loss (none at month 0)
        prin_recov=0.0,                                 # No recovery at month 0
        prin_loss=0.0,                                  # No loss at month 0
        adb=0.0,                                        # No defaulted balance at month 0
        
        # Yield/Duration - GIVEN VALUES from BMA SF-50 (whole-loan projection)
        price=100.0000,                                 # Given: at par
        yield_pct=9.10675,                              # Given: bond-equivalent yield
        mortgage_yield=8.93863,                         # Given: mortgage yield (monthly compounding)
        avg_life=9.77844,                               # Given: in years, Σ(t*CF)/Σ(CF)
        duration=5.73147,                               # Given: Macaulay duration in years
        mod_duration=5.48186,                           # Given: = duration / (1 + y/2) = 5.73147/(1+0.0910675/2)
        convexity=54.4326,                              # Given: cash-flow convexity in years²
        eff_duration=5.44,                              # Given: from ±10bp repricing
        eff_convexity=-60.0,                            # Given: negative due to prepay optionality
    )},
)

# =============================================================================
# SF-51: YIELD CALCULATION EXAMPLE - SETTLED 7 DAYS AFTER ISSUE
# =============================================================================
SF51_YIELD = BMAExample(
    id="SF-51",
    description=(
        "Same Ginnie Mae I 9.0% as SF-49, but settled 7 days after issue date. "
        "Price includes 7 days accrued interest."
    ),
    
    origination=OriginationParams(
        original_balance=100.0,
        gross_coupon=9.5,
        original_term=360,
        origination_date=None,
    ),
    
    current=CurrentState(
        asof_date=None,                                 # 7 days after issue
        loan_age=0,                                     # WALA at start: 0 (new issue)
        current_balance=100.0,
        current_factor=1.0,
        remaining_term=360,
    ),
    
    assumptions=CashFlowAssumptions(
        end_date=None,
        end_period=360,                                 # Full term projection
        prepay_type=PrepayType.PSA,
        prepay_speed=150.0,
        default_type=DefaultType.MDR,
        default_speed=0.0,
        servicing_fee=0.50,
        recovery_months=12,
        loss_severity=0.20,
    ),
    
    # (4) CASH FLOWS - at issue + 7 days accrued, yield/duration from BMA SF-51
    # Key: (asof_period=0, window_length=1) = snapshot at issue + 7 days
    cashflows={(0, 1): PeriodCashFlows(
        # Period/Temporal Info
        asof_date=None,                                 # 7 days after issue (not specified)
        beg_date=None,                                  # N/A for issue snapshot
        asof_period=0,                                  # Still period 0 (before first payment)
        beg_period=None,                                # N/A for issue snapshot (no prior period)
        loan_age=0,                                     # New loan (7 days old)
        remaining_term=360,                             # Full term
        
        # Balances & Factors (at issue + 7 days, period 0 = no payments yet)
        bal1=100.0,                                     # Scheduled balance at issue (no prepay ever)
        bal2=100.0,                                     # = bal1 (no payment yet)
        surv_fac1=1.0,                                  # Actual factor at issue (= bal1/100)
        surv_fac2=1.0,                                  # = surv_fac1 (no payment yet)
        surv_fac2_sched=1.0,                             # = surv_fac1 (no payment yet)
        perf_bal=100.0,                                 # = bal1 (at issue)
        
        # Amortization (none - before first payment)
        sch_am=0.0,                                     # No payment yet
        exp_am=0.0,                                     # No payment yet
        act_am=0.0,                                     # No payment yet
        tot_am=0.0,                                     # No payment yet
        
        # Prepayment (none - before first payment)
        vol_prepay=0.0,                                 # No prepay yet
        smm=0.00000000,                                 # No prepay yet
        cpr=0.00000000,                                 # No prepay yet
        psa=150.0000000,                                # Given: assumption for projection
        
        # Defaults (none - before first payment)
        new_def=0.0,                                    # No defaults yet
        fcl=0.0,                                        # No foreclosures yet
        am_def=0.0,                                     # No amortized defaults yet
        mdr=0.0,                                        # No defaults yet
        cdr=0.0,                                        # No defaults yet
        
        # Interest (7 days accrued, not yet collected)
        gross_int=100.0 * 9.5 / 100 / 360 * 7,          # = 7 days gross accrued = 0.18472
        svc_fee=100.0 * 0.5 / 100 / 360 * 7,            # = 7 days servicing = 0.00972
        net_int=100.0 * 9.0 / 100 / 360 * 7,            # = 7 days net accrued = 0.17500
        exp_int=100.0 * 9.0 / 100 / 360 * 7,            # = net_int
        lost_int=0.0,                                   # No lost interest
        act_int=100.0 * 9.0 / 100 / 360 * 7,            # = net_int
        
        # Pass-through (none - before first payment)
        pt_prin=0.0,                                    # No principal yet
        pt_int=0.0,                                     # No interest payment yet
        pt_cf=0.0,                                      # No cash flow yet
        
        # Recovery/Loss (none)
        prin_recov=0.0,                                 # No recovery
        prin_loss=0.0,                                  # No loss
        adb=0.0,                                        # No defaulted balance
        
        # Yield/Duration - GIVEN VALUES from BMA SF-51
        price=100.1750,                                 # Given: par + 7 days accrued = 100 + 7/30*9.0/12
        yield_pct=9.10644,                              # Given: slightly lower than SF-49
        mortgage_yield=8.93863,                         # Same as SF-49 (same underlying cash flows)
        avg_life=9.77844,                               # Same as SF-49 (same cash flows)
        duration=5.73147,                               # Same as SF-49 (same cash flows)
        mod_duration=5.48186,                           # Same as SF-49
        convexity=54.4326,                              # Same as SF-49
        eff_duration=5.44,                              # Same as SF-49
        eff_convexity=-60.0,                            # Same as SF-49
    )},
)

# =============================================================================
# SF-56: AVERAGE LIFE - ACCRUAL INSTRUMENT EXAMPLE (GPM/ARM vs Z-bond)
# =============================================================================
SF56_AVGLIFE = BMAExample(
    id="SF-56",
    description=(
        "Hypothetical accrual instrument illustrating GPM/ARM vs Z-bond "
        "average life conventions. 10% periodic interest, 3 periods, $100 initial."
    ),
    
    origination=OriginationParams(
        original_balance=100.0,                         # Given: $100 initial
        gross_coupon=10.0,                              # Given: 10% periodic interest
        original_term=3,                                # Given: 3 periods
        origination_date=None,
    ),
    
    current=CurrentState(
        asof_date=None,
        loan_age=0,                                     # WALA at start: 0 (new issue)
        current_balance=100.0,
        current_factor=1.0,
        remaining_term=3,
    ),
    
    assumptions=CashFlowAssumptions(
        end_date=None,
        end_period=3,                                   # 3 periods total
        prepay_type=PrepayType.SMM,
        prepay_speed=0.0,                               # No prepay in this example
        default_type=DefaultType.MDR,
        default_speed=0.0,
        servicing_fee=0.0,                              # Not specified
        recovery_months=12,
        loss_severity=0.20,
    ),
    
    # (4) CASH FLOWS - SF-56 accrual instrument example
    # Period 0: -100 (investment)
    # Period 1: 0 CF, 10 interest, -10 principal (balance grows to 110)
    # Period 2: 11 CF, 11 interest, 0 principal (balance stays 110)
    # Period 3: 121 CF, 11 interest, 110 principal (balance -> 0)
    # Key: (asof_period=3, window_length=1) = final period (month 3)
    cashflows={(3, 1): PeriodCashFlows(
        # Period/Temporal Info
        asof_date=None,                                 # Not specified
        beg_date=None,                                  # Not specified
        asof_period=3,                                  # End period: final period
        beg_period=2,                                   # Beginning period: end of period 2
        loan_age=3,                                     # After 3 periods
        remaining_term=0,                               # Fully amortized
        
        # Balances & Factors (at end of period 3 - accrual instrument)
        bal1=110.0,                                     # Scheduled balance at period 3 start (accrued)
        bal2=0.0,                                       # Scheduled balance at period 3 end (paid off)
        surv_fac1=1.10,                                 # = bal1 / orig = 110/100 (no prepay in example)
        surv_fac2=0.0,                                  # = bal2 / orig = 0/100 (paid off)
        surv_fac2_sched=0.0,                             # N/A for accrual instrument
        perf_bal=0.0,                                   # = bal2
        
        # Amortization (accrual instrument has negative amort in early periods)
        sch_am=-10.0,                                   # Period 1: negative (balance grows by 10)
        exp_am=0.0,                                     # Period 2: 0 (balance unchanged)
        act_am=110.0,                                   # Period 3: 110 (full payoff)
        tot_am=100.0,                                   # Total: -10 + 0 + 110 = 100 (original balance)
        
        # Prepayment
        vol_prepay=0.0,                                 # No prepayment in example
        smm=0.00000000,                                 # No prepayment
        cpr=0.00000000,                                 # No prepayment
        psa=0.00000000,                                 # No prepayment
        
        # Defaults
        new_def=0.0,                                    # No defaults in example
        fcl=0.0,                                        # No defaults
        am_def=0.0,                                     # No defaults
        mdr=0.0,                                        # No defaults
        cdr=0.0,                                        # No defaults
        
        # Interest (period 3 values)
        gross_int=11.0,                                 # = 110 * 10% = 11 (period 3)
        svc_fee=0.0,                                    # Not specified
        net_int=11.0,                                   # = gross_int (no servicing)
        exp_int=11.0,                                   # = net_int
        lost_int=0.0,                                   # No defaults
        act_int=11.0,                                   # = exp_int
        
        # Pass-through (period 3: 121 total CF = 110 prin + 11 int)
        pt_prin=110.0,                                  # Principal payoff at period 3
        pt_int=11.0,                                    # Interest at period 3
        pt_cf=121.0,                                    # = pt_prin + pt_int
        
        # Recovery/Loss
        prin_recov=0.0,                                 # No defaults
        prin_loss=0.0,                                  # No defaults
        adb=0.0,                                        # No defaults
        
        # Yield/Duration
        price=100.0,                                    # At par (initial investment)
        yield_pct=10.0,                                 # = coupon rate (at par)
        mortgage_yield=10.0,                            # = coupon rate
        # Average life calculation from SF-56:
        # GPM/ARM: (1*(-10) + 2*(0) + 3*(110)) / (-10 + 0 + 110) = 320/100 = 3.20 periods
        # Z-bond:  (1*(0) + 2*(0) + 3*(110)) / (0 + 0 + 110) = 330/110 = 3.00 periods
        avg_life=3.20,                                  # Given: GPM/ARM convention (periods)
        duration=2.73,                                  # ≈ Σ(t*CF)/Σ(CF)/price = (11+2*11+3*121)/(11+11+121)/1
        mod_duration=2.48,                              # = duration / (1 + y) = 2.73 / 1.10
        convexity=8.26,                                 # = Σ(t²*CF)/Σ(CF)/price
        eff_duration=0.0,                               # N/A for fixed accrual
        eff_convexity=0.0,                              # N/A for fixed accrual
    )},
)


BMA_EXAMPLES = {
    # Basic cash flows (SF-4)
    "SF4": SF4,
    
    # Prepayment rates (SF-7)
    "SF7": SF7,
    
    # Multi-pool averages (SF-12)
    "SF12_POOL1": SF12_POOL1,
    "SF12_POOL2": SF12_POOL2,
    "SF12": SF12,
    
    # Cash flow with defaults - Constant rates (SF-23 to SF-30)
    "SF23": SF23_CASHFLOW_A,
    
    # Cash flow with defaults - PSA/SDA (SF-31 to SF-38)
    "SF31": SF31_CASHFLOW_B,
    
    # Loan age calculation (SF-42)
    "SF42_FNMA": SF42_FNMA,
    "SF42_GNMA": SF42_GNMA,
    
    # Yield/Duration (SF-49 to SF-51)
    "SF49": SF49_YIELD,
    "SF51": SF51_YIELD,
    
    # Average life conventions (SF-56)
    "SF56": SF56_AVGLIFE,
}


# =============================================================================
# QUICK TEST
# =============================================================================
if __name__ == "__main__":
    print("BMA Examples (New Structure)")
    print("=" * 70)
    
    for name, ex in BMA_EXAMPLES.items():
        print(f"\n{name}: {ex.description[:60]}...")
        print(f"  Origination: {ex.origination.original_balance:,.0f} @ {ex.origination.gross_coupon}%, {ex.origination.original_term}mo")
        print(f"  Current: factor={ex.current.current_factor:.6f}, remaining={ex.current.remaining_term}mo")
        print(f"  Loan age: {ex.loan_age} months ({'seasoned' if ex.is_seasoned else 'new'})")
        print(f"  Assumptions: {ex.assumptions.prepay_type.value}@{ex.assumptions.prepay_speed}, {ex.assumptions.default_type.value}@{ex.assumptions.default_speed}")
        
        # Check if cash flows are in a file or inline
        if ex.cashflows_file:
            print(f"  Cash Flows: see {ex.cashflows_file}")
        elif ex.cashflows:
            for period, cf in ex.cashflows.items():
                print(f"  Cash Flows (period {period}, age={cf.loan_age}, rem={cf.remaining_term}):")
                if cf.surv_fac2 != 0:
                    print(f"    surv_fac2={cf.surv_fac2:.6f}")
                if cf.smm != 0 or cf.cpr != 0 or cf.psa != 0:
                    print(f"    smm={cf.smm*100:.4f}%, cpr={cf.cpr:.4f}%, psa={cf.psa:.2f}%")
                if cf.price != 0:
                    print(f"    price={cf.price:.4f}, yield={cf.yield_pct:.5f}%")
                if cf.avg_life != 0:
                    print(f"    avg_life={cf.avg_life:.5f}, duration={cf.duration:.5f}")
        else:
            print(f"  Cash Flows: (not specified)")
