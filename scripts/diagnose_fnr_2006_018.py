"""Period-by-period diagnostic dump of FNR 2006-018 Group 1 at one PSA speed.

Produces a tabular breakdown of:

  - Pool principal delivered each period (BMA cashflow engine)
  - Implied published "schedule cap" for Aggregate Group I and II (derived
    from the published planned balance vectors)
  - Cash that flows to each priority level in the deal engine each period
  - Balance trajectory for each class

Usage::

    python scripts/diagnose_fnr_2006_018.py --psa 100
    python scripts/diagnose_fnr_2006_018.py --psa 100 --max-periods 60

The output highlights periods where pool delivery > or < schedule expectation,
which class absorbs the gap, and how that cascades through Z and supports.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make src/ importable when running from repo root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from bma_standard_formulas.deals.runtime import run_deal  # noqa: E402

from tests.fixtures.fnr_2006_018 import (  # noqa: E402
    GROUP_1_CLASSES,
    expand_to_monthly_balance_vector,
    load_planned_balance_schedule,
)
from tests.fixtures.fnr_2006_018.deal_definition import (  # noqa: E402
    build_fnr_2006_018_group_1_deal,
)
from tests.test_fnr_2006_018_parity import _deal_input_from_repline  # noqa: E402


def diagnose(psa: float, max_periods: int) -> str:
    """Build a single-PSA period-by-period diagnostic report."""
    n_periods = 360
    run_input = _deal_input_from_repline(psa, n_periods)
    deal = build_fnr_2006_018_group_1_deal(n_periods=n_periods)
    result = run_deal(deal, run_input, scenario_name=f"{psa:.0f}PSA")

    coll = run_input.collateral.collateral
    pool_principal = list(coll.principal)

    monthly_i = expand_to_monthly_balance_vector(load_planned_balance_schedule("I"), n_periods)
    monthly_ii = expand_to_monthly_balance_vector(load_planned_balance_schedule("II"), n_periods)

    pac_i_classes = [c["name"] for c in GROUP_1_CLASSES if c["type"] in ("PAC", "PAC_PO")]
    pac_ii_classes = [c["name"] for c in GROUP_1_CLASSES if c["type"] == "PAC_AD"]
    sup_classes = [c["name"] for c in GROUP_1_CLASSES if c["type"] == "SUP"]

    def agg_balance(class_names: list[str], period: int) -> float:
        return float(sum(
            r.end_balance for r in result.bond_cashflows
            if r.tranche_id in class_names and r.period == period
        ))

    def class_principal(class_name: str, period: int) -> float:
        rows = [r for r in result.bond_cashflows if r.tranche_id == class_name and r.period == period]
        if not rows:
            return 0.0
        return float(rows[0].total_principal)

    def class_balance(class_name: str, period: int) -> float:
        rows = [r for r in result.bond_cashflows if r.tranche_id == class_name and r.period == period]
        if not rows:
            return 0.0
        return float(rows[0].end_balance)

    lines: list[str] = []
    lines.append(f"FNR 2006-018 Group 1 diagnostic @ {psa:.0f}% PSA "
                 f"(showing {min(max_periods, n_periods)} periods)")
    lines.append("=" * 100)
    lines.append("")
    lines.append("Pool delivery vs published schedule expectations")
    lines.append("-" * 100)
    lines.append(
        f"{'period':>6} | {'pool_pri':>11} | {'aggI_drop':>11} | {'aggII_drop':>11} | "
        f"{'engI_drop':>11} | {'engII_drop':>11} | "
        f"{'engZ_pri':>10} | {'engSup_pri':>11} | {'engZ_bal':>10}"
    )
    lines.append("-" * 100)

    cumulative_pool = 0.0
    cumulative_pub_aggI = 0.0
    cumulative_pub_aggII = 0.0

    last_period = min(max_periods, n_periods, len(pool_principal) - 1, len(monthly_i) - 1, len(monthly_ii) - 1)
    for p in range(1, last_period + 1):
        pp = float(pool_principal[p])
        pub_aggI_drop = max(0.0, monthly_i[p - 1] - monthly_i[p])
        pub_aggII_drop = max(0.0, monthly_ii[p - 1] - monthly_ii[p])

        eng_aggI_drop = sum(class_principal(c, p) for c in pac_i_classes)
        eng_aggII_drop = sum(class_principal(c, p) for c in pac_ii_classes)
        eng_z_pri = class_principal("Z", p)
        eng_sup_pri = sum(class_principal(c, p) for c in sup_classes) + class_principal("PO", p)
        eng_z_bal = class_balance("Z", p)

        cumulative_pool += pp
        cumulative_pub_aggI += pub_aggI_drop
        cumulative_pub_aggII += pub_aggII_drop

        lines.append(
            f"{p:>6} | {pp:>11,.0f} | {pub_aggI_drop:>11,.0f} | {pub_aggII_drop:>11,.0f} | "
            f"{eng_aggI_drop:>11,.0f} | {eng_aggII_drop:>11,.0f} | "
            f"{eng_z_pri:>10,.0f} | {eng_sup_pri:>11,.0f} | {eng_z_bal:>10,.0f}"
        )

    lines.append("-" * 100)
    lines.append(
        f"Cumulative through period {min(max_periods, n_periods)}: "
        f"pool=${cumulative_pool:,.0f}, "
        f"pubAggI_drop=${cumulative_pub_aggI:,.0f}, "
        f"pubAggII_drop=${cumulative_pub_aggII:,.0f}, "
        f"pub_total=${cumulative_pub_aggI + cumulative_pub_aggII:,.0f}"
    )
    excess = cumulative_pool - (cumulative_pub_aggI + cumulative_pub_aggII)
    lines.append(
        f"Pool excess vs published PAC schedules: ${excess:,.0f} "
        f"({'(pool > schedule, flows to Z + supports)' if excess > 0 else '(pool < schedule, PAC underfills)'})"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Period-by-period FNR 2006-018 diagnostic.")
    parser.add_argument("--psa", type=float, default=100.0,
                        help="PSA speed to diagnose (default: 100)")
    parser.add_argument("--max-periods", type=int, default=60,
                        help="Number of periods to dump (default: 60)")
    args = parser.parse_args()
    print(diagnose(args.psa, args.max_periods))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
