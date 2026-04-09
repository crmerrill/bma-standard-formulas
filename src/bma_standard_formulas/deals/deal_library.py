"""Pre-built deal IR definitions ported from LDCMA Deals_lib.

Each function returns a DealDefinition that faithfully reproduces the
waterfall semantics of its LDCMA Python-module counterpart.
"""
from .schemas.common import (
    AccountType,
    CouponType,
    FeeBasisType,
    MinimumBasis,
    RuleType,
    TrancheType,
    TriggerMetricType,
)
from .schemas.ir import (
    AccountDef,
    BondDef,
    CalculationNode,
    DealDefinition,
    FeeDef,
    RuleNode,
    TriggerNode,
)


def passthrough_deal() -> DealDefinition:
    """Simple passthrough — all collateral cashflow goes to residual."""
    return DealDefinition(
        deal_name="Passthrough",
        bonds=[
            BondDef(name="R", tranche_type=TrancheType.RESIDUAL,
                    is_bond=False, is_pseudo=True),
        ],
        waterfall_rules=[
            RuleNode(rule_id="pay_resid", rule_type=RuleType.PAY_RESIDUAL,
                     order=0, from_sources=["CASH"], to_targets=["R"]),
        ],
    )


def ldcma_3class_2016(
    *,
    class_a_pctbal: float = 70.0,
    class_b_pctbal: float = 10.0,
    class_c_pctbal: float = 10.0,
    class_a_coupon: float = 3.90,
    class_b_coupon: float = 5.50,
    class_c_coupon: float = 7.50,
    reserve_account_pct: float = 0.01,
) -> DealDefinition:
    """Three-class sequential structure with OC, reserve, triggers, and fees.

    Port of LDCMA Deals_lib/LDCMA3CLASS2016.py.
    """
    order = iter(range(100))
    return DealDefinition(
        deal_name="LDCMA3CLASS2016",
        origination_date=None,
        bonds=[
            BondDef(name="A", tranche_type=TrancheType.SEQUENTIAL,
                    coupon=class_a_coupon, size_pct=class_a_pctbal,
                    maturity_date=None, solver_knob_coupon=True, solver_knob_size=True),
            BondDef(name="B", tranche_type=TrancheType.SEQUENTIAL,
                    coupon=class_b_coupon, size_pct=class_b_pctbal,
                    maturity_date=None, solver_knob_coupon=True, solver_knob_size=True),
            BondDef(name="C", tranche_type=TrancheType.SEQUENTIAL,
                    coupon=class_c_coupon, size_pct=class_c_pctbal,
                    maturity_date=None, solver_knob_coupon=True, solver_knob_size=True),
            BondDef(name="SPREAD_ACCT", tranche_type=TrancheType.PSEUDO,
                    is_bond=False, is_pseudo=True),
            BondDef(name="INDENTURE_FEE", tranche_type=TrancheType.PSEUDO,
                    is_bond=False, is_pseudo=True),
            BondDef(name="OWNER_FEE", tranche_type=TrancheType.PSEUDO,
                    is_bond=False, is_pseudo=True),
            BondDef(name="ADMIN_FEE", tranche_type=TrancheType.PSEUDO,
                    is_bond=False, is_pseudo=True),
            BondDef(name="SERVICING_FEE", tranche_type=TrancheType.PSEUDO,
                    is_bond=False, is_pseudo=True),
            BondDef(name="BACKUP_SFEE", tranche_type=TrancheType.PSEUDO,
                    is_bond=False, is_pseudo=True),
            BondDef(name="CUSTODIAN_FEE", tranche_type=TrancheType.PSEUDO,
                    is_bond=False, is_pseudo=True),
            BondDef(name="TRIGGER_CUMLOSS", tranche_type=TrancheType.PSEUDO,
                    is_bond=False, is_pseudo=True),
            BondDef(name="R", tranche_type=TrancheType.RESIDUAL,
                    is_bond=False, is_pseudo=True),
        ],
        triggers=[
            TriggerNode(
                name="TRIGGER_CUMLOSS",
                metric_type=TriggerMetricType.CUMULATIVE_LOSS,
                threshold_schedule=[
                    0.0081, 0.0158, 0.0231, 0.0301, 0.0369, 0.0432, 0.0493,
                    0.0552, 0.0607, 0.0659, 0.0709, 0.0757, 0.0802, 0.0845,
                    0.0885, 0.0923, 0.0959, 0.0993, 0.1025, 0.1056, 0.1084,
                    0.111, 0.1135, 0.1158, 0.1179, 0.1199, 0.1217, 0.1234,
                    0.1249, 0.1263, 0.1276, 0.1289, 0.13, 0.1311, 0.1321,
                    0.1331, 0.1339, 0.1347, 0.1355, 0.1362, 0.1368, 0.1374,
                    0.1379, 0.1384, 0.1388, 0.1392, 0.1395, 0.1397, 0.1399,
                    0.1393, 0.1395, 0.1398, 0.1398, 0.1399,
                ],
            ),
        ],
        waterfall_rules=[
            # --- Fees ---
            RuleNode(rule_id="fee_indenture", rule_type=RuleType.PAY_FEE,
                     order=next(order), from_sources=["CASH"],
                     to_targets=["INDENTURE_FEE"], max_amount_fixed=1250.0),
            RuleNode(rule_id="fee_owner", rule_type=RuleType.PAY_FEE,
                     order=next(order), from_sources=["CASH"],
                     to_targets=["OWNER_FEE"], max_amount_fixed=500.0),
            RuleNode(rule_id="fee_admin", rule_type=RuleType.PAY_FEE,
                     order=next(order), from_sources=["CASH"],
                     to_targets=["ADMIN_FEE"], max_amount_fixed=0.0),
            RuleNode(rule_id="fee_servicing", rule_type=RuleType.PAY_FEE,
                     order=next(order), from_sources=["CASH"],
                     to_targets=["SERVICING_FEE"], max_amount_fixed=5000.0),
            RuleNode(rule_id="fee_backup", rule_type=RuleType.PAY_FEE,
                     order=next(order), from_sources=["CASH"],
                     to_targets=["BACKUP_SFEE"], max_amount_fixed=0.0),
            RuleNode(rule_id="fee_custodian", rule_type=RuleType.PAY_FEE,
                     order=next(order), from_sources=["CASH"],
                     to_targets=["CUSTODIAN_FEE"], max_amount_fixed=0.0),
            # --- Interest (A, B, C) ---
            RuleNode(rule_id="int_a", rule_type=RuleType.PAY_INTEREST,
                     order=next(order), from_sources=["CASH"], to_targets=["A"]),
            RuleNode(rule_id="int_a_sf", rule_type=RuleType.PAY_INTEREST_SHORTFALL,
                     order=next(order), from_sources=["CASH"], to_targets=["A"]),
            RuleNode(rule_id="prin_a_pda1", rule_type=RuleType.PAY_PRINCIPAL,
                     order=next(order), from_sources=["CASH"], to_targets=["A"]),
            RuleNode(rule_id="int_b", rule_type=RuleType.PAY_INTEREST,
                     order=next(order), from_sources=["CASH"], to_targets=["B"]),
            RuleNode(rule_id="int_b_sf", rule_type=RuleType.PAY_INTEREST_SHORTFALL,
                     order=next(order), from_sources=["CASH"], to_targets=["B"]),
            RuleNode(rule_id="prin_ab_pda2", rule_type=RuleType.PAY_PRINCIPAL,
                     order=next(order), from_sources=["CASH"], to_targets=["A"]),
            RuleNode(rule_id="prin_b_pda2", rule_type=RuleType.PAY_PRINCIPAL,
                     order=next(order), from_sources=["CASH"], to_targets=["B"]),
            RuleNode(rule_id="int_c", rule_type=RuleType.PAY_INTEREST,
                     order=next(order), from_sources=["CASH"], to_targets=["C"]),
            RuleNode(rule_id="int_c_sf", rule_type=RuleType.PAY_INTEREST_SHORTFALL,
                     order=next(order), from_sources=["CASH"], to_targets=["C"]),
            # --- Reserve interest payments ---
            RuleNode(rule_id="res_int_a", rule_type=RuleType.PAY_FROM_RESERVE_INTEREST,
                     order=next(order), from_sources=["CASH"], to_targets=["A"],
                     reserve_account="SPREAD_ACCT"),
            RuleNode(rule_id="res_int_a_sf", rule_type=RuleType.PAY_FROM_RESERVE_INTEREST,
                     order=next(order), from_sources=["CASH"], to_targets=["A"],
                     reserve_account="SPREAD_ACCT"),
            RuleNode(rule_id="res_prin_a", rule_type=RuleType.PAY_FROM_RESERVE_PRINCIPAL,
                     order=next(order), from_sources=["CASH"], to_targets=["A"],
                     reserve_account="SPREAD_ACCT"),
            RuleNode(rule_id="res_int_b", rule_type=RuleType.PAY_FROM_RESERVE_INTEREST,
                     order=next(order), from_sources=["CASH"], to_targets=["B"],
                     reserve_account="SPREAD_ACCT"),
            RuleNode(rule_id="res_int_b_sf", rule_type=RuleType.PAY_FROM_RESERVE_INTEREST,
                     order=next(order), from_sources=["CASH"], to_targets=["B"],
                     reserve_account="SPREAD_ACCT"),
            RuleNode(rule_id="res_prin_ab2", rule_type=RuleType.PAY_FROM_RESERVE_PRINCIPAL,
                     order=next(order), from_sources=["CASH"], to_targets=["A"],
                     reserve_account="SPREAD_ACCT"),
            RuleNode(rule_id="res_prin_b2", rule_type=RuleType.PAY_FROM_RESERVE_PRINCIPAL,
                     order=next(order), from_sources=["CASH"], to_targets=["B"],
                     reserve_account="SPREAD_ACCT"),
            RuleNode(rule_id="res_int_c", rule_type=RuleType.PAY_FROM_RESERVE_INTEREST,
                     order=next(order), from_sources=["CASH"], to_targets=["C"],
                     reserve_account="SPREAD_ACCT"),
            RuleNode(rule_id="res_int_c_sf", rule_type=RuleType.PAY_FROM_RESERVE_INTEREST,
                     order=next(order), from_sources=["CASH"], to_targets=["C"],
                     reserve_account="SPREAD_ACCT"),
            # --- Reserve funding ---
            RuleNode(rule_id="fund_reserve", rule_type=RuleType.PAY_TO_RESERVE,
                     order=next(order), from_sources=["CASH"],
                     to_targets=["SPREAD_ACCT"]),
            # --- Regular principal (A, B, C) ---
            RuleNode(rule_id="reg_prin_a", rule_type=RuleType.PAY_PRINCIPAL,
                     order=next(order), from_sources=["CASH"], to_targets=["A"]),
            RuleNode(rule_id="reg_prin_b", rule_type=RuleType.PAY_PRINCIPAL,
                     order=next(order), from_sources=["CASH"], to_targets=["B"]),
            RuleNode(rule_id="reg_prin_c", rule_type=RuleType.PAY_PRINCIPAL,
                     order=next(order), from_sources=["CASH"], to_targets=["C"]),
            # --- Residual ---
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL,
                     order=next(order), from_sources=["CASH"], to_targets=["R"]),
        ],
        deal_knobs={
            "class_a_pctbal": class_a_pctbal,
            "class_b_pctbal": class_b_pctbal,
            "class_c_pctbal": class_c_pctbal,
            "class_a_coupon": class_a_coupon,
            "class_b_coupon": class_b_coupon,
            "class_c_coupon": class_c_coupon,
            "reserve_account_pct": reserve_account_pct,
        },
    )


