"""Contract tests for the solver-template API endpoints.

These tests call the route handlers directly (as async functions) to
avoid pulling in `fastapi.testclient` -- which currently fails to load
in some dev environments due to NumPy ABI mismatches with the system
Python install. The route handlers are pure async functions that just
delegate to the orchestrator; testing them this way verifies the
contract (path parameters, response shape, error mapping) without the
ASGI plumbing.

Each handler is monkey-patched on its dependency seam (`load_deal`,
``_ensure_canonical_deal``) so we don't need a writable deals
directory. The deal IR is constructed directly from the FNR 2006-018
Group 2 fixture.
"""
from __future__ import annotations

import asyncio

import pytest

from tests.fixtures.fnr_2006_018.deal_definition import (
    build_fnr_2006_018_group_2_deal,
)


pytest.importorskip(
    "fastapi",
    reason="fastapi is not installed in this environment; "
           "API contract tests require it.",
)


# Late-imports so pytest.importorskip can run before module import errors.
from fastapi import HTTPException  # noqa: E402

from bma_cfengine_app.api.routers import deals as deals_router  # noqa: E402
from bma_standard_formulas.deals.schemas.solver_template import (  # noqa: E402
    TemplateInstantiationRequest,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def reference_deal():
    return build_fnr_2006_018_group_2_deal(n_periods=240)


@pytest.fixture
def patched_canonical_deal(monkeypatch, reference_deal):
    """Patch ``_ensure_canonical_deal`` to return the FNR Group 2 fixture.

    All template endpoints go through this seam to load and migrate the
    deal IR; replacing it with the in-memory fixture lets the tests run
    without a writable deals directory.
    """
    monkeypatch.setattr(
        deals_router,
        "_ensure_canonical_deal",
        lambda deal_id, version=None: reference_deal,
    )
    return reference_deal


# ---------------------------------------------------------------------------
# GET /deals/{deal_id}/solver-templates
# ---------------------------------------------------------------------------


class TestListSolverTemplatesEndpoint:
    def test_returns_registered_templates_with_resolved_knobs(
        self, patched_canonical_deal
    ):
        result = asyncio.run(deals_router.list_solver_templates("g2_test"))
        assert result["deal_id"] == "g2_test"
        templates = result["templates"]
        assert templates, "expected at least the auto_tieout_carry template"

        ids = [t["template"]["template_id"] for t in templates]
        assert "auto_tieout_carry" in ids

        auto = next(
            t for t in templates if t["template"]["template_id"] == "auto_tieout_carry"
        )
        # UX surface: title, summary, primary input present.
        assert auto["template"]["title"] == "Balance the deal"
        assert auto["template"]["one_line_summary"]
        assert auto["template"]["primary_input"]["field_id"] == "target_residual_yield_pct"
        assert auto["template"]["primary_button_label"] == "Find the coupons"
        # Deal-aware defaults: knobs resolved against FNR Group 2.
        knob_ids = {rk["knob_id"] for rk in auto["resolved_knobs"]}
        assert "coupon_BA" in knob_ids
        assert "coupon_BC" in knob_ids
        assert "coupon_BD" in knob_ids
        # IO and zero-coupon excluded.
        assert "coupon_DI" not in knob_ids
        assert "coupon_DO" not in knob_ids


# ---------------------------------------------------------------------------
# GET /deals/{deal_id}/solver-templates/{template_id}
# ---------------------------------------------------------------------------


class TestGetSolverTemplateEndpoint:
    def test_returns_one_template_view(self, patched_canonical_deal):
        result = asyncio.run(
            deals_router.get_solver_template("g2_test", "auto_tieout_carry")
        )
        assert result["template"]["template_id"] == "auto_tieout_carry"
        assert "resolved_knobs" in result
        assert "resolved_constraints" in result

    def test_unknown_template_raises_404(self, patched_canonical_deal):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                deals_router.get_solver_template("g2_test", "does_not_exist")
            )
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# POST /deals/{deal_id}/solver-templates/{template_id}/instantiate
# ---------------------------------------------------------------------------


class TestInstantiateTemplateEndpoint:
    def test_with_user_target_yields_runnable_solverspec(
        self, patched_canonical_deal
    ):
        request = TemplateInstantiationRequest(primary_input_value=10.0)
        response = asyncio.run(
            deals_router.instantiate_solver_template(
                "g2_test", "auto_tieout_carry", request
            )
        )
        assert response.template_id == "auto_tieout_carry"
        spec = response.spec
        assert spec.layers, "spec has no layers"
        layer = spec.layers[0]
        assert layer.knobs, "layer has no knobs"
        assert layer.objectives, "layer has no objectives"
        # User's level-1 value drove the objective target.
        assert layer.objectives[0].target_value == 10.0

    def test_with_locked_knob_removes_it_from_spec(self, patched_canonical_deal):
        request = TemplateInstantiationRequest(
            primary_input_value=12.0,
            locked_knob_ids=["coupon_BA"],
        )
        response = asyncio.run(
            deals_router.instantiate_solver_template(
                "g2_test", "auto_tieout_carry", request
            )
        )
        knob_paths = {k.knob_path for k in response.spec.layers[0].knobs}
        assert "bonds[BA].coupon" not in knob_paths
        assert "bonds[BC].coupon" in knob_paths

    def test_locking_all_knobs_returns_400(self, patched_canonical_deal):
        # Lock every cash-paying bond -> ValueError -> HTTP 400.
        all_knob_ids = ["coupon_BA", "coupon_BC", "coupon_BD"]
        request = TemplateInstantiationRequest(
            primary_input_value=12.0,
            locked_knob_ids=all_knob_ids,
        )
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                deals_router.instantiate_solver_template(
                    "g2_test", "auto_tieout_carry", request
                )
            )
        assert exc_info.value.status_code == 400
        assert "no tunable knobs" in exc_info.value.detail.lower()

    def test_unknown_template_raises_404(self, patched_canonical_deal):
        request = TemplateInstantiationRequest(primary_input_value=12.0)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                deals_router.instantiate_solver_template(
                    "g2_test", "does_not_exist", request
                )
            )
        assert exc_info.value.status_code == 404
