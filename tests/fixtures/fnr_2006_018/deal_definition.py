"""DealDefinition factory for FNR 2006-018 Group 1 (PAC + Z + Support).

Mirrors the prospectus Group 1 waterfall:

  Z accrual amount:
    1. To Aggregate Group II to its Planned Balance
    2. Then to Z Class

  Group 1 cash flow:
    1. To Aggregate Group I to its Planned Balance (PA -> PB -> PC -> PD -> EO sequential)
    2. To Aggregate Group II to its Planned Balance (TA -> TB sequential)
    3. To Z Class to zero
    4a. 95.6521694276% to WA -> WB -> WC -> WD -> WE -> WG sequential to zero
    4b. 4.3478305724% to PO to zero
    5. To Aggregate Group II to zero (no schedule)
    6. To Aggregate Group I to zero (no schedule)

For runtime IR, schedules become per-bond `schedule_contract` derived from the
published Aggregate Group I / Group II planned balance vectors. The Z bond is
modeled with `tranche_behavior=Z`, `pay_mode=PIK`, `supported_by_tranches`
pointing at TA then TB.
"""
from __future__ import annotations

from typing import Any

from bma_standard_formulas.deals.schemas.common import (
    CouponType,
    PayMode,
    PaymentStyle,
    RuleType,
    TrancheBehavior,
    TrancheType,
)
from bma_standard_formulas.deals.schemas.ir import BondDef, DealDefinition, RuleNode

from . import (
    GROUP_1_CLASSES,
    load_planned_balance_schedule,
    planned_balances_to_principal_schedule,
)


def _per_bond_schedule(
    aggregate_schedule: list[dict[str, float]],
    bond_size: float,
    bonds_in_aggregate: list[dict],
    bond_name: str,
) -> list[dict[str, float]]:
    """Allocate aggregate schedule to one bond using sequential rule within aggregate.

    Within Aggregate Group I, principal pays PA first to zero, then PB, etc.
    Convert the aggregate schedule into per-bond schedules by sequentially
    consuming aggregate principal up to each bond's notional size.
    """
    seniority_order = [b["name"] for b in bonds_in_aggregate]
    if bond_name not in seniority_order:
        return []
    bond_idx = seniority_order.index(bond_name)
    senior_total = sum(b["size"] for b in bonds_in_aggregate[:bond_idx])
    bond_total = bond_total_remaining = bond_size
    senior_remaining = senior_total
    out: list[dict[str, float]] = []
    for entry in aggregate_schedule:
        period = int(entry["period"])
        amount = float(entry["target_principal"])
        if amount <= 0.0:
            continue
        # Senior bonds consume aggregate principal first.
        if senior_remaining > 0.0:
            consumed = min(amount, senior_remaining)
            senior_remaining -= consumed
            amount -= consumed
        if amount <= 0.0 or bond_total_remaining <= 0.0:
            continue
        my_share = min(amount, bond_total_remaining)
        bond_total_remaining -= my_share
        if my_share > 0.0:
            out.append({"period": period, "target_principal": round(my_share, 2)})
    _ = bond_total  # keep unused-name lint quiet (documentation purpose).
    return out


