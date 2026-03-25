
# Requires Python 3.12+
# Uses native type hints: list[x], tuple[x, y], X | None (PEP 585, PEP 604)
from __future__ import annotations

import warnings
import numpy as np



# =============================================================================
# BMA Section B: Prepayments (SF-4 to SF-15)
# =============================================================================

def sch_balance_factor_fixed_rate(
        coupon: float,
        original_term: int,
        remaining_term: int
) -> float:
    """
    Calculate the scheduled balance (BAL) as a fraction of par for a fixed-rate,
    fully amortizing loan with level payments.

    BMA Reference: Section B.1, SF-4

    For a level-payment fixed-rate mortgage pool with gross weighted-average coupon C%
    and original term M₀ months, the scheduled balance BAL(Mₙ) represents the outstanding
    principal as a fraction of par when Mₙ months remain (i.e., at age n = M₀ - Mₙ).

    Formula:
        BAL(Mₙ) = [1 - (1 + r)^-Mₙ] / [1 - (1 + r)^-M₀]

    Where:
        r   = Monthly coupon rate (C / 1200)
        M₀  = Original term (months)
        Mₙ  = Remaining term at age n (months), where n = M₀ - Mₙ

    Author's Note:
    --------------
    This balance factor is the ratio of the actuarial present value annuity factors:

    BAL(Mₙ) = PVAF(Mₙ) / PVAF(M₀)

    Where:
        PVAF(M) = [1 - (1 + r)^-M] / r

    So:
        PVAF(Mₙ) / PVAF(M₀) = [(1 - (1 + r)^-Mₙ) / r] / [(1 - (1 + r)^-M₀) / r]
                            = [1 - (1 + r)^-Mₙ] / [1 - (1 + r)^-M₀]

    Connection to Gross Mortgage Payment:
    -------------------------------------
    Per BMA SF-4, the gross mortgage payment for period n can be computed as:

        PAYMENTₙ = PRINCIPAL + INTEREST
                 = [BAL(Mₙ₋₁) - BAL(Mₙ)] + BAL(Mₙ₋₁) × r

    Where BAL(Mₙ₋₁) is the balance at period start and BAL(Mₙ) is at period end.
    See sch_payment_factor() for the algebraic proof that this
    decomposition yields the standard annuity formula.

    IMPLEMENTATION:
    ---------------
    Args:
        coupon: Annual coupon rate as percentage (e.g., 8.0 for 8.0%)
        original_term: Original term in months (M₀)
        remaining_term: Remaining term in months (Mₙ)

    Returns:
        Scheduled balance factor (fraction of par)
    
    Raises: 
        ValueError: If original_term is not positive
        ValueError: If remaining_term is negative
        ValueError: If remaining_term is greater than original_term
        ValueError: If coupon is negative
        Warning: If remaining_term is zero
        Warning: If coupon is zero

    """
    # Check input validity
    if original_term <= 0:
        raise ValueError(f"original_term must be positive, got {original_term}")
    if remaining_term < 0:
        raise ValueError(f"remaining_term must be non-negative, got {remaining_term}")
    if remaining_term > original_term:
        raise ValueError(f"remaining_term cannot exceed original_term, got {remaining_term} > {original_term}")
    if coupon < 0:
        raise ValueError(f"coupon must be non-negative, got {coupon}")
    # Handle edge cases and balance factor computation
    if remaining_term == 0:
        warnings.warn("remaining_term is zero, returning maturity balance")
        return 0.0
    elif coupon == 0.0:
        warnings.warn("coupon is zero, returning straight-line amortization")
        return remaining_term / original_term
    else:
        return (1 - (1 + coupon/1200) ** (-remaining_term)) / (1 - (1 + coupon/1200) ** (-original_term))


