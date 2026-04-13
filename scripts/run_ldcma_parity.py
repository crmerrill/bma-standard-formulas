"""Run native LDCMA vs BMA parity on shared collateral paths.

Examples:
  python scripts/run_ldcma_parity.py --portfolio-run-id run_fdf472751ed2
  python scripts/run_ldcma_parity.py --portfolio-run-id run_fdf472751ed2 --deal all
  python scripts/run_ldcma_parity.py --portfolio-run-id run_fdf472751ed2 --deal jumbo17
"""
from __future__ import annotations

import argparse
import os
import sys
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

from bma_cfengine_app.storage import run_store
from bma_standard_formulas.deals.adapters import from_collateral_dict
from bma_standard_formulas.deals.deal_library import (
    jumbo_sequential,
    ldcma_3class_2016,
    passthrough_deal,
)
from bma_standard_formulas.deals.runtime import run_deal


def _patch_quantlib_if_needed() -> None:
    try:
        import QuantLib as ql
    except Exception:
        return
    orig = ql.Thirty360

    def _patched(*args, **kwargs):
        if not args and not kwargs:
            return orig(orig.BondBasis)
        return orig(*args, **kwargs)

    ql.Thirty360 = _patched


def _build_collcf_from_portfolio_df(df: pd.DataFrame) -> dict[str, dict[str, list[float]]]:
    n = len(df)
    cf_dates = [d.date() for d in pd.date_range("2016-06-01", periods=n, freq="MS")]
    gross_rate = df.get("gross_rate", pd.Series([0.0] * n)).fillna(0).astype(float)
    return {
        "COLLAT": {
            "cfdate": cf_dates,
            "balance": df["perf_bal"].astype(float).tolist(),
            "principal": (df["act_am"].fillna(0) + df["vol_prepay"].fillna(0)).astype(float).tolist(),
            "interest": df["act_int"].fillna(0).astype(float).tolist(),
            "cashflow": (df["act_am"].fillna(0) + df["vol_prepay"].fillna(0) + df["act_int"].fillna(0)).astype(float).tolist(),
            "loss": df["prin_loss"].fillna(0).astype(float).tolist(),
            "prepbal": df["vol_prepay"].fillna(0).astype(float).tolist(),
            "defbal": df["new_def"].fillna(0).astype(float).tolist(),
            "recovery": df["prin_recov"].fillna(0).astype(float).tolist(),
            "principal_sched": df["act_am"].fillna(0).astype(float).tolist(),
            "principal_unsched": df["vol_prepay"].fillna(0).astype(float).tolist(),
            "cpr": [0.0] * n,
            "cdr": [0.0] * n,
            "sev": [0.0] * n,
            "dq": [0.0] * n,
            "surv_fac": [1.0] * n,
            "sched_coupon": [0.0] * n,
            "sched_netcoupon": [0.0] * n,
            "coupon": gross_rate.tolist(),
            "effcoupon": gross_rate.tolist(),
            "sched_balance": df["perf_bal"].astype(float).tolist(),
            "discount_factor": [1.0] * n,
        }
    }


DEAL_CONFIGS = {
    "ldcma3class2016": {
        "ldcma_subdir": "Deals_lib",
        "ldcma_file": "LDCMA3CLASS2016.py",
        "bma_factory": ldcma_3class_2016,
        "loan_count": 5000,
    },
    "jumbo17": {
        "ldcma_subdir": "Deals_lib",
        "ldcma_file": "JUMBO17.py",
        "bma_factory": jumbo_sequential,
        "loan_count": 5000,
    },
    "passthru": {
        "ldcma_subdir": "deal",
        "ldcma_file": "Passthru.py",
        "bma_factory": passthrough_deal,
        "loan_count": 5000,
    },
}


def _run_ldcma_deal(
    deal_name: str,
    collcf: dict[str, dict[str, list[float]]],
    ldcma_root: str,
):
    from ldcma.deal.deal import Deal  # type: ignore

    cfg = DEAL_CONFIGS[deal_name]
    ldcma_collcf: dict[str, dict[str, Any]] = {}
    for gname, payload in collcf.items():
        group: dict[str, Any] = {}
        for key, value in payload.items():
            if key == "cfdate":
                group[key] = value
            else:
                group[key] = np.array(value, dtype=float)
        ldcma_collcf[gname] = group

    ld_file = os.path.join(ldcma_root, "LDCMA", "ldcma", cfg["ldcma_subdir"], cfg["ldcma_file"])
    req = SimpleNamespace(cusip=f"PARITY_{deal_name}", dealstructure=ld_file, dealknob={}, marketdate=None)
    ld_deal = Deal(req)
    ld_deal.loancount = cfg["loan_count"]
    ld_deal.rundeal(ldcma_collcf)

    ld_rows = []
    for bname, bond in ld_deal.bonds.items():
        bcf = bond.getbondCFdict(ldcma_collcf)
        bdf = pd.DataFrame(bcf)
        if "period" not in bdf.columns:
            bdf["period"] = range(len(bdf))
        bdf["Bond"] = bname
        ld_rows.append(
            bdf[
                [
                    "Bond",
                    "period",
                    "balance",
                    "principal",
                    "interest",
                    "intshortfall",
                    "cashflow",
                    "writedown",
                    "coupon",
                ]
            ]
        )
    return pd.concat(ld_rows, ignore_index=True).rename(
        columns={
            "Bond": "tranche_id",
            "balance": "end_balance",
            "principal": "total_principal",
            "interest": "interest_paid",
            "intshortfall": "interest_shortfall",
            "cashflow": "cashflow_total",
            "coupon": "coupon_rate",
        }
    )


