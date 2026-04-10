from __future__ import annotations

from fastapi.testclient import TestClient

from bma_cfengine_app.api.main import app
from bma_standard_formulas.deals.schemas.input import DealRunInput


def _minimal_run_input() -> DealRunInput:
    return DealRunInput.model_validate(
        {
            "collateral": {
                "mode": "POOLED",
                "collateral": {
                    "cfdate": [0, 1],
                    "balance": [100.0, 90.0],
                    "principal": [0.0, 10.0],
                    "interest": [0.0, 1.0],
                    "cashflow": [0.0, 11.0],
                    "loss": [0.0, 0.0],
                    "prepbal": [0.0, 0.0],
                    "defbal": [0.0, 0.0],
                    "recovery": [0.0, 0.0],
                    "principal_sched": [0.0, 10.0],
                    "principal_unsched": [0.0, 0.0],
                    "cpr": [0.0, 0.0],
                    "cdr": [0.0, 0.0],
                    "sev": [0.0, 0.0],
                    "dq": [0.0, 0.0],
                    "surv_fac": [1.0, 1.0],
                    "sched_coupon": [6.0, 6.0],
                    "sched_netcoupon": [5.0, 5.0],
                    "coupon": [6.0, 6.0],
                    "effcoupon": [6.0, 6.0],
                    "sched_balance": [100.0, 90.0],
                    "discount_factor": [1.0, 1.0],
                },
            }
        }
    )


def test_post_deal_run_contract(monkeypatch):
    from bma_cfengine_app.api.routers import deals as deals_router

    monkeypatch.setattr(deals_router, "_ensure_canonical_deal", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        deals_router,
        "_build_inputs",
        lambda source, scenario_names: {"Base Case": _minimal_run_input()},
    )
    monkeypatch.setattr(deals_router.run_store, "new_run_id", lambda: "run_contract")
    monkeypatch.setattr(
        deals_router,
        "execute_deal_run",
        lambda **kwargs: {"status": "completed", "deal_id": "deal_x", "scenario_names": ["Base Case"]},
    )

    client = TestClient(app)
    res = client.post(
        "/api/deals/deal_x/runs",
        json={
            "source": {"source_mode": "runsetup_ref", "run_id": "run_seed"},
            "scenario_names": ["Base Case"],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["run_id"] == "run_contract"
    assert body["status"] == "completed"
    assert body["deal_id"] == "deal_x"


def test_post_deal_solve_contract(monkeypatch):
    from bma_cfengine_app.api.routers import deals as deals_router

    monkeypatch.setattr(deals_router, "_ensure_canonical_deal", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        deals_router,
        "_build_inputs",
        lambda source, scenario_names: {"Base Case": _minimal_run_input()},
    )
    monkeypatch.setattr(deals_router.run_store, "new_run_id", lambda: "run_solver")
    monkeypatch.setattr(
        deals_router,
        "execute_deal_solve",
        lambda **kwargs: {"status": "completed", "deal_id": "deal_x", "scenario_names": ["Base Case"]},
    )

    client = TestClient(app)
    res = client.post(
        "/api/deals/deal_x/solve",
        json={
            "source": {"source_mode": "runsetup_ref", "run_id": "run_seed"},
            "scenario_name": "Base Case",
            "solver_spec": {
                "solver_name": "s1",
                "layers": [
                    {
                        "layer_name": "l1",
                        "objectives": [
                            {
                                "name": "o1",
                                "metric_path": "tranche_risk_summary[A].yield_pct",
                                "objective_type": "TARGET",
                                "target_value": 6.0,
                                "weight": 1.0,
                            }
                        ],
                        "constraints": [],
                        "knobs": [
                            {"knob_path": "deal_knobs.class_a_coupon", "lower": 3.0, "upper": 9.0}
                        ],
                    }
                ],
            },
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["run_id"] == "run_solver"
    assert body["status"] == "completed"