def sch_payment_factor_fixed_rate(
        coupon: float,
        original_term: int,
        remaining_term: int
) -> float:
    """
    Calculate the gross monthly payment for a loan age
    n = (M₀ - Mₙ) = (original_term - remaining_term) (i.e. the period beginning at
    age n-1 and ending at age n) using BMA's balance decomposition method expressed
    as a fraction of the beginning balance for the period n
    (i.e. Balance at age n-1 with Mₙ₋₁ months remaining).

    BMA Reference: Section B.1, SF-4

    NOTATION CONVENTION:
    --------------------
    For period n (from age n-1 to age n):
        - Start: BAL(Mₙ₋₁) with Mₙ₋₁ months remaining (at age n-1)
        - End:   BAL(Mₙ) with Mₙ = Mₙ₋₁ - 1 months remaining (at age n)

    This function implements the BMA definition DIRECTLY as stated in SF-4:

        PAYMENTₙ = PRINCIPAL + INTEREST
                 = [BAL(Mₙ₋₁) - BAL(Mₙ)] + BAL(Mₙ₋₁) × r

    Where:
        BAL(Mₙ₋₁) = Scheduled balance at START of period (Mₙ₋₁ months remaining)
        BAL(Mₙ)   = Scheduled balance at END of period (Mₙ months remaining)
        r         = Monthly coupon rate (C / 1200)

    Key Insight:
    ------------
    This formulation shows that the gross payment depends ONLY on:
        - M₀: Original term (embedded in BAL calculations)
        - C:  Coupon rate (used for both BAL and interest)

    For a fixed-rate loan, the payment is constant across all periods because:
        - As n increases, BAL(Mₙ₋₁) decreases (less principal remaining)
        - But BAL(Mₙ₋₁) - BAL(Mₙ) increases (principal portion grows)
        - And BAL(Mₙ₋₁) × r decreases (interest portion shrinks)
        - These changes exactly offset, yielding a constant payment

    CONNECTION TO ANNUITY FACTOR:
    -----------------------------
    Starting from the expanded payment formula:

        PAYMENTₙ = [BAL(Mₙ₋₁) - BAL(Mₙ)] + BAL(Mₙ₋₁) × r

    Factor out BAL(Mₙ₋₁):

        PAYMENTₙ = BAL(Mₙ₋₁) × [1 - BAL(Mₙ)/BAL(Mₙ₋₁) + r]

    The ratio BAL(Mₙ)/BAL(Mₙ₋₁), using the SF-4 balance formula, is:

        BAL(Mₙ)/BAL(Mₙ₋₁) = [1 - (1+r)^-Mₙ] / [1 - (1+r)^-Mₙ₋₁]

    (The common [1 - (1+r)^-M₀] denominators cancel.)

    Substituting and simplifying (see sch_payment_factor() Step 5 for details):

        1 - BAL(Mₙ)/BAL(Mₙ₋₁) + r = r / [1 - (1+r)^-Mₙ₋₁] = AF(Mₙ₋₁)

    Therefore:

        PAYMENTₙ = BAL(Mₙ₋₁) × r / [1 - (1+r)^-Mₙ₋₁]

    This is the level payment that fully amortizes the present value of an
    annuity with Mₙ₋₁ periods remaining. The Annuity Factor AF(Mₙ₋₁) = AF(n) is
    the payment per dollar of balance that exactly pays off the loan over
    Mₙ₋₁ equal installments at rate r. See sch_payment_factor() Step 6
    for the proof that PV of Mₙ₋₁ payments of AF(Mₙ₋₁) equals 1.

    This function serves as a REFERENCE IMPLEMENTATION that directly follows
    the BMA text. See sch_payment_factor() for the algebraically equivalent
    closed-form formula: BAL(Mₙ₋₁) × r / [1 - (1+r)^-Mₙ₋₁]

     IMPLEMENTATION:
    ----------------
    Args:
        coupon: Annual coupon rate as percentage (e.g., 8.0 for 8.0%)
        original_term: Original term in months (M₀)
        remaining_term: Remaining term at START of period (Mₙ₋₁)

    Returns:
        Gross payment factor as fraction of original par

    Raises: 
        ValueError: If original_term is not positive
        ValueError: If remaining_term is negative
        ValueError: If remaining_term is greater than original_term
        ValueError: If coupon is negative
        Warning: If remaining_term is zero
        Warning: If coupon is zero

    Example:
        For a 9.5% loan with 360-month original term, computing period 1:
        - remaining_term = M₀ = 360 (at age 0, start of period 1)

        >>> bma_sch_gross_payment_factor_fixed(9.5, 360, 360)
        0.00840854...  # = 0.00049188 (principal) + 0.00791667 (interest)

        This equals $8.41 per $1000 of original balance per month.
    """

    # Let M = Mₙ = remaining term at END of period (at age n)
    # Then M + 1 = Mₙ₋₁ = remaining term at START of period (at age n-1)
    # Note: remaining_term parameter = M + 1 (remaining at start)

    # BAL(M+1) = beginning balance (at age n-1, with M+1 months remaining)
    bal_m_plus_1 = sch_balance_factor_fixed_rate(coupon, original_term, remaining_term)

    # BAL(M) = ending balance (at age n, with M months remaining)
    bal_m = sch_balance_factor_fixed_rate(coupon, original_term, remaining_term - 1)

    # BMA SF-4: GROSS PAYMENT = PRINCIPAL + INTEREST
    scheduled_principal = bal_m_plus_1 - bal_m
    scheduled_interest = bal_m_plus_1 * coupon / 1200.0

    return scheduled_principal + scheduled_interest