def build_fnr_2006_018_group_1_deal(
    n_periods: int = 360,
) -> DealDefinition:
    """Construct the FNR 2006-018 Group 1 DealDefinition with published schedules.

    Parameters
    ----------
    n_periods:
        Number of cashflow periods to model. Should be >= the deal's final
        scheduled distribution (March 2035 = period ~349).
    """
    pac_i_balances = load_planned_balance_schedule("I")
    pac_ii_balances = load_planned_balance_schedule("II")
    pac_i_aggregate_schedule = planned_balances_to_principal_schedule(pac_i_balances, n_periods)
    pac_ii_aggregate_schedule = planned_balances_to_principal_schedule(pac_ii_balances, n_periods)

    pac_i_bond_specs = [c for c in GROUP_1_CLASSES if c["type"] in ("PAC", "PAC_PO")]
    pac_ii_bond_specs = [c for c in GROUP_1_CLASSES if c["type"] == "PAC_AD"]
    z_bond_spec = next(c for c in GROUP_1_CLASSES if c["type"] == "Z_BOND")
    sup_bond_specs = [c for c in GROUP_1_CLASSES if c["type"] == "SUP"]
    sup_po_spec = next(c for c in GROUP_1_CLASSES if c["type"] == "SUP_PO")

    bonds: list[BondDef] = []
    for spec in pac_i_bond_specs:
        per_bond = _per_bond_schedule(pac_i_aggregate_schedule, spec["size"], pac_i_bond_specs, spec["name"])
        bonds.append(BondDef(
            name=spec["name"],
            tranche_type=TrancheType.PAC,
            tranche_behavior=TrancheBehavior.PAC,
            coupon_type=CouponType.FIXED if spec["type"] == "PAC" else CouponType.ZERO,
            coupon=spec["coupon_pct"] if spec["coupon_pct"] > 0 else None,
            size_dollars=spec["size"],
            schedule_contract=per_bond,
            support_tranches=[s["name"] for s in sup_bond_specs] + ["PO"],
        ))
    for spec in pac_ii_bond_specs:
        per_bond = _per_bond_schedule(pac_ii_aggregate_schedule, spec["size"], pac_ii_bond_specs, spec["name"])
        bonds.append(BondDef(
            name=spec["name"],
            tranche_type=TrancheType.PAC,
            tranche_behavior=TrancheBehavior.PAC,
            coupon_type=CouponType.FIXED,
            coupon=spec["coupon_pct"],
            size_dollars=spec["size"],
            schedule_contract=per_bond,
            support_tranches=[s["name"] for s in sup_bond_specs] + ["PO"],
        ))
    bonds.append(BondDef(
        name=z_bond_spec["name"],
        tranche_type=TrancheType.Z_BOND,
        tranche_behavior=TrancheBehavior.Z,
        pay_mode=PayMode.PIK,
        coupon_type=CouponType.FIXED,
        coupon=z_bond_spec["coupon_pct"],
        size_dollars=z_bond_spec["size"],
        z_accrual_enabled=True,
        # Z accrual is paid as principal of TA then TB until each reaches zero.
        supported_by_tranches=["TA", "TB"],
    ))
    bonds.append(BondDef(
        name=sup_po_spec["name"],
        tranche_type=TrancheType.PO,
        tranche_behavior=TrancheBehavior.SEQUENTIAL,
        coupon_type=CouponType.ZERO,
        coupon=None,
        size_dollars=sup_po_spec["size"],
    ))
    for spec in sup_bond_specs:
        bonds.append(BondDef(
            name=spec["name"],
            tranche_type=TrancheType.SUPPORT,
            tranche_behavior=TrancheBehavior.SEQUENTIAL,
            coupon_type=CouponType.FIXED,
            coupon=spec["coupon_pct"],
            size_dollars=spec["size"],
        ))
    bonds.append(BondDef(
        name="R",
        tranche_type=TrancheType.RESIDUAL,
        is_bond=False,
        is_pseudo=True,
    ))

    pac_i_targets = [c["name"] for c in pac_i_bond_specs]
    pac_ii_targets = [c["name"] for c in pac_ii_bond_specs]
    sup_targets_seq = [c["name"] for c in sup_bond_specs]

    rules: list[RuleNode] = []
    order = 0

    def add(
        rule_id: str,
        rule_type: RuleType,
        sources: list[str],
        targets: list[str],
        style: PaymentStyle = PaymentStyle.SEQUENTIAL,
        max_amount_expr: str | None = None,
        ignore_schedule_cap: bool = False,
    ) -> None:
        nonlocal order
        rules.append(RuleNode(
            rule_id=rule_id,
            rule_type=rule_type,
            order=order,
            from_sources=sources,
            to_targets=targets,
            payment_style=style,
            max_amount_expr=max_amount_expr,
            ignore_schedule_cap=ignore_schedule_cap,
        ))
        order += 1

    # 1. Pay interest on each fixed-coupon bond first (PAC then PAC/AD then SUP);
    #    Z is PIK, gets accrual via runtime _apply_z_accrual instead of cash interest.
    for name in pac_i_targets + pac_ii_targets + sup_targets_seq:
        if name == "EO" or name == "PO":  # zero-coupon bonds, no interest payment.
            continue
        add(f"r_int_{name}", RuleType.PAY_INTEREST, ["CASH"], [name])

    # 2. Principal cascade as published: Group I PAC schedule -> Group II PAC schedule
    #    -> Z -> WA-WG sequential / PO split -> Group II to zero -> Group I to zero.
    for name in pac_i_targets:
        add(f"r_prin_{name}", RuleType.PAY_PRINCIPAL, ["CASH"], [name])
    for name in pac_ii_targets:
        add(f"r_prin_{name}", RuleType.PAY_PRINCIPAL, ["CASH"], [name])
    add("r_prin_Z", RuleType.PAY_PRINCIPAL, ["CASH"], ["Z"])
    # Support cash split (face-weighted pro-rata):
    #   95.6521694276% to WA -> WG sequentially within the share
    #    4.3478305724% to PO
    # Both rules anchor to the cash level at the start of `r_supp_split_anchor`
    # (the first support rule), so PO's allocation is 4.35% of the SAME cash
    # pool that WA-WG draw 95.65% from -- not 4.35% of leftover.
    add(
        "r_supp_split_anchor",
        RuleType.PAY_PRINCIPAL,
        ["CASH"],
        sup_targets_seq,
        max_amount_expr="cash_at_r_supp_split_anchor * 0.956521694276",
    )
    add(
        "r_prin_PO",
        RuleType.PAY_PRINCIPAL,
        ["CASH"],
        ["PO"],
        max_amount_expr="cash_at_r_supp_split_anchor * 0.043478305724",
    )
    # 6 + 7. Aggregate Group II / Group I "to zero" cleanup rules. These run
    # AFTER supports and pay PAC bonds beyond their published planned-balance
    # schedule, so we set `ignore_schedule_cap=True` to bypass the cap.
    for name in pac_ii_targets:
        add(
            f"r_prin_{name}_uncapped",
            RuleType.PAY_PRINCIPAL,
            ["CASH"],
            [name],
            ignore_schedule_cap=True,
        )
    for name in pac_i_targets:
        add(
            f"r_prin_{name}_uncapped",
            RuleType.PAY_PRINCIPAL,
            ["CASH"],
            [name],
            ignore_schedule_cap=True,
        )
    # Residual sweep
    add("r_resid", RuleType.PAY_RESIDUAL, ["CASH"], ["R"])

    return DealDefinition(
        deal_name="FNR 2006-018 Group 1",
        bonds=bonds,
        waterfall_rules=rules,
        deal_knobs={"allow_negative_cashflow_math": False},
    )
