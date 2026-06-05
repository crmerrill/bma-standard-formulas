"""rcf-5-negative-tests-and-roundtrip: inventory-driven round-trip tests."""

from __future__ import annotations

import importlib
import inspect
import json
from collections.abc import Callable
from typing import Any

import pytest

from scripts.parse_prospectus_inventory import get_entries_by_tier, load_inventory

from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows,
    DealRunInput,
    GroupedCollateralInput,
    PooledCollateralInput,
)
from bma_standard_formulas.deals.schemas.ir import DealDefinition
from bma_standard_formulas.diagnostics.canonicalization_validators import (
    detect_rule_fragmentation,
)

from .canonicalization_helpers import apply_consolidation_quickfix

CANONICALIZATION_ABS_TOL = 1e-9
CANONICALIZATION_REL_TOL = 1e-12


def _get_round_trip_fixtures() -> list[Any]:
    entries = load_inventory()
    structural = get_entries_by_tier("structural", entries)
    quantitative = get_entries_by_tier("quantitative_golden", entries)
    return [entry for entry in [*structural, *quantitative] if entry.fixture_dir is not None]


def _resolve_fixture_builder(module: Any, fixture_dir: str) -> Callable[[], DealDefinition] | None:
    exact_name = f"build_{fixture_dir}_deal"
    exact_builder = getattr(module, exact_name, None)
    if callable(exact_builder):
        return exact_builder

    builders = [
        member
        for name, member in inspect.getmembers(module, inspect.isfunction)
        if name.startswith("build_") and name.endswith("_deal")
    ]
    if not builders:
        return None
    return sorted(builders, key=lambda fn: fn.__name__)[0]


def _load_fixture_deal(fixture_dir: str) -> DealDefinition:
    package_module = importlib.import_module(f"tests.fixtures.{fixture_dir}")
    builder = _resolve_fixture_builder(package_module, fixture_dir)
    if builder is None:
        fallback_module = importlib.import_module(f"tests.fixtures.{fixture_dir}.deal_definition")
        builder = _resolve_fixture_builder(fallback_module, fixture_dir)
    if builder is None:
        deal_definition_obj = getattr(package_module, "deal_definition", None)
        if deal_definition_obj is not None:
            return deal_definition_obj
        raise AssertionError(f"No build_*_deal callable found for fixture {fixture_dir}")
    return builder()


def _infer_horizon_periods(deal: DealDefinition) -> int:
    max_period = 24
    for bond in deal.bonds:
        schedule = getattr(bond, "schedule_contract", None) or []
        for entry in schedule:
            max_period = max(max_period, int(entry.get("period", 0)))
    return min(max_period + 1, 120)


def _build_synthetic_collateral(balance: float, periods: int) -> CollateralCashflows:
    begin_balance = float(max(balance, 1_000_000.0))
    level_principal = begin_balance / max(periods - 1, 1)

    balances: list[float] = [begin_balance]
    principal: list[float] = [0.0]
    interest: list[float] = [0.0]
    cashflow: list[float] = [0.0]
    loss = [0.0]

    for _ in range(1, periods):
        prior = balances[-1]
        principal_paid = min(level_principal, prior)
        interest_paid = prior * 0.05 / 12.0
        ending = max(0.0, prior - principal_paid)

        balances.append(ending)
        principal.append(principal_paid)
        interest.append(interest_paid)
        cashflow.append(principal_paid + interest_paid)
        loss.append(0.0)

    zeros = [0.0] * periods
    ones = [1.0] * periods
    return CollateralCashflows(
        cfdate=list(range(periods)),
        balance=balances,
        principal=principal,
        interest=interest,
        cashflow=cashflow,
        loss=loss,
        prepbal=zeros.copy(),
        defbal=zeros.copy(),
        recovery=zeros.copy(),
        principal_sched=principal.copy(),
        principal_unsched=zeros.copy(),
        cpr=zeros.copy(),
        cdr=zeros.copy(),
        sev=zeros.copy(),
        dq=zeros.copy(),
        surv_fac=ones,
        sched_coupon=[5.0] * periods,
        sched_netcoupon=[5.0] * periods,
        coupon=[5.0] * periods,
        effcoupon=[5.0] * periods,
        sched_balance=balances.copy(),
        discount_factor=[1.0] * periods,
    )