def sch_am_factor_fixed_rate(
        coupon: float,
        original_term: int,
        remaining_term: int
) -> float:
    """
    Calculate the scheduled amortization factor (principal/balance) for a fixed-rate loan.

    The amortization factor represents the fraction of the beginning balance BAL(Mₙ₋₁)
    that is amortized (paid as principal) during period n.

    BMA Reference: Section B.1, SF-4, SF-17; Section C.3, SF-18

    BMA NOTATION CONVENTION:
    ------------------------
    BMA uses BAL(Mₙ) where n is the AGE INDEX (subscript) and Mₙ is the remaining term
    at age n. The relationship is:

        Mₙ = M₀ - n

    Where:
        n   = AGE (0-indexed, number of periods elapsed since origination)
        M₀  = Original term (remaining term at age 0 / origination)
        Mₙ  = Remaining term at age n

    Examples:
        Age 0 (origination):     M₀ = original_term, BAL(M₀) = 1.0
        Age 1 (after 1 month):   M₁ = original_term - 1, BAL(M₁) = balance at age 1
        Age 2 (after 2 months):  M₂ = original_term - 2, BAL(M₂) = balance at age 2
        ...
        Age n:                   Mₙ = original_term - n, BAL(Mₙ) = balance at age n

    So BAL(Mₙ) means "balance at age n, where Mₙ is the remaining term at that age".

    DEFINITION:
    -----------
    The am_factor is the scheduled principal payment as a fraction of the beginning balance
    BAL(Mₙ₋₁) for period n (from age n-1 to age n):

        am_factor = PRINCIPAL / BAL(Mₙ₋₁)
                  = [BAL(Mₙ₋₁) - BAL(Mₙ)] / BAL(Mₙ₋₁)
                  = 1 - BAL(Mₙ) / BAL(Mₙ₋₁)

    Where:
        BAL(Mₙ₋₁) = balance at START of period n (at age n-1, with Mₙ₋₁ months remaining)
        BAL(Mₙ)   = balance at END of period n (at age n, with Mₙ = Mₙ₋₁ - 1 months remaining)

    RELATIONSHIP TO SURVIVAL:
    -------------------------
    The balance survival ratio for period n is (1 - am_factor):

        BAL(Mₙ) = BAL(Mₙ₋₁) × (1 - am_factor)

    ALIGNMENT WITH SF-18:
    ---------------------
    This function aligns with BMA SF-18's balance survival ratio convention:

        ACT AM(i) = PERF BAL(i-1) * [1 - SCH AM(i)/SCH AM(i-1)]

    Where SCH AM(i-1) is the scheduled balance at START of period i, and SCH AM(i) is at END.
    The survival ratio SCH AM(i)/SCH AM(i-1) rolls PERF BAL(i-1) forward to PERF BAL(i).

    FORMULA:
    --------
    Given remaining_term at the START of a period:

        survival_ratio = BAL(remaining_term - 1) / BAL(remaining_term)
        am_factor = 1 - survival_ratio

    This matches SF-18: SCH AM(i)/SCH AM(i-1) = BAL(remaining_term - 1) / BAL(remaining_term)
    where remaining_term is the remaining term at START of period i.

    ITERATIVE COMPUTATION:
    ----------------------
    Starting from BAL(M₀) = 1.0 at age 0:

        Period 1 (age 0→1): BAL(M₁) = BAL(M₀) × (1 - am_factor(remaining_term=M₀))
        Period 2 (age 1→2): BAL(M₂) = BAL(M₁) × (1 - am_factor(remaining_term=M₁))
        ...
        Period n (age n-1→n): BAL(Mₙ) = BAL(Mₙ₋₁) × (1 - am_factor(remaining_term=Mₙ₋₁))

    Scheduled principal for any period:
        PRINCIPAL = BAL(Mₙ₋₁) × am_factor

    CONNECTION TO CLOSED-FORM FORMULA:
    ----------------------------------
    The iterative computation above produces the same result as the closed-form formula
    derived from present value annuity factors. By repeatedly applying the balance survival
    ratio (1 - am_factor), we arrive at:

        BAL(Mₙ) = PVAF(Mₙ) / PVAF(M₀)

    Where PVAF(M) is the Present Value Annuity Factor for M periods:
        PVAF(M) = [1 - (1 + r)^-M] / r

    PVAF(M) gives the present value of M payments of $1 each, discounted at rate r.
    It is the reciprocal of the Annuity Factor AF(M) = r / [1 - (1+r)^-M], which
    gives the level payment needed to amortize $1 over M periods.

    Expanding the ratio:
        PVAF(Mₙ) / PVAF(M₀) = [(1 - (1+r)^-Mₙ) / r] / [(1 - (1+r)^-M₀) / r]
                              = [1 - (1+r)^-Mₙ] / [1 - (1+r)^-M₀]

    Intuition: The remaining balance is the ratio of the PV of remaining payments
    to the PV of all original payments. At origination, PVAF(M₀)/PVAF(M₀) = 1.
    At maturity, PVAF(0)/PVAF(M₀) = 0.

    This closed-form formula is equivalent to the iterative computation because:
    1. Each period's am_factor is computed from the balance survival ratio
    2. The survival ratio BAL(Mₙ)/BAL(Mₙ₋₁) equals PVAF(Mₙ)/PVAF(Mₙ₋₁) for fixed-rate loans
    3. Multiplying all survival ratios from age 0 to age n gives PVAF(Mₙ)/PVAF(M₀)

    For fixed-rate loans, this function uses the closed-form formula (via
    sch_balance_factor_fixed_rate) rather than iterating, which is more efficient.

    IMPLEMENTATION:
    ---------------
    Args:
        coupon: Annual coupon rate as percentage (e.g., 8.0 for 8.0%)
        original_term: Original term in months
        remaining_term: Remaining term in months at START of the period

    Returns:
        Amortization factor = PRINCIPAL / BAL(start) = 1 - survival_ratio

    Raises: 
        ValueError: If original_term is not positive
        ValueError: If remaining_term is negative
        ValueError: If remaining_term is greater than original_term
        ValueError: If coupon is negative
        Warning: If remaining_term is zero
        Warning: If coupon is zero

    Example (9.5%, 360-term, first period):
        >>> am = sch_am_factor_fixed_rate(9.5, 360, 360)
        >>> print(f"am_factor: {am:.8f}")
        am_factor: 0.00049188
    """
    survival_ratio = (sch_balance_factor_fixed_rate(coupon, original_term, remaining_term - 1) /
                      sch_balance_factor_fixed_rate(coupon, original_term, remaining_term))
    am_factor = 1 - survival_ratio
    return am_factor


# =============================================================================
# AMORTIZATION: PAYMENT, PRINCIPAL, AND BALANCE COMPUTATION
# =============================================================================
#
# The functions in this section compute payments, amortization, and balance
# trajectories. They work for both fixed-rate and floating-rate loans.
#
# For fixed-rate loans, the balance has a closed-form solution (see
# sch_balance_factor_fixed_rate above). For floating-rate loans, the balance
# must be computed iteratively because rates vary by period. The full algebraic
# derivation — including why only the current period's rate rₙ matters for
# single-period computations — is in the sch_payment_factor() docstring.
#
# FUNCTION ARCHITECTURE:
#
#   sch_payment_factor(coupon, remaining_term, beginning_balance_factor)
#       The annuity factor: payment per dollar of balance that amortizes the
#       loan to zero over M periods at rate r.
#
#       PMTₙ = BAL(Mₙ₋₁) × AF(Mₙ₋₁, rₙ)
#            = BAL(Mₙ₋₁) × rₙ / [1 - (1+rₙ)^-Mₙ₋₁]
#
#   am_factor(beginning_balance, coupon, remaining_term)
#       The principal fraction: what share of beginning balance amortizes.
#       Works with ANY balance (scheduled or actual).
#
#       am_factorₙ = AF(Mₙ₋₁, rₙ) - rₙ
#       BAL(Mₙ) = BAL(Mₙ₋₁) × (1 - am_factorₙ)
#
#   sch_payment_factor_vector(coupon_vector, original_term)
#       Vectorized annuity factors for multiple periods at once.
#
#   sch_balance_factors(coupon_vector, original_term)
#       Iterates from origination along the SCHEDULED (0% CPR, 0% CDR) path.
#       Returns vectors of (periods, rates, am_factors, balance_factors)
#       all indexed by age (n=0 is origination).
#
#   sch_ending_balance_factor(coupon_vector, original_term, remaining_term)
#       Convenience wrapper: returns just the final balance factor.
# =============================================================================

