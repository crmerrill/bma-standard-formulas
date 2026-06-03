"""Seed the FNR 2006-018 fixture deal into the local app workspace.

After running this, the Structuring Studio UI will list the deal under
"Open Deal" and the Structured Deal Analysis page will be able to run
it against the pre-seeded portfolio runs at 100/147/250/500% PSA.

The seeded objects are:

  - Synthesized loan tape ``upl_fnr2006018`` with ~1180 representative
    loans split between Group 1 (132.65MM, WAC 5.94%, 360-term) and
    Group 2 (128.625MM, WAC 5.94%, 240-term). Pool stats tie out
    exactly to the prospectus.
  - Auto-mapping ``map_fnr2006018_default`` selecting all canonical
    fields directly (the tape uses canonical column names).
  - Combined deal ``deal_fnr_2006_018`` covering both Group 1 and
    Group 2 in one DealDefinition with `collateral_groups` declared.
  - Per-PSA portfolio runs (one per group) so the deal can replay
    against pre-computed Group 1 + Group 2 cashflows.

Usage::

    python scripts/seed_fnr_2006_018.py
    python scripts/seed_fnr_2006_018.py --psa-speeds 100 147 250 500

The seeded ids are deterministic; re-running bumps the deal version
without churning the upload/run ids.
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
)
from bma_cfengine_app.storage import run_store  # noqa: E402

from tests.fixtures.fnr_2006_018 import (  # noqa: E402
    GROUP_2_POOL_ASSUMPTIONS,
    GROUP_2_REPLINE,
    POOL_ASSUMPTIONS,
)
from tests.fixtures.fnr_2006_018.deal_definition import (  # noqa: E402
    build_fnr_2006_018_combined_deal,
)
from tests.fixtures.fnr_2006_018.tape import (  # noqa: E402
    synthesize_tape_csv,
    synthesize_tape_dataframe,
)
from tests.test_fnr_2006_018_parity import _amortize_pool_at_psa  # noqa: E402


DEAL_ID = "deal_fnr_2006_018"
DEAL_NAME = "FNR 2006-018 (Group 1 + Group 2)"
TAPE_UPLOAD_ID = "upl_fnr2006018"
TAPE_DEFAULT_MAPPING_ID = "map_fnr2006018_default"
N_PERIODS_GROUP_1 = 360
N_PERIODS_GROUP_2 = 240
# Legacy alias kept for the portfolio-run seed function below.
N_PERIODS = N_PERIODS_GROUP_1


def _portfolio_run_id_for(psa: float, group: str = "g1") -> str:
    """Stable run id, e.g. `run_fnr2006018_g1_psa100`."""
    return f"run_fnr2006018_{group}_psa{int(round(psa)):03d}"


def seed_tape() -> dict[str, Any]:
    """Seed the synthesized FNR 2006-018 loan tape into the upload library.

    The tape carries two ``group_id`` values (GROUP_1, GROUP_2) so the
    upload viewer surfaces both pools and the deal can later route
    each loan to the right collateral group via the mapping system.
    Re-running overwrites the file (deterministic content) and
    refreshes the metadata timestamp.
    """
    csv_text = synthesize_tape_csv()
    run_store.save_upload(
        upload_id=TAPE_UPLOAD_ID,
        file_name="FNR_2006_018_tape.csv",
        content=csv_text.encode("utf-8"),
        display_name="FNR 2006-018 (synthesized)",
    )
    # Save a working copy in parquet too so the tape viewer's typed
    # path reads the same data (the upload library prefers parquet
    # when present).
    df = synthesize_tape_dataframe()
    run_store.save_working_copy(TAPE_UPLOAD_ID, df)

    # Auto-mapping: every column in the synthesized tape is named
    # exactly as its canonical TapeSchema field, so source==canonical
    # for each entry. This produces a 1:1 mapping that the Tape Intake
    # auto-bind step can use without manual intervention.
    canonical_fields = list(df.columns)
    mapping_payload = {
        "mappings": [
            {"source_column": col, "canonical_field": col}
            for col in canonical_fields
        ],
        "asof_date": "2006-02-01",
    }
    run_store.save_mapping(
        upload_id=TAPE_UPLOAD_ID,
        mapping_id=TAPE_DEFAULT_MAPPING_ID,
        mapping_data=mapping_payload,
    )
    return {
        "upload_id": TAPE_UPLOAD_ID,
        "mapping_id": TAPE_DEFAULT_MAPPING_ID,
        "row_count": int(len(df)),
        "groups": {
            "GROUP_1": int((df["group_id"] == "GROUP_1").sum()),
            "GROUP_2": int((df["group_id"] == "GROUP_2").sum()),
        },
        "total_balance": float(df["current_balance"].sum()),
    }


def _build_portfolio_actual_artifact(
    psa_speed: float,
    *,
    group: str = "g1",
) -> pd.DataFrame:
    """Generate the pool cashflow artifact in the schema produced by Run Setup.

    The Structuring Studio's collateral bridge (`build_from_runsetup_ref`)
    reads `Base_Case_portfolio_actual.parquet` and converts it to a
    `DealRunInput`. We mirror that schema here so the deal can replay
    against these seeded portfolio runs. ``group`` selects between
    ``"g1"`` (Group 1: $132.65MM, 30-yr aggregate) and ``"g2"``
    (Group 2: $128.625MM, 20-yr repline).
    """
    if group == "g2":
        initial_balance = float(GROUP_2_POOL_ASSUMPTIONS["aggregate_upb_dollars"])
        wac_pct = float(GROUP_2_REPLINE["wac_pct"])
        net_pct = float(GROUP_2_POOL_ASSUMPTIONS["mbs_pass_through_rate_pct"])
        term = int(GROUP_2_REPLINE["original_term_months"])
        remaining = int(GROUP_2_REPLINE["remaining_term_months"])
        n_periods = N_PERIODS_GROUP_2
    else:
        initial_balance = float(POOL_ASSUMPTIONS["aggregate_upb_dollars"])
        wac_pct = float(POOL_ASSUMPTIONS["weighted_average_coupon_pct"])
        net_pct = float(POOL_ASSUMPTIONS["mbs_pass_through_rate_pct"])
        term = int(POOL_ASSUMPTIONS["original_term_months"])
        remaining = int(POOL_ASSUMPTIONS["weighted_average_remaining_term_months"])
        n_periods = N_PERIODS_GROUP_1

    bal, sched_prin, vol_prepay = _amortize_pool_at_psa(
        initial_balance, wac_pct, term, remaining, psa_speed, n_periods
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


def seed_portfolio_run(psa_speed: float, *, group: str = "g1") -> str:
    """Persist a portfolio run artifact + manifest for one PSA speed and group.

    ``group`` is ``"g1"`` (Group 1) or ``"g2"`` (Group 2). One run is
    seeded per (group, PSA) combination so the combined deal run-time
    can pull both groups' cashflows.
    """
    if group == "g2":
        upb = float(GROUP_2_POOL_ASSUMPTIONS["aggregate_upb_dollars"])
        wac = float(GROUP_2_REPLINE["wac_pct"])
        wam = int(GROUP_2_REPLINE["remaining_term_months"])
        label = f"FNR 2006-018 Group 2 @ {int(psa_speed)}% PSA"
    else:
        upb = float(POOL_ASSUMPTIONS["aggregate_upb_dollars"])
        wac = float(POOL_ASSUMPTIONS["weighted_average_coupon_pct"])
        wam = int(POOL_ASSUMPTIONS["weighted_average_remaining_term_months"])
        label = f"FNR 2006-018 Group 1 @ {int(psa_speed)}% PSA"
    run_id = _portfolio_run_id_for(psa_speed, group=group)
    manifest = {
        "status": "completed",
        "run_type": "portfolio",
        "run_kind": "deal_run_seed",
        "run_id": run_id,
        "scenario_names": ["Base Case"],
        "loan_count": int(upb / 200_000.0),
        "total_balance": upb,
        "wac": wac,
        "wam": wam,
        "elapsed_seconds": 0.0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "label": label,
            "psa_speed": float(psa_speed),
            "group": group.upper(),
        },
    }
    run_store.save_manifest(run_id, manifest)
    df = _build_portfolio_actual_artifact(psa_speed, group=group)
    run_store.save_artifact(run_id, "Base_Case_portfolio_actual", df)
    run_store.save_artifact_csv(run_id, "Base_Case_portfolio_actual", df)
    return run_id


def seed_deal(
    default_source_run_id: str,
    *,
    tape_upload_id: str = TAPE_UPLOAD_ID,
    tape_mapping_id: str = TAPE_DEFAULT_MAPPING_ID,
) -> dict[str, Any]:
    deal = build_fnr_2006_018_combined_deal(
        n_periods_group_1=N_PERIODS_GROUP_1,
        n_periods_group_2=N_PERIODS_GROUP_2,
    )
    payload = json.loads(deal.model_dump_json())
    payload["solver_presets"] = {
        "source_mode": "runsetup_ref",
        "runsetup_ref_run_id": default_source_run_id,
        "scenario_set": ["Base Case"],
        "source_scenario_name": "Base Case",
        "collateral_risk_settings": {
            "productFamily": "AGENCY",
            "tapeId": tape_upload_id,
            "tapeMappingId": tape_mapping_id,
            "poolId": None,
            "poolName": "FNR 2006-018 Pool (Group 1 + Group 2)",
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
    return {"canonical": canonical_meta}


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

    tape_meta = seed_tape()

    seeded_runs: list[tuple[float, str, str]] = []
    for psa in args.psa_speeds:
        seeded_runs.append((psa, "g1", seed_portfolio_run(psa, group="g1")))
        seeded_runs.append((psa, "g2", seed_portfolio_run(psa, group="g2")))
    default_run_id = seeded_runs[0][2] if seeded_runs else ""

    deal_meta = seed_deal(default_source_run_id=default_run_id)

    print("Seeded synthesized loan tape:")
    print(f"  upload_id: {tape_meta['upload_id']}  ({tape_meta['row_count']} loans)")
    print(f"  mapping_id: {tape_meta['mapping_id']}")
    print(
        f"  GROUP_1: {tape_meta['groups']['GROUP_1']} loans, "
        f"GROUP_2: {tape_meta['groups']['GROUP_2']} loans, "
        f"total UPB: ${tape_meta['total_balance']:,.0f}"
    )
    print()
    print("Seeded portfolio runs (one per group + PSA speed):")
    for psa, group, run_id in seeded_runs:
        label = "Group 1" if group == "g1" else "Group 2"
        print(f"  {run_id}: FNR 2006-018 {label} @ {int(psa)}% PSA")
    print()
    print(f"Seeded combined deal: {DEAL_ID}  ({DEAL_NAME})")
    print(f"  Canonical version: {deal_meta['canonical'].get('version')}")
    print(f"  Studio version: {deal_meta['studio'].get('version')}")
    print()
    print("Open the Structuring Studio UI; the deal will be available under")
    print("'Open Deal' with the synthesized tape pre-bound and the default")
    print("source pointing at the Group 1 / 100% PSA portfolio run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