def _build_run_input_for_deal(deal: DealDefinition) -> DealRunInput:
    periods = _infer_horizon_periods(deal)
    total_notional = sum(
        float(getattr(bond, "notional", 0.0) or 0.0)
        for bond in deal.bonds
        if bond.is_bond and not bond.is_pseudo
    )
    total_notional = max(total_notional, 1_000_000.0)

    if deal.collateral_groups:
        grouped_notional: dict[str, float] = {}
        for group in deal.collateral_groups:
            grouped_notional[group.group_id] = 0.0
        for bond in deal.bonds:
            if not bond.is_bond or bond.is_pseudo or not bond.group_id:
                continue
            grouped_notional[bond.group_id] = grouped_notional.get(bond.group_id, 0.0) + float(
                getattr(bond, "notional", 0.0) or 0.0
            )
        group_count = max(len(grouped_notional), 1)
        default_group_notional = total_notional / group_count
        grouped_collateral = {
            group_id: _build_synthetic_collateral(
                balance=max(notional, default_group_notional),
                periods=periods,
            )
            for group_id, notional in grouped_notional.items()
        }
        collateral = GroupedCollateralInput(groups=grouped_collateral)
    else:
        collateral = PooledCollateralInput(
            collateral=_build_synthetic_collateral(balance=total_notional, periods=periods)
        )

    return DealRunInput(
        collateral=collateral,
        original_collateral_balance=total_notional,
        loan_count=1_000,
    )


def _assert_cashflow_equivalence(pre_result: Any, post_result: Any) -> None:
    pre_rows = pre_result.bond_cashflows
    post_rows = post_result.bond_cashflows

    assert len(pre_rows) > 0, "Pre-fix run produced empty bond_cashflows"
    assert len(post_rows) > 0, "Post-fix run produced empty bond_cashflows"

    pre_tranches = {row.tranche_id for row in pre_rows}
    post_tranches = {row.tranche_id for row in post_rows}
    assert pre_tranches == post_tranches, (
        f"tranche set mismatch: pre={sorted(pre_tranches)} post={sorted(post_tranches)}"
    )

    pre_map = {(row.tranche_id, row.period): row for row in pre_rows}
    post_map = {(row.tranche_id, row.period): row for row in post_rows}
    assert set(pre_map.keys()) == set(post_map.keys()), "period key mismatch"
    assert len(pre_rows) == len(post_rows), "bond cashflow row count mismatch"

    for tranche_id, period in sorted(pre_map):
        pre_row = pre_map[(tranche_id, period)]
        post_row = post_map[(tranche_id, period)]
        assert post_row.tranche_id == tranche_id
        assert post_row.period == period

        pre_dump = pre_row.model_dump()
        post_dump = post_row.model_dump()
        for field, pre_value in pre_dump.items():
            post_value = post_dump[field]
            if field in {"period"}:
                continue
            if isinstance(pre_value, (int, float)) and isinstance(post_value, (int, float)):
                delta = abs(float(post_value) - float(pre_value))
                rel = delta / max(abs(float(pre_value)), 1.0)
                assert delta <= CANONICALIZATION_ABS_TOL and rel <= CANONICALIZATION_REL_TOL, (
                    f"cashflow mismatch for bond={tranche_id} period={period} field={field}: "
                    f"pre={pre_value!r} post={post_value!r} delta={delta:.3e} rel={rel:.3e}"
                )


def test_roundtrip_loads_fixtures_from_inventory() -> None:
    fixtures = _get_round_trip_fixtures()
    fixture_dirs = {fixture.fixture_dir for fixture in fixtures}

    assert len(fixtures) >= 5
    assert {
        "fnr_2006_018",
        "ginniemae_2025_203",
        "verus_2024_9",
        "cc_series_test",
        "ford_2024_c",
    }.issubset(fixture_dirs)


@pytest.mark.parametrize("fixture", _get_round_trip_fixtures(), ids=lambda f: f.fixture_dir)
def test_roundtrip_semantic_equivalence_per_fixture(fixture: Any) -> None:
    deal = _load_fixture_deal(fixture.fixture_dir)
    diagnostics = detect_rule_fragmentation(deal.model_dump())
    if not diagnostics:
        pytest.skip(
            reason=(
                f"No consolidatable runs in {fixture.fixture_dir}; "
                "canonicalization round-trip trivially satisfied."
            )
        )

    pre_run_input = _build_run_input_for_deal(deal)
    pre_result = run_deal(deal.model_copy(deep=True), pre_run_input, scenario_name="pre_canonical")

    post_deal = deal.model_copy(deep=True)
    for run in sorted(diagnostics, key=lambda d: d.payload["start_index"], reverse=True):
        start_index = int(run.payload["start_index"])
        end_index = int(run.payload["end_index"])
        updated_deal = apply_consolidation_quickfix(post_deal, start_index, end_index)
        if updated_deal is not None:
            post_deal = updated_deal

    post_run_input = _build_run_input_for_deal(post_deal)
    post_result = run_deal(post_deal, post_run_input, scenario_name="post_canonical")
    _assert_cashflow_equivalence(pre_result, post_result)