def sch_payment_factor(
        coupon: float,
        remaining_term: int,
        beginning_balance_factor: float = 1.0
) -> float:
    """
    Calculate the scheduled gross monthly payment using the annuity factor.

    BMA Reference: Section B.1, SF-4

    This function implements the standard Annuity Factor for a level-payment loan.
    The key insight is that the gross payment for ANY period can be computed in two equivalent
    ways for a fixed-rate, fully amortizing loan with level payments. The extension to
    floating-rate is straightforward: recompute the payment each period based on the prior
    period ending balance and the new annuity factor for the remaining term with updated
    coupon (shown in BMA SF-18 and SF-19).

    NOTATION CONVENTION:
    --------------------
    We distinguish between the mathematical function AF(M) and the period-indexed AFₙ:

        AF(M) = r / [1 - (1+r)^-M]     Mathematical formula (M = remaining term)
        AFₙ   = AF(Mₙ₋₁)               Annuity factor for period n

    For period n (from age n-1 to age n):
        - Beginning balance = BAL(Mₙ₋₁)  (balance at age n-1)
        - Annuity factor    = AFₙ = AF(Mₙ₋₁)
        - Payment           = BAL(Mₙ₋₁) × AFₙ
        - Ending balance    = BAL(Mₙ)    (balance at age n)

    Example - Period 1 (from age 0 to age 1):
        - Beginning balance = BAL(M₀) = 1.0
        - AF₁ = AF(M₀) = r / [1 - (1+r)^-M₀]
        - Payment = 1.0 × AF₁

    The two equivalent ways to compute the gross payment for a fixed-rate loan are:
        1. As a constant fraction of original par (BMA SF-4 formula)
        2. As BAL(Mₙ₋₁) × AFₙ, using the balance and annuity factor at period start

    Where:
        r   = monthly coupon rate (C / 1200)
        M₀  = original term (months)
        Mₙ  = remaining term at age n (months), where n = M₀ - Mₙ

    This function works for BOTH fixed-rate and floating-rate loans:
        - Fixed-rate: Call with the same coupon each period; payment is constant
        - Floating-rate: Call with updated coupon each period; payment varies

    ===========================================================================
    ALGEBRAIC DERIVATION: From BMA SF-4 to Annuity Formula
    ===========================================================================

    ---------------------------------------------------------------------------
    Step 1: The Level Payment that Amortizes a Balance to Zero
    ---------------------------------------------------------------------------

    The Present Value Annuity Factor (PVAF) gives the present value of M
    payments of $1 each, discounted at rate r per period:

        PVAF(M, r) = [1 - (1+r)^-M] / r

    At the start of any period n, the balance BAL(Mₙ₋₁) equals the present
    value of the Mₙ₋₁ remaining level payments PMT, discounted at rate r:

        BAL(Mₙ₋₁) = PMT × PVAF(Mₙ₋₁, r)

    Knowing this, and given the starting balance of a loan with interest rate 
    r, we can solve for the level payment that amortizes BAL(Mₙ₋₁) to zero over 
    Mₙ₋₁ periods:

        PMTₙ = BAL(Mₙ₋₁) / PVAF(Mₙ₋₁, r)

             = BAL(Mₙ₋₁) / { [1 - (1+r)^-Mₙ₋₁] / r }        ... expand PVAF

             = BAL(Mₙ₋₁) × r / [1 - (1+r)^-Mₙ₋₁]             ... invert the fraction

             = BAL(Mₙ₋₁) × AF(Mₙ₋₁, r)                        ... define AF = 1/PVAF

    We call AFₙ = AF(Mₙ₋₁, r) the Annuity Factor for period n: the fraction
    of beginning balance that, if paid for each of the Mₙ₋₁ remaining periods,
    exactly amortizes the loan to zero at interest rate r.

    ---------------------------------------------------------------------------
    Step 2: Recognize the SF-4 Balance as a Ratio of PVAFs
    ---------------------------------------------------------------------------

    BMA SF-4 defines the scheduled balance for a fixed-rate loan as:

        BAL(Mₙ) = [1 - (1+r)^-Mₙ] / [1 - (1+r)^-M₀]

    This is cleverly a ratio of PVAFs (the r denominators cancel):

        BAL(Mₙ) = { [1 - (1+r)^-Mₙ] / r } / { [1 - (1+r)^-M₀] / r }

                 = PVAF(Mₙ, r) / PVAF(M₀, r)

    INTERPRETATION: The balance at any age n is simply the present value of
    the Mₙ remaining payments divided by the present value of all M₀ original
    payments, both discounted at rate r.

    At origination: BAL(M₀) = PVAF(M₀, r) / PVAF(M₀, r) = 1.0
    At maturity:    BAL(0)  = PVAF(0, r) / PVAF(M₀, r)   = 0.0

    ---------------------------------------------------------------------------
    Step 3: Show the Fixed-Rate Dollar Payment is Constant
    ---------------------------------------------------------------------------

    For a fixed-rate loan (constant r), we show the DOLLAR payment is the
    same in every period — this is what makes it a "level-payment" mortgage.

    From Step 1, the dollar payment in period n is:

        PMTₙ = BAL(Mₙ₋₁) × AF(Mₙ₋₁, r)

    Note: AF(Mₙ₋₁, r) as a PERCENTAGE of current balance changes every
    period (it increases as the balance declines). But the absolute dollar
    product must be shown to be constant.

    Substituting BAL(Mₙ₋₁) = PVAF(Mₙ₋₁, r) / PVAF(M₀, r) from Step 2:

        PMTₙ = PVAF(Mₙ₋₁, r) / PVAF(M₀, r)  ×  1 / PVAF(Mₙ₋₁, r)

             = 1 / PVAF(M₀, r)

             = AF(M₀, r)

             = r / [1 - (1+r)^-M₀]

    PVAF(Mₙ₋₁, r) cancels. The dollar payment reduces to a constant that
    depends only on r and M₀ — it is the same in period 1 as in period 300.

    Equivalently, since BAL(M₀) = 1.0 (per unit of par):

        PMTₙ = AF(M₀, r) = BAL(M₀) × AF(M₀, r)    for all n

    So the dollar payment can also be expressed as a fixed percentage of
    ORIGINAL balance, which never changes.

    To summarize:
        - % of original balance: AF(M₀, r)     — CONSTANT (same every period)
        - % of current balance:  AF(Mₙ₋₁, r)   — VARIES (increases as balance falls)
        - Dollar payment:        BAL(Mₙ₋₁) × AF(Mₙ₋₁, r) = AF(M₀, r) — CONSTANT

    ---------------------------------------------------------------------------
    Step 4: Verify via BMA SF-4 Payment Decomposition
    ---------------------------------------------------------------------------

    BMA SF-4 defines the gross payment as:

        PMTₙ = PRINCIPAL + INTEREST = [BAL(Mₙ₋₁) - BAL(Mₙ)] + BAL(Mₙ₋₁) × r

    Using the SF-4 balance formula with D = [1 - (1+r)^-M₀]:

        PRINCIPAL = BAL(Mₙ₋₁) - BAL(Mₙ)
                  = { [1-(1+r)^-Mₙ₋₁] - [1-(1+r)^-Mₙ] } / D
                  = { (1+r)^-Mₙ₋₁ × [(1+r) - 1] } / D      ... since Mₙ = Mₙ₋₁ - 1
                  = r × (1+r)^-Mₙ₋₁ / D

        INTEREST  = BAL(Mₙ₋₁) × r = r × [1 - (1+r)^-Mₙ₋₁] / D

        PMTₙ     = r/D × { (1+r)^-Mₙ₋₁ + 1 - (1+r)^-Mₙ₋₁ }
                  = r / D = AF(M₀, r)  ✓   ... same result as Step 3

    ---------------------------------------------------------------------------
    Step 5: Extension to Floating-Rate
    ---------------------------------------------------------------------------

    For floating-rate loans, rₙ varies by period. In Step 3 we showed that
    for fixed rate, the payment can be expressed two ways:

        PMTₙ = BAL(M₀) × AF(M₀, r)        ... % of original balance
             = BAL(Mₙ₋₁) × AF(Mₙ₋₁, r)    ... % of current balance

    When r varies by period however, the "% of original balance" form has no
    simple closed-form expression. To see why, note that the balance is the
    product of single-period balance survival ratios:

        BAL(Mₙ₋₁) = BAL(M₀) × ∏ₖ₌₁ⁿ⁻¹ [PVAF(Mₖ, rₖ) / PVAF(Mₖ₋₁, rₖ)]

    For FIXED rate, r₁ = r₂ = ... = rₙ₋₁ = r, so:

        ∏ₖ₌₁ⁿ⁻¹ PVAF(Mₖ, rₖ)/PVAF(Mₖ₋₁, rₖ)

            = PVAF(M₁, r)/PVAF(M₀, r) × PVAF(M₂, r)/PVAF(M₁, r) × ... × PVAF(Mₙ₋₁, r)/PVAF(Mₙ₋₂, r)

        Because all rₖ = r, adjacent PVAF terms cancel (telescope):

            = PVAF(Mₙ₋₁, r) / PVAF(M₀, r)    ... which is the SF-4 closed-form.

    For FLOATING rate (rₖ varies), the adjacent terms do NOT cancel because
    each ratio uses a different rate:

        PVAF(M₁, r₁)/PVAF(M₀, r₁) × PVAF(M₂, r₂)/PVAF(M₁, r₂) × ...

    PVAF(M₁, r₁) ≠ PVAF(M₁, r₂) in general, so there is no telescoping
    and the balance depends on the full rate history.
        
    So the only closed-form
    expression available is the "% of current balance" form:

        PMTₙ = BAL(Mₙ₋₁) × AF(Mₙ₋₁, rₙ)

             = BAL(Mₙ₋₁) × rₙ / [1 - (1+rₙ)^-Mₙ₋₁]

    This is the payment that would amortize BAL(Mₙ₋₁) to zero over Mₙ₋₁
    periods at the current rate rₙ. The balance BAL(Mₙ₋₁) itself must be
    computed iteratively using the full rate history r₁, r₂, ..., rₙ₋₁,
    but once you have it, the payment depends only on rₙ and Mₙ₋₁.

    This determines the period's cash flows:

        INTEREST  = BAL(Mₙ₋₁) × rₙ
        PRINCIPAL = BAL(Mₙ₋₁) × [AF(Mₙ₋₁, rₙ) - rₙ]
        BAL(Mₙ)  = BAL(Mₙ₋₁) - PRINCIPAL
                  = BAL(Mₙ₋₁) × [1 - AF(Mₙ₋₁, rₙ) + rₙ]

    The single-period balance survival ratio BAL(Mₙ)/BAL(Mₙ₋₁) expands to:

        1 - AF(Mₙ₋₁, rₙ) + rₙ

            = 1 - rₙ/[1-(1+rₙ)^-Mₙ₋₁] + rₙ

            = {1 - (1+rₙ)^-Mₙ₋₁ - rₙ + rₙ - rₙ(1+rₙ)^-Mₙ₋₁} / [1-(1+rₙ)^-Mₙ₋₁]

            = {1 - (1+rₙ)^-Mₙ₋₁(1 + rₙ)} / [1-(1+rₙ)^-Mₙ₋₁]

            = [1 - (1+rₙ)^-Mₙ] / [1 - (1+rₙ)^-Mₙ₋₁]     ... since (1+rₙ)^-Mₙ₋₁(1+rₙ) = (1+rₙ)^-Mₙ

            = PVAF(Mₙ, rₙ) / PVAF(Mₙ₋₁, rₙ)

    CRITICAL OBSERVATION: The only rate that appears is rₙ. No prior rates
    r₁, ..., rₙ₋₁ appear anywhere. Prior rates determined the LEVEL of
    BAL(Mₙ₋₁), but the FRACTION that amortizes depends only on rₙ and Mₙ₋₁.

    This is the essential mechanism for floating-rate amortization: at each
    period, recompute the payment using AF(Mₙ₋₁, rₙ) — the payment that
    would amortize the current balance to zero over the remaining term at the
    current rate. The PVAF ratio at the current rate gives the scheduled
    balacne survival ratio.

   
    ===========================================================================
    CONCLUSION
    ===========================================================================

    The gross payment for period n can be expressed as:

    (1) BMA SF-4:     PMTₙ = [BAL(Mₙ₋₁) - BAL(Mₙ)] + BAL(Mₙ₋₁) × rₙ

    (2) PV Inversion: PMTₙ = BAL(Mₙ₋₁) / PVAF(Mₙ₋₁, rₙ)
                            = BAL(Mₙ₋₁) × AF(Mₙ₋₁, rₙ)

    For FIXED-RATE loans (rₙ = r for all n):
        PMTₙ = AF(M₀, r) = r / [1 - (1+r)^-M₀]   ... constant for all n

    For FLOATING-RATE loans (rₙ varies):
        PMTₙ = BAL(Mₙ₋₁) × AF(Mₙ₋₁, rₙ)         ... recomputed each period
        BAL(Mₙ₋₁) must be computed iteratively from the rate history.

    
    ===========================================================================
    Implementation Notes
    ===========================================================================

    The implementation of the annuity factor is straightforward. The annuity factor
    is the payment per dollar of balance that exactly amortizes the loan to zero over 
    M equal installments at rate r.
    
    Args:
        coupon: Annual coupon rate as percentage (e.g., 8.0 for 8.0%)
        remaining_term: Remaining term at period start (Mₙ₋₁)
        beginning_balance_factor: BAL(Mₙ₋₁), balance as fraction of par (default=1.0)

    Returns:
        If beginning_balance_factor=1.0: returns AFₙ = r / [1 - (1+r)^-Mₙ₋₁]
        Otherwise: returns payment = BAL(Mₙ₋₁) × AFₙ

    Raises: 
        ValueError: If remaining_term is negative
        ValueError: If coupon is negative
    """
    if remaining_term < 0:
        raise ValueError(f"remaining_term must be non-negative, got {remaining_term}")
    if coupon < 0:
        raise ValueError(f"coupon must be non-negative, got {coupon}")
    if remaining_term == 0:
        warnings.warn("remaining_term is zero, returning maturity balance")
        annuity_factor = 0.0
    elif coupon == 0.0:
        warnings.warn("coupon is zero, returning straight-line amortization")
        annuity_factor = 1.0 / remaining_term
    else: 
        r = coupon / 1200.0
        annuity_factor = r / (1.0 - (1.0 + r) ** (-remaining_term))
    return beginning_balance_factor * annuity_factor


