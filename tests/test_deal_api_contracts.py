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
    monkeypatch.setattr(deals_router, "_verify_or_raise", lambda *args, **kwargs: {"valid": True})
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
    monkeypatch.setattr(deals_router, "_verify_or_raise", lambda *args, **kwargs: {"valid": True})
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
    assert body["status"] == "running"
    assert body["progress_handle"]["run_id"] == "run_solver"


def test_list_solver_runs_contract(monkeypatch):
    from bma_cfengine_app.api.routers import deals as deals_router

    monkeypatch.setattr(
        deals_router,
        "list_all_runs",
        lambda: [
            {"run_id": "run_1", "deal_id": "deal_x", "run_type": "structured_deal", "run_kind": "solver"},
            {"run_id": "run_2", "deal_id": "deal_x", "run_type": "structured_deal", "run_kind": "deal_run"},
        ],
    )
    client = TestClient(app)
    res = client.get("/api/deals/deal_x/solver-runs")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["run_kind"] == "solver"


def test_solver_catalog_contract(monkeypatch):
    from bma_cfengine_app.api.routers import deals as deals_router

    monkeypatch.setattr(deals_router, "_ensure_canonical_deal", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        deals_router,
        "build_solver_catalog",
        lambda deal_id, canonical_deal: {
            "deal_id": deal_id,
            "metric_paths": ["tranche_risk_summary[A].yield_pct"],
            "knobs": [{"knob_path": "deal_knobs.class_a_coupon"}],
            "typed_enums": {
                "objective_types": ["TARGET", "MINIMIZE", "MAXIMIZE"],
                "constraint_comparisons": ["GE", "LE", "EQ", "BETWEEN"],
                "waterfall_target_primitives": [
                    "CUM_LOSS_MULTIPLE_GAP",
                    "NO_SHORTFALL_INTEREST",
                    "PAC_SCHEDULE_MISS",
                ],
            },
            "template_families": [
                {
                    "family": "PRIME_JUMBO",
                    "targets": ["CUM_LOSS_MULTIPLE_GAP"],
                },
                {"family": "AGENCY", "targets": ["PAC_SCHEDULE_MISS"]},
            ],
            "suggested_defaults": {"solver_name": "studio_solver"},
            "source_run_id": "run_abc",
        },
    )
    client = TestClient(app)
    res = client.get("/api/deals/deal_x/solver-catalog")
    assert res.status_code == 200
    body = res.json()
    assert body["deal_id"] == "deal_x"
    assert body["source_run_id"] == "run_abc"
    assert "typed_enums" in body


def test_verify_structure_contract(monkeypatch):
    from bma_cfengine_app.api.routers import deals as deals_router

    monkeypatch.setattr(deals_router, "_ensure_canonical_deal", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        deals_router,
        "verify_structure",
        lambda deal, scenario_context=None: {
            "valid": False,
            "errors": ["A: PAC requires schedule contract points."],
            "warnings": ["A: schedule_tolerance_bps not set."],
            "suggestions": ["Add schedule points for A."],
        },
    )
    client = TestClient(app)
    res = client.post("/api/deals/deal_x/verify-structure?version=2")
    assert res.status_code == 200
    body = res.json()
    assert body["valid"] is False
    assert body["errors"]


def test_run_and_solve_blocked_when_verification_fails(monkeypatch):
    from bma_cfengine_app.api.routers import deals as deals_router

    monkeypatch.setattr(deals_router, "_ensure_canonical_deal", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        deals_router,
        "_verify_or_raise",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            deals_router.HTTPException(
                status_code=422,
                detail={
                    "message": "Structuring verification failed.",
                    "verification": {"valid": False, "errors": ["bad"], "warnings": [], "suggestions": []},
                },
            )
        ),
    )
    client = TestClient(app)
    run_res = client.post(
        "/api/deals/deal_x/runs",
        json={"source": {"source_mode": "runsetup_ref", "run_id": "run_seed"}},
    )
    assert run_res.status_code == 422
    solve_res = client.post(
        "/api/deals/deal_x/solve",
        json={
            "source": {"source_mode": "runsetup_ref", "run_id": "run_seed"},
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
                        "knobs": [{"knob_path": "deal_knobs.class_a_coupon", "lower": 3.0, "upper": 9.0}],
                    }
                ],
            },
        },
    )
    assert solve_res.status_code == 422


def test_solver_presets_contract(monkeypatch):
    from bma_cfengine_app.api.routers import deals as deals_router

    monkeypatch.setattr(
        deals_router,
        "list_solver_presets",
        lambda deal_id: [{"preset_name": "balanced", "solver_spec": {"solver_name": "s1"}}],
    )
    monkeypatch.setattr(
        deals_router,
        "save_solver_preset",
        lambda deal_id, preset_name, solver_spec, notes=None: {
            "preset_name": preset_name,
            "solver_spec": solver_spec,
            "notes": notes or "",
            "created_at": "t1",
            "updated_at": "t1",
        },
    )
    client = TestClient(app)
    get_res = client.get("/api/deals/deal_x/solver-presets")
    assert get_res.status_code == 200
    assert get_res.json()["presets"][0]["preset_name"] == "balanced"

    post_res = client.post(
        "/api/deals/deal_x/solver-presets",
        json={"preset_name": "balanced", "solver_spec": {"solver_name": "s1"}},
    )
    assert post_res.status_code == 200
    assert post_res.json()["preset"]["preset_name"] == "balanced"


