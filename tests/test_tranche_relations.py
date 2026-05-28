from bma_standard_formulas.deals.schemas.common import TrancheRelationType
from bma_standard_formulas.deals.schemas.ir import BondDef, TrancheRelation
from bma_standard_formulas.deals.schemas.migrations import migrate_deal_payload


def test_all_relation_types_validate_on_bonddef():
    relation_types = [
        TrancheRelationType.SUPPORTED_BY,
        TrancheRelationType.ACCRETES_TO,
        TrancheRelationType.NOTIONAL_TRACKS,
        TrancheRelationType.BALANCE_TRACKS,
        TrancheRelationType.COUPON_INVERSE_OF,
        TrancheRelationType.COUPON_LEVERAGE_OF,
        TrancheRelationType.MACR_EXCHANGE,
    ]
    bond = BondDef(
        name="X",
        relations=[
            TrancheRelation(
                relation_type=relation_type,
                targets=["A"],
                leverage=2.0 if relation_type == TrancheRelationType.COUPON_LEVERAGE_OF else None,
            )
            for relation_type in relation_types
        ],
    )
    assert len(bond.relations) == len(relation_types)


def test_migration_collapses_legacy_relationship_fields_to_relations():
    payload = {
        "deal_name": "LegacyRelations",
        "bonds": [
            {
                "name": "PAC",
                "kind": "PAC",
                "support_tranches": ["S1", "S2"],
            },
            {
                "name": "Z",
                "kind": "Z",
                "supported_by_tranches": ["A"],
                "tracks_bonds": {"balance": ["PO"]},
                "parent_tranche": "FLT",
                "relation_type": "floater_inverse",
                "notional_ratio": 1.5,
            },
        ],
        "waterfall_rules": [],
    }
    migrated = migrate_deal_payload(payload)
    pac = migrated["bonds"][0]
    z = migrated["bonds"][1]

    assert "support_tranches" not in pac
    assert pac["relations"] == [
        {"relation_type": "SUPPORTED_BY", "targets": ["S1", "S2"]},
    ]

    assert "supported_by_tranches" not in z
    assert "tracks_bonds" not in z
    assert "parent_tranche" not in z
    assert "relation_type" not in z
    assert "notional_ratio" not in z
    rel_types = {rel["relation_type"] for rel in z["relations"]}
    assert rel_types == {"ACCRETES_TO", "NOTIONAL_TRACKS", "COUPON_INVERSE_OF"}


# ---------------------------------------------------------------------------
# RG6: Runtime routing tests for relation types that affect cashflows
# ---------------------------------------------------------------------------

import numpy as np
import pytest

from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.common import (
    PayMode, RuleType, TrancheKind, TrancheRelationType,
)
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows, DealRunInput, PooledCollateralInput,
)
from bma_standard_formulas.deals.schemas.ir import (
    BondDef, DealDefinition, RuleNode, TrancheRelation,
)


def _flat_collateral(balance: float, monthly_principal: float, annual_coupon: float, n: int = 12) -> DealRunInput:
    b = np.zeros(n)
    p = np.zeros(n)
    interest = np.zeros(n)
    b[0] = balance
    for i in range(1, n):
        p[i] = min(monthly_principal, b[i - 1])
        interest[i] = b[i - 1] * annual_coupon / 1200.0
        b[i] = max(0.0, b[i - 1] - p[i])
    cf = CollateralCashflows(
        cfdate=list(range(n)),
        balance=b.tolist(), principal=p.tolist(), interest=interest.tolist(),
        cashflow=(p + interest).tolist(),
        loss=[0.0]*n, prepbal=[0.0]*n, defbal=[0.0]*n, recovery=[0.0]*n,
        principal_sched=p.tolist(), principal_unsched=[0.0]*n,
        cpr=[0.0]*n, cdr=[0.0]*n, sev=[0.0]*n, dq=[0.0]*n, surv_fac=[1.0]*n,
        sched_coupon=[annual_coupon]*n, sched_netcoupon=[annual_coupon]*n,
        coupon=[annual_coupon]*n, effcoupon=[annual_coupon]*n,
        sched_balance=b.tolist(), discount_factor=[1.0]*n,
    )
    return DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        original_collateral_balance=balance,
        loan_count=1,
    )