def am_factor(
        beginning_balance: float,
        coupon: float,
        remaining_term: int
) -> float:
    """
    The primitive single-period principal amortization factor calculation.

    BMA Reference: Section B.1, SF-4; Section C.3, SF-17

    Given ANY beginning balance, compute the am_factor (scheduled principal
    payment as a fraction of balance) for one period. This is pure math - it
    does not assume scheduled vs. actual balance, or 0% CPR/CDR.

    MATHEMATICS:
    ------------
    For a loan with beginning_balance B, annual coupon C, and remaining_term M:

        r = C / 1200                                    (monthly rate)
        annuity_factor = r / [1 - (1+r)^-M]            (payment per dollar of balance)
        payment = B × annuity_factor                    (scheduled payment)
        interest = B × r                                (interest portion)
        principal = payment - interest                  (principal portion)
        am_factor = principal / B                       (amortization as fraction)

    SIMPLIFICATION:
    ---------------
    The am_factor can be expressed without reference to B (it cancels):

        am_factor = principal / B
                  = (payment - interest) / B
                  = payment/B - interest/B
                  = annuity_factor - r

    KEY INSIGHT:
    ------------
    This function works with ANY balance - scheduled or actual. The am_factor
    tells you: "what fraction of beginning balance amortizes (pays down) this
    period?" This is the building block for all amortization calculations.

    To get ending_balance: ending_balance = beginning_balance × (1 - am_factor)
    To get scheduled balance factor: BAL(Mₙ) = BAL(Mₙ₋₁) × (1 - am_factor(n))

    Args:
        beginning_balance: Balance at start of period (fraction of original par,
                          or actual dollar amount - the math works either way)
        coupon: Annual coupon rate for THIS period as percentage (e.g., 8.0 for 8.0%).
                      For floating-rate loans, this changes each period.
        remaining_term: Remaining term in months at START of this period

    Returns:
        am_factor: Amortization factor = principal / beginning_balance
                   (fraction of balance that amortizes this period)

    Raises:
        ValueError: If remaining_term is negative
        ValueError: If coupon is negative

    Example (BMA SF-4, page 4):
        9.5% gross coupon, 360-month term, first period:

        >>> am = am_factor(1.0, 9.5, 360)
        >>> print(f"am_factor: {am:.8f}")
        am_factor: 0.00049188
        >>> ending_balance = 1.0 * (1 - am)  # BAL after first payment
        >>> print(f"ending_balance: {ending_balance:.8f}")
        ending_balance: 0.99950812
    """
    if remaining_term < 0:
        raise ValueError(f"remaining_term must be non-negative, got {remaining_term}")
    if coupon < 0:
        raise ValueError(f"coupon must be non-negative, got {coupon}")
    if remaining_term == 0:
        warnings.warn("remaining_term is zero, returning zero amortization")
        return 0.0
    elif coupon == 0.0:
        warnings.warn("coupon is zero, returning straight-line amortization")
        return 1.0 / remaining_term
    else:
        r = coupon / 1200.0
        annuity_factor = r / (1.0 - (1.0 + r) ** (-remaining_term))
        return annuity_factor - r