def test_deal_run_sources_query_contract(monkeypatch):
    from bma_cfengine_app.api.routers import deals as deals_router

    monkeypatch.setattr(
        deals_router,
        "list_all_runs",
        lambda: [
            {
                "run_id": "run_1",
                "deal_id": "deal_x",
                "deal_name": "Deal X",
                "run_type": "structured_deal",
                "run_kind": "solver",
                "status": "completed",
                "scenario_names": ["Base Case"],
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "run_id": "run_2",
                "deal_id": "deal_x",
                "deal_name": "Deal X",
                "run_type": "structured_deal",
                "run_kind": "deal_run",
                "status": "failed",
                "scenario_names": ["Stress"],
                "created_at": "2025-01-01T00:00:00Z",
            },
        ],
    )
    client = TestClient(app)
    res = client.get(
        "/api/deals/deal_x/run-sources?status=completed&run_type=structured_deal&run_kind=solver&search=base&limit=10&cursor=0"
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["run_id"] == "run_1"


def test_solver_progress_and_cancel_contract(monkeypatch):
    from bma_cfengine_app.api.routers import deals as deals_router

    monkeypatch.setattr(
        deals_router,
        "get_solver_progress",
        lambda run_id: {
            "run_id": run_id,
            "deal_id": "deal_x",
            "status": "running",
            "stage": "optimizing",
            "iteration": 3,
            "cancel_requested": False,
            "diagnostic_artifacts": ["Base_Case_solver_ce_ladder"],
        },
    )
    monkeypatch.setattr(
        deals_router,
        "request_solver_cancel",
        lambda run_id: {
            "run_id": run_id,
            "deal_id": "deal_x",
            "status": "running",
            "cancel_requested": True,
        },
    )
    client = TestClient(app)
    progress_res = client.get("/api/deals/deal_x/runs/run_solver/progress")
    assert progress_res.status_code == 200
    assert progress_res.json()["iteration"] == 3
    assert progress_res.json()["diagnostic_artifacts"] == ["Base_Case_solver_ce_ladder"]

    cancel_res = client.post("/api/deals/deal_x/runs/run_solver/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["cancel_requested"] is True


def test_pool_snapshot_contract(monkeypatch):
    from bma_cfengine_app.api.routers import deals as deals_router

    monkeypatch.setattr(
        deals_router,
        "list_pool_snapshots",
        lambda search=None: [
            {
                "pool_id": "pool_abc",
                "pool_name": "Prime Jumbo",
                "current_version": 3,
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(
        deals_router,
        "load_pool_snapshot",
        lambda pool_id, version=None: {
            "pool_id": pool_id,
            "pool_name": "Prime Jumbo",
            "version": version or 3,
            "payload": {"tapeId": "upload_1"},
        },
    )
    monkeypatch.setattr(
        deals_router,
        "save_pool_snapshot",
        lambda pool_id, pool_name, payload: (
            pool_id or "pool_new",
            {
                "pool_id": pool_id or "pool_new",
                "pool_name": pool_name,
                "version": 1,
                "saved_at": "2026-01-01T00:00:00Z",
            },
        ),
    )

    client = TestClient(app)

    list_res = client.get("/api/deals/pools?search=prime")
    assert list_res.status_code == 200
    assert list_res.json()["items"][0]["pool_id"] == "pool_abc"

    get_res = client.get("/api/deals/pools/pool_abc?version=2")
    assert get_res.status_code == 200
    assert get_res.json()["version"] == 2

    post_res = client.post(
        "/api/deals/pools",
        json={"pool_name": "Prime Jumbo", "payload": {"tapeId": "upload_1"}},
    )
    assert post_res.status_code == 200
    assert post_res.json()["pool_id"] == "pool_new"


def test_ensure_canonical_deal_normalizes_legacy_enums(monkeypatch):
    from bma_cfengine_app.api.routers import deals as deals_router

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        deals_router,
        "load_deal",
        lambda deal_id, version=None: (_ for _ in ()).throw(FileNotFoundError("missing canonical")),
    )
    monkeypatch.setattr(
        deals_router,
        "load_studio_snapshot",
        lambda deal_id, version=None: {
            "ir": {
                "schema_version": "1.0.0",
                "deal_name": "Legacy Deal",
                "bonds": [
                    {
                        "name": "A",
                        "tranche_type": "SEQUENTIAL",
                        "coupon_type": "FIXED",
                        "coupon": 5.0,
                        "size_dollars": 100.0,
                    }
                ],
                "accounts": [],
                "fees": [
                    {"name": "SERVICER", "basis_type": "PCT_POOL", "amount": 0.0, "bps": 25.0}
                ],
                "triggers": [
                    {"name": "CumLoss", "metric_type": "CUM_LOSS", "threshold_value": 0.05}
                ],
                "waterfall_rules": [
                    {
                        "rule_id": "rule_1",
                        "rule_type": "PAY_INTEREST",
                        "order": 0,
                        "from_sources": ["COLLECTION"],
                        "to_targets": ["A"],
                        "payment_style": "SEQUENTIAL",
                    }
                ],
                "deal_knobs": {},
            }
        },
    )
    monkeypatch.setattr(
        deals_router,
        "save_canonical_deal",
        lambda deal_id, canonical, version=None: captured.update({"deal_id": deal_id, "canonical": canonical}),
    )

    canonical = deals_router._ensure_canonical_deal("deal_legacy")
    assert canonical.fees[0].basis_type.value == "COLLATERAL_BALANCE"
    assert canonical.fees[0].rate == 0.25
    assert canonical.triggers[0].metric_type.value == "CUMULATIVE_LOSS"
    assert canonical.waterfall_rules[0].from_sources == ["CASH"]
    assert captured["deal_id"] == "deal_legacy"
