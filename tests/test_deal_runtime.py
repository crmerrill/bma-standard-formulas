"""Golden regression tests for deal waterfall runtime.

Tests cover:
- Passthrough: all cashflow reaches residual
- 3-class sequential: interest priority, principal waterfall, fee deductions
- Jumbo sequential: multi-tranche with IO strip and writedowns
- Schema validation: IR reference checking, cycle detection
- Adapter round-trip: LDCMA-style dict -> DealRunInput -> run
"""
import numpy as np
import pytest

from bma_standard_formulas.deals.deal_library import (
    jumbo_sequential,
    ldcma_3class_2016,
    passthrough_deal,
)
from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schema import DealValidationError, validate_deal
from bma_standard_formulas.deals.adapters import from_collateral_dict
from bma_standard_formulas.deals.schemas.migrations import migrate_deal_payload
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows,
    DealRunInput,
    PooledCollateralInput,
)
from bma_standard_formulas.deals.schemas.ir import (
    AccountDef,
    BondDef,
    CalculationNode,
    DealDefinition,
    FeeDef,
    RuleNode,
    TriggerNode,
)
from bma_standard_formulas.deals.schemas.common import (
    PayMode,
    RuleType,
    TrancheBehavior,
    TrancheType,
    TriggerMetricType,
)

TOLERANCE = 1e-2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_simple_collateral(
    initial_balance: float = 100_000_000.0,
    n_periods: int = 61,
    monthly_principal_rate: float = 0.015,
    annual_coupon: float = 6.0,
    monthly_loss_rate: float = 0.001,
) -> tuple[DealRunInput, int]:
    bal = np.zeros(n_periods)
    bal[0] = initial_balance
    principal = np.zeros(n_periods)
    interest = np.zeros(n_periods)
    loss = np.zeros(n_periods)
    for i in range(1, n_periods):
        sched_prin = bal[i - 1] * monthly_principal_rate
        int_pmt = bal[i - 1] * annual_coupon / 1200.0
        default_amt = bal[i - 1] * monthly_loss_rate
        principal[i] = sched_prin
        interest[i] = int_pmt
        loss[i] = default_amt
        bal[i] = max(0.0, bal[i - 1] - principal[i] - default_amt)

    cf = CollateralCashflows(
        cfdate=list(range(n_periods)),
        balance=bal.tolist(),
        principal=principal.tolist(),
        interest=interest.tolist(),
        cashflow=(principal + interest).tolist(),
        loss=loss.tolist(),
        prepbal=[0.0] * n_periods,
        defbal=[0.0] * n_periods,
        recovery=[0.0] * n_periods,
        principal_sched=principal.tolist(),
        principal_unsched=[0.0] * n_periods,
        cpr=[0.0] * n_periods,
        cdr=[0.0] * n_periods,
        sev=[0.0] * n_periods,
        dq=[0.0] * n_periods,
        surv_fac=[1.0] * n_periods,
        sched_coupon=[annual_coupon] * n_periods,
        sched_netcoupon=[annual_coupon - 0.5] * n_periods,
        coupon=[annual_coupon] * n_periods,
        effcoupon=[annual_coupon] * n_periods,
        sched_balance=bal.tolist(),
        discount_factor=[1.0] * n_periods,
    )

    run_input = DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        original_collateral_balance=initial_balance,
        loan_count=500,
    )
    return run_input, n_periods


def _bond_totals(result, bond_name: str):
    rows = [r for r in result.bond_cashflows if r.tranche_id == bond_name and r.period > 0]
    return {
        "interest": sum(r.interest_paid for r in rows),
        "principal": sum(r.total_principal for r in rows),
        "final_balance": rows[-1].end_balance if rows else 0.0,
        "cashflow": sum(r.cashflow_total for r in rows),
    }


# ---------------------------------------------------------------------------
# Passthrough tests
# ---------------------------------------------------------------------------