def sch_payment_factor_vector(
        coupon_vector: float | list[float] | np.ndarray,
        original_term: int,
        age: int | None = None,
) -> tuple[np.ndarray[int], np.ndarray[float], np.ndarray[float]]:
    """
    Compute scheduled payment factors (annuity factors) for an age-indexed coupon vector.

    For each period n (from age n-1 to age n), computes the annuity factor:

        AFₙ = AF(Mₙ₋₁, rₙ) = rₙ / [1 - (1+rₙ)^-Mₙ₋₁]

    Where:
        rₙ   = coupon_vector[n] / 1200  (monthly rate for period ending at age n)
        Mₙ₋₁ = original_term - (n-1)    (remaining term at START of period n)

    BMA Reference: Section B.1, SF-4

    COUPON VECTOR CONVENTION (age-indexed):
    ---------------------------------------
    coupon_vector[0] = 0.0   (origination — no payment in this period)
    coupon_vector[n] = annual coupon rate (%) for the period ending at age n

    The vector has length num_periods + 1, where num_periods = len(coupon_vector) - 1.
    Please use Loan.build_coupon_vector() to construct from partial coupon data.

    As a convenience, a bare scalar (float/int) is accepted and treated as a
    fixed-rate loan: expanded with a warning.

    Args:
        coupon_vector: Age-indexed annual coupon rates (%).  coupon_vector[0] = 0.0,
            coupon_vector[n] = coupon for period n.  A bare scalar triggers
            fixed-rate expansion (with warning).
        original_term: Original term in months (M₀).
        age: Compute periods 0 through age.  Default None = original_term (full life).
            For a seasoned loan, pass age=loan_age to compute only the historical
            path needed to anchor the BAL at that age.

    Returns:
        Tuple of (periods, rates, payment_factors), all age-indexed (length age + 1):
        - periods[n]: Age index (0 = origination)
        - rates[n]: Annual coupon rate (%) for period ending at age n (0.0 at n=0)
        - payment_factors[n]: Annuity factor for period ending at age n (0.0 at n=0)

    Raises:
        ValueError: If coupon_vector is empty or original_term <= 0.

    Warns:
        UserWarning: If a bare scalar is provided (int or float).

    Example:
        >>> cv = np.concatenate([[0.0], np.full(360, 9.5)])  # age-indexed
        >>> periods, rates_used, factors = sch_payment_factor_vector(cv, 360)
        >>> # Compute only first 60 periods (for a loan at age 60):
        >>> periods, rates_used, factors = sch_payment_factor_vector(cv, 360, age=60)
    """
    if original_term <= 0:
        raise ValueError(f"original_term must be positive, got {original_term}")
    if age is None:
        age = original_term

    rates = np.atleast_1d(np.asarray(coupon_vector, dtype=float))
    if len(rates) == 0:
        raise ValueError("coupon_vector cannot be empty")
    if len(rates) == 1:
        rates = np.concatenate([[0.0], np.full(age, rates[0])])
        warnings.warn(
            f"Single rate ({rates[1]}%) passed to sch_payment_factor_vector; "
            f"treating as fixed-rate and expanding to {age} periods. "
            f"Use Loan.build_coupon_vector() to construct the full vector explicitly.",
            UserWarning,
        )

    num_periods = min(len(rates) - 1, age)
    rates = rates[:num_periods + 1]

    if num_periods > original_term:
        raise ValueError(
            f"coupon_vector implies {num_periods} periods but original_term is {original_term}"
        )

    periods = np.arange(num_periods + 1, dtype=int)

    # Computation vectors: length num_periods, one per period (1..num_periods)
    # r[i] and M[i] are paired for period i+1: rate for the period, remaining term at its start
    r = rates[1:] / 1200.0
    M = original_term - np.arange(num_periods)

    payment_factors = np.zeros(num_periods + 1)
    payment_factors[1:] = np.where(r == 0.0, 1.0 / M, r / (1.0 - np.power(1.0 + r, -M)))

    return (periods, rates, payment_factors)