def _run_bma_deal(
    deal_name: str,
    collcf: dict[str, dict[str, list[float]]],
):
    cfg = DEAL_CONFIGS[deal_name]
    n = len(collcf["COLLAT"]["balance"])
    bma_collcf = {k: (v if k != "cfdate" else list(range(n))) for k, v in collcf["COLLAT"].items()}
    bma_input = from_collateral_dict({"COLLAT": bma_collcf}, loan_count=cfg["loan_count"])
    bma_out = run_deal(cfg["bma_factory"](), bma_input)
    return pd.DataFrame(
        [
            {
                "tranche_id": r.tranche_id,
                "period": r.period,
                "end_balance": r.end_balance,
                "total_principal": r.total_principal,
                "interest_paid": r.interest_paid,
                "interest_shortfall": r.interest_shortfall,
                "cashflow_total": r.cashflow_total,
                "writedown": r.writedown,
                "coupon_rate": r.coupon_rate,
            }
            for r in bma_out.bond_cashflows
        ]
    )


def _compare_frames(
    ld_df: pd.DataFrame,
    bma_df: pd.DataFrame,
):
    fields = [
        "end_balance",
        "total_principal",
        "interest_paid",
        "interest_shortfall",
        "cashflow_total",
        "writedown",
        "coupon_rate",
    ]
    merged = ld_df[ld_df["period"] > 0].merge(
        bma_df[bma_df["period"] > 0],
        on=["tranche_id", "period"],
        suffixes=("_ldcma", "_bma"),
    )
    summary_rows = []
    for field in fields:
        diff = (merged[f"{field}_bma"] - merged[f"{field}_ldcma"]).astype(float)
        denom = np.maximum(np.abs(merged[f"{field}_ldcma"].astype(float)), 1.0)
        rel = np.abs(diff) / denom
        summary_rows.append(
            {
                "field": field,
                "rows": int(len(diff)),
                "max_abs": float(np.max(np.abs(diff))) if len(diff) else 0.0,
                "mean_abs": float(np.mean(np.abs(diff))) if len(diff) else 0.0,
                "max_rel": float(np.max(rel)) if len(rel) else 0.0,
                "mean_rel": float(np.mean(rel)) if len(rel) else 0.0,
            }
        )
    return merged, pd.DataFrame(summary_rows)


def run_parity(
    portfolio_run_id: str,
    ldcma_root: str,
    output_dir: str,
    deal: str,
) -> str:
    _patch_quantlib_if_needed()
    sys.path.insert(0, os.path.join(ldcma_root, "LDCommon"))
    sys.path.insert(0, os.path.join(ldcma_root, "LDCMA"))

    portfolio_df = run_store.load_artifact(portfolio_run_id, "Base_Case_portfolio_actual")
    collcf = _build_collcf_from_portfolio_df(portfolio_df)
    selected = list(DEAL_CONFIGS.keys()) if deal == "all" else [deal]

    os.makedirs(output_dir, exist_ok=True)
    matrix_rows = []
    for deal_name in selected:
        ld_df = _run_ldcma_deal(deal_name, collcf, ldcma_root)
        bma_df = _run_bma_deal(deal_name, collcf)
        merged, summary_df = _compare_frames(ld_df, bma_df)
        deal_dir = os.path.join(output_dir, deal_name)
        os.makedirs(deal_dir, exist_ok=True)
        merged.to_parquet(os.path.join(deal_dir, "row_level_merged.parquet"), index=False)
        summary_df.to_csv(os.path.join(deal_dir, "field_summary.csv"), index=False)
        matrix_rows.append(
            {
                "deal": deal_name,
                "max_abs_any_field": float(summary_df["max_abs"].max()) if not summary_df.empty else 0.0,
                "mean_abs_any_field": float(summary_df["mean_abs"].mean()) if not summary_df.empty else 0.0,
            }
        )
    pd.DataFrame(matrix_rows).to_csv(os.path.join(output_dir, "parity_matrix.csv"), index=False)
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LDCMA-vs-BMA parity comparison.")
    parser.add_argument("--portfolio-run-id", required=True, help="Run id with Base_Case_portfolio_actual artifact.")
    parser.add_argument("--ldcma-root", default=os.path.expanduser("~/Developer/LDCMA"), help="Path to local LDCMA monorepo root.")
    parser.add_argument(
        "--deal",
        default="ldcma3class2016",
        choices=["ldcma3class2016", "jumbo17", "passthru", "all"],
        help="Which deal to run parity for.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.abspath("tmp_ldcma_bma_parity"),
        help="Directory to write parity artifacts.",
    )
    args = parser.parse_args()
    out = run_parity(args.portfolio_run_id, args.ldcma_root, args.output_dir, args.deal)
    print(f"Parity artifacts written to: {out}")


if __name__ == "__main__":
    main()
