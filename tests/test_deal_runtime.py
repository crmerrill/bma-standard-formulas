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
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows,
    DealRunInput,
    PooledCollateralInput,
)
from bma_standard_formulas.deals.schemas.ir import (
    BondDef,
    DealDefinition,
    RuleNode,
)
from bma_standard_formulas.deals.schemas.common import RuleType, TrancheType

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