def sch_balance_factors(
        coupon_vector: float | list[float] | np.ndarray,
        original_term: int,
        age: int | None = None,
) -> tuple[np.ndarray[int], np.ndarray[float], np.ndarray[float], np.ndarray[float], np.ndarray[float]]:
    """
    Compute scheduled balance factors (and amortization factors) by iterating from origination.

    BMA Reference: Section B.1, SF-4; Section C.3, SF-17

    This function computes the scheduled (0% CPR, 0% CDR) balance trajectory from
    origination to a target age, returning the balance factor, amortization factor,
    and rate used for each period. It works for both fixed-rate and floating-rate loans.

    WHAT THIS FUNCTION DOES:
    ------------------------
    Starting from BAL(M₀) = 1.0 at origination, iterates period by period:

        BAL(Mₙ) = BAL(Mₙ₋₁) × (1 - am_factorₙ)

    where am_factorₙ = AF(Mₙ₋₁, rₙ) - rₙ  (see am_factor() and sch_payment_factor()).

    This always uses the SCHEDULED balance from the prior period — it traces the
    0% CPR, 0% CDR amortization path, not any actual/observed balance.

    WHY ITERATION IS REQUIRED:
    --------------------------
    For a fixed-rate loan (constant r), the balance has a closed-form solution:

        BAL(Mₙ) = PVAF(Mₙ, r) / PVAF(M₀, r)     (see sch_balance_factor_fixed_rate)

    For a floating-rate loan (rₙ varies by period), no closed-form exists because
    the balance is a product of single-period ratios each at a different rate:

        BAL(Mₙ) = ∏ₖ₌₁ⁿ PVAF(Mₖ, rₖ) / PVAF(Mₖ₋₁, rₖ)

    When all rₖ = r, adjacent PVAFs cancel (telescope) to the closed-form ratio.
    When rₖ varies, they do not cancel (see sch_payment_factor() Step 5 for the
    full derivation of why only rₙ matters for each single-period ratio).

    This function handles both cases: it calls sch_payment_factor_vector() to get
    all annuity factors at once, converts to am_factors, then iterates to accumulate
    the balance trajectory.

    COUPON VECTOR CONVENTION (age-indexed):
    ---------------------------------------
    coupon_vector[0] = 0.0   (origination — no payment in this period)
    coupon_vector[n] = annual coupon rate (%) for the period ending at age n

    Use Loan.build_coupon_vector() to construct from a RateIndex, or construct
    a coupon_vector manually that is age-indexed.

    A bare scalar (float/int) is accepted as a fixed-rate convenience and
    expanded with a warning (delegated to sch_payment_factor_vector).

    INDEXING CONVENTION:
    --------------------
    All returned vectors are indexed by AGE (n), where age 0 = origination:

        balance_factors[0] = 1.0                   (origination)
        balance_factors[n] = BAL(Mₙ)               (scheduled balance at age n)
        am_factors[0]      = 0.0                   (no amortization at origination)
        am_factors[n]      = am_factor for period ending at age n
        rates[0]           = 0.0                   (no rate at origination)
        rates[n]           = coupon rate for period ending at age n

        balance_factors[n] = balance_factors[n-1] × (1 - am_factors[n])  for n >= 1

    Args:
        coupon_vector: Age-indexed annual coupon rates (%).  coupon_vector[0] = 0.0,
            coupon_vector[n] = coupon for period n.  A bare scalar triggers
            fixed-rate expansion (with warning).
        original_term: Original term in months (M₀).
        age: Compute periods 0 through age.  Default None = original_term (full life).
            For a seasoned loan, pass age=loan_age to compute only the historical
            path needed to anchor the scheduled BAL at that age.

    Returns:
        Tuple of (periods, rates, payment_factors, am_factors, balance_factors),
        all age-indexed with length age + 1:
        - periods[n]: Age index n (0 = origination through n = age)
        - rates[n]: Annual coupon rate (%) for period ending at age n (0.0 at n=0)
        - payment_factors[n]: Annuity factor AF for period ending at age n (0.0 at n=0)
        - am_factors[n]: Amortization factor (AF - r) for period ending at age n (0.0 at n=0)
        - balance_factors[n]: BAL(Mₙ) = scheduled balance at age n (1.0 at n=0)

    Raises:
        ValueError: If coupon_vector is empty or original_term <= 0.

    Example (BMA SF-4):
        >>> cv = np.concatenate([[0.0], np.full(360, 9.5)])
        >>> periods, rates_used, pf, am, bal = sch_balance_factors(cv, 360)
        >>> print(f"At age 12 (M₁₂ = 348): BAL = {bal[12]:.8f}")
        At age 12 (M₁₂ = 348): BAL = 0.99417759
        >>> # Just the first 60 periods (for anchoring at age 60):
        >>> _, _, _, _, bal60 = sch_balance_factors(cv, 360, age=60)
        >>> print(f"BAL at age 60: {bal60[-1]:.8f}")

    See Also:
        sch_payment_factor: Full algebraic derivation (Steps 1-6) including
            the PVAF ratio insight and floating-rate extension.
        sch_payment_factor_vector: Vectorized annuity factor computation.
        am_factor: Single-period amortization primitive.
    """
    periods, rates_used, payment_factors = sch_payment_factor_vector(
        coupon_vector, original_term, age=age,
    )

    # Convert payment factors to am_factors: am_factor = payment_factor - monthly_rate
    monthly_rates = rates_used / 1200.0
    am_factors = payment_factors - monthly_rates

    # BAL[n] = BAL[n-1] × (1 - am_factors[n])
    #
    # Each period, the balance shrinks by the amortization fraction.  The cumulative
    # product telescopes the full path from origination:
    #
    #   BAL[n] = ∏ₖ₌₀ⁿ (1 - am_factors[k])
    #
    # At k=0: am_factors[0] = 0 → factor is 1.0, so BAL[0] = 1.0 (par at origination).
    # At k=n: (1 - am_factors[n]) = 1 - (AF[n] - r[n]) = PVAF(M[n], r[n]) / PVAF(M[n-1], r[n])
    #         which is the single-period balance decay ratio at rate r[n].
    balance_factors = np.cumprod(1.0 - am_factors)

    return periods, rates_used, payment_factors, am_factors, balance_factors


def sch_ending_balance_factor(
        coupon_vector: float | list[float] | np.ndarray,
        original_term: int,
        age: int | None = None,
) -> float:
    """
    Get the scheduled balance factor at a given age.

    Convenience wrapper around sch_balance_factors that returns only the final
    balance factor.  With age=loan_age, this gives the anchor BAL the cashflow
    runner needs at period 0.

    Args:
        coupon_vector: Age-indexed annual coupon rates (%).  coupon_vector[0] = 0.0,
            coupon_vector[n] = coupon for period n.  A bare scalar triggers
            fixed-rate expansion (with warning).
        original_term: Original term in months (M₀).
        age: BAL at this age.  Default None = original_term (BAL at maturity).

    Returns:
        BAL at the specified age: scheduled balance as fraction of par.

    See Also:
        sch_balance_factors: Returns full trajectory, not just final value.
    """
    _, _, _, _, balance_factors = sch_balance_factors(coupon_vector, original_term, age=age)
    return balance_factors[-1]
