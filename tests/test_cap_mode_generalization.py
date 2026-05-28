"""Tests for the `CapMode` enum on `RuleNode` and structuring verification.

Confirms:
- The new `cap_mode` field on RuleNode accepts the four canonical values.
- Migration shim translates legacy `ignore_schedule_cap=True` into `CapMode.NONE`.
- Runtime honors `cap_mode=PLANNED/SCHEDULED/TARGETED` as schedule-bound and
  `cap_mode=NONE` as cleanup (bypasses the schedule cap).
- Structuring verification emits warnings for premature cleanup placement and
  PAC/TAC bonds without cleanup coverage.
"""
from __future__ import annotations

import numpy as np
import pytest

from bma_cfengine_app.orchestrator.deals.structuring_verification import verify_structure
from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.common import (
    CapMode,
    PayMode,
    RuleType,
    TrancheKind,
    TrancheRelationType,
)
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows,
    DealRunInput,
    PooledCollateralInput,
)
from bma_standard_formulas.deals.schemas.ir import BondDef, DealDefinition, RuleNode, TrancheRelation
from bma_standard_formulas.deals.schemas.migrations import migrate_deal_payload


def _flat_pool(initial_balance: float, monthly_principal: float, n_periods: int, annual_coupon: float = 6.0) -> DealRunInput:
    bal = np.zeros(n_periods + 1)
    principal = np.zeros(n_periods + 1)
    interest = np.zeros(n_periods + 1)
    bal[0] = initial_balance
    for i in range(1, n_periods + 1):
        prev = bal[i - 1]
        prin = min(monthly_principal, prev)
        principal[i] = prin
        interest[i] = prev * annual_coupon / 1200.0
        bal[i] = max(0.0, prev - prin)
    cf = CollateralCashflows(
        cfdate=list(range(n_periods + 1)),
        balance=bal.tolist(),
        principal=principal.tolist(),
        interest=interest.tolist(),
        cashflow=(principal + interest).tolist(),
        loss=[0.0] * (n_periods + 1),
        prepbal=[0.0] * (n_periods + 1),
        defbal=[0.0] * (n_periods + 1),
        recovery=[0.0] * (n_periods + 1),
        principal_sched=principal.tolist(),
        principal_unsched=[0.0] * (n_periods + 1),
        cpr=[0.0] * (n_periods + 1),
        cdr=[0.0] * (n_periods + 1),
        sev=[0.0] * (n_periods + 1),
        dq=[0.0] * (n_periods + 1),
        surv_fac=[1.0] * (n_periods + 1),
        sched_coupon=[annual_coupon] * (n_periods + 1),
        sched_netcoupon=[annual_coupon] * (n_periods + 1),
        coupon=[annual_coupon] * (n_periods + 1),
        effcoupon=[annual_coupon] * (n_periods + 1),
        sched_balance=bal.tolist(),
        discount_factor=[1.0] * (n_periods + 1),
    )
    return DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        original_collateral_balance=initial_balance,
        loan_count=10,
    )


class TestCapModeEnum:
    def test_all_four_values_accepted(self):
        bond = BondDef(name="A", kind=TrancheKind.PAC, coupon=4.0, notional=1_000_000.0)
        for mode in (CapMode.PLANNED, CapMode.SCHEDULED, CapMode.TARGETED, CapMode.NONE):
            rule = RuleNode(
                rule_id=f"r_{mode.value}",
                rule_type=RuleType.PAY_PRINCIPAL,
                order=0,
                from_sources=["CASH"],
                to_targets=["A"],
                cap_mode=mode,
            )
            assert rule.cap_mode == mode

    def test_default_cap_mode_is_none(self):
        rule = RuleNode(
            rule_id="r_default",
            rule_type=RuleType.PAY_PRINCIPAL,
            order=0,
            from_sources=["CASH"],
            to_targets=["A"],
        )
        assert rule.cap_mode is None
        assert rule.ignore_schedule_cap is False


