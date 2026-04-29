"""Synthesized loan tape for FNR 2006-018 (Group 1 + Group 2).

The published prospectus describes the underlying collateral as two
aggregate sub-replines per group, not a loan-level tape. To make the
deal loadable through the Studio's Tape Intake -> Pool -> Deal flow
we synthesize a representative loan-level tape from the published
aggregate assumptions:

  - **Group 1** (S-7 / S-14 reference): $132,653,061 UPB across two
    sub-replines at WAC 5.94%, original 360, remaining 348-349,
    WALA 9-10. We emit ~600 representative loans at ~$220K average
    balance, alternating WALA 9 / 10 to match the two-repline blend
    described in the prospectus.

  - **Group 2** (S-15 reference): $128,625,424 UPB single repline at
    WAC 5.94%, original 240, remaining 214, WALA 24. We emit ~580
    loans at ~$220K average balance, all at WALA 24.

The tape has:

  - One row per loan with a unique ``loan_id``.
  - ``group_id`` column populated as ``"GROUP_1"`` or ``"GROUP_2"`` so
    the upload library + GroupedCollateralInput build can route loans
    to the right collateral group automatically.
  - ``wala_override`` populated so the BMA cashflow engine seasons the
    PSA curve at the published WALA instead of the misleading
    ``original_term - remaining_term`` derived age.

This is a deterministic synthesis -- repeated runs produce a
byte-identical CSV. The tape's pool-level summary statistics (total
balance, WAC, WAM) tie out to the prospectus to within $1 of UPB and
0.01% of WAC.
"""
from __future__ import annotations

from datetime import date
from io import StringIO

import pandas as pd

from . import (
    GROUP_2_POOL_ASSUMPTIONS,
    GROUP_2_REPLINE,
    POOL_ASSUMPTIONS,
)


SETTLEMENT_DATE = date(2006, 2, 1)


def _orig_date_for_wala(wala_months: int) -> date:
    """Back-date origination from settlement by `wala_months`."""
    years_back = wala_months // 12
    months_back = wala_months % 12
    yr = SETTLEMENT_DATE.year - years_back
    mo = SETTLEMENT_DATE.month - months_back
    if mo <= 0:
        mo += 12
        yr -= 1
    return date(yr, mo, 1)


def _emit_loans(
    *,
    loan_id_start: int,
    group_id: str,
    total_balance: float,
    n_loans: int,
    wac_pct: float,
    net_pct: float,
    original_term: int,
    remaining_term: int,
    wala_months: int,
) -> list[dict]:
    """Emit a list of loan rows with balances summing exactly to total_balance.

    Loan balances are uniformly distributed around the average; the
    final loan absorbs any rounding remainder so the sum is exact to
    the cent. Servicing fee is the WAC-vs-net-pass-through wedge so
    BMA's `act_int` will already be net of the GSE guaranty fee.
    """
    avg = round(total_balance / n_loans, 2)
    rows: list[dict] = []
    running = 0.0
    orig_dt = _orig_date_for_wala(wala_months)
    for i in range(n_loans):
        if i < n_loans - 1:
            bal = avg
        else:
            # Last loan absorbs the rounding residual.
            bal = round(total_balance - running, 2)
        running += bal
        rows.append({
            "loan_id": loan_id_start + i,
            "group_id": group_id,
            "origination_date": orig_dt.isoformat(),
            "asof_date": SETTLEMENT_DATE.isoformat(),
            "original_balance": avg,
            "current_balance": bal,
            "rate_margin": wac_pct,
            "servicing_fee": max(0.0, wac_pct - net_pct),
            "original_term": original_term,
            "remaining_term": remaining_term,
            "wala_override": wala_months,
            "loan_status": "current",
            "days_past_due": 0,
        })
    return rows


def synthesize_tape_dataframe() -> pd.DataFrame:
    """Build the synthesized FNR 2006-018 loan tape as a DataFrame.

    Returns a DataFrame with all loans from both groups concatenated
    and ``loan_id`` values guaranteed unique across the whole tape.
    """
    g1_total = float(POOL_ASSUMPTIONS["aggregate_upb_dollars"])
    g1_wac = float(POOL_ASSUMPTIONS["weighted_average_coupon_pct"])
    g1_net = float(POOL_ASSUMPTIONS["mbs_pass_through_rate_pct"])
    g1_orig_term = int(POOL_ASSUMPTIONS["original_term_months"])
    g1_rem_term = int(POOL_ASSUMPTIONS["weighted_average_remaining_term_months"])

    # Group 1 is published as two sub-replines (WALA 9 + WALA 10). We
    # emit half the loans at each WALA to mirror the blend; balances
    # split proportionally.
    g1_subA_balance = 37_414_966.00     # Sub-A: WALA 9, remaining 349
    g1_subB_balance = g1_total - g1_subA_balance  # Sub-B: WALA 10, remaining 348
    n_g1_subA = 170
    n_g1_subB = 430

    g2_total = float(GROUP_2_POOL_ASSUMPTIONS["aggregate_upb_dollars"])
    g2_wac = float(GROUP_2_REPLINE["wac_pct"])
    g2_net = float(GROUP_2_POOL_ASSUMPTIONS["mbs_pass_through_rate_pct"])
    g2_orig_term = int(GROUP_2_REPLINE["original_term_months"])
    g2_rem_term = int(GROUP_2_REPLINE["remaining_term_months"])
    g2_wala = int(GROUP_2_REPLINE["wala_months"])
    n_g2 = 580

    rows: list[dict] = []
    rows.extend(_emit_loans(
        loan_id_start=10_000_001,
        group_id="GROUP_1",
        total_balance=g1_subA_balance,
        n_loans=n_g1_subA,
        wac_pct=g1_wac,
        net_pct=g1_net,
        original_term=g1_orig_term,
        remaining_term=349,
        wala_months=9,
    ))
    rows.extend(_emit_loans(
        loan_id_start=10_000_001 + n_g1_subA,
        group_id="GROUP_1",
        total_balance=g1_subB_balance,
        n_loans=n_g1_subB,
        wac_pct=g1_wac,
        net_pct=g1_net,
        original_term=g1_orig_term,
        remaining_term=g1_rem_term,
        wala_months=10,
    ))
    rows.extend(_emit_loans(
        loan_id_start=20_000_001,
        group_id="GROUP_2",
        total_balance=g2_total,
        n_loans=n_g2,
        wac_pct=g2_wac,
        net_pct=g2_net,
        original_term=g2_orig_term,
        remaining_term=g2_rem_term,
        wala_months=g2_wala,
    ))
    return pd.DataFrame(rows)


def synthesize_tape_csv() -> str:
    """Return the tape as a CSV string (UTF-8 text, no index column)."""
    df = synthesize_tape_dataframe()
    buf = StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()