class TestPassthrough:
    def test_all_cashflow_reaches_residual(self):
        deal = passthrough_deal()
        run_input, n = _make_simple_collateral(initial_balance=1_000_000, n_periods=25)
        result = run_deal(deal, run_input)

        total_collat_cf = sum(
            run_input.collateral.collateral.cashflow[i] for i in range(1, n)
        )
        resid = _bond_totals(result, "R")
        assert abs(resid["interest"] - total_collat_cf) < TOLERANCE

    def test_output_row_count(self):
        deal = passthrough_deal()
        run_input, n = _make_simple_collateral(n_periods=13)
        result = run_deal(deal, run_input)
        assert len(result.bond_cashflows) == n  # 1 bond x n periods
        assert len(result.waterfall_trace) == n - 1  # 1 rule x (n-1) active periods


# ---------------------------------------------------------------------------
# 3-Class sequential tests
# ---------------------------------------------------------------------------


class TestThreeClass:
    def test_senior_interest_paid_first(self):
        deal = ldcma_3class_2016()
        run_input, n = _make_simple_collateral()
        result = run_deal(deal, run_input)

        a = _bond_totals(result, "A")
        assert a["interest"] > 0, "Class A should receive interest"

    def test_fees_deducted(self):
        deal = ldcma_3class_2016()
        run_input, n = _make_simple_collateral()
        result = run_deal(deal, run_input)

        ind_fee = _bond_totals(result, "INDENTURE_FEE")
        owner_fee = _bond_totals(result, "OWNER_FEE")
        assert ind_fee["interest"] > 0, "Indenture fee should be paid"
        assert owner_fee["interest"] > 0, "Owner fee should be paid"

    def test_all_bond_names_present(self):
        deal = ldcma_3class_2016()
        run_input, _ = _make_simple_collateral()
        result = run_deal(deal, run_input)

        bond_names = set(r.tranche_id for r in result.bond_cashflows)
        expected = {
            "A", "B", "C", "R", "SPREAD_ACCT", "INDENTURE_FEE",
            "OWNER_FEE", "ADMIN_FEE", "SERVICING_FEE", "BACKUP_SFEE",
            "CUSTODIAN_FEE", "TRIGGER_CUMLOSS",
        }
        assert expected.issubset(bond_names)

    def test_waterfall_trace_populated(self):
        deal = ldcma_3class_2016()
        run_input, n = _make_simple_collateral()
        result = run_deal(deal, run_input)

        assert len(result.waterfall_trace) > 0
        rule_types = set(r.rule_type for r in result.waterfall_trace)
        assert "PAY_INTEREST" in rule_types
        assert "PAY_PRINCIPAL" in rule_types

    def test_pool_bps_fee_is_applied(self):
        deal = DealDefinition(
            deal_name="FeeBpsDeal",
            bonds=[
                BondDef(name="SERVICER_FEE", tranche_type=TrancheType.PSEUDO, is_bond=False, is_pseudo=True),
                BondDef(name="R", tranche_type=TrancheType.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            fees=[
                FeeDef(
                    name="SERVICER_FEE",
                    basis_type="COLLATERAL_BALANCE",
                    rate=0.5,  # 50 bps = 0.50% annual.
                )
            ],
            waterfall_rules=[
                RuleNode(
                    rule_id="fee_1",
                    rule_type=RuleType.PAY_FEE,
                    order=0,
                    from_sources=["CASH"],
                    to_targets=["SERVICER_FEE"],
                ),
                RuleNode(
                    rule_id="resid_1",
                    rule_type=RuleType.PAY_RESIDUAL,
                    order=1,
                    from_sources=["CASH"],
                    to_targets=["R"],
                ),
            ],
        )
        run_input, _ = _make_simple_collateral(
            initial_balance=1_000_000,
            n_periods=3,
            monthly_principal_rate=0.0,
            annual_coupon=12.0,
            monthly_loss_rate=0.0,
        )
        result = run_deal(deal, run_input)
        fee_totals = _bond_totals(result, "SERVICER_FEE")
        # 0.50% annual -> 1,000,000 * 0.50% / 12 = 416.67 per month, two active periods.
        assert fee_totals["interest"] == pytest.approx(833.33, rel=0.02)

    def test_pool_bps_fee_honors_quarterly_frequency(self):
        deal = DealDefinition(
            deal_name="FeeBpsQuarterly",
            bonds=[
                BondDef(name="SERVICER_FEE", tranche_type=TrancheType.PSEUDO, is_bond=False, is_pseudo=True),
                BondDef(name="R", tranche_type=TrancheType.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            fees=[
                FeeDef(
                    name="SERVICER_FEE",
                    basis_type="COLLATERAL_BALANCE",
                    rate=1.2,  # 1.20% annual.
                    frequency="QUARTERLY",
                )
            ],
            waterfall_rules=[
                RuleNode(
                    rule_id="fee_1",
                    rule_type=RuleType.PAY_FEE,
                    order=0,
                    from_sources=["CASH"],
                    to_targets=["SERVICER_FEE"],
                ),
                RuleNode(
                    rule_id="resid_1",
                    rule_type=RuleType.PAY_RESIDUAL,
                    order=1,
                    from_sources=["CASH"],
                    to_targets=["R"],
                ),
            ],
        )
        run_input, _ = _make_simple_collateral(
            initial_balance=1_000_000,
            n_periods=13,
            monthly_principal_rate=0.0,
            annual_coupon=24.0,
            monthly_loss_rate=0.0,
        )
        result = run_deal(deal, run_input)
        fee_totals = _bond_totals(result, "SERVICER_FEE")
        # Quarterly frequency with 1.20% annual rate -> 3,000 per payment, four payments.
        assert fee_totals["interest"] == pytest.approx(12_000.0, rel=0.01)

    def test_pool_bps_fee_honors_annual_frequency(self):
        deal = DealDefinition(
            deal_name="FeeBpsAnnual",
            bonds=[
                BondDef(name="SERVICER_FEE", tranche_type=TrancheType.PSEUDO, is_bond=False, is_pseudo=True),
                BondDef(name="R", tranche_type=TrancheType.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            fees=[
                FeeDef(
                    name="SERVICER_FEE",
                    basis_type="COLLATERAL_BALANCE",
                    rate=1.2,  # 1.20% annual.
                    frequency="ANNUAL",
                )
            ],
            waterfall_rules=[
                RuleNode(
                    rule_id="fee_1",
                    rule_type=RuleType.PAY_FEE,
                    order=0,
                    from_sources=["CASH"],
                    to_targets=["SERVICER_FEE"],
                ),
                RuleNode(
                    rule_id="resid_1",
                    rule_type=RuleType.PAY_RESIDUAL,
                    order=1,
                    from_sources=["CASH"],
                    to_targets=["R"],
                ),
            ],
        )
        run_input, _ = _make_simple_collateral(
            initial_balance=1_000_000,
            n_periods=13,
            monthly_principal_rate=0.0,
            annual_coupon=24.0,
            monthly_loss_rate=0.0,
        )
        result = run_deal(deal, run_input)
        fee_totals = _bond_totals(result, "SERVICER_FEE")
        # Annual: one payment at month 12 equal to annual fee.
        assert fee_totals["interest"] == pytest.approx(12_000.0, rel=0.01)


# ---------------------------------------------------------------------------
# Jumbo sequential tests
# ---------------------------------------------------------------------------


class TestJumboSequential:
    def test_snr_receives_principal(self):
        deal = jumbo_sequential()
        run_input, _ = _make_simple_collateral()
        result = run_deal(deal, run_input)

        snr = _bond_totals(result, "SNR")
        assert snr["principal"] > 0, "SNR should receive principal"

    def test_all_bonds_present(self):
        deal = jumbo_sequential()
        run_input, _ = _make_simple_collateral()
        result = run_deal(deal, run_input)

        names = set(r.tranche_id for r in result.bond_cashflows)
        assert {"SNR", "B1", "B2", "B3", "B4", "B5", "R"}.issubset(names)


# ---------------------------------------------------------------------------
# Adapter tests
# ---------------------------------------------------------------------------


class TestAdapters:
    def test_ldcma_dict_adapter(self):
        n = 13
        collcf = {
            "COLLAT": {
                "cfdate": list(range(n)),
                "balance": [100000 - i * 7500 for i in range(n)],
                "principal": [0] + [7500] * 12,
                "interest": [0] + [500] * 12,
                "cashflow": [0] + [8000] * 12,
                "loss": [0] * n,
                "prepbal": [0] * n,
                "defbal": [0] * n,
                "recovery": [0] * n,
                "principal_sched": [0] + [7500] * 12,
                "principal_unsched": [0] * n,
                "cpr": [0] * n,
                "cdr": [0] * n,
                "sev": [0] * n,
                "dq": [0] * n,
                "surv_fac": [1.0] * n,
                "sched_coupon": [6.0] * n,
                "sched_netcoupon": [5.5] * n,
                "coupon": [6.0] * n,
                "effcoupon": [6.0] * n,
                "sched_balance": [100000 - i * 7500 for i in range(n)],
                "discount_factor": [1.0] * n,
            }
        }
        run_input = from_collateral_dict(collcf, loan_count=10)
        deal = passthrough_deal()
        result = run_deal(deal, run_input)
        resid = _bond_totals(result, "R")
        assert abs(resid["interest"] - 96000.0) < TOLERANCE


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    def test_valid_deal_passes(self):
        deal = passthrough_deal()
        warnings = validate_deal(deal)
        assert isinstance(warnings, list)

    def test_duplicate_names_fails(self):
        deal = DealDefinition(
            deal_name="DupTest",
            bonds=[
                BondDef(name="A", coupon=5.0),
                BondDef(name="A", coupon=6.0),
            ],
            waterfall_rules=[
                RuleNode(rule_id="r1", rule_type=RuleType.PAY_INTEREST,
                         order=0, from_sources=["CASH"], to_targets=["A"]),
            ],
        )
        with pytest.raises(DealValidationError, match="Duplicate"):
            validate_deal(deal)

    def test_invalid_reference_fails_at_construction(self):
        with pytest.raises(Exception):
            DealDefinition(
                deal_name="BadRef",
                bonds=[
                    BondDef(name="A", coupon=5.0),
                ],
                waterfall_rules=[
                    RuleNode(rule_id="r1", rule_type=RuleType.PAY_INTEREST,
                             order=0, from_sources=["CASH"],
                             to_targets=["NONEXISTENT"]),
                ],
            )

    def test_pac_requires_schedule_contract(self):
        with pytest.raises(Exception):
            DealDefinition(
                deal_name="PACNeedsSchedule",
                bonds=[BondDef(name="A", tranche_behavior=TrancheBehavior.PAC)],
                waterfall_rules=[
                    RuleNode(
                        rule_id="r1",
                        rule_type=RuleType.PAY_PRINCIPAL,
                        order=0,
                        from_sources=["CASH"],
                        to_targets=["A"],
                    )
                ],
            )

    def test_support_graph_cycle_fails(self):
        with pytest.raises(Exception):
            DealDefinition(
                deal_name="SupportCycle",
                bonds=[
                    BondDef(name="A", support_tranches=["B"]),
                    BondDef(name="B", support_tranches=["A"]),
                ],
                waterfall_rules=[
                    RuleNode(
                        rule_id="r1",
                        rule_type=RuleType.PAY_PRINCIPAL,
                        order=0,
                        from_sources=["CASH"],
                        to_targets=["A"],
                    )
                ],
            )


class TestGeneralizedRuntime:
    def test_pac_tac_diagnostics_rows_are_emitted(self):
        deal = DealDefinition(
            deal_name="PacTacDiag",
            bonds=[
                BondDef(
                    name="A",
                    tranche_type=TrancheType.SEQUENTIAL,
                    tranche_behavior=TrancheBehavior.PAC,
                    size_dollars=80_000_000.0,
                    schedule_contract=[{"period": 1, "target_principal": 500_000.0}],
                    schedule_tolerance_bps=5.0,
                    support_tranches=["B"],
                ),
                BondDef(
                    name="B",
                    tranche_type=TrancheType.SEQUENTIAL,
                    size_dollars=10_000_000.0,
                ),
                BondDef(name="R", tranche_type=TrancheType.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=[
                RuleNode(
                    rule_id="a_prin",
                    rule_type=RuleType.PAY_PRINCIPAL,
                    order=0,
                    from_sources=["CASH"],
                    to_targets=["A"],
                ),
                RuleNode(
                    rule_id="resid",
                    rule_type=RuleType.PAY_RESIDUAL,
                    order=2,
                    from_sources=["CASH"],
                    to_targets=["R"],
                ),
            ],
        )
        run_input, _ = _make_simple_collateral(initial_balance=100_000_000, n_periods=4)
        result = run_deal(deal, run_input)
        assert result.pac_tac_diagnostics
        assert any(row.tranche_id == "A" for row in result.pac_tac_diagnostics)

    def test_z_structure_composition_rows_are_emitted(self):
        deal = DealDefinition(
            deal_name="ZSupportDiag",
            bonds=[
                BondDef(name="B", tranche_type=TrancheType.SEQUENTIAL, size_dollars=30_000_000.0),
                BondDef(
                    name="Z",
                    tranche_type=TrancheType.Z_BOND,
                    tranche_behavior=TrancheBehavior.Z,
                    pay_mode=PayMode.PIK,
                    z_accrual_enabled=True,
                    supported_by_tranches=["B"],
                    size_dollars=10_000_000.0,
                ),
                BondDef(name="R", tranche_type=TrancheType.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=[
                RuleNode(
                    rule_id="b_prin",
                    rule_type=RuleType.PAY_PRINCIPAL,
                    order=0,
                    from_sources=["CASH"],
                    to_targets=["B"],
                ),
                RuleNode(
                    rule_id="z_prin",
                    rule_type=RuleType.PAY_PRINCIPAL,
                    order=1,
                    from_sources=["CASH"],
                    to_targets=["Z"],
                ),
                RuleNode(
                    rule_id="resid",
                    rule_type=RuleType.PAY_RESIDUAL,
                    order=2,
                    from_sources=["CASH"],
                    to_targets=["R"],
                ),
            ],
        )
        run_input, _ = _make_simple_collateral(initial_balance=100_000_000, n_periods=4)
        result = run_deal(deal, run_input)
        assert result.structure_composition
        assert any(row.child_tranche_id == "Z" for row in result.structure_composition)

    def test_pik_mode_capitalizes_unpaid_coupon_into_balance(self):
        deal = DealDefinition(
            deal_name="PIKAccrual",
            bonds=[
                BondDef(
                    name="Z",
                    tranche_type=TrancheType.Z_BOND,
                    tranche_behavior=TrancheBehavior.Z,
                    pay_mode=PayMode.PIK,
                    z_accrual_enabled=True,
                    size_dollars=10_000_000.0,
                    coupon=12.0,
                ),
                BondDef(name="R", tranche_type=TrancheType.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=[
                RuleNode(
                    rule_id="resid",
                    rule_type=RuleType.PAY_RESIDUAL,
                    order=0,
                    from_sources=["CASH"],
                    to_targets=["R"],
                ),
            ],
        )
        run_input, _ = _make_simple_collateral(initial_balance=100_000_000, n_periods=3)
        result = run_deal(deal, run_input)
        z_rows = [row for row in result.bond_cashflows if row.tranche_id == "Z"]
        assert len(z_rows) >= 2
        assert z_rows[1].end_balance > z_rows[1].begin_balance

    def test_dollar_face_takes_precedence_over_size_pct(self):
        deal = DealDefinition(
            deal_name="DollarFacePriority",
            bonds=[
                BondDef(
                    name="A",
                    tranche_type=TrancheType.SEQUENTIAL,
                    size_dollars=21_000_000.0,
                    size_pct=40.0,
                    coupon=0.0,
                ),
                BondDef(name="R", tranche_type=TrancheType.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=[
                RuleNode(
                    rule_id="a_prin",
                    rule_type=RuleType.PAY_PRINCIPAL,
                    order=0,
                    from_sources=["CASH"],
                    to_targets=["A"],
                ),
                RuleNode(
                    rule_id="resid",
                    rule_type=RuleType.PAY_RESIDUAL,
                    order=1,
                    from_sources=["CASH"],
                    to_targets=["R"],
                ),
            ],
        )
        run_input, _ = _make_simple_collateral(initial_balance=100_000_000, n_periods=4)
        result = run_deal(deal, run_input)
        a0 = next(row for row in result.bond_cashflows if row.tranche_id == "A" and row.period == 0)
        assert a0.begin_balance == pytest.approx(21_000_000.0, rel=1e-9)
        assert a0.end_balance == pytest.approx(21_000_000.0, rel=1e-9)

    def test_rule_max_amount_expression_is_applied(self):
        deal = DealDefinition(
            deal_name="MaxAmountExpr",
            bonds=[
                BondDef(name="A", tranche_type=TrancheType.SEQUENTIAL, size_pct=100.0, coupon=0.0),
                BondDef(name="R", tranche_type=TrancheType.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            waterfall_rules=[
                RuleNode(
                    rule_id="prin_cap",
                    rule_type=RuleType.PAY_PRINCIPAL,
                    order=0,
                    from_sources=["CASH"],
                    to_targets=["A"],
                    max_amount_expr="1000 + period",
                ),
                RuleNode(
                    rule_id="resid",
                    rule_type=RuleType.PAY_RESIDUAL,
                    order=1,
                    from_sources=["CASH"],
                    to_targets=["R"],
                ),
            ],
        )
        run_input, _ = _make_simple_collateral(
            initial_balance=100_000,
            n_periods=3,
            monthly_principal_rate=0.0,
            annual_coupon=120.0,
            monthly_loss_rate=0.0,
        )
        result = run_deal(deal, run_input)
        a_rows = [r for r in result.bond_cashflows if r.tranche_id == "A" and r.period > 0]
        assert a_rows[0].total_principal == pytest.approx(1001.0, rel=1e-6)
        assert a_rows[1].total_principal == pytest.approx(1002.0, rel=1e-6)

    def test_fee_amount_expression_uses_loan_count_and_survival(self):
        deal = DealDefinition(
            deal_name="FeeExpr",
            bonds=[
                BondDef(name="FEE", tranche_type=TrancheType.PSEUDO, is_bond=False, is_pseudo=True),
                BondDef(name="R", tranche_type=TrancheType.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            fees=[
                FeeDef(
                    name="FEE",
                    basis_type="FIXED_DOLLAR",
                    amount_expr="1.2 * loan_count * surv_fac_prev",
                )
            ],
            waterfall_rules=[
                RuleNode(rule_id="fee", rule_type=RuleType.PAY_FEE, order=0, from_sources=["CASH"], to_targets=["FEE"]),
                RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=1, from_sources=["CASH"], to_targets=["R"]),
            ],
        )
        run_input, _ = _make_simple_collateral(
            initial_balance=1_000_000,
            n_periods=3,
            monthly_principal_rate=0.0,
            annual_coupon=24.0,
            monthly_loss_rate=0.0,
        )
        run_input.loan_count = 100
        result = run_deal(deal, run_input)
        fee_totals = _bond_totals(result, "FEE")
        # Monthly amount should be 0.1 * loan_count = 10 for each active period.
        assert fee_totals["interest"] == pytest.approx(20.0, rel=0.01)

    def test_account_rows_emitted_for_reserve_accounts(self):
        deal = DealDefinition(
            deal_name="AccountLedger",
            bonds=[
                BondDef(name="R", tranche_type=TrancheType.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            accounts=[
                AccountDef(name="RESV", account_type="RESERVE", starting_amount=100.0)
            ],
            waterfall_rules=[
                RuleNode(rule_id="fund", rule_type=RuleType.PAY_TO_RESERVE, order=0, from_sources=["CASH"], to_targets=["RESV"], max_amount_fixed=50.0),
                RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=1, from_sources=["CASH"], to_targets=["R"]),
            ],
        )
        run_input, _ = _make_simple_collateral(
            initial_balance=100_000,
            n_periods=3,
            monthly_principal_rate=0.0,
            annual_coupon=12.0,
            monthly_loss_rate=0.0,
        )
        result = run_deal(deal, run_input)
        reserve_rows = [r for r in result.deal_accounts if r.account_id == "RESV" and r.period > 0]
        assert len(reserve_rows) == 2
        assert reserve_rows[0].deposit == pytest.approx(50.0, rel=1e-6)

    def test_trigger_uses_calculation_refs(self):
        deal = DealDefinition(
            deal_name="TriggerCalcRef",
            bonds=[
                BondDef(name="A", tranche_type=TrancheType.SEQUENTIAL, size_pct=100.0, coupon=0.0),
                BondDef(name="TRIG", tranche_type=TrancheType.PSEUDO, is_bond=False, is_pseudo=True),
                BondDef(name="R", tranche_type=TrancheType.RESIDUAL, is_bond=False, is_pseudo=True),
            ],
            calculations=[
                CalculationNode(name="metric_calc", expression="collateral_loss * 2"),
                CalculationNode(name="threshold_calc", expression="100"),
            ],
            triggers=[
                TriggerNode(
                    name="TRIG",
                    metric_type=TriggerMetricType.CUSTOM,
                    calculation_ref="metric_calc",
                    comparison_ref="threshold_calc",
                ),
            ],
            waterfall_rules=[
                RuleNode(rule_id="a_int", rule_type=RuleType.PAY_INTEREST, order=0, from_sources=["CASH"], to_targets=["A"], condition_trigger="TRIG"),
                RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL, order=1, from_sources=["CASH"], to_targets=["R"]),
            ],
        )
        run_input, _ = _make_simple_collateral(
            initial_balance=1_000_000,
            n_periods=3,
            monthly_principal_rate=0.0,
            annual_coupon=0.0,
            monthly_loss_rate=0.001,
        )
        result = run_deal(deal, run_input)
        assert any(row.trigger_id == "TRIG" for row in result.trigger_state_history)

    def test_collect_trace_false_preserves_api_contract(self):
        deal = passthrough_deal()
        run_input, _ = _make_simple_collateral(initial_balance=500_000, n_periods=6)
        result = run_deal(deal, run_input, collect_trace=False)
        assert result.scenario_name == "Base Case"
        assert len(result.bond_cashflows) == 6
        assert result.waterfall_trace == []

    def test_migration_helper_injects_new_optional_fields(self):
        payload = {
            "deal_name": "LegacyPayload",
            "bonds": [{"name": "A"}, {"name": "R", "is_bond": False, "is_pseudo": True}],
            "fees": [{"name": "FEE", "basis_type": "FIXED_DOLLAR", "amount": 0.0}],
            "triggers": [{"name": "TRIG", "metric_type": "CUSTOM"}],
            "waterfall_rules": [
                {
                    "rule_id": "r1",
                    "rule_type": "PAY_RESIDUAL",
                    "order": 0,
                    "from_sources": ["CASH"],
                    "to_targets": ["R"],
                }
            ],
        }
        migrated = migrate_deal_payload(payload)
        assert "amount_expr" in migrated["fees"][0]
        assert "rate_expr" in migrated["fees"][0]
        assert "max_amount_expr" in migrated["waterfall_rules"][0]
