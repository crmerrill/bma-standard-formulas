"""RG5: coverage_mode correctness, fail-closed behavior, and golden reserve tests.

Verifies:
- coverage_mode=INTEREST_SHORTFALL fills the accumulated int_shortfall ledger
  (not the current-period opt_interest). This is the correct semantic for a
  reserve account that tops up *past* shortfalls.
- coverage_mode=PRINCIPAL_ACCELERATION draws from a reserve/account balance
  to pay bond principal beyond what collateral alone provides.
- Runtime raises RuntimeError (does not silently fall back) when the coverage
  source cannot be resolved — which validates the fail-closed contract.
- Invalid coverage sources are caught by the IR validator before the runtime
  ever sees them.
"""
from __future__ import annotations

import numpy as np
import pytest

from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.common import CoverageMode, RuleType, TrancheKind
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows,
    DealRunInput,
    PooledCollateralInput,
)
from bma_standard_formulas.deals.schemas.ir import (
    AccountDef,
    BondDef,
    DealDefinition,
    RuleNode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _zero_collateral(n: int = 8) -> DealRunInput:
    """Collateral that produces zero cashflow — only reserve/account balance drives payments."""
    cf = CollateralCashflows(
        cfdate=list(range(n)),
        balance=[0.0] * n,
        principal=[0.0] * n,
        interest=[0.0] * n,
        cashflow=[0.0] * n,
        loss=[0.0] * n, prepbal=[0.0] * n, defbal=[0.0] * n,
        recovery=[0.0] * n,
        principal_sched=[0.0] * n, principal_unsched=[0.0] * n,
        cpr=[0.0] * n, cdr=[0.0] * n, sev=[0.0] * n, dq=[0.0] * n,
        surv_fac=[1.0] * n,
        sched_coupon=[0.0] * n, sched_netcoupon=[0.0] * n,
        coupon=[0.0] * n, effcoupon=[0.0] * n,
        sched_balance=[0.0] * n, discount_factor=[1.0] * n,
    )
    return DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        original_collateral_balance=0.0,
        loan_count=1,
    )


def _flat_collateral(balance: float, monthly_principal: float, annual_coupon: float, n: int = 8) -> DealRunInput:
    bal = np.zeros(n)
    principal = np.zeros(n)
    interest = np.zeros(n)
    bal[0] = balance
    for i in range(1, n):
        p = min(monthly_principal, bal[i - 1])
        principal[i] = p
        interest[i] = bal[i - 1] * annual_coupon / 1200.0
        bal[i] = max(0.0, bal[i - 1] - p)
    cf = CollateralCashflows(
        cfdate=list(range(n)),
        balance=bal.tolist(), principal=principal.tolist(),
        interest=interest.tolist(), cashflow=(principal + interest).tolist(),
        loss=[0.0] * n, prepbal=[0.0] * n, defbal=[0.0] * n,
        recovery=[0.0] * n,
        principal_sched=principal.tolist(), principal_unsched=[0.0] * n,
        cpr=[0.0] * n, cdr=[0.0] * n, sev=[0.0] * n, dq=[0.0] * n,
        surv_fac=[1.0] * n,
        sched_coupon=[annual_coupon] * n, sched_netcoupon=[annual_coupon] * n,
        coupon=[annual_coupon] * n, effcoupon=[annual_coupon] * n,
        sched_balance=bal.tolist(), discount_factor=[1.0] * n,
    )
    return DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        original_collateral_balance=balance,
        loan_count=1,
    )


# ---------------------------------------------------------------------------
# Fail-closed: coverage source not in bonds/accounts raises RuntimeError
# ---------------------------------------------------------------------------


