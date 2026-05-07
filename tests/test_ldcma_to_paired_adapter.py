"""Phase 1e parity adapter — ``ldcma_to_paired``.

Validates the legacy-LDCMA → BMA-PAIRED parity adapter that routes
LDCMA-format inputs through the runtime's PAIRED branch so we can
verify bond cashflow parity before migrating fixtures (Phases 1f / 1g).

Coverage:

  1. **Input shape coverage** — DealRunInput(Pooled), DealRunInput(Grouped),
     bare PooledCollateralInput, bare GroupedCollateralInput, raw LDCMA
     collCF dict.
  2. **Output structure** — produces ``PairedCollateralInput`` with an
     ACTUAL_ONLY portfolio; one constituent per LDCMA group; group_id
     tagged correctly for multi-group; metadata propagated from input
     unless overridden.
  3. **Parity** — running the same fixture through the LDCMA branch and
     the PAIRED branch (via this adapter) yields identical bond cashflows
     and identical account states. This is the central correctness
     guarantee of the adapter.
  4. **Edge cases** — empty input rejected, unknown input types rejected.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from bma_standard_formulas.deals.adapters import (
    from_actual_cashflow,
    from_collateral_dict,
    ldcma_to_paired,
)
from bma_standard_formulas.deals.deal_library import passthrough_deal
from bma_standard_formulas.deals.runtime import run_deal
from bma_standard_formulas.deals.schemas.input import (
    DealRunInput,
    GroupedCollateralInput,
    PairedCollateralInput,
    PooledCollateralInput,
)
from bma_standard_formulas.engine import PortfolioCashflow
from bma_standard_formulas.engine.loan import (
    Loan,
    actual_cashflow_from_loan,
    scheduled_cashflow_from_loan,
)
from bma_standard_formulas.engine.portfolio import PortfolioMode
from bma_standard_formulas.formulas import generate_smm_curve_from_psa
from bma_standard_formulas.formulas.cashflows import BMAActualCashflow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_loan(loan_id: int, group_id: str | None, balance: float = 1_000_000.0) -> Loan:
    return Loan(
        loan_id=loan_id,
        origination_date=date(2024, 1, 1),
        asof_date=date(2024, 1, 1),
        original_balance=balance,
        current_balance=balance,
        rate_margin=6.0,
        original_term=360,
        remaining_term=360,
        group_id=group_id,
    )


def _ldcma_input_from_loan(loan: Loan, psa_speed: float = 100.0) -> DealRunInput:
    """Build an LDCMA-format ``DealRunInput`` (PooledCollateralInput) for a loan."""
    sched = scheduled_cashflow_from_loan(loan)
    smm = generate_smm_curve_from_psa(psa_speed, loan.original_term)
    n = loan.original_term + 1
    actual = actual_cashflow_from_loan(
        loan=loan,
        scheduled_cf=sched,
        smm_curve=smm,
        mdr_curve=np.zeros(n),
        severity_curve=np.zeros(n),
    )
    return from_actual_cashflow(
        actual,
        horizon=n,
        loan_count=1,
        initial_balance=loan.current_balance,
    )


# ---------------------------------------------------------------------------
# 1. Output structure
# ---------------------------------------------------------------------------


class TestOutputStructure:
    def test_pooled_input_produces_paired_actual_only(self):
        loan = _build_loan(1, group_id=None)
        ldcma_input = _ldcma_input_from_loan(loan)

        paired_input = ldcma_to_paired(ldcma_input)

        assert isinstance(paired_input.collateral, PairedCollateralInput)
        portfolio = paired_input.collateral.portfolio
        assert isinstance(portfolio, PortfolioCashflow)
        assert portfolio.mode == PortfolioMode.ACTUAL_ONLY
        # Single-pool input: one constituent, untagged (group_id=None).
        assert len(portfolio._pending) == 1
        assert portfolio._pending[0].group_id is None

    def test_grouped_input_tags_constituents_with_group_id(self):
        loan_g1 = _build_loan(1, "GROUP_1")
        loan_g2 = _build_loan(2, "GROUP_2")
        ldcma_g1 = _ldcma_input_from_loan(loan_g1)
        ldcma_g2 = _ldcma_input_from_loan(loan_g2)

        # Build a multi-group LDCMA input by combining the two single-pool
        # ones into a GroupedCollateralInput.
        grouped = GroupedCollateralInput(
            groups={
                "GROUP_1": ldcma_g1.collateral.collateral,
                "GROUP_2": ldcma_g2.collateral.collateral,
            }
        )
        run_input = DealRunInput(
            collateral=grouped,
            loan_count=2,
            original_collateral_balance=2_000_000.0,
        )

        paired_input = ldcma_to_paired(run_input)
        portfolio = paired_input.collateral.portfolio

        assert len(portfolio._pending) == 2
        group_ids = sorted(c.group_id for c in portfolio._pending)
        assert group_ids == ["GROUP_1", "GROUP_2"]

    def test_metadata_propagated_from_input(self):
        loan = _build_loan(1, group_id=None)
        ldcma_input = _ldcma_input_from_loan(loan)
        # Stash a market_date so the propagation is visible.
        ldcma_input = DealRunInput(
            collateral=ldcma_input.collateral,
            loan_count=42,
            original_collateral_balance=1_234_567.0,
            market_date="2024-01-01",
        )

        paired_input = ldcma_to_paired(ldcma_input)

        assert paired_input.loan_count == 42
        assert paired_input.original_collateral_balance == pytest.approx(1_234_567.0)
        assert paired_input.market_date == "2024-01-01"

    def test_metadata_overrides_take_precedence(self):
        loan = _build_loan(1, group_id=None)
        ldcma_input = _ldcma_input_from_loan(loan)

        paired_input = ldcma_to_paired(
            ldcma_input,
            loan_count=999,
            original_collateral_balance=1.0,
            market_date="2030-12-31",
        )

        assert paired_input.loan_count == 999
        assert paired_input.original_collateral_balance == pytest.approx(1.0)
        assert paired_input.market_date == "2030-12-31"

    def test_bare_pooled_input_accepted(self):
        loan = _build_loan(1, group_id=None)
        ldcma_input = _ldcma_input_from_loan(loan)

        # Pass the bare PooledCollateralInput, not a DealRunInput.
        paired_input = ldcma_to_paired(ldcma_input.collateral)

        assert isinstance(paired_input.collateral, PairedCollateralInput)
        assert paired_input.collateral.portfolio.mode == PortfolioMode.ACTUAL_ONLY

    def test_bare_grouped_input_accepted(self):
        loan_g1 = _build_loan(1, "GROUP_1")
        loan_g2 = _build_loan(2, "GROUP_2")
        ldcma_g1 = _ldcma_input_from_loan(loan_g1)
        ldcma_g2 = _ldcma_input_from_loan(loan_g2)
        grouped = GroupedCollateralInput(
            groups={
                "GROUP_1": ldcma_g1.collateral.collateral,
                "GROUP_2": ldcma_g2.collateral.collateral,
            }
        )

        paired_input = ldcma_to_paired(grouped)

        portfolio = paired_input.collateral.portfolio
        assert {c.group_id for c in portfolio._pending} == {"GROUP_1", "GROUP_2"}

    def test_raw_ldcma_dict_accepted(self):
        """The collCF dict shape consumed by ``from_collateral_dict``."""
        loan = _build_loan(1, group_id=None)
        ldcma_input = _ldcma_input_from_loan(loan)
        # Reverse-extract the dict from the CollateralCashflows model.
        cf = ldcma_input.collateral.collateral
        coll_cf = {
            "COLLAT": {
                "balance": cf.balance,
                "principal": cf.principal,
                "interest": cf.interest,
                "loss": cf.loss,
                "prepbal": cf.prepbal,
                "defbal": cf.defbal,
                "recovery": cf.recovery,
                "principal_sched": cf.principal_sched,
                "principal_unsched": cf.principal_unsched,
                "cpr": cf.cpr,
                "cdr": cf.cdr,
                "sev": cf.sev,
                "dq": cf.dq,
                "surv_fac": cf.surv_fac,
                "sched_coupon": cf.sched_coupon,
                "sched_netcoupon": cf.sched_netcoupon,
                "coupon": cf.coupon,
                "effcoupon": cf.effcoupon,
                "sched_balance": cf.sched_balance,
                "discount_factor": cf.discount_factor,
                "cashflow": cf.cashflow,
            }
        }

        paired_input = ldcma_to_paired(coll_cf, loan_count=1)

        assert isinstance(paired_input.collateral, PairedCollateralInput)
        assert paired_input.loan_count == 1


# ---------------------------------------------------------------------------
# 2. Parity — same bond outputs regardless of which branch runs
# ---------------------------------------------------------------------------


class TestParity:
    """Running the same data through the LDCMA branch and through
    ``ldcma_to_paired`` -> PAIRED branch produces identical bond cashflows.

    This is the central correctness guarantee of Phase 1e — it's what
    lets us migrate fixtures one at a time in 1f / 1g without worrying
    about silent regressions.
    """

    @pytest.fixture(scope="class")
    def fixtures(self):
        loan = _build_loan(1, group_id=None)
        ldcma_input = _ldcma_input_from_loan(loan, psa_speed=100.0)
        return ldcma_input

    def test_residual_cashflows_match(self, fixtures):
        ldcma_input = fixtures
        paired_input = ldcma_to_paired(ldcma_input)

        ldcma_bundle = run_deal(passthrough_deal(), ldcma_input, scenario_name="ldcma")
        paired_bundle = run_deal(passthrough_deal(), paired_input, scenario_name="paired")

        ldcma_r = sorted(
            (r for r in ldcma_bundle.bond_cashflows if r.tranche_id == "R"),
            key=lambda r: r.period,
        )
        paired_r = sorted(
            (r for r in paired_bundle.bond_cashflows if r.tranche_id == "R"),
            key=lambda r: r.period,
        )
        assert len(ldcma_r) == len(paired_r)
        for l_row, p_row in zip(ldcma_r, paired_r):
            assert l_row.period == p_row.period
            assert l_row.cashflow_total == pytest.approx(
                p_row.cashflow_total, rel=1e-9, abs=1e-6,
            ), f"period {l_row.period} mismatch: ldcma={l_row.cashflow_total} paired={p_row.cashflow_total}"

    def test_account_states_match(self, fixtures):
        ldcma_input = fixtures
        paired_input = ldcma_to_paired(ldcma_input)

        ldcma_bundle = run_deal(passthrough_deal(), ldcma_input, scenario_name="ldcma")
        paired_bundle = run_deal(passthrough_deal(), paired_input, scenario_name="paired")

        ldcma_acc = {(r.account_id, r.period): r for r in ldcma_bundle.deal_accounts}
        paired_acc = {(r.account_id, r.period): r for r in paired_bundle.deal_accounts}
        assert ldcma_acc.keys() == paired_acc.keys()
        for key, l_row in ldcma_acc.items():
            p_row = paired_acc[key]
            assert l_row.end_balance == pytest.approx(
                p_row.end_balance, rel=1e-9, abs=1e-6,
            )

    def test_grouped_parity(self):
        """Multi-group LDCMA input parity: per-group routing in the PAIRED
        branch matches per-group routing in the LDCMA branch.

        Uses a minimal inline two-group passthrough deal because the
        ``passthrough_deal()`` helper only declares a single pool. Multi-
        group cashflow input requires the deal IR to declare matching
        ``collateral_groups`` and tag rules with ``group_id``.
        """
        from bma_standard_formulas.deals.schemas.ir import (
            BondDef,
            CollateralGroupDef,
            DealDefinition,
            RuleNode,
        )
        from bma_standard_formulas.deals.schemas.common import RuleType, TrancheType

        loan_g1 = _build_loan(1, "GROUP_1")
        loan_g2 = _build_loan(2, "GROUP_2")
        ldcma_g1 = _ldcma_input_from_loan(loan_g1)
        ldcma_g2 = _ldcma_input_from_loan(loan_g2)
        grouped = GroupedCollateralInput(
            groups={
                "GROUP_1": ldcma_g1.collateral.collateral,
                "GROUP_2": ldcma_g2.collateral.collateral,
            }
        )
        ldcma_input = DealRunInput(
            collateral=grouped,
            loan_count=2,
            original_collateral_balance=2_000_000.0,
        )
        paired_input = ldcma_to_paired(ldcma_input)

        # Two-group passthrough deal: each group's CASH flows to its own
        # residual bond. Declares matching collateral_groups so the runtime
        # pre-allocates per-group cash arrays.
        deal = DealDefinition(
            deal_name="Passthrough_2Group",
            collateral_groups=[
                CollateralGroupDef(group_id="GROUP_1"),
                CollateralGroupDef(group_id="GROUP_2"),
            ],
            bonds=[
                BondDef(name="R1", tranche_type=TrancheType.RESIDUAL,
                        is_bond=False, is_pseudo=True, group_id="GROUP_1"),
                BondDef(name="R2", tranche_type=TrancheType.RESIDUAL,
                        is_bond=False, is_pseudo=True, group_id="GROUP_2"),
            ],
            waterfall_rules=[
                RuleNode(rule_id="pay_r1", rule_type=RuleType.PAY_RESIDUAL,
                         order=0, group_id="GROUP_1",
                         from_sources=["CASH"], to_targets=["R1"]),
                RuleNode(rule_id="pay_r2", rule_type=RuleType.PAY_RESIDUAL,
                         order=1, group_id="GROUP_2",
                         from_sources=["CASH"], to_targets=["R2"]),
            ],
        )

        ldcma_bundle = run_deal(deal, ldcma_input, scenario_name="ldcma_g")
        paired_bundle = run_deal(deal, paired_input, scenario_name="paired_g")

        # Each residual must match across both branches.
        for tranche_id in ("R1", "R2"):
            ldcma_rows = sorted(
                (r for r in ldcma_bundle.bond_cashflows if r.tranche_id == tranche_id),
                key=lambda r: r.period,
            )
            paired_rows = sorted(
                (r for r in paired_bundle.bond_cashflows if r.tranche_id == tranche_id),
                key=lambda r: r.period,
            )
            assert len(ldcma_rows) == len(paired_rows)
            for l_row, p_row in zip(ldcma_rows, paired_rows):
                assert l_row.cashflow_total == pytest.approx(
                    p_row.cashflow_total, rel=1e-9, abs=1e-6,
                ), f"{tranche_id} period {l_row.period} mismatch"


# ---------------------------------------------------------------------------
# 3. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_grouped_input_raises(self):
        with pytest.raises(ValueError, match="empty"):
            empty_grouped = GroupedCollateralInput.model_construct(groups={})
            ldcma_to_paired(empty_grouped)

    def test_unknown_input_type_raises(self):
        with pytest.raises(TypeError, match="DealRunInput|PooledCollateralInput|GroupedCollateralInput"):
            ldcma_to_paired("not a valid input")  # type: ignore[arg-type]

    def test_bma_actual_cashflow_loses_no_data(self):
        """Round-trip invariant: the synthesized BMAActualCashflow's
        primitive fields match the LDCMA dict's source values exactly.

        Pins the boundary helper ``_ldcma_to_bma_actual`` semantics from
        the perspective of the parity adapter — any drift here would cause
        bond cashflow mismatches in the parity tests above.
        """
        loan = _build_loan(1, group_id=None)
        ldcma_input = _ldcma_input_from_loan(loan)

        paired_input = ldcma_to_paired(ldcma_input)
        portfolio = paired_input.collateral.portfolio
        synth: BMAActualCashflow = portfolio._pending[0]

        # perf_bal should match the LDCMA balance array element-for-element.
        np.testing.assert_array_equal(
            synth.perf_bal, np.asarray(ldcma_input.collateral.collateral.balance),
        )
        # act_int matches LDCMA interest.
        np.testing.assert_array_equal(
            synth.act_int, np.asarray(ldcma_input.collateral.collateral.interest),
        )