class TestLegacyMigration:
    def test_legacy_ignore_schedule_cap_translates_to_none(self):
        # Migration is a pure dict-to-dict transform; no schema validation here.
        payload = {
            "waterfall_rules": [
                {
                    "rule_id": "r1",
                    "rule_type": "PAY_PRINCIPAL",
                    "order": 0,
                    "from_sources": ["CASH"],
                    "to_targets": ["A"],
                    "ignore_schedule_cap": True,
                }
            ],
        }
        migrated = migrate_deal_payload(payload)
        rule = migrated["waterfall_rules"][0]
        assert rule["cap_mode"] == "NONE"
        assert rule["ignore_schedule_cap"] is True  # legacy field preserved.

    def test_legacy_no_flag_yields_none_cap_mode(self):
        payload = {
            "waterfall_rules": [
                {
                    "rule_id": "r1",
                    "rule_type": "PAY_PRINCIPAL",
                    "order": 0,
                    "from_sources": ["CASH"],
                    "to_targets": ["A"],
                }
            ],
        }
        migrated = migrate_deal_payload(payload)
        rule = migrated["waterfall_rules"][0]
        # When neither cap_mode nor ignore_schedule_cap is present, leave None
        # so the runtime can default based on whether the bond has a schedule.
        assert rule["cap_mode"] is None


