"""OA4, OA7, OA8 acceptance tests.

OA4: Group source-token auto-prefixing policy is explicit and tested.
OA7: DealDefinition enforces PAC/TAC schedule requirement and Z invariants.
OA8: Duplicate from_period rejected for RateOrSchedule schedules.
"""
from __future__ import annotations

import pytest
import pydantic

from bma_standard_formulas.deals.schemas.common import (
    CouponType,
    RuleType,
    TrancheKind,
)
from bma_standard_formulas.deals.schemas.common import PayMode
from bma_standard_formulas.deals.schemas.ir import (
    BondDef,
    CollateralGroupDef,
    DealDefinition,
    RuleNode,
    RateScheduleEntry,
    TrancheRelation,
)
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows,
    DealRunInput,
    PooledCollateralInput,
)
from bma_standard_formulas.deals.runtime import run_deal
import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_bond(name: str, kind: TrancheKind = TrancheKind.CASH_PAY, **kw) -> BondDef:
    return BondDef(name=name, kind=kind, coupon=5.0, notional=1_000.0, **kw)


def _residual() -> BondDef:
    return BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True)


def _flat_run_input(balance: float = 1_000.0, n: int = 5) -> DealRunInput:
    p = np.zeros(n)
    b = np.full(n, balance)
    interest = np.array([0.0] + [balance * 5.0 / 1200] * (n - 1))
    cf = CollateralCashflows(
        cfdate=list(range(n)), balance=b.tolist(), principal=p.tolist(),
        interest=interest.tolist(), cashflow=(p + interest).tolist(),
        loss=[0.0]*n, prepbal=[0.0]*n, defbal=[0.0]*n, recovery=[0.0]*n,
        principal_sched=p.tolist(), principal_unsched=[0.0]*n,
        cpr=[0.0]*n, cdr=[0.0]*n, sev=[0.0]*n, dq=[0.0]*n, surv_fac=[1.0]*n,
        sched_coupon=[5.0]*n, sched_netcoupon=[5.0]*n,
        coupon=[5.0]*n, effcoupon=[5.0]*n,
        sched_balance=b.tolist(), discount_factor=[1.0]*n,
    )
    return DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        original_collateral_balance=balance,
        loan_count=1,
    )


# ---------------------------------------------------------------------------
# OA4: Group source-token auto-prefixing policy
# ---------------------------------------------------------------------------