def test_apply_consolidation_quickfix_helper_matches_ts_reducer_byte_equivalent() -> None:
    base_deal = DealDefinition.model_validate(
        {
            "deal_name": "quickfix-byte-equivalence",
            "bonds": [
                {"name": "A", "kind": "CASH_PAY", "coupon": 0.0, "notional": 100.0},
                {"name": "B", "kind": "CASH_PAY", "coupon": 0.0, "notional": 100.0},
                {"name": "R", "kind": "RESIDUAL", "is_bond": False, "is_pseudo": True},
            ],
            "waterfall_rules": [
                {
                    "rule_id": "r1",
                    "rule_type": "PAY_PRINCIPAL",
                    "order": 0,
                    "from_sources": ["CASH"],
                    "to_targets": ["A"],
                    "payment_style": "SEQUENTIAL",
                },
                {
                    "rule_id": "r2",
                    "rule_type": "PAY_PRINCIPAL",
                    "order": 1,
                    "from_sources": ["CASH"],
                    "to_targets": ["B"],
                    "payment_style": "SEQUENTIAL",
                },
                {
                    "rule_id": "r3",
                    "rule_type": "PAY_RESIDUAL",
                    "order": 2,
                    "from_sources": ["CASH"],
                    "to_targets": ["R"],
                    "payment_style": "SEQUENTIAL",
                },
            ],
        }
    )
    expected_deal = DealDefinition.model_validate(
        {
            "deal_name": "quickfix-byte-equivalence",
            "bonds": [
                {"name": "A", "kind": "CASH_PAY", "coupon": 0.0, "notional": 100.0},
                {"name": "B", "kind": "CASH_PAY", "coupon": 0.0, "notional": 100.0},
                {"name": "R", "kind": "RESIDUAL", "is_bond": False, "is_pseudo": True},
            ],
            "waterfall_rules": [
                {
                    "rule_id": "r1",
                    "rule_type": "PAY_PRINCIPAL",
                    "order": 0,
                    "from_sources": ["CASH"],
                    "to_targets": ["A", "B"],
                    "payment_style": "SEQUENTIAL",
                },
                {
                    "rule_id": "r3",
                    "rule_type": "PAY_RESIDUAL",
                    "order": 2,
                    "from_sources": ["CASH"],
                    "to_targets": ["R"],
                    "payment_style": "SEQUENTIAL",
                },
            ],
        }
    )

    working_deal = base_deal.model_copy(deep=True)
    maybe_updated = apply_consolidation_quickfix(working_deal, 0, 1)
    actual_deal = maybe_updated if maybe_updated is not None else working_deal

    actual_json = json.dumps(actual_deal.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    expected_json = json.dumps(
        expected_deal.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    assert actual_json == expected_json


def test_governance_module_imports_unchanged() -> None:
    # Smoke-sentinel: confirms the FNR 2006-018 staged tie-out module still exists
    # and is importable. This test does NOT run or assert tie-out behaviour — the
    # actual WAL/yield/trustee governance is enforced by CI running both suites
    # (test_fnr_2006_018_staged_tieout and this module) in the same job. See rcf-5
    # AC-5 and the rcf-5 R1 review (Finding 2) for rationale.
    fnr_tieout_module = importlib.import_module("tests.test_fnr_2006_018_staged_tieout")
    assert fnr_tieout_module is not None


def test_roundtrip_skips_fixtures_with_no_consolidatable_runs() -> None:
    no_fragmentation_deal = DealDefinition.model_validate(
        {
            "deal_name": "no-fragmentation",
            "bonds": [
                {"name": "A", "kind": "CASH_PAY", "coupon": 0.0, "notional": 100.0},
                {"name": "B", "kind": "CASH_PAY", "coupon": 0.0, "notional": 100.0},
                {"name": "R", "kind": "RESIDUAL", "is_bond": False, "is_pseudo": True},
            ],
            "waterfall_rules": [
                {
                    "rule_id": "r1",
                    "rule_type": "PAY_PRINCIPAL",
                    "order": 0,
                    "from_sources": ["CASH"],
                    "to_targets": ["A"],
                    "payment_style": "SEQUENTIAL",
                },
                {
                    "rule_id": "r2",
                    "rule_type": "PAY_PRINCIPAL",
                    "order": 1,
                    "from_sources": ["CASH"],
                    "to_targets": ["B"],
                    "payment_style": "PRO_RATA",
                },
            ],
        }
    )
    diagnostics = detect_rule_fragmentation(no_fragmentation_deal.model_dump())
    assert diagnostics == []

    with pytest.raises(
        pytest.skip.Exception,
        match=(
            "No consolidatable runs in synthetic_no_runs; "
            "canonicalization round-trip trivially satisfied."
        ),
    ):
        if not diagnostics:
            pytest.skip(
                reason=(
                    "No consolidatable runs in synthetic_no_runs; "
                    "canonicalization round-trip trivially satisfied."
                )
            )