def _bypass_validation_deal(rule_type: RuleType, coverage_mode: CoverageMode, bad_source: str, deal_name: str) -> DealDefinition:
    """Build a DealDefinition that bypasses _validate_references so we can test
    the runtime's fail-closed behavior independently of the validator."""
    from bma_standard_formulas.deals.schemas.common import PaymentStyle
    # Build a valid deal first, then replace the waterfall rule using model_copy.
    valid_deal = DealDefinition(
        deal_name=deal_name,
        bonds=[
            BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=6.0, notional=100.0),
            BondDef(name="FAKE_ACCT", kind=TrancheKind.CASH_PAY, coupon=0.0, notional=10.0),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        waterfall_rules=[
            RuleNode(
                rule_id="cov_rule",
                rule_type=rule_type,
                order=0,
                from_sources=["FAKE_ACCT"],
                to_targets=["A"],
                coverage_mode=coverage_mode,
            ),
            RuleNode(rule_id="r", rule_type=RuleType.PAY_RESIDUAL, order=1,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    # Now bypass validation to swap in a bad source name.
    bad_rule = RuleNode.model_construct(
        rule_id="cov_rule",
        rule_type=rule_type,
        order=0,
        from_sources=[bad_source],
        to_targets=["A"],
        coverage_mode=coverage_mode,
        condition_trigger=None,
        condition_invert=False,
        condition_expr=None,
        max_amount_fixed=None,
        max_amount_expr=None,
        allow_negative_source=False,
        payment_style=PaymentStyle.SEQUENTIAL,
        ignore_schedule_cap=False,
        cap_mode=None,
        target_weights=None,
        group_id=None,
        reserve_account=None,
    )
    return valid_deal.model_copy(update={"waterfall_rules": [bad_rule]})


def test_interest_shortfall_with_invalid_source_raises_at_runtime():
    """Runtime must raise RuntimeError — not silently fall back — when the
    coverage-mode source cannot be resolved to a bond or account."""
    deal = _bypass_validation_deal(
        rule_type=RuleType.PAY_INTEREST,
        coverage_mode=CoverageMode.INTEREST_SHORTFALL,
        bad_source="NONEXISTENT_ACCOUNT",
        deal_name="BrokenCoverageSource",
    )
    run_input = _zero_collateral()
    with pytest.raises(RuntimeError, match="not found in bonds or accounts"):
        run_deal(deal, run_input)


def test_principal_acceleration_with_invalid_source_raises_at_runtime():
    """Same fail-closed contract for PRINCIPAL_ACCELERATION."""
    deal = _bypass_validation_deal(
        rule_type=RuleType.PAY_PRINCIPAL,
        coverage_mode=CoverageMode.PRINCIPAL_ACCELERATION,
        bad_source="GHOST_RESERVE",
        deal_name="BrokenAccelSource",
    )
    run_input = _zero_collateral()
    with pytest.raises(RuntimeError, match="not found in bonds or accounts"):
        run_deal(deal, run_input)


# ---------------------------------------------------------------------------
# IR validator rejects invalid coverage sources before runtime
# ---------------------------------------------------------------------------


def test_coverage_mode_source_must_be_bond_or_account_in_validator():
    with pytest.raises(Exception, match="bond/account"):
        DealDefinition(
            deal_name="BadCoverageSource",
            bonds=[
                BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=5.0, notional=100.0),
                BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=[
                RuleNode(
                    rule_id="bad",
                    rule_type=RuleType.PAY_INTEREST,
                    order=0,
                    from_sources=["CASH"],  # CASH is a stream, not a bond/account
                    to_targets=["A"],
                    coverage_mode=CoverageMode.INTEREST_SHORTFALL,
                ),
                RuleNode(rule_id="r", rule_type=RuleType.PAY_RESIDUAL, order=1,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )


def test_coverage_mode_requires_exactly_one_source():
    with pytest.raises(Exception, match="exactly one from_source"):
        DealDefinition(
            deal_name="MultiSource",
            bonds=[
                BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=5.0, notional=100.0),
                BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            accounts=[
                AccountDef(name="RSRV1"),
                AccountDef(name="RSRV2"),
            ],
            waterfall_rules=[
                RuleNode(
                    rule_id="multi",
                    rule_type=RuleType.PAY_INTEREST,
                    order=0,
                    from_sources=["RSRV1", "RSRV2"],
                    to_targets=["A"],
                    coverage_mode=CoverageMode.INTEREST_SHORTFALL,
                ),
                RuleNode(rule_id="r", rule_type=RuleType.PAY_RESIDUAL, order=1,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )


# ---------------------------------------------------------------------------
# Golden vector: reserve interest fills accumulated int_shortfall
# ---------------------------------------------------------------------------


def test_interest_shortfall_fills_prior_period_accumulated_shortfall():
    """INTEREST_SHORTFALL semantics: the reserve pays PRIOR-PERIOD accumulated
    int_shortfall — not the current-period coupon gap.

    Mechanics:
      - update_bonds_pre_ws: carries int_shortfall[i] = int_shortfall[i-1]
      - waterfall runs: coverage rule fills int_shortfall[i] from reserve
      - update_bonds_post_ws: int_shortfall[i] += max(0, remaining opt_interest[i])

    So a reserve rule that fires at period N pays the shortfall accumulated
    through period N-1, not the coupon due in period N.

    Timeline (500 face, 12% coupon = 5.0/month, reserve 8.0):
      Period 1: int_shortfall carried in = 0 (no prior shortfall).
                Reserve pays min(8, 0) = 0.  interest_paid = 0.
                Post-ws: int_shortfall[1] += opt_interest[1] = 5.0
      Period 2: int_shortfall carried in = 5.0.
                Reserve pays min(8, 5) = 5.0.  Reserve left = 3.0.
                Post-ws: int_shortfall[2] = (5 - 5) + 5 = 5.0
      Period 3: int_shortfall carried in = 5.0.
                Reserve pays min(3, 5) = 3.0.  Reserve left = 0.
                Post-ws: int_shortfall[3] = (5 - 3) + 5 = 7.0
      Period 4: reserve exhausted; pays 0.
    """
    deal = DealDefinition(
        deal_name="ReserveShortfallTest",
        bonds=[
            BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=12.0, notional=500.0),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        accounts=[
            AccountDef(name="RESERVE", starting_amount=8.0),
        ],
        waterfall_rules=[
            RuleNode(
                rule_id="int_normal",
                rule_type=RuleType.PAY_INTEREST,
                order=0,
                from_sources=["CASH"],
                to_targets=["A"],
            ),
            RuleNode(
                rule_id="int_reserve",
                rule_type=RuleType.PAY_INTEREST,
                order=1,
                from_sources=["RESERVE"],
                to_targets=["A"],
                coverage_mode=CoverageMode.INTEREST_SHORTFALL,
            ),
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=2,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    run_input = _zero_collateral(n=7)
    result = run_deal(deal, run_input)
    a_rows = {r.period: r for r in result.bond_cashflows if r.tranche_id == "A"}

    # Period 1: no prior shortfall yet — reserve cannot help.
    assert a_rows[1].interest_paid == pytest.approx(0.0, abs=0.01), (
        "Period 1: no prior-period shortfall; reserve rule must pay 0"
    )
    # Period 2: prior shortfall = 5.0; reserve = 8.0; pays 5.0.
    assert a_rows[2].interest_paid == pytest.approx(5.0, abs=0.01), (
        "Period 2: reserve covers prior shortfall of 5.0"
    )
    # Period 3: prior shortfall = 5.0; reserve = 3.0; pays 3.0.
    assert a_rows[3].interest_paid == pytest.approx(3.0, abs=0.01), (
        "Period 3: reserve pays remaining 3.0 then is exhausted"
    )
    # Period 4+: reserve = 0; no payment.
    assert a_rows[4].interest_paid == pytest.approx(0.0, abs=0.01), (
        "Period 4: reserve exhausted"
    )


def test_principal_acceleration_draws_from_account():
    """PRINCIPAL_ACCELERATION: reserve account pays bond principal."""
    deal = DealDefinition(
        deal_name="PrinAccelTest",
        bonds=[
            BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=0.0, notional=100.0),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        accounts=[
            AccountDef(name="RESERVE", starting_amount=25.0),
        ],
        waterfall_rules=[
            RuleNode(
                rule_id="prin_accel",
                rule_type=RuleType.PAY_PRINCIPAL,
                order=0,
                from_sources=["RESERVE"],
                to_targets=["A"],
                coverage_mode=CoverageMode.PRINCIPAL_ACCELERATION,
            ),
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=1,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    run_input = _zero_collateral(n=6)
    result = run_deal(deal, run_input)

    a_rows = {r.period: r for r in result.bond_cashflows if r.tranche_id == "A"}

    # Period 1: reserve 25.0; bond balance 100.0; pays min(25, 100) = 25.0.
    p1 = a_rows[1]
    assert p1.total_principal == pytest.approx(25.0, abs=0.01)
    assert p1.end_balance == pytest.approx(75.0, abs=0.01)

    # Period 2: reserve exhausted; no more principal.
    p2 = a_rows[2]
    assert p2.total_principal == pytest.approx(0.0, abs=0.01)
    assert p2.end_balance == pytest.approx(75.0, abs=0.01)


def test_coverage_mode_source_from_another_bond():
    """A bond can be the coverage source (recourse-line pattern).
    Bond B has balance 10.0; INTEREST_SHORTFALL rule draws from B to pay A's shortfall."""
    deal = DealDefinition(
        deal_name="BondCoverageSource",
        bonds=[
            BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=12.0, notional=100.0),
            BondDef(name="B", kind=TrancheKind.CASH_PAY, coupon=0.0, notional=10.0),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        waterfall_rules=[
            RuleNode(rule_id="int_normal", rule_type=RuleType.PAY_INTEREST, order=0,
                     from_sources=["CASH"], to_targets=["A"]),
            RuleNode(
                rule_id="int_b_cov",
                rule_type=RuleType.PAY_INTEREST,
                order=1,
                from_sources=["B"],
                to_targets=["A"],
                coverage_mode=CoverageMode.INTEREST_SHORTFALL,
            ),
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=2,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    run_input = _zero_collateral(n=6)
    result = run_deal(deal, run_input)

    a_rows = {r.period: r for r in result.bond_cashflows if r.tranche_id == "A"}
    b_rows = {r.period: r for r in result.bond_cashflows if r.tranche_id == "B"}

    # Period 1: no prior shortfall; coverage rule pays 0.
    assert a_rows[1].interest_paid == pytest.approx(0.0, abs=0.01), (
        "Period 1: no prior-period shortfall; coverage rule from B must pay 0"
    )
    # Period 2: prior shortfall = 1.0 (from period 1); B pays 1.0; B balance 9.0.
    assert a_rows[2].interest_paid == pytest.approx(1.0, abs=0.01), (
        "Period 2: coverage rule pays prior shortfall of 1.0"
    )
    assert b_rows[2].end_balance == pytest.approx(9.0, abs=0.01), (
        "Period 2: bond B debited 1.0 as coverage source"
    )
