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
POOL_ASSUMPTIONS = {
    "aggregate_upb_dollars": 132_653_061.00,
    "mbs_pass_through_rate_pct": 5.50,
    "weighted_average_coupon_pct": 5.94,
    "weighted_average_remaining_term_months": 348,
    "original_term_months": 360,
    "settlement_date": "2006-02-28",
}

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
}
PUBLISHED_WAL_PSA_COLUMNS = [0, 100, 147, 180, 227, 250, 375, 500]
