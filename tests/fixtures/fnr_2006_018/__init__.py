"""Fixture data for Fannie Mae REMIC Trust 2006-018 (Group 1 PAC/Z/Support).

Public-record source: Fannie Mae REMIC Trust 2006-018 Prospectus Supplement
dated February 2, 2006. This fixture exercises:

  - PAC schedule-first runtime enforcement (Aggregate Group I planned balance).
  - Z-bond accrual mechanic (Z accrual paid as principal of Aggregate Group II).
  - Support tranche cascade (WA-WG, PO).

Published reference data captured here:

  - Pool: Group 1 MBS aggregate UPB, gross/net WAC, original term, WAM.
  - Schedule 1: Aggregate Group I planned balance vector (339 entries).
  - Schedule 2: Aggregate Group II planned balance vector (349 entries).
  - Decrement table: published weighted-average lives by class and PSA speed.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent


def load_planned_balance_schedule(group: str) -> list[tuple[date, float]]:
    """Return the published planned balance vector as (date, balance) pairs.

    `group` must be one of `"I"` or `"II"`. Returned list is sorted by date
    ascending and starts with the 2006-02-01 settlement entry.
    """
    if group == "I":
        path = FIXTURE_DIR / "aggregate_group_i_planned_balances.csv"
    elif group == "II":
        path = FIXTURE_DIR / "aggregate_group_ii_planned_balances.csv"
    else:
        raise ValueError(f"Unknown group {group!r}")
    rows: list[tuple[date, float]] = []
    with path.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append((date.fromisoformat(row["distribution_date"]), float(row["planned_balance"])))
    rows.sort()
    return rows


SETTLEMENT_DATE = date(2006, 2, 1)


def _months_since_settlement(d: date) -> int:
    """Return integer month offset from settlement (Feb 2006 = period 0)."""
    return (d.year - SETTLEMENT_DATE.year) * 12 + (d.month - SETTLEMENT_DATE.month)


def expand_to_monthly_balance_vector(
    balances: list[tuple[date, float]],
    horizon_periods: int,
) -> list[float]:
    """Expand a sparse published balance schedule into a dense monthly vector.

    The published Schedule 1 has gaps where balance is intentionally held flat
    (e.g., the Aggregate Group I "lockout" period of Feb 2006 - Feb 2007 has
    only a single entry signaling a constant balance). The dense vector
    interpolates between published anchors using **forward-fill**: any missing
    month uses the most recent prior published balance.

    Returns a list of length `horizon_periods + 1` indexed by period
    (period 0 = settlement, period 1 = first distribution, ...).
    """
    by_period: dict[int, float] = {
        _months_since_settlement(d): bal for d, bal in balances
    }
    out: list[float] = [0.0] * (horizon_periods + 1)
    last = float(by_period.get(0, balances[0][1] if balances else 0.0))
    out[0] = last
    for t in range(1, horizon_periods + 1):
        if t in by_period:
            last = float(by_period[t])
        out[t] = last
    return out


def planned_balances_to_principal_schedule(
    balances: list[tuple[date, float]],
    horizon_periods: int,
) -> list[dict[str, float]]:
    """Convert a published planned-balance vector into our IR schedule_contract.

    Translation: `target_principal[t] = monthly_balance[t-1] - monthly_balance[t]`
    after expanding the sparse published vector into a dense monthly path.
    Period 0 is settlement; period 1 is the first distribution date.
    Schedule entries beyond `horizon_periods` are dropped, and entries with
    zero or negative target are suppressed.
    """
    monthly = expand_to_monthly_balance_vector(balances, horizon_periods)
    schedule: list[dict[str, float]] = []
    for t in range(1, horizon_periods + 1):
        target = monthly[t - 1] - monthly[t]
        if target <= 0.0:
            continue
        schedule.append({"period": t, "target_principal": round(target, 2)})
    return schedule


# Pool assumptions (Group 1) per Reference Sheet & Pricing Assumptions.
# The aggregate is a weighted blend of two sub-replines used by the
# prospectus's pricing model (S-7 / S-14):
#   - $ 37,414,966 at WAC 5.94%, original 360, remaining 349, WALA 9
#   - $ 95,238,095 at WAC 5.94%, original 360, remaining 348, WALA 10
# Both sub-replines have the same WAC and pass-through, so for many
# computations a single aggregate repline is equivalent. The remaining-term
# difference (349 vs 348) materially affects per-period principal at high
# PSA and is why the prospectus models them separately.
POOL_ASSUMPTIONS = {
    "aggregate_upb_dollars": 132_653_061.00,
    "mbs_pass_through_rate_pct": 5.50,
    "weighted_average_coupon_pct": 5.94,
    "weighted_average_remaining_term_months": 348,
    "original_term_months": 360,
    "settlement_date": "2006-02-28",
}

# Two sub-replines that compose Group 1, used at non-zero PSA per the
# prospectus's Pricing Assumptions (matches the published Reference Sheet
# verbatim). At 0% PSA the prospectus uses a single override repline
# (see ZERO_PSA_PRICING_OVERRIDE).
GROUP_1_SUB_REPLINES = [
    {
        "label": "Group 1 MBS A (37.4MM)",
        "current_balance": 37_414_966.00,
        "original_balance": 37_414_966.00,
        "wac_pct": 5.94,
        "net_pass_through_pct": 5.50,
        "original_term_months": 360,
        "remaining_term_months": 349,
        "wala_months": 9,
    },
    {
        "label": "Group 1 MBS B (95.2MM)",
        "current_balance": 95_238_095.00,
        "original_balance": 95_238_095.00,
        "wac_pct": 5.94,
        "net_pass_through_pct": 5.50,
        "original_term_months": 360,
        "remaining_term_months": 348,
        "wala_months": 10,
    },
]
GROUP_1_REPLINE_TOTAL = sum(r["current_balance"] for r in GROUP_1_SUB_REPLINES)
assert abs(GROUP_1_REPLINE_TOTAL - 132_653_061.00) < 1.0, (
    f"sub-repline total mismatch: {GROUP_1_REPLINE_TOTAL}"
)

# Group 1 class structure (verbatim from prospectus cover).
GROUP_1_CLASSES = [
    {"name": "PA", "size": 33_710_000.00, "coupon_pct": 5.50, "type": "PAC"},
    {"name": "PB", "size": 13_470_000.00, "coupon_pct": 5.50, "type": "PAC"},
    {"name": "PC", "size": 13_060_000.00, "coupon_pct": 5.50, "type": "PAC"},
    {"name": "PD", "size": 16_020_000.00, "coupon_pct": 5.50, "type": "PAC"},
    {"name": "EO", "size": 12_150_000.00, "coupon_pct": 0.00, "type": "PAC_PO"},
    {"name": "TA", "size": 25_000_000.00, "coupon_pct": 5.50, "type": "PAC_AD"},
    {"name": "TB", "size": 94_599.00, "coupon_pct": 5.50, "type": "PAC_AD"},
    {"name": "Z", "size": 1_700_680.00, "coupon_pct": 5.50, "type": "Z_BOND"},
    {"name": "PO", "size": 758_600.00, "coupon_pct": 0.00, "type": "SUP_PO"},
    {"name": "WA", "size": 4_748_972.00, "coupon_pct": 5.75, "type": "SUP"},
    {"name": "WB", "size": 1_688_013.00, "coupon_pct": 5.75, "type": "SUP"},
    {"name": "WC", "size": 3_518_626.00, "coupon_pct": 5.75, "type": "SUP"},
    {"name": "WD", "size": 2_165_180.00, "coupon_pct": 5.75, "type": "SUP"},
    {"name": "WE", "size": 1_687_590.00, "coupon_pct": 5.75, "type": "SUP"},
    {"name": "WG", "size": 2_880_801.00, "coupon_pct": 5.75, "type": "SUP"},
]
GROUP_1_TOTAL = sum(c["size"] for c in GROUP_1_CLASSES)
assert abs(GROUP_1_TOTAL - 132_653_061.0) < 100.0, f"Group 1 sizing mismatch: {GROUP_1_TOTAL}"

STRUCTURING_RANGES = {
    "aggregate_group_i": {"low_psa": 100.0, "high_psa": 250.0},
    "aggregate_group_ii": {"low_psa": 147.0, "high_psa": 227.0},
}

# Annual decrement-table snapshot dates (period offsets from settlement).
# The prospectus reports factors on each February distribution date plus
# initial; period 0 is settlement (Feb 28, 2006), period 12 is the Feb 25,
# 2007 distribution, period 360 is Feb 25, 2036. Published values use
# integer-percent rounding with `*` denoting "0% < balance <= 0.5%".
DECREMENT_TABLE_PERIODS: list[int] = [0] + [12 * y for y in range(1, 31)]

# Per-tranche published factor table per PSA column. Indexed by
# `DECREMENT_TABLE_PERIODS` (31 entries). Z exceeds 100% during PIK accrual.
# `*` in the prospectus is encoded as 0.4 (mid-point of the 0-0.5% bucket).
#
# Keyed by integer PSA percentage. Add a column key when its full set of
# published factors has been digitized; tests automatically pick up new
# PSA columns and run them as additional parametrized scenarios.
PUBLISHED_FACTORS_GROUP_1_0PSA: dict[str, list[float]] = {
    "PA": [100, 100, 96, 93, 88, 84, 79, 74, 68, 62, 55, 48,
            40,  31, 22, 12,  1,  0,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    "PB": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100, 73, 41,  7,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    "PC": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100, 68, 27,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    "PD": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,100,100, 85, 45,
             1,   0,  0,  0,  0,  0,  0],
    "EO": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,100,100,100,100,
           100,  40,  3,  2,  1,  0,  0],
    "TA": [100,  95, 95, 94, 94, 93, 93, 92, 92, 91, 91, 90,
            89,  88, 88, 87, 86, 85, 84, 83, 82, 81, 80, 78,
            77,  76, 59, 23,  0,  0,  0],
    "TB": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100, 65,  2,  0],
    "Z":  [100, 106,112,118,125,132,139,147,155,164,173,183,
           193, 204,216,228,241,254,269,284,300,317,334,353,
           373, 394,417,440,229,  0,  0],
    "PO": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100, 64,  0],
    "WA": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,  0],
    "WB": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,  0],
    "WC": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,  0],
    "WD": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,  0],
    "WE": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,  0],
    "WG": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,  0],
}

# Per-tranche published factor table at the 100% PSA column. Verified
# verbatim from prospectus pages S-23 through S-27.
#
# Index -> Period -> Date map:
#   0=init,
#   1=12=Feb2007, 2=24=Feb2008, 3=36=Feb2009, 4=48=Feb2010, 5=60=Feb2011,
#   6=72=Feb2012, 7=84=Feb2013, 8=96=Feb2014, 9=108=Feb2015, 10=120=Feb2016,
#   11=132=Feb2017, 12=144=Feb2018, 13=156=Feb2019, 14=168=Feb2020,
#   15=180=Feb2021, 16=192=Feb2022, 17=204=Feb2023, 18=216=Feb2024,
#   19=228=Feb2025, 20=240=Feb2026, 21=252=Feb2027, 22=264=Feb2028,
#   23=276=Feb2029, 24=288=Feb2030, 25=300=Feb2031, 26=312=Feb2032,
#   27=324=Feb2033, 28=336=Feb2034, 29=348=Feb2035, 30=360=Feb2036
#
# Prospectus `*` (between 0% and 0.5%) is encoded as 0.4 (mid-bucket).
PUBLISHED_FACTORS_GROUP_1_100PSA: dict[str, list[float]] = {
    # PA: F08=74, F09=48, F10=24, F11=1, F12+=0
    "PA": [100, 100, 74, 48, 24,  1,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    # PB: F12=48, F13+=0
    "PB": [100, 100,100,100,100,100, 48,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    # PC: F13=97, F14=48, F15=3, F16+=0
    "PC": [100, 100,100,100,100,100,100, 97, 48,  3,  0,  0,
             0,   0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    # PD: F16=71, F17=46, F18=24, F19=6, F20+=0
    "PD": [100, 100,100,100,100,100,100,100,100,100, 71, 46,
            24,   6,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    # EO: F20=88, F21=72, F22=58, F23=47, F24=38, F25=30, F26=23, F27=18,
    # F28=14, F29=10, F30=8, F31=5, F32=3, F33=2, F34=1, F35=*, F36=0
    "EO": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100, 88, 72, 58, 47, 38, 30, 23, 18, 14, 10,
             8,   5,  3,  2,  1,  0.4, 0],
    # TA: F07=76, F08=75, F09=75, F10=74, F11=74, F12=73, F13=73, F14=72,
    # F15=71, F16=67, F17=62, F18=55, F19=47, F20=38, F21=29, F22=19,
    # F23=9, F24=6, F25=5, F26=4, F27=3, F28=2, F29=2, F30=1, F31=1,
    # F32=*, F33=*, F34=0, F35=0, F36=0
    "TA": [100,  76, 75, 75, 74, 74, 73, 73, 72, 71, 67, 62,
            55,  47, 38, 29, 19,  9,  6,  5,  4,  3,  2,  2,
             1,   1,0.4,0.4,  0,  0,  0],
    # TB: F07-F33 = 100, F34 = 65, F35 = 2, F36 = 0
    "TB": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100, 65,  2,  0],
    # Z: PIK accrues F07=106, F08=112, ..., F22=241, F23=254 (peak),
    # then F24=167, F25=47, F26+=0 (cash-pay phase).
    "Z":  [100, 106,112,118,125,132,139,147,155,164,173,183,
           193, 204,216,228,241,254,167, 47,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    # PO: F26=93, F27=81, F28=70, F29=59, F30=48, F31=38, F32=28, F33=18,
    # F34=9, F35=*, F36=0
    "PO": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100, 93, 81, 70, 59,
            48,  38, 28, 18,  9,  0.4, 0],
    # WA: F26=75, F27=34, F28+=0
    "WA": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100, 75, 34,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    # WB: F28=84, F29+=0
    "WB": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,100,100, 84,  0,
             0,   0,  0,  0,  0,  0,  0],
    # WC: F29=88, F30=37, F31+=0
    "WC": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,100,100,100, 88,
            37,   0,  0,  0,  0,  0,  0],
    # WD: F31=80, F32=3, F33+=0
    "WD": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,100,100,100,100,
           100,  80,  3,  0,  0,  0,  0],
    # WE: F33=9, F34+=0
    "WE": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,  9,  0,  0,  0],
    # WG: F34=52, F35=1, F36=0
    "WG": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100, 52,  1,  0],
}


# Master keyed-by-PSA registry. Tests iterate this dict to discover which
# PSA columns have been digitized and run them as additional parametrized
# scenarios. Add a key here when a new column is captured from the prospectus.
PUBLISHED_FACTORS_GROUP_1_BY_PSA: dict[int, dict[str, list[float]]] = {
    0: PUBLISHED_FACTORS_GROUP_1_0PSA,
    100: PUBLISHED_FACTORS_GROUP_1_100PSA,
}


# Published weighted-average lives by class and PSA (years), from prospectus
# Decrement Tables section. Used as numerical sanity targets in tie-out tests.
PUBLISHED_WAL_GROUP_1 = {
    # PSA: 0%, 100%, 147%, 180%, 227%, 250%, 375%, 500%
    "PA": [10.1, 3.0, 3.0, 3.0, 3.0, 3.0, 2.7, 2.2],
    "PB": [17.7, 6.0, 6.0, 6.0, 6.0, 6.0, 4.4, 3.4],
    "PC": [20.5, 8.0, 8.0, 8.0, 8.0, 8.0, 5.5, 4.2],
    "PD": [22.9, 11.0, 11.0, 11.0, 11.0, 11.0, 7.6, 5.7],
    "EO": [24.9, 17.7, 17.7, 17.7, 17.7, 17.7, 12.7, 9.6],
    "TA": [23.2, 10.7, 4.7, 4.7, 4.7, 2.8, 1.6, 1.3],
    "TB": [28.3, 28.3, 28.3, 28.3, 28.3, 8.0, 2.8, 2.0],
    "Z":  [28.0, 18.3, 9.8, 0.7, 0.3, 0.3, 0.2, 0.1],
    "PO": [29.2, 24.0, 19.1, 11.8, 2.8, 2.1, 1.1, 0.8],
    "WA": [28.7, 20.6, 13.3, 2.5, 1.2, 1.0, 0.5, 0.4],
    "WB": [29.0, 22.3, 16.2, 5.2, 1.9, 1.5, 0.8, 0.6],
    "WC": [29.2, 23.8, 18.5, 11.2, 2.5, 2.0, 1.1, 0.8],
    "WD": [29.5, 25.4, 21.3, 15.9, 3.3, 2.5, 1.3, 0.9],
    "WE": [29.7, 26.6, 23.5, 19.1, 4.0, 2.9, 1.4, 1.0],
    "WG": [29.9, 28.1, 26.7, 24.3, 5.4, 3.5, 1.6, 1.2],
}
PUBLISHED_WAL_PSA_COLUMNS = [0, 100, 147, 180, 227, 250, 375, 500]

# Pricing assumption applied for the **0% PSA** column only. The prospectus
# uses a worst-case 8.00% gross / 360 month full term assumption when no
# prepayment occurs. Other PSA speeds use the actual pool characteristics.
ZERO_PSA_PRICING_OVERRIDE = {
    "weighted_average_coupon_pct": 8.00,
    "weighted_average_remaining_term_months": 360,
    "original_term_months": 360,
}


# ---------------------------------------------------------------------------
# Group 2 sub-deal: BA / BC / BD / DO (sequential pay) + DI (notional IO)
# ---------------------------------------------------------------------------
#
# Group 2 is a pure 4-class sequential cascade backed by a single MBS pool of
# 20-year fixed-rate loans (FNMA pool with WALA 24, original term 240 mo).
# The waterfall is verbatim from prospectus S-18:
#
#     Group 2 Principal Distribution Amount: sequentially as principal of
#     BA, BC, BD and DO Classes, in that order, until each balance reaches
#     zero.
#
# Bond stack:
#   BA $104,600,000 SEQ 5.50% (priority 1, first to receive principal)
#   BC   6,700,000 SEQ 5.50%
#   BD   5,400,000 SEQ 5.50%
#   DO  11,925,424 SEQ PO  (zero coupon, last priority)
#   DI  11,925,424 NTL 5.50% IO (notional balance = DO outstanding)
#
# DI is a notional interest-only class; its principal "balance" tracks DO's
# outstanding so DI's coupon accrues against the DO leg only. The runtime
# expresses this via ``BondDef.tracks_bonds={"balance": ["DO"]}``.

GROUP_2_POOL_ASSUMPTIONS = {
    "aggregate_upb_dollars": 128_625_424.00,
    "mbs_pass_through_rate_pct": 5.50,
    "weighted_average_coupon_pct": 5.94,
    "weighted_average_remaining_term_months": 214,
    "original_term_months": 240,
    "wala_months": 24,
    "settlement_date": "2006-02-28",
}

GROUP_2_REPLINE = {
    "label": "Group 2 MBS",
    "current_balance": 128_625_424.00,
    "original_balance": 128_625_424.00,
    "wac_pct": 5.94,
    "net_pass_through_pct": 5.50,
    "original_term_months": 240,
    "remaining_term_months": 214,
    "wala_months": 24,
}

GROUP_2_CLASSES = [
    {"name": "BA", "size": 104_600_000.00, "coupon_pct": 5.50, "type": "SEQ"},
    {"name": "BC", "size":   6_700_000.00, "coupon_pct": 5.50, "type": "SEQ"},
    {"name": "BD", "size":   5_400_000.00, "coupon_pct": 5.50, "type": "SEQ"},
    {"name": "DO", "size":  11_925_424.00, "coupon_pct": 0.00, "type": "SEQ_PO"},
    {"name": "DI", "size":  11_925_424.00, "coupon_pct": 5.50, "type": "NTL_IO"},
]
GROUP_2_TOTAL_PRINCIPAL = sum(
    c["size"] for c in GROUP_2_CLASSES if c["type"] != "NTL_IO"
)
assert abs(GROUP_2_TOTAL_PRINCIPAL - 128_625_424.0) < 1.0, (
    f"Group 2 sizing mismatch: {GROUP_2_TOTAL_PRINCIPAL}"
)

# Pricing override at 0% PSA for Group 2: 240-month full-term @ 8.00%.
GROUP_2_ZERO_PSA_PRICING_OVERRIDE = {
    "weighted_average_coupon_pct": 8.00,
    "weighted_average_remaining_term_months": 240,
    "original_term_months": 240,
}

# Group 2 published PSA columns (different from Group 1!).
PUBLISHED_WAL_PSA_COLUMNS_GROUP_2 = [0, 100, 206, 300, 400, 500]

PUBLISHED_WAL_GROUP_2 = {
    # PSA columns: 0%, 100%, 206%, 300%, 400%, 500%
    "BA": [11.1,  5.5,  3.6,  2.7,  2.0,  1.6],
    "BC": [18.3, 13.3,  9.8,  7.5,  5.8,  4.7],
    "BD": [18.8, 14.5, 11.3,  8.8,  6.9,  5.5],
    "DO": [19.6, 16.4, 14.4, 12.2, 10.1,  8.3],
    "DI": [19.6, 16.4, 14.4, 12.2, 10.1,  8.3],  # IO shares DO's WAL.
}

# Per-tranche published factor table at the 0% PSA column for Group 2.
# Index -> period -> date map matches DECREMENT_TABLE_PERIODS.
PUBLISHED_FACTORS_GROUP_2_0PSA: dict[str, list[float]] = {
    "BA": [100,  97, 95, 92, 88, 85, 81, 77, 72, 67, 62, 56,
            50,  43, 36, 28, 19, 10,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    "BC": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100, 96,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    "BD": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,  8,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    "DO": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    "DI": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100,100,100,100,100,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
}

PUBLISHED_FACTORS_GROUP_2_100PSA: dict[str, list[float]] = {
    # BA: F07=89, F08=79, F09=69, F10=60, F11=51, F12=43, F13=35, F14=28,
    #     F15=21, F16=15, F17=9, F18=3, F19+=0
    "BA": [100,  89, 79, 69, 60, 51, 43, 35, 28, 21, 15,  9,
             3,   0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    # BC: F07-F18=100, F19=69, F20+=0
    "BC": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100,  69,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    # BD: F07-F19=100, F20=91, F21=2, F22+=0
    "BD": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100, 91,  2,  0,  0,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    # DO: F07-F21=100, F22=63, F23=28, F24+=0
    "DO": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100, 63, 28,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    # DI: notional balance tracks DO, so the published factor row is identical.
    "DI": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100, 100,100,100, 63, 28,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
}

PUBLISHED_FACTORS_GROUP_2_206PSA: dict[str, list[float]] = {
    # 206% PSA is the canonical pricing speed for the Group 2 PO/IO pair.
    # Verified verbatim from prospectus S-26 / S-27.
    # BA: F07=82, F08=66, F09=52, F10=40, F11=29, F12=20, F13=13, F14=6,
    #     F15=1, F16+=0
    "BA": [100,  82, 66, 52, 40, 29, 20, 13,  6,  1,  0,  0,
             0,   0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    # BC: F07-F15=100, F16=35, F17+=0
    "BC": [100, 100,100,100,100,100,100,100,100,100, 35,  0,
             0,   0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    # BD: F07-F16=100, F17=65, F18+=0
    "BD": [100, 100,100,100,100,100,100,100,100,100,100, 65,
             0,   0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    # DO: F07-F18=100, F19=74, F20=53, F21=35, F22=21, F23=8, F24+=0
    "DO": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100,  74, 53, 35, 21,  8,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
    "DI": [100, 100,100,100,100,100,100,100,100,100,100,100,
           100,  74, 53, 35, 21,  8,  0,  0,  0,  0,  0,  0,
             0,   0,  0,  0,  0,  0,  0],
}


PUBLISHED_FACTORS_GROUP_2_BY_PSA: dict[int, dict[str, list[float]]] = {
    0: PUBLISHED_FACTORS_GROUP_2_0PSA,
    100: PUBLISHED_FACTORS_GROUP_2_100PSA,
    206: PUBLISHED_FACTORS_GROUP_2_206PSA,
}