def jumbo_sequential() -> DealDefinition:
    """Six-tranche sequential with IO strip and MSR pseudo-bond.

    Port of LDCMA Deals_lib/JUMBO17.py.
    """
    order = iter(range(100))
    return DealDefinition(
        deal_name="JUMBO17",
        bonds=[
            BondDef(name="SNR", tranche_type=TrancheType.SEQUENTIAL,
                    coupon=3.5, size_pct=94.0),
            BondDef(name="SNR_IO", tranche_type=TrancheType.IO,
                    coupon=0.3245, size_pct=94.0,
                    is_bond=True, is_pseudo=True),
            BondDef(name="B1", tranche_type=TrancheType.SEQUENTIAL,
                    coupon=3.8245, size_pct=1.27),
            BondDef(name="B2", tranche_type=TrancheType.SEQUENTIAL,
                    coupon=3.8245, size_pct=1.19),
            BondDef(name="B3", tranche_type=TrancheType.SEQUENTIAL,
                    coupon=3.8245, size_pct=1.41),
            BondDef(name="B4", tranche_type=TrancheType.SEQUENTIAL,
                    coupon=3.8245, size_pct=1.05),
            BondDef(name="B5", tranche_type=TrancheType.SEQUENTIAL,
                    coupon=3.9101, size_pct=1.08),
            BondDef(name="MSR", tranche_type=TrancheType.PSEUDO,
                    coupon=0.25, size_pct=100.0,
                    is_bond=True, is_pseudo=True),
            BondDef(name="R", tranche_type=TrancheType.RESIDUAL,
                    is_bond=False, is_pseudo=True),
        ],
        waterfall_rules=[
            # MSR servicing fee
            RuleNode(rule_id="msr_fee", rule_type=RuleType.PAY_FEE,
                     order=next(order), from_sources=["CASH"], to_targets=["MSR"]),
            # Interest
            RuleNode(rule_id="int_snr", rule_type=RuleType.PAY_INTEREST,
                     order=next(order), from_sources=["CASH"], to_targets=["SNR"]),
            RuleNode(rule_id="int_snr_io", rule_type=RuleType.PAY_FEE,
                     order=next(order), from_sources=["CASH"], to_targets=["SNR_IO"]),
            RuleNode(rule_id="int_b1", rule_type=RuleType.PAY_INTEREST,
                     order=next(order), from_sources=["CASH"], to_targets=["B1"]),
            RuleNode(rule_id="int_b2", rule_type=RuleType.PAY_INTEREST,
                     order=next(order), from_sources=["CASH"], to_targets=["B2"]),
            RuleNode(rule_id="int_b3", rule_type=RuleType.PAY_INTEREST,
                     order=next(order), from_sources=["CASH"], to_targets=["B3"]),
            RuleNode(rule_id="int_b4", rule_type=RuleType.PAY_INTEREST,
                     order=next(order), from_sources=["CASH"], to_targets=["B4"]),
            RuleNode(rule_id="int_b5", rule_type=RuleType.PAY_INTEREST,
                     order=next(order), from_sources=["CASH"], to_targets=["B5"]),
            # Principal (sequential)
            RuleNode(rule_id="prin_snr", rule_type=RuleType.PAY_PRINCIPAL,
                     order=next(order), from_sources=["CASH"], to_targets=["SNR"]),
            RuleNode(rule_id="prin_b1", rule_type=RuleType.PAY_PRINCIPAL,
                     order=next(order), from_sources=["CASH"], to_targets=["B1"]),
            RuleNode(rule_id="prin_b2", rule_type=RuleType.PAY_PRINCIPAL,
                     order=next(order), from_sources=["CASH"], to_targets=["B2"]),
            RuleNode(rule_id="prin_b3", rule_type=RuleType.PAY_PRINCIPAL,
                     order=next(order), from_sources=["CASH"], to_targets=["B3"]),
            RuleNode(rule_id="prin_b4", rule_type=RuleType.PAY_PRINCIPAL,
                     order=next(order), from_sources=["CASH"], to_targets=["B4"]),
            RuleNode(rule_id="prin_b5", rule_type=RuleType.PAY_PRINCIPAL,
                     order=next(order), from_sources=["CASH"], to_targets=["B5"]),
            # Writedowns (reverse seniority)
            RuleNode(rule_id="wd_b5", rule_type=RuleType.PAY_WRITEDOWN,
                     order=next(order), from_sources=["CASH"], to_targets=["B5"]),
            RuleNode(rule_id="wd_b4", rule_type=RuleType.PAY_WRITEDOWN,
                     order=next(order), from_sources=["CASH"], to_targets=["B4"]),
            RuleNode(rule_id="wd_b3", rule_type=RuleType.PAY_WRITEDOWN,
                     order=next(order), from_sources=["CASH"], to_targets=["B3"]),
            RuleNode(rule_id="wd_b2", rule_type=RuleType.PAY_WRITEDOWN,
                     order=next(order), from_sources=["CASH"], to_targets=["B2"]),
            RuleNode(rule_id="wd_b1", rule_type=RuleType.PAY_WRITEDOWN,
                     order=next(order), from_sources=["CASH"], to_targets=["B1"]),
            RuleNode(rule_id="wd_snr", rule_type=RuleType.PAY_WRITEDOWN,
                     order=next(order), from_sources=["CASH"], to_targets=["SNR"]),
            # Residual
            RuleNode(rule_id="resid", rule_type=RuleType.PAY_RESIDUAL,
                     order=next(order), from_sources=["CASH"], to_targets=["R"]),
        ],
    )
