"""Tests for PAC/TAC schedule derivation helpers.

Exercises pool projection, PAC lower-envelope construction, and TAC single-PSA
projection. Uses small horizons so test runtime stays trivial.
"""
from __future__ import annotations

import pytest

from bma_cfengine_app.orchestrator.deals.schedule_derivation import (
    build_schedule_provenance,
    derive_pac_schedule,
    derive_tac_schedule,
    project_pool_principal,
)


class TestPoolProjection:
    def test_returns_zero_at_period_zero(self):
        principal = project_pool_principal(
            initial_balance=1_000_000.0,
            wac_pct=6.0,
            term_months=360,
            psa_speed=100.0,
            n_periods=12,
        )
        assert principal[0] == pytest.approx(0.0, abs=1e-6)

    def test_higher_psa_produces_more_early_principal(self):
        slow = project_pool_principal(
            initial_balance=1_000_000.0,
            wac_pct=6.0,
            term_months=360,
            psa_speed=100.0,
            n_periods=24,
        )
        fast = project_pool_principal(
            initial_balance=1_000_000.0,
            wac_pct=6.0,
            term_months=360,
            psa_speed=300.0,
            n_periods=24,
        )
        # Cumulative principal in first 12 months should be higher under faster PSA.
        assert fast[1:13].sum() > slow[1:13].sum()

    def test_returns_correct_length(self):
        principal = project_pool_principal(
            initial_balance=1_000_000.0,
            wac_pct=5.0,
            term_months=360,
            psa_speed=150.0,
            n_periods=10,
        )
        assert len(principal) == 11  # n_periods + 1 (period 0 + 10 modeled)


class TestPacScheduleDerivation:
    def test_schedule_is_lower_envelope(self):
        # Derive PAC schedule for 100-250 PSA range. The schedule should never
        # exceed pool projections at either endpoint.
        schedule = derive_pac_schedule(
            pool_balance=10_000_000.0,
            pool_wac_pct=6.0,
            pool_term_months=360,
            psa_low=100.0,
            psa_high=250.0,
            pac_size=5_000_000.0,
            n_periods=60,
        )
        proj_lo = project_pool_principal(10_000_000.0, 6.0, 360, 100.0, 60)
        proj_hi = project_pool_principal(10_000_000.0, 6.0, 360, 250.0, 60)
        for entry in schedule:
            t = entry["period"]
            assert entry["target_principal"] <= float(proj_lo[t]) + 0.01
            assert entry["target_principal"] <= float(proj_hi[t]) + 0.01

    def test_total_schedule_does_not_exceed_pac_size(self):
        schedule = derive_pac_schedule(
            pool_balance=10_000_000.0,
            pool_wac_pct=6.0,
            pool_term_months=360,
            psa_low=100.0,
            psa_high=250.0,
            pac_size=2_000_000.0,
            n_periods=120,
        )
        total = sum(float(entry["target_principal"]) for entry in schedule)
        assert total <= 2_000_000.0 + 0.01

    def test_psa_low_high_order_doesnt_matter(self):
        a = derive_pac_schedule(10_000_000.0, 6.0, 360, 100.0, 250.0, 4_000_000.0, 36)
        b = derive_pac_schedule(10_000_000.0, 6.0, 360, 250.0, 100.0, 4_000_000.0, 36)
        assert len(a) == len(b)
        for e1, e2 in zip(a, b):
            assert e1["period"] == e2["period"]
            assert e1["target_principal"] == pytest.approx(e2["target_principal"], abs=0.01)

    def test_zero_size_returns_empty_schedule(self):
        schedule = derive_pac_schedule(10_000_000.0, 6.0, 360, 100.0, 250.0, 0.0, 60)
        assert schedule == []

    def test_schedule_entries_strictly_increasing_period(self):
        schedule = derive_pac_schedule(10_000_000.0, 6.0, 360, 100.0, 250.0, 5_000_000.0, 60)
        periods = [e["period"] for e in schedule]
        assert periods == sorted(periods)
        assert len(periods) == len(set(periods))


class TestTacScheduleDerivation:
    def test_tac_schedule_matches_single_psa_projection(self):
        schedule = derive_tac_schedule(
            pool_balance=5_000_000.0,
            pool_wac_pct=6.0,
            pool_term_months=360,
            psa_target=200.0,
            tac_size=3_000_000.0,
            n_periods=36,
        )
        proj = project_pool_principal(5_000_000.0, 6.0, 360, 200.0, 36)
        # Each schedule entry should be <= projected principal at the target.
        for entry in schedule:
            t = entry["period"]
            assert entry["target_principal"] <= float(proj[t]) + 0.01

    def test_tac_size_caps_total_principal(self):
        schedule = derive_tac_schedule(5_000_000.0, 6.0, 360, 200.0, 1_000_000.0, 60)
        total = sum(float(e["target_principal"]) for e in schedule)
        assert total <= 1_000_000.0 + 0.01


class TestProvenance:
    def test_provenance_records_all_inputs(self):
        provenance = build_schedule_provenance(
            method="PSA_RANGE",
            inputs={"psa_low": 100, "psa_high": 250, "pac_size": 5_000_000},
            schedule_length=60,
        )
        assert provenance["method"] == "PSA_RANGE"
        assert provenance["inputs"]["psa_low"] == 100
        assert provenance["schedule_length"] == 60
        assert "generated_at" in provenance
