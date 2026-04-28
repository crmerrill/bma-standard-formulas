"""PSA curve correctness validation.

These tests verify the BMA PSA prepayment model end to end:

1. **Curve generation against BMA SF-5/SF-6 known values**: 100% PSA hits
   0.2% CPR at month 1, 3.0% at month 15, 6.0% at month 30+; the standard
   SMM = 1 - (1 - CPR/100)^(1/12) conversion holds at every month.

2. **Linearity in PSA speed**: 200% PSA is exactly 2x 100% in CPR space at
   every age <= 30. Above month 30 both plateau (200% at 12% CPR, 100% at
   6%).

3. **Seasoning alignment** (the FNR 2006-018 issue): a loan with WALA = N
   at 100% PSA should see CPR = min(0.2 * (N + period), 6.0)% at each
   period, NOT the unseasoned 0.2 * period curve. This is what the BMA
   `Loan` wrapper's age-indexed curve slicing must produce.

4. **Per-period vol_prepay identity**: voluntary prepayment dollars at
   period i equal SMM[age_at_i] * (performing_balance[i-1] - act_am[i]).
   This is the contract between the SMM curve and the loan amortization.

5. **Collateral-only WAL sanity**: aggregate Group 1 collateral WAL at
   each published PSA speed lands in the expected band given the
   prospectus's pool-projection model.

The 100% PSA TA WAL drift in the FNR decrement-table tie-out (engine
shorter than prospectus by ~0.39y) almost certainly originates from a
boundary case in this PSA model. These tests are the precise locations
where any divergence between BMA and the prospectus pool projection will
surface.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from bma_standard_formulas.engine.loan import (
    Loan,
    actual_cashflow_from_loan,
    scheduled_cashflow_from_loan,
)
from bma_standard_formulas.formulas import generate_smm_curve_from_psa
from bma_standard_formulas.formulas.payment_models import (
    cpr_to_smm,
    generate_psa_curve,
    psa_to_cpr,
)


# ---------------------------------------------------------------------------
# 1. Known-value math identities
# ---------------------------------------------------------------------------


class TestPSAKnownValues:
    """Validate against textbook BMA SF-5/SF-6 PSA values."""

    @pytest.mark.parametrize(
        "month,expected_cpr_pct",
        [
            (0, 0.0),     # Origination, no month elapsed.
            (1, 0.2),     # First month of ramp.
            (5, 1.0),     # 5 * 0.2.
            (15, 3.0),    # Mid-ramp.
            (29, 5.8),    # Just before plateau.
            (30, 6.0),    # Plateau begins.
            (60, 6.0),    # Plateau persists.
            (180, 6.0),   # Late plateau.
            (360, 6.0),   # Maturity-era.
        ],
    )
    def test_100_psa_cpr_at_canonical_months(self, month, expected_cpr_pct):
        assert psa_to_cpr(100.0, month) == pytest.approx(expected_cpr_pct, abs=1e-9)

    @pytest.mark.parametrize(
        "psa_speed,month,expected_cpr_pct",
        [
            (50, 30, 3.0),      # 50% PSA = half the 100% plateau.
            (150, 30, 9.0),     # 150% = 1.5x plateau.
            (200, 15, 6.0),     # 200% PSA at month 15 = 6% CPR.
            (200, 30, 12.0),    # 200% plateau.
            (250, 30, 15.0),    # 250% plateau.
            (500, 30, 30.0),    # 500% plateau.
            (0, 30, 0.0),       # 0% PSA: no prepays ever.
        ],
    )
    def test_psa_speed_scaling(self, psa_speed, month, expected_cpr_pct):
        assert psa_to_cpr(psa_speed, month) == pytest.approx(expected_cpr_pct, abs=1e-9)

    def test_cpr_to_smm_identity(self):
        # SMM = 1 - (1 - CPR/100)^(1/12) at canonical CPR values.
        assert cpr_to_smm(0.0) == pytest.approx(0.0, abs=1e-12)
        assert cpr_to_smm(6.0) == pytest.approx(
            1.0 - (1.0 - 0.06) ** (1.0 / 12.0), abs=1e-12
        )
        assert cpr_to_smm(12.0) == pytest.approx(
            1.0 - (1.0 - 0.12) ** (1.0 / 12.0), abs=1e-12
        )

    def test_curve_length_and_age_zero(self):
        cpr_curve = generate_psa_curve(100.0, 360)
        smm_curve = generate_smm_curve_from_psa(100.0, 360)
        assert len(cpr_curve) == 361
        assert len(smm_curve) == 361
        assert cpr_curve[0] == 0.0
        assert smm_curve[0] == 0.0

    def test_curve_matches_pointwise_psa_to_cpr(self):
        curve = generate_psa_curve(100.0, 360)
        for month in [0, 1, 15, 29, 30, 31, 60, 180, 360]:
            assert curve[month] == pytest.approx(
                psa_to_cpr(100.0, month), abs=1e-12
            ), f"curve[{month}] != psa_to_cpr at month {month}"


# ---------------------------------------------------------------------------
# 2. Seasoning (WALA) alignment
# ---------------------------------------------------------------------------


def _build_loan(
    wala: int,
    original_term: int = 360,
    balance: float = 1_000_000.0,
    gross_rate_pct: float = 6.0,
    servicing_pct: float = 0.0,
) -> Loan:
    """Build a single-loan Loan with the requested seasoning."""
    age_months = max(0, wala)
    asof = date(2006, 2, 1)
    origination_year = asof.year - (age_months // 12)
    origination_month = asof.month - (age_months % 12)
    if origination_month <= 0:
        origination_month += 12
        origination_year -= 1
    origination = date(origination_year, origination_month, 1)
    return Loan(
        loan_id=1,
        origination_date=origination,
        asof_date=asof,
        original_balance=balance,
        current_balance=balance,
        rate_margin=gross_rate_pct,
        servicing_fee=servicing_pct,
        original_term=original_term,
        remaining_term=original_term - age_months,
    )


class TestSeasoningAlignment:
    """A WALA-N loan at 100% PSA should see CPR for ages N+1, N+2, ... not 1, 2, ...

    This is the linchpin of FNR 2006-018: the underlying MBS pools at
    issuance had WALA 9-10 months, so period 1 of the deal is loan age
    10-11, NOT age 1. If the SMM curve is mis-aligned to age the
    voluntary prepay is wrong from period 1, and that error compounds
    over the deal life.
    """

    @pytest.mark.parametrize("wala", [0, 9, 10, 24, 60])
    def test_loan_age_property_matches_wala(self, wala):
        loan = _build_loan(wala=wala)
        assert loan.age == wala

    @pytest.mark.parametrize("wala,period", [
        (0, 1),    # Unseasoned, period 1 = age 1, CPR = 0.2%
        (9, 1),    # Group 1 sub-repline A, period 1 = age 10, CPR = 2.0%
        (10, 1),   # Group 1 sub-repline B, period 1 = age 11, CPR = 2.2%
        (24, 1),   # Group 2 MBS, period 1 = age 25, CPR = 5.0%
        (29, 1),   # One month before plateau.
        (29, 2),   # First period at plateau (age 31).
        (60, 1),   # Deeply seasoned, plateau already.
    ])
    def test_runtime_smm_at_period_1_matches_psa_for_age(self, wala, period):
        """Voluntary prepay at the requested period uses SMM at the loan's
        actual age, not period number.

        The contract: vol_prepay[period] = SMM[age_at_period] *
        (performing_balance_before_prepay - act_am[period]).
        """
        loan = _build_loan(wala=wala, gross_rate_pct=6.0)
        sched = scheduled_cashflow_from_loan(loan)
        smm_curve = generate_smm_curve_from_psa(100.0, loan.original_term)
        n = loan.original_term + 1
        actual = actual_cashflow_from_loan(
            loan=loan,
            scheduled_cf=sched,
            smm_curve=smm_curve,
            mdr_curve=np.zeros(n),
            severity_curve=np.zeros(n),
        )
        # Compute expected SMM at this period given the loan's seasoning.
        age_at_period = loan.age + period
        expected_smm = (
            smm_curve[age_at_period] if age_at_period < len(smm_curve) else 0.0
        )
        # Performing balance entering the period (pre-amortization) is
        # actual.perf_bal[period - 1] (the prior end-of-period balance).
        prev_bal = float(actual.perf_bal[period - 1])
        # Pre-prepay balance = prev_bal - act_am[period] (BMA convention:
        # scheduled amortization happens before voluntary prepay each month).
        pre_prepay_bal = prev_bal - float(actual.act_am[period])
        expected_vol_prepay = expected_smm * pre_prepay_bal
        actual_vol_prepay = float(actual.vol_prepay[period])
        assert actual_vol_prepay == pytest.approx(
            expected_vol_prepay, rel=1e-6, abs=1e-3
        ), (
            f"WALA={wala} period={period} (age={age_at_period}): "
            f"expected vol_prepay={expected_vol_prepay:.4f}, "
            f"got {actual_vol_prepay:.4f} (SMM[age]={expected_smm:.6e}, "
            f"pre_prepay_bal={pre_prepay_bal:.2f})"
        )


# ---------------------------------------------------------------------------
# 3. Per-period vol_prepay identity end-to-end
# ---------------------------------------------------------------------------


class TestVolPrepayPerPeriodIdentity:
    """Across many periods, voluntary prepay matches the SMM[age]*balance contract."""

    @pytest.mark.parametrize("wala", [0, 10, 30, 60])
    def test_identity_holds_for_all_periods(self, wala):
        loan = _build_loan(wala=wala, gross_rate_pct=6.0)
        sched = scheduled_cashflow_from_loan(loan)
        smm_curve = generate_smm_curve_from_psa(100.0, loan.original_term)
        n = loan.original_term + 1
        actual = actual_cashflow_from_loan(
            loan=loan,
            scheduled_cf=sched,
            smm_curve=smm_curve,
            mdr_curve=np.zeros(n),
            severity_curve=np.zeros(n),
        )
        max_period = min(len(actual.perf_bal) - 1, loan.remaining_term)
        for period in range(1, max_period + 1):
            age = loan.age + period
            if age >= len(smm_curve):
                expected = 0.0
            else:
                pre_prepay_bal = (
                    float(actual.perf_bal[period - 1])
                    - float(actual.act_am[period])
                )
                expected = float(smm_curve[age]) * pre_prepay_bal
            actual_vp = float(actual.vol_prepay[period])
            assert actual_vp == pytest.approx(expected, rel=1e-5, abs=1e-2), (
                f"WALA={wala} period={period} (age={age}): "
                f"vol_prepay identity broken: expected={expected:.4f}, "
                f"got={actual_vp:.4f}"
            )


# ---------------------------------------------------------------------------
# 4. Collateral-only WAL sanity at canonical PSA speeds
# ---------------------------------------------------------------------------


def _principal_only_wal_years(actual) -> float:
    """WAL of principal-only cashflow (treats the pool as a bullet to a
    notional bondholder receiving every dollar of principal cash).
    """
    pri = np.asarray(actual.act_am, dtype=float) + np.asarray(
        actual.vol_prepay, dtype=float
    )
    n = len(pri)
    periods = np.arange(n, dtype=float)
    total = float(pri.sum())
    if total <= 0.0:
        return 0.0
    return float((periods * pri).sum() / total / 12.0)


class TestCollateralWAL:
    """Aggregate Group 1 pool WAL sanity at each published PSA column.

    We compute the principal-cash-weighted average life of the pool itself
    (independent of any deal structure). At very low PSA (no prepays) the
    WAL is dominated by scheduled amortization (~21 years for a 30-year
    loan); at very high PSA the WAL collapses.

    Loose tolerance (+/- 1.5 years) because this is a model-level sanity
    check, not a tie to a specific published number. The decrement-table
    test handles tight tie-out.
    """

    # Group 1 sub-replines per FNR 2006-018 Pricing Assumptions.
    SUB_REPLINES = [
        # (current_balance, gross_pct, net_pct, original, remaining, wala)
        (37_414_966.0, 5.94, 5.50, 360, 349, 9),
        (95_238_095.0, 5.94, 5.50, 360, 348, 10),
    ]

    @pytest.mark.parametrize(
        "psa,expected_wal_band",
        [
            # (psa, (low_y, high_y)) -- expected WAL band for the pool.
            (0,    (18.0, 24.0)),  # Pure scheduled amortization on a 30y loan.
            (100,  (8.0, 14.0)),
            (250,  (3.5, 7.5)),
            (500,  (2.0, 5.0)),
        ],
    )
    def test_aggregate_pool_wal_in_band(self, psa, expected_wal_band):
        agg_actual = self._aggregate_actual(psa_speed=psa)
        wal = _principal_only_wal_years(agg_actual)
        low, high = expected_wal_band
        assert low <= wal <= high, (
            f"{psa}% PSA: aggregate Group 1 pool WAL {wal:.2f}y outside "
            f"sanity band [{low:.1f}, {high:.1f}]y"
        )

    def _aggregate_actual(self, psa_speed: float):
        """Sum extensive fields across the Group 1 sub-replines."""
        sub_actuals = []
        for current_bal, wac_pct, net_pct, orig_term, rem_term, wala in self.SUB_REPLINES:
            servicing_pct = max(0.0, wac_pct - net_pct)
            asof = date(2006, 2, 1)
            origination_year = asof.year - (wala // 12)
            origination_month = asof.month - (wala % 12)
            if origination_month <= 0:
                origination_month += 12
                origination_year -= 1
            origination = date(origination_year, origination_month, 1)
            loan = Loan(
                loan_id=hash((current_bal, wala)) % (10**9),
                origination_date=origination,
                asof_date=asof,
                original_balance=current_bal,
                current_balance=current_bal,
                rate_margin=wac_pct,
                servicing_fee=servicing_pct,
                original_term=orig_term,
                remaining_term=rem_term,
            )
            sched = scheduled_cashflow_from_loan(loan)
            smm_curve = generate_smm_curve_from_psa(float(psa_speed), orig_term)
            n = orig_term + 1
            actual = actual_cashflow_from_loan(
                loan=loan,
                scheduled_cf=sched,
                smm_curve=smm_curve,
                mdr_curve=np.zeros(n),
                severity_curve=np.zeros(n),
            )
            sub_actuals.append(actual)

        horizon = min(len(a.perf_bal) for a in sub_actuals)

        class _Agg:
            pass

        agg = _Agg()
        for fname in ("act_am", "vol_prepay", "act_int", "perf_bal"):
            agg.__dict__[fname] = sum(
                getattr(a, fname)[:horizon] for a in sub_actuals
            )
        return agg