class TestRuntimeHonorsCapMode:
    """Confirm runtime executes cleanup vs scheduled rules consistently with cap_mode."""

    def _make_pac_with_support_deal(self, cleanup_cap_mode: CapMode | None) -> DealDefinition:
        return DealDefinition(
            deal_name="CapModeTest",
            bonds=[
                BondDef(
                    name="PAC",
                    kind=TrancheKind.PAC,
                    coupon=4.0,
                    notional=10_000_000.0,
                    schedule_contract=[
                        {"period": p, "target_balance": max(0.0, 10_000_000.0 - p * 100_000.0)}
                        for p in range(1, 100)
                    ],
                    relations=[TrancheRelation(relation_type=TrancheRelationType.SUPPORTED_BY, targets=["S"])],
                ),
                BondDef(
                    name="S",
                    kind=TrancheKind.CASH_PAY,
                    coupon=5.0,
                    notional=2_000_000.0,
                ),
                BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=[
                RuleNode(rule_id="r_int_pac", rule_type=RuleType.PAY_INTEREST, order=0,
                         from_sources=["CASH"], to_targets=["PAC"]),
                RuleNode(rule_id="r_int_s", rule_type=RuleType.PAY_INTEREST, order=1,
                         from_sources=["CASH"], to_targets=["S"]),
                RuleNode(rule_id="r_prin_pac", rule_type=RuleType.PAY_PRINCIPAL, order=2,
                         from_sources=["CASH"], to_targets=["PAC"], cap_mode=CapMode.PLANNED),
                RuleNode(rule_id="r_prin_s", rule_type=RuleType.PAY_PRINCIPAL, order=3,
                         from_sources=["CASH"], to_targets=["S"]),
                RuleNode(rule_id="r_prin_pac_cleanup", rule_type=RuleType.PAY_PRINCIPAL, order=4,
                         from_sources=["CASH"], to_targets=["PAC"], cap_mode=cleanup_cap_mode),
                RuleNode(rule_id="r_resid", rule_type=RuleType.PAY_RESIDUAL, order=5,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )

    def test_cleanup_with_cap_mode_none_drains_pac(self):
        deal = self._make_pac_with_support_deal(cleanup_cap_mode=CapMode.NONE)
        # Pool delivers way more than schedule expects so support drains and
        # cleanup must fire to bring PAC to zero by horizon end.
        run_input = _flat_pool(initial_balance=12_000_000.0, monthly_principal=2_000_000.0, n_periods=10)
        result = run_deal(deal, run_input)
        last = max(r.period for r in result.bond_cashflows)
        pac_final = next(r.end_balance for r in result.bond_cashflows if r.tranche_id == "PAC" and r.period == last)
        assert pac_final < 100.0, f"cleanup should retire PAC by horizon, got {pac_final}"

    def test_cleanup_with_cap_mode_planned_does_not_drain(self):
        deal = self._make_pac_with_support_deal(cleanup_cap_mode=CapMode.PLANNED)
        run_input = _flat_pool(initial_balance=12_000_000.0, monthly_principal=2_000_000.0, n_periods=10)
        result = run_deal(deal, run_input)
        last = max(r.period for r in result.bond_cashflows)
        pac_final = next(r.end_balance for r in result.bond_cashflows if r.tranche_id == "PAC" and r.period == last)
        # With PLANNED cap mode on the cleanup rule, PAC should still be
        # bounded by its schedule and remain outstanding above schedule floor.
        assert pac_final > 100.0, f"PLANNED cap should keep PAC outstanding, got {pac_final}"


class TestStructuringVerificationCleanupWarnings:
    def _deal_with_cleanup_position(self, cleanup_before_supports: bool) -> DealDefinition:
        """Return a deal where the cleanup rule is either before (bad) or after (good) supports."""
        rules: list[RuleNode] = [
            RuleNode(rule_id="r_int_pac", rule_type=RuleType.PAY_INTEREST, order=0,
                     from_sources=["CASH"], to_targets=["PAC"]),
            RuleNode(rule_id="r_prin_pac", rule_type=RuleType.PAY_PRINCIPAL, order=1,
                     from_sources=["CASH"], to_targets=["PAC"], cap_mode=CapMode.PLANNED),
        ]
        if cleanup_before_supports:
            rules.append(RuleNode(rule_id="r_prin_pac_cleanup", rule_type=RuleType.PAY_PRINCIPAL, order=2,
                                  from_sources=["CASH"], to_targets=["PAC"], cap_mode=CapMode.NONE))
            rules.append(RuleNode(rule_id="r_prin_s", rule_type=RuleType.PAY_PRINCIPAL, order=3,
                                  from_sources=["CASH"], to_targets=["S"]))
        else:
            rules.append(RuleNode(rule_id="r_prin_s", rule_type=RuleType.PAY_PRINCIPAL, order=2,
                                  from_sources=["CASH"], to_targets=["S"]))
            rules.append(RuleNode(rule_id="r_prin_pac_cleanup", rule_type=RuleType.PAY_PRINCIPAL, order=3,
                                  from_sources=["CASH"], to_targets=["PAC"], cap_mode=CapMode.NONE))
        rules.append(RuleNode(rule_id="r_resid", rule_type=RuleType.PAY_RESIDUAL, order=4,
                              from_sources=["CASH"], to_targets=["R"]))
        return DealDefinition(
            deal_name="VerifyCleanup",
            bonds=[
                BondDef(name="PAC", kind=TrancheKind.PAC,
                        coupon=4.0, notional=10_000_000.0,
                        schedule_contract=[{"period": 1, "target_balance": 9_500_000.0}],
                        relations=[TrancheRelation(relation_type=TrancheRelationType.SUPPORTED_BY, targets=["S"])]),
                BondDef(name="S", kind=TrancheKind.CASH_PAY, coupon=5.0, notional=2_000_000.0),
                BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=rules,
        )

    def test_warns_on_premature_cleanup(self):
        deal = self._deal_with_cleanup_position(cleanup_before_supports=True)
        result = verify_structure(deal)
        assert any("cleanup rule" in w and "before any support" in w for w in result["warnings"]), (
            f"expected premature cleanup warning, got warnings: {result['warnings']}"
        )

    def test_no_warning_when_cleanup_after_supports(self):
        deal = self._deal_with_cleanup_position(cleanup_before_supports=False)
        result = verify_structure(deal)
        premature = [w for w in result["warnings"] if "before any support" in w]
        assert not premature, f"unexpected premature-cleanup warning: {premature}"

    def test_warns_on_pac_without_cleanup(self):
        deal = DealDefinition(
            deal_name="NoCleanup",
            bonds=[
                BondDef(name="PAC", kind=TrancheKind.PAC,
                        coupon=4.0, notional=10_000_000.0,
                        schedule_contract=[{"period": 1, "target_balance": 9_500_000.0}],
                        relations=[TrancheRelation(relation_type=TrancheRelationType.SUPPORTED_BY, targets=["S"])]),
                BondDef(name="S", kind=TrancheKind.CASH_PAY, coupon=5.0, notional=2_000_000.0),
                BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=[
                RuleNode(rule_id="r_prin_pac", rule_type=RuleType.PAY_PRINCIPAL, order=0,
                         from_sources=["CASH"], to_targets=["PAC"], cap_mode=CapMode.PLANNED),
                RuleNode(rule_id="r_prin_s", rule_type=RuleType.PAY_PRINCIPAL, order=1,
                         from_sources=["CASH"], to_targets=["S"]),
                RuleNode(rule_id="r_resid", rule_type=RuleType.PAY_RESIDUAL, order=2,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )
        result = verify_structure(deal)
        assert any("PAC" in w and "no cleanup rule" in w for w in result["warnings"]), (
            f"expected PAC-without-cleanup warning, got: {result['warnings']}"
        )