class TestOA4GroupTokenPolicy:
    """OA4: Rules tagged with group_id may use bare tokens (CASH, ACT_INT, etc.);
    the runtime auto-prefixes them to GROUP_<id>_* at compile time.
    """

    def _two_group_deal(self) -> DealDefinition:
        """Minimal two-group deal where each group pays its own interest."""
        return DealDefinition(
            deal_name="OA4 Two-Group",
            collateral_groups=[
                CollateralGroupDef(group_id="GROUP_1", label="G1"),
                CollateralGroupDef(group_id="GROUP_2", label="G2"),
            ],
            bonds=[
                BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=5.0,
                        notional=500.0, group_id="GROUP_1"),
                BondDef(name="B", kind=TrancheKind.CASH_PAY, coupon=5.0,
                        notional=500.0, group_id="GROUP_2"),
                BondDef(name="R", kind=TrancheKind.RESIDUAL,
                        is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=[
                # Bare tokens — runtime auto-prefixes to GROUP_GROUP_1_ACT_INT
                RuleNode(rule_id="int_a", rule_type=RuleType.PAY_INTEREST, order=0,
                         from_sources=["ACT_INT"], to_targets=["A"], group_id="GROUP_1"),
                RuleNode(rule_id="int_b", rule_type=RuleType.PAY_INTEREST, order=1,
                         from_sources=["ACT_INT"], to_targets=["B"], group_id="GROUP_2"),
                RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=2,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )

    def test_deal_validates_with_bare_tokens_and_group_id(self):
        """DealDefinition with group_id + bare tokens must validate without error."""
        deal = self._two_group_deal()
        assert deal.deal_name == "OA4 Two-Group"

    def test_explicit_prefixed_tokens_also_valid(self):
        """Explicitly prefixed GROUP_<id>_* tokens are also valid in from_sources."""
        deal = DealDefinition(
            deal_name="OA4 Explicit Tokens",
            collateral_groups=[CollateralGroupDef(group_id="GROUP_1")],
            bonds=[
                BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=5.0,
                        notional=1000.0, group_id="GROUP_1"),
                _residual(),
            ],
            waterfall_rules=[
                RuleNode(rule_id="int_a", rule_type=RuleType.PAY_INTEREST, order=0,
                         from_sources=["GROUP_GROUP_1_ACT_INT"], to_targets=["A"]),
                RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=1,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )
        assert deal.collateral_groups[0].group_id == "GROUP_1"

    def test_cross_group_source_token_mixing_rejected(self):
        """A rule with group_id='GROUP_1' cannot mix bare tokens AND explicit cross-group tokens."""
        with pytest.raises(pydantic.ValidationError, match="mixes bare collateral tokens"):
            DealDefinition(
                deal_name="OA4 Bad Mix",
                collateral_groups=[
                    CollateralGroupDef(group_id="GROUP_1"),
                    CollateralGroupDef(group_id="GROUP_2"),
                ],
                bonds=[
                    BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=5.0,
                            notional=500.0, group_id="GROUP_1"),
                    _residual(),
                ],
                waterfall_rules=[
                    # group_id=GROUP_1 + explicit GROUP_GROUP_2_* AND bare CASH — mixing
                    RuleNode(rule_id="int_a", rule_type=RuleType.PAY_INTEREST, order=0,
                             from_sources=["CASH", "GROUP_GROUP_2_ACT_INT"], to_targets=["A"],
                             group_id="GROUP_1"),
                    RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=1,
                             from_sources=["CASH"], to_targets=["R"]),
                ],
            )

    def test_fnr_combined_still_passes(self):
        """Regression: FNR 2006-018 combined deal (the anchor fixture) still validates."""
        from tests.fixtures.fnr_2006_018.deal_definition import build_fnr_2006_018_combined_deal
        deal = build_fnr_2006_018_combined_deal(n_periods_group_1=4, n_periods_group_2=4)
        assert len(deal.collateral_groups) == 2


# ---------------------------------------------------------------------------
# OA7: DealDefinition-level bond structural invariants
# ---------------------------------------------------------------------------