def test_supported_by_relation_enforces_pac_schedule_cap():
    """SUPPORTED_BY is used at runtime to derive the schedule_cap array on the PAC.

    Without the SUPPORTED_BY relation the validator rejects the deal, so this test
    verifies both the validation contract (SUPPORTED_BY required for PAC) and the
    runtime effect (schedule cap applied at exactly the declared contract amount).

    Mutation-sensitive assertion: the contract is set to 5.0/period while the pool
    delivers 15.0/period — PAC must receive exactly 5.0 (not 6, not 15) because
    the schedule cap is derived from the schedule_contract list, which the runtime
    populates from the bond's `SUPPORTED_BY` linkage metadata.
    """
    deal = DealDefinition(
        deal_name="SupportedByTest",
        bonds=[
            BondDef(
                name="PAC",
                kind=TrancheKind.PAC,
                coupon=5.0,
                notional=60.0,
                schedule_model_type=None,
                schedule_contract=[{"period": i, "target_principal": 5.0} for i in range(1, 12)],
                relations=[TrancheRelation(
                    relation_type=TrancheRelationType.SUPPORTED_BY,
                    targets=["S"],
                )],
            ),
            BondDef(name="S", kind=TrancheKind.CASH_PAY, coupon=5.0, notional=40.0),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        waterfall_rules=[
            RuleNode(rule_id="pac_int", rule_type=RuleType.PAY_INTEREST, order=0,
                     from_sources=["CASH"], to_targets=["PAC"]),
            RuleNode(rule_id="pac_prin", rule_type=RuleType.PAY_PRINCIPAL, order=1,
                     from_sources=["CASH"], to_targets=["PAC"]),
            RuleNode(rule_id="sup_prin", rule_type=RuleType.PAY_PRINCIPAL, order=2,
                     from_sources=["CASH"], to_targets=["S"]),
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=3,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    run_input = _flat_collateral(balance=200.0, monthly_principal=15.0, annual_coupon=6.0)
    result = run_deal(deal, run_input)
    pac_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "PAC" and r.period == 1)
    s_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "S" and r.period == 1)

    # EXACT assertion: PAC must receive exactly schedule=5.0, not more.
    assert pac_p1.total_principal == pytest.approx(5.0, abs=0.01), (
        f"PAC period-1 principal {pac_p1.total_principal:.3f} != schedule cap 5.0"
    )
    # Support receives remaining CASH after PAC interest + PAC principal.
    # Pool CASH = 15 (principal) + 1 (interest) = 16; PAC interest ≈ 0.25; PAC principal = 5.
    # Remaining ≈ 10.75 — more than the pool-only principal excess (10).
    assert s_p1.total_principal > 5.0, (
        f"Support period-1 principal {s_p1.total_principal:.3f} must exceed 5 (PAC cap). "
        "If support gets 0 or ≤ 5, the excess routing is broken."
    )
    # Strict upper bound: support cannot exceed total pool cash for the period.
    assert s_p1.total_principal < 16.0, (
        "Support cannot receive more than total pool cash"
    )

    # Mutation sensitivity: verify the validator rejects a PAC without SUPPORTED_BY.
    import pydantic
    with pytest.raises(pydantic.ValidationError, match="support tranche"):
        DealDefinition(
            deal_name="NoPACSupport",
            bonds=[
                BondDef(name="PAC_bad", kind=TrancheKind.PAC, coupon=5.0, notional=60.0,
                        schedule_contract=[{"period": 1, "target_principal": 5.0}],
                        relations=[]),  # No SUPPORTED_BY
                BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=[
                RuleNode(rule_id="r", rule_type=RuleType.PAY_RESIDUAL, order=0,
                         from_sources=["CASH"], to_targets=["R"]),
            ],
        )


def test_accretes_to_relation_routes_z_accrual_to_support():
    """ACCRETES_TO: Z accrual must be paid as principal to the named support bond.

    The test is isolation-sensitive: we use a zero-cash pool (no collateral
    principal flow) so the ONLY way A can receive principal in period 1 is via
    Z accrual. If the ACCRETES_TO relation is not wired, A.total_principal == 0.
    """
    deal = DealDefinition(
        deal_name="AccresToTest",
        bonds=[
            BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=6.0, notional=100.0),
            BondDef(
                name="Z",
                kind=TrancheKind.Z,
                coupon=6.0,
                notional=50.0,
                pay_mode=PayMode.PIK,
                z_accrual_enabled=True,
                relations=[TrancheRelation(
                    relation_type=TrancheRelationType.ACCRETES_TO,
                    targets=["A"],
                )],
            ),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        waterfall_rules=[
            # Only ACT_INT from pool → interest to A (no principal rule for A).
            # A's principal can ONLY come from Z accrual in the pre-waterfall step.
            RuleNode(rule_id="int_a", rule_type=RuleType.PAY_INTEREST, order=0,
                     from_sources=["ACT_INT"], to_targets=["A"]),
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=1,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    # Zero-cash pool: only interest is delivered, no collateral principal.
    run_input = _flat_collateral(balance=200.0, monthly_principal=0.0, annual_coupon=8.0)
    result = run_deal(deal, run_input)

    z_monthly_coupon = 50.0 * 6.0 / 1200.0  # exactly 0.25/period
    a_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "A" and r.period == 1)
    z_p1 = next(r for r in result.bond_cashflows if r.tranche_id == "Z" and r.period == 1)

    # Z must not receive cash interest while accruing.
    assert z_p1.interest_paid == pytest.approx(0.0, abs=1e-6), "Z must not cash-pay interest"
    # Z balance grows by exact accrual amount.
    assert z_p1.end_balance == pytest.approx(50.0 + z_monthly_coupon, abs=1e-4), (
        f"Z balance {z_p1.end_balance:.6f} != expected {50.0 + z_monthly_coupon:.6f}"
    )
    # A receives principal equal to Z accrual (the ONLY source of A principal here).
    assert a_p1.total_principal == pytest.approx(z_monthly_coupon, abs=1e-4), (
        f"A principal {a_p1.total_principal:.6f} != Z accrual {z_monthly_coupon:.6f}; "
        "ACCRETES_TO wiring may be broken"
    )


def test_notional_tracks_relation_is_reflected_in_carry_tieout():
    """NOTIONAL_TRACKS: IO bond's carry tie-out row is identified as an IO class
    (not cash-paying) and its coupon rate is read from BondDef, not from principal
    cashflows (which are zero for an IO).

    The runtime tracks IO balance by mirroring the underlying bond's balance via
    the `tracks_bonds` mechanism wired from `NOTIONAL_TRACKS`. We verify this
    routes the carry tie-out to the correct IO classification path.
    """
    from bma_standard_formulas.deals.carry_tieout import compute_carry_tieout, _is_io_bond
    deal = DealDefinition(
        deal_name="NotionalTracksTest",
        bonds=[
            BondDef(name="A", kind=TrancheKind.CASH_PAY, coupon=5.0, notional=100.0),
            BondDef(
                name="IO",
                kind=TrancheKind.IO,
                coupon=5.0,
                notional=0.0,
                is_bond=True,
                is_pseudo=False,
                coupon_type="FIXED",
                relations=[TrancheRelation(
                    relation_type=TrancheRelationType.NOTIONAL_TRACKS,
                    targets=["A"],
                )],
            ),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        waterfall_rules=[
            RuleNode(rule_id="int_a", rule_type=RuleType.PAY_INTEREST, order=0,
                     from_sources=["CASH"], to_targets=["A"]),
            RuleNode(rule_id="int_io", rule_type=RuleType.PAY_INTEREST, order=1,
                     from_sources=["CASH"], to_targets=["IO"]),
            RuleNode(rule_id="prin_a", rule_type=RuleType.PAY_PRINCIPAL, order=2,
                     from_sources=["CASH"], to_targets=["A"]),
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=3,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    run_input = _flat_collateral(balance=100.0, monthly_principal=8.0, annual_coupon=6.0)
    result = run_deal(deal, run_input)

    # Verify the NOTIONAL_TRACKS relation makes _is_io_bond() recognise the IO class.
    io_bond_def = next(b for b in deal.bonds if b.name == "IO")
    assert _is_io_bond(io_bond_def), (
        "IO bond with NOTIONAL_TRACKS relation must be identified as IO by carry tie-out"
    )

    # Carry tie-out must include the IO in tieout.tranches.
    tieout = compute_carry_tieout(deal, run_input, result)
    io_row = next((r for r in tieout.tranches if r.tranche_id == "IO"), None)
    assert io_row is not None, "IO bond must appear in carry tie-out"

    # IO coupon_pct should reflect the stated 5.0% rate, not a YTM computed
    # from principal cashflows (which are zero).
    assert io_row.coupon_pct == pytest.approx(5.0, abs=0.01), (
        f"IO coupon_pct {io_row.coupon_pct} should be 5.0% from BondDef.coupon"
    )


def test_schema_only_relation_types_produce_verification_warnings():
    """COUPON_INVERSE_OF, COUPON_LEVERAGE_OF, MACR_EXCHANGE must produce warnings
    that explicitly state they are declarative-only and do not affect cashflows."""
    from bma_cfengine_app.orchestrator.deals.structuring_verification import verify_structure

    deal = DealDefinition(
        deal_name="SchemaOnlyRelations",
        bonds=[
            BondDef(
                name="FLT",
                kind=TrancheKind.CASH_PAY,
                coupon=5.0,
                notional=50.0,
                relations=[
                    TrancheRelation(
                        relation_type=TrancheRelationType.COUPON_INVERSE_OF,
                        targets=["INV"],
                    ),
                ],
            ),
            BondDef(
                name="LEV",
                kind=TrancheKind.CASH_PAY,
                coupon=5.0,
                notional=30.0,
                relations=[
                    TrancheRelation(
                        relation_type=TrancheRelationType.COUPON_LEVERAGE_OF,
                        targets=["FLT"],
                        leverage=2.0,
                    ),
                ],
            ),
            BondDef(
                name="MACR",
                kind=TrancheKind.CASH_PAY,
                coupon=5.0,
                notional=20.0,
                relations=[
                    TrancheRelation(
                        relation_type=TrancheRelationType.MACR_EXCHANGE,
                        targets=["FLT"],
                    ),
                ],
            ),
            BondDef(name="INV", kind=TrancheKind.CASH_PAY, coupon=0.0, notional=50.0),
            BondDef(name="R", kind=TrancheKind.RESIDUAL, is_bond=False, is_pseudo=True),
        ],
        waterfall_rules=[
            RuleNode(rule_id="r", rule_type=RuleType.PAY_RESIDUAL, order=0,
                     from_sources=["CASH"], to_targets=["R"]),
        ],
    )
    result = verify_structure(deal)
    warning_text = " ".join(result.get("warnings", []))

    # Each schema-only relation type must produce at least one warning.
    assert "COUPON_INVERSE_OF" in warning_text, "Must warn about COUPON_INVERSE_OF"
    assert "COUPON_LEVERAGE_OF" in warning_text, "Must warn about COUPON_LEVERAGE_OF"
    assert "MACR_EXCHANGE" in warning_text, "Must warn about MACR_EXCHANGE"

    # Warnings must explicitly state the relation is declarative-only.
    assert "declarative" in warning_text.lower(), (
        "Warnings must say relation types are declarative-only"
    )
