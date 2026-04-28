"""Seed the FNR 2006-018 fixture deal into the local app workspace.

After running this, the Structuring Studio UI will list the deal under
"Open Deal" and the Structured Deal Analysis page will be able to run it
against the pre-seeded portfolio runs at 100/147/250/500% PSA.

Usage::

    python scripts/seed_fnr_2006_018.py
    python scripts/seed_fnr_2006_018.py --psa-speeds 100 147 250 500

The seeded deal id is `deal_fnr_2006_018`. Re-running this script bumps the
deal version. The portfolio runs are seeded under deterministic ids so they
are stable across re-runs.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Make src/ importable when running from the repo root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))  # for tests/ namespace

from bma_cfengine_app.orchestrator.deals.deal_store import (  # noqa: E402
    save_deal,
    save_studio_ir,
)
from bma_cfengine_app.storage import run_store  # noqa: E402

from tests.fixtures.fnr_2006_018 import POOL_ASSUMPTIONS  # noqa: E402
from tests.fixtures.fnr_2006_018.deal_definition import (  # noqa: E402
    build_fnr_2006_018_group_1_deal,
)
from tests.test_fnr_2006_018_parity import _amortize_pool_at_psa  # noqa: E402


DEAL_ID = "deal_fnr_2006_018"
DEAL_NAME = "FNR 2006-018 Group 1 (PAC + Z + Support)"
N_PERIODS = 360


def _portfolio_run_id_for(psa: float) -> str:
    """Stable run id like `run_fnr2006018_psa100`."""
    return f"run_fnr2006018_psa{int(round(psa)):03d}"


def _build_portfolio_actual_artifact(psa_speed: float) -> pd.DataFrame:
    """Generate the pool cashflow artifact in the schema produced by Run Setup.

    The Structuring Studio's collateral bridge (`build_from_runsetup_ref`)
    reads `Base_Case_portfolio_actual.parquet` and converts it to a
    `DealRunInput`. We mirror that schema here so the deal can replay against
    these seeded portfolio runs.
    """
    initial_balance = float(POOL_ASSUMPTIONS["aggregate_upb_dollars"])
    wac_pct = float(POOL_ASSUMPTIONS["weighted_average_coupon_pct"])
    net_pct = float(POOL_ASSUMPTIONS["mbs_pass_through_rate_pct"])
    term = int(POOL_ASSUMPTIONS["original_term_months"])
    remaining = int(POOL_ASSUMPTIONS["weighted_average_remaining_term_months"])

    bal, sched_prin, vol_prepay = _amortize_pool_at_psa(
        initial_balance, wac_pct, term, remaining, psa_speed, N_PERIODS
    )
    horizon = len(bal)
    principal = sched_prin + vol_prepay
    net_monthly_rate = net_pct / 1200.0
    interest_net = np.zeros(horizon)
    for i in range(1, horizon):
        interest_net[i] = bal[i - 1] * net_monthly_rate

    return pd.DataFrame({
        "period": np.arange(horizon),
        "perf_bal": bal,
        "new_def": np.zeros(horizon),
        "fcl": np.zeros(horizon),
        "sch_am": sched_prin,
        "exp_am": sched_prin,
        "vol_prepay": vol_prepay,
        "am_def": np.zeros(horizon),
        "act_am": sched_prin,
        "exp_int": interest_net,
        "lost_int": np.zeros(horizon),
        "act_int": interest_net,
        "prin_recov": np.zeros(horizon),
        "prin_loss": np.zeros(horizon),
        "adb": np.zeros(horizon),
        "svc_billed": np.zeros(horizon),
        "adv_prin": np.zeros(horizon),
        "adv_int": np.zeros(horizon),
        "adv_reimbursed_prin": np.zeros(horizon),
        "adv_reimbursed_int": np.zeros(horizon),
        # Deal runtime adapter expects these aggregated fields too.
        "principal": principal,
        "interest": interest_net,
        "cashflow": principal + interest_net,
        "loss": np.zeros(horizon),
        "balance": bal,
    })


def seed_portfolio_run(psa_speed: float) -> str:
    """Persist a portfolio run artifact + manifest for the given PSA speed."""
    run_id = _portfolio_run_id_for(psa_speed)
    manifest = {
        "status": "completed",
        "run_type": "portfolio",
        "run_kind": "deal_run_seed",
        "run_id": run_id,
        "scenario_names": ["Base Case"],
        "loan_count": int(POOL_ASSUMPTIONS["aggregate_upb_dollars"] / 200_000.0),
        "total_balance": float(POOL_ASSUMPTIONS["aggregate_upb_dollars"]),
        "wac": float(POOL_ASSUMPTIONS["weighted_average_coupon_pct"]),
        "wam": int(POOL_ASSUMPTIONS["weighted_average_remaining_term_months"]),
        "elapsed_seconds": 0.0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "label": f"FNR 2006-018 pool @ {int(psa_speed)}% PSA",
            "psa_speed": float(psa_speed),
        },
    }
    run_store.save_manifest(run_id, manifest)
    df = _build_portfolio_actual_artifact(psa_speed)
    run_store.save_artifact(run_id, "Base_Case_portfolio_actual", df)
    run_store.save_artifact_csv(run_id, "Base_Case_portfolio_actual", df)
    return run_id


def seed_deal(default_source_run_id: str) -> dict[str, Any]:
    deal = build_fnr_2006_018_group_1_deal(n_periods=N_PERIODS)
    payload = json.loads(deal.model_dump_json())
    payload["solver_presets"] = {
        "source_mode": "runsetup_ref",
        "runsetup_ref_run_id": default_source_run_id,
        "scenario_set": ["Base Case"],
        "source_scenario_name": "Base Case",
        "collateral_risk_settings": {
            "productFamily": "AGENCY",
            "tapeId": None,
            "tapeMappingId": None,
            "poolId": None,
            "poolName": "FNR 2006-018 Pool (Group 1 MBS)",
            "poolVersion": None,
            "riskSourceMode": "existing",
            "existingRiskRunId": default_source_run_id,
            "newRiskParams": {
                "cpr": 0,
                "cdr": 0,
                "severity": 0,
                "horizonMonths": 360,
            },
            "rateScenario": {
                "scenarioName": "Base",
                "spreadShockBps": 0,
                "yieldShockBps": 0,
            },
            "execution": {
                "runMode": "cashflow",
                "artifactScope": "full",
                "compareBaselineRunId": None,
            },
            "validation": {
                "isValid": True,
                "messages": [],
            },
        },
    }
    # Save canonical (validated) snapshot first so subsequent loads do not need
    # the studio normalization step. Reset version counter for a clean re-seed.
    deal_dir = run_store.APP_HOME / "deals" / DEAL_ID
    if deal_dir.exists():
        # Wipe prior snapshots so the deal starts clean each seed run.
        for p in deal_dir.glob("*.json"):
            p.unlink()
    canonical_meta = save_deal(DEAL_ID, deal, version=1)
    studio_id, studio_meta = save_studio_ir(DEAL_ID, DEAL_NAME, payload)
    assert studio_id == DEAL_ID
    return {"canonical": canonical_meta, "studio": studio_meta}


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the FNR 2006-018 fixture deal.")
    parser.add_argument(
        "--psa-speeds",
        nargs="+",
        type=float,
        default=[100.0, 147.0, 250.0, 500.0],
        help="PSA speeds to pre-seed as portfolio runs (default: 100, 147, 250, 500).",
    )
    args = parser.parse_args()

    run_store.init_workspace()
    seeded_runs: list[tuple[float, str]] = []
    for psa in args.psa_speeds:
        run_id = seed_portfolio_run(psa)
        seeded_runs.append((psa, run_id))
    default_run_id = seeded_runs[0][1] if seeded_runs else ""

    deal_meta = seed_deal(default_source_run_id=default_run_id)

    print("Seeded portfolio runs:")
    for psa, run_id in seeded_runs:
        print(f"  {run_id}: FNR 2006-018 pool @ {int(psa)}% PSA")
    print()
    print(f"Seeded deal: {DEAL_ID}  ({DEAL_NAME})")
    print(f"  Canonical version: {deal_meta['canonical'].get('version')}")
    print(f"  Studio version: {deal_meta['studio'].get('version')}")
    print()
    print("Open the Structuring Studio UI; the deal will be available under")
    print("'Open Deal' with the default source bound to the 100% PSA run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