class TestOA7BondInvariants:
    """OA7: PAC/TAC bonds must have a schedule; Z bonds must have z_accrual_enabled."""

    def test_pac_without_schedule_rejected_in_deal(self):
        """A PAC bond with no schedule_contract AND no schedule_model_type is rejected."""
        with pytest.raises(pydantic.ValidationError, match="requires either"):
            DealDefinition(
                deal_name="Bad PAC",
                bonds=[
                    BondDef(name="PA", kind=TrancheKind.PAC, coupon=5.0, notional=1000.0),
                    _residual(),
                ],
                waterfall_rules=[
                    RuleNode(rule_id="r", rule_type=RuleType.PAY_RESIDUAL, order=0,
                             from_sources=["CASH"], to_targets=["R"]),
                ],
            )

    def _pac_with_support(self, **kw) -> BondDef:
        """Helper: PAC bond with the required SUPPORTED_BY relation."""
        return BondDef(
            name="PA", kind=TrancheKind.PAC, coupon=5.0, notional=900.0,
            relations=[TrancheRelation(
                relation_type="SUPPORTED_BY", targets=["WA"]
            )],
            **kw,
        )

    def test_pac_with_schedule_model_type_passes(self):
        """A PAC bond with only schedule_model_type (no contract yet) should pass."""
        deal = DealDefinition(
            deal_name="PAC with model",
            bonds=[
                self._pac_with_support(
                    schedule_model_type="PSA",
                    schedule_speed_low=100.0,
                    schedule_speed_high=250.0,
                ),
                BondDef(name="WA", kind=TrancheKind.CASH_PAY, coupon=5.0, notional=100.0),
                _residual(),
            ],
            waterfall_rules=[
                RuleNode(rule_id="r", rule_type=RuleType.PAY_RESIDUAL, order=0,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )
        pa = next(b for b in deal.bonds if b.name == "PA")
        assert pa.schedule_model_type.value == "PSA"

    def test_pac_with_schedule_contract_passes(self):
        """A PAC bond with an explicit schedule_contract should pass."""
        deal = DealDefinition(
            deal_name="PAC with contract",
            bonds=[
                self._pac_with_support(
                    schedule_contract=[{"period": 1, "target_balance": 900.0}],
                    schedule_tolerance_bps=25.0,
                ),
                BondDef(name="WA", kind=TrancheKind.CASH_PAY, coupon=5.0, notional=100.0),
                _residual(),
            ],
            waterfall_rules=[
                RuleNode(rule_id="r", rule_type=RuleType.PAY_RESIDUAL, order=0,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )
        assert len(deal.bonds[0].schedule_contract) == 1

    def test_z_without_accrual_rejected_in_deal(self):
        """A Z bond with z_accrual_enabled=False should be rejected in a DealDefinition."""
        with pytest.raises(pydantic.ValidationError, match="z_accrual_enabled"):
            DealDefinition(
                deal_name="Bad Z",
                bonds=[
                    BondDef(name="Z", kind=TrancheKind.Z, coupon=5.0, notional=500.0,
                            z_accrual_enabled=False),  # Z without PIK accrual
                    _residual(),
                ],
                waterfall_rules=[
                    RuleNode(rule_id="r", rule_type=RuleType.PAY_RESIDUAL, order=0,
                             from_sources=["CASH"], to_targets=["R"]),
                ],
            )

    def test_z_with_accrual_enabled_passes(self):
        """Z bond with z_accrual_enabled=True and PIK pay_mode should pass."""
        deal = DealDefinition(
            deal_name="Good Z",
            bonds=[
                BondDef(name="Z", kind=TrancheKind.Z, coupon=5.0, notional=500.0,
                        z_accrual_enabled=True, pay_mode=PayMode.PIK),
                _residual(),
            ],
            waterfall_rules=[
                RuleNode(rule_id="r", rule_type=RuleType.PAY_RESIDUAL, order=0,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )
        assert deal.bonds[0].z_accrual_enabled is True

    def test_isolated_bond_def_pac_without_schedule_is_allowed(self):
        """Isolated BondDef construction does NOT enforce schedule requirement
        (enforcement is at DealDefinition level to allow partial authoring)."""
        bond = BondDef(name="PA", kind=TrancheKind.PAC, coupon=5.0, notional=1000.0)
        assert bond.kind == TrancheKind.PAC  # no error at BondDef level


# ---------------------------------------------------------------------------
# OA8: Duplicate from_period rejected in RateOrSchedule fields
# ---------------------------------------------------------------------------

class TestOA8DuplicateFromPeriod:
    """OA8: Duplicate from_period values in coupon/margin/cap/floor schedules are rejected."""

    def test_duplicate_coupon_from_period_rejected(self):
        with pytest.raises(pydantic.ValidationError, match="duplicate from_period"):
            BondDef(
                name="A", kind=TrancheKind.CASH_PAY, notional=1000.0,
                coupon=[
                    RateScheduleEntry(from_period=1, rate=5.0),
                    RateScheduleEntry(from_period=1, rate=6.0),  # duplicate
                ],
            )

    def test_duplicate_margin_from_period_rejected(self):
        with pytest.raises(pydantic.ValidationError, match="duplicate from_period"):
            BondDef(
                name="F", kind=TrancheKind.CASH_PAY, notional=1000.0,
                coupon_type=CouponType.FLOATING,
                margin=[
                    RateScheduleEntry(from_period=1, rate=1.0),
                    RateScheduleEntry(from_period=3, rate=1.5),
                    RateScheduleEntry(from_period=3, rate=2.0),  # duplicate period 3
                ],
            )

    def test_unique_from_periods_accepted(self):
        """Multiple entries with distinct from_period values must be accepted."""
        bond = BondDef(
            name="A", kind=TrancheKind.CASH_PAY, notional=1000.0,
            coupon=[
                RateScheduleEntry(from_period=1, rate=5.0),
                RateScheduleEntry(from_period=13, rate=6.0),
            ],
        )
        assert isinstance(bond.coupon, list)
        assert len(bond.coupon) == 2

    def test_scalar_coupon_still_accepted(self):
        """A plain scalar coupon (float) must still be accepted (backward compat)."""
        bond = BondDef(name="A", kind=TrancheKind.CASH_PAY, notional=1000.0, coupon=5.0)
        assert bond.coupon == 5.0
