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

IR translation:

  - Per-bond `schedule_contract` is derived from the published Aggregate
    Group I / Group II planned balance vectors via
    ``_per_bond_planned_balance_schedule`` (sequential apportionment).
  - Z is modeled with ``kind=Z``, ``pay_mode=PIK``,
    ``supported_by_tranches=["TA", "TB"]``.
  - Step 4 face-weighted split is expressed with the IR's ``SPLIT_CASH``
    primitive: ACT_PRIN -> WAWG_BUCKET / PO_BUCKET (95.65 / 4.35), each
    bucket feeds its own PAY_PRINCIPAL cascade, leftover sweeps back to
    ACT_PRIN via N->1 merge for the cleanup phase.

GSE guaranty wedge:

  The 0.44% wedge between gross WAC (5.94%) and the MBS pass-through rate
  (5.50%) is **not** modeled as a trust-level FeeDef. Each underlying
  Fannie Mae MBS pool delivers ONLY the 5.50% pass-through rate to the
  REMIC trust; the wedge is netted at the MBS layer by Fannie Mae as the
  guarantor and never enters the REMIC waterfall. The fixture therefore
  configures each sub-repline ``Loan`` with
  ``servicing_fee = wac_gross - net_pass_through``, which makes BMA's
  ``act_int`` already net of the wedge by the time it reaches
  ``from_actual_cashflow`` and the deal engine. Modeling the wedge as a
  trust-level fee would double-count it.

  The IR's ``FeeDef`` + ``PAY_FEE`` primitives remain the right
  abstraction for deals where fees ARE deducted at the trust waterfall
  (e.g., private-label master servicer, trustee, third-party servicing
  fees, OC test pre-fund deposits, etc.).
"""
from __future__ import annotations

from typing import Any

from bma_standard_formulas.deals.schemas.common import (
    CapMode,
    CouponType,
    PayMode,
    PaymentStyle,
    RuleType,
    TrancheKind,
    TrancheRelationType,
)
from bma_standard_formulas.deals.schemas.ir import (
    BondDef,
    CollateralGroupDef,
    DealDefinition,
    RuleNode,
    TrancheRelation,
)

from . import (
    GROUP_1_CLASSES,
    expand_to_monthly_balance_vector,
    load_planned_balance_schedule,
)


def _per_bond_planned_balance_schedule(
    aggregate_balance_vector: list[float],
    bonds_in_aggregate: list[dict],
    bond_name: str,
    horizon_periods: int,
) -> list[dict[str, float]]:
    """Derive a per-bond planned-balance vector from the aggregate planned balance.

    Within an aggregate paid sequentially (PA first to zero, then PB, ...), the
    senior class's planned balance at period t equals the aggregate planned
    balance minus the sum of the more-junior classes' faces, capped at the
    senior class's own face. Once the senior class reaches zero, the next class
    starts paying down. Returned entries are `{period, target_balance}`
    consumable by the runtime's `to-Planned-Balance` schedule cap semantics.
    """
    seniority_order = [b["name"] for b in bonds_in_aggregate]
    if bond_name not in seniority_order:
        return []
    bond_idx = seniority_order.index(bond_name)
    junior_face_total = sum(
        float(b["size"]) for b in bonds_in_aggregate[bond_idx + 1:]
    )
    bond_face = float(bonds_in_aggregate[bond_idx]["size"])

    out: list[dict[str, float]] = []
    last_emitted: float | None = None
    horizon = min(len(aggregate_balance_vector), horizon_periods + 1)
    for period in range(horizon):
        agg_balance = float(aggregate_balance_vector[period])
        # The bond owns whatever portion of the aggregate is above the junior
        # class faces, capped at its own face.
        planned_balance = max(0.0, agg_balance - junior_face_total)
        planned_balance = min(planned_balance, bond_face)
        rounded = round(planned_balance, 2)
        # Only emit on changes (forward-fill is handled by the runtime).
        if last_emitted is None or rounded != last_emitted:
            out.append({"period": period, "target_balance": rounded})
            last_emitted = rounded
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
    # Use the dense monthly aggregate planned balance vector (forward-filled
    # across published "lockout" gaps) so per-bond derivation is consistent
    # with the runtime's "to Planned Balance" semantics.
    pac_i_balances = load_planned_balance_schedule("I")
    pac_ii_balances = load_planned_balance_schedule("II")
    pac_i_monthly = expand_to_monthly_balance_vector(pac_i_balances, n_periods)
    pac_ii_monthly = expand_to_monthly_balance_vector(pac_ii_balances, n_periods)

    pac_i_bond_specs = [c for c in GROUP_1_CLASSES if c["type"] in ("PAC", "PAC_PO")]
    pac_ii_bond_specs = [c for c in GROUP_1_CLASSES if c["type"] == "PAC_AD"]
    z_bond_spec = next(c for c in GROUP_1_CLASSES if c["type"] == "Z_BOND")
    sup_bond_specs = [c for c in GROUP_1_CLASSES if c["type"] == "SUP"]
    sup_po_spec = next(c for c in GROUP_1_CLASSES if c["type"] == "SUP_PO")

    bonds: list[BondDef] = []
    for spec in pac_i_bond_specs:
        per_bond = _per_bond_planned_balance_schedule(
            pac_i_monthly, pac_i_bond_specs, spec["name"], n_periods
        )
        bonds.append(BondDef(
            name=spec["name"],
            kind=TrancheKind.PAC,
            coupon_type=CouponType.FIXED if spec["type"] == "PAC" else CouponType.ZERO,
            coupon=spec["coupon_pct"] if spec["coupon_pct"] > 0 else None,
            notional=spec["size"],
            schedule_contract=per_bond,
            relations=[
                TrancheRelation(
                    relation_type=TrancheRelationType.SUPPORTED_BY,
                    targets=[s["name"] for s in sup_bond_specs] + ["PO"],
                )
            ],
        ))
    for spec in pac_ii_bond_specs:
        per_bond = _per_bond_planned_balance_schedule(
            pac_ii_monthly, pac_ii_bond_specs, spec["name"], n_periods
        )
        bonds.append(BondDef(
            name=spec["name"],
            kind=TrancheKind.PAC,
            coupon_type=CouponType.FIXED,
            coupon=spec["coupon_pct"],
            notional=spec["size"],
            schedule_contract=per_bond,
            relations=[
                TrancheRelation(
                    relation_type=TrancheRelationType.SUPPORTED_BY,
                    targets=[s["name"] for s in sup_bond_specs] + ["PO"],
                )
            ],
        ))
    bonds.append(BondDef(
        name=z_bond_spec["name"],
        kind=TrancheKind.Z,
        pay_mode=PayMode.PIK,
        coupon_type=CouponType.FIXED,
        coupon=z_bond_spec["coupon_pct"],
        notional=z_bond_spec["size"],
        z_accrual_enabled=True,
        # Z accrual is paid as principal of TA then TB until each reaches zero.
        relations=[
            TrancheRelation(
                relation_type=TrancheRelationType.ACCRETES_TO,
                targets=["TA", "TB"],
            )
        ],
    ))
    bonds.append(BondDef(
        name=sup_po_spec["name"],
        kind=TrancheKind.CASH_PAY,
        coupon_type=CouponType.ZERO,
        coupon=None,
        notional=sup_po_spec["size"],
    ))
    for spec in sup_bond_specs:
        bonds.append(BondDef(
            name=spec["name"],
            kind=TrancheKind.CASH_PAY,
            coupon_type=CouponType.FIXED,
            coupon=spec["coupon_pct"],
            notional=spec["size"],
        ))
    bonds.append(BondDef(
        name="R",
        kind=TrancheKind.RESIDUAL,
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
        cap_mode: CapMode | None = None,
        target_weights: list[float] | None = None,
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
            cap_mode=cap_mode,
            target_weights=target_weights,
        ))
        order += 1

    # 1. Interest cascade: PAY_INTEREST rules draw from the dedicated
    #    `ACT_INT` stream (pool interest cash). Z is PIK -- its accrued
    #    coupon is capitalized into Z balance and re-routed to TA principal
    #    by the Z-accrual mechanic, with the matching pool interest deducted
    #    from ACT_INT so the principal cascade sees only true pool principal.
    for name in pac_i_targets + pac_ii_targets + sup_targets_seq:
        if name == "EO" or name == "PO":  # zero-coupon bonds, no interest payment.
            continue
        add(f"r_int_{name}", RuleType.PAY_INTEREST, ["ACT_INT"], [name])

    # 2. Principal cascade: PAY_PRINCIPAL rules draw from the dedicated
    #    `ACT_PRIN` stream (pool principal cash + Z accrual amount routed
    #    here via the Z mechanic). This is the prospectus's "Group 1 Cash
    #    Flow Distribution Amount" priority of payments verbatim.
    for name in pac_i_targets:
        add(f"r_prin_{name}", RuleType.PAY_PRINCIPAL, ["ACT_PRIN"], [name])
    for name in pac_ii_targets:
        add(f"r_prin_{name}", RuleType.PAY_PRINCIPAL, ["ACT_PRIN"], [name])
    add("r_prin_Z", RuleType.PAY_PRINCIPAL, ["ACT_PRIN"], ["Z"])

    # Step 4 -- Support cash split using the SPLIT_CASH IR primitive.
    # The prospectus directs 95.6521694276% of remaining principal cash to
    # WA-WG sequentially and 4.3478305724% to PO; the ratio is exactly the
    # face-weighted split of (WA+WB+...+WG) vs PO, so both buckets retire
    # at the same time when the support stack is fully funded.
    #
    # SPLIT_CASH drains ACT_PRIN and writes the two buckets:
    #   ACT_PRIN -> WAWG_BUCKET (95.65%)
    #              -> PO_BUCKET   (4.35%)
    # Then PAY_PRINCIPAL rules pull from each bucket independently. Any
    # cash left in either bucket after the support bonds retire flows back
    # to ACT_PRIN via a sweep-back SPLIT_CASH (N -> 1 merge) so the
    # cleanup cascade can drain it.
    add(
        "r_supp_split",
        RuleType.SPLIT_CASH,
        ["ACT_PRIN"],
        ["WAWG_BUCKET", "PO_BUCKET"],
        target_weights=[0.956521694276, 0.043478305724],
    )
    add(
        "r_pay_wawg",
        RuleType.PAY_PRINCIPAL,
        ["WAWG_BUCKET"],
        sup_targets_seq,
    )
    add(
        "r_prin_PO",
        RuleType.PAY_PRINCIPAL,
        ["PO_BUCKET"],
        ["PO"],
    )
    # Sweep both support buckets back into ACT_PRIN so the cleanup cascade
    # below can drain any residual to remaining PAC bonds.
    add(
        "r_supp_sweep_back",
        RuleType.SPLIT_CASH,
        ["WAWG_BUCKET", "PO_BUCKET"],
        ["ACT_PRIN"],
        target_weights=[1.0],
    )
    # 6 + 7 + cleanup-all. Modular cleanup pattern: every outstanding bond
    # gets a "to zero" rule with `cap_mode=NONE` after the support cascade
    # so leftover principal cash drains to whoever still has balance. This
    # is the prospectus's "without regard to Planned Balance" pattern
    # (steps v + vi), generalized to cover the support PO as well so PO
    # is not stranded when WA-WG retire ahead of schedule.
    #
    # Order: PAC II first, then PAC I, then supports + PO. This matches
    # the prospectus's steps (v) and (vi) for PAC, and ensures the
    # support PO drains last (after PAC cleanup) so we do not accidentally
    # steal cash that the published priority sends to PAC II/I cleanup.
    for name in pac_ii_targets:
        add(
            f"r_prin_{name}_uncapped",
            RuleType.PAY_PRINCIPAL,
            ["ACT_PRIN"],
            [name],
            cap_mode=CapMode.NONE,
        )
    for name in pac_i_targets:
        add(
            f"r_prin_{name}_uncapped",
            RuleType.PAY_PRINCIPAL,
            ["ACT_PRIN"],
            [name],
            cap_mode=CapMode.NONE,
        )
    # Support cleanup -- supports + PO each get a final "to zero" rule so
    # tail-period residual principal that survives the face-weighted split
    # (e.g., when WA-WG retire one period before PO does) drains to whoever
    # still has balance.
    for name in sup_targets_seq + ["PO"]:
        add(
            f"r_prin_{name}_uncapped",
            RuleType.PAY_PRINCIPAL,
            ["ACT_PRIN"],
            [name],
            cap_mode=CapMode.NONE,
        )
    # Residual sweeps both streams: leftover pool interest (after bond cash
    # interest and Z accrual) plus leftover pool principal (e.g., after
    # cleanup rules retire all bonds) flow to the residual class.
    add("r_resid_int", RuleType.PAY_RESIDUAL, ["ACT_INT"], ["R"])
    add("r_resid_prin", RuleType.PAY_RESIDUAL, ["ACT_PRIN"], ["R"])

    return DealDefinition(
        deal_name="FNR 2006-018 Group 1",
        bonds=bonds,
        waterfall_rules=rules,
    )


def build_fnr_2006_018_group_2_deal(n_periods: int = 240) -> DealDefinition:
    """Construct the FNR 2006-018 Group 2 sub-deal DealDefinition.

    Group 2 is a pure 4-class sequential cascade (BA -> BC -> BD -> DO)
    plus a notional IO class (DI) whose balance tracks DO. The waterfall
    is verbatim from prospectus S-18:

        "On each Distribution Date, we will pay the Group 2 Principal
        Distribution Amount, sequentially, as principal of the BA, BC,
        BD and DO Classes, in that order, until their principal balances
        are reduced to zero."

    Parameters
    ----------
    n_periods:
        Number of cashflow periods to model. The pool's natural maturity
        is 240 (= original term) but at faster PSA the deal retires in
        well under 240 periods.
    """
    from . import GROUP_2_CLASSES  # local import to avoid cycle

    classes_by_type: dict[str, list[dict]] = {}
    for spec in GROUP_2_CLASSES:
        classes_by_type.setdefault(spec["type"], []).append(spec)

    seq_specs = classes_by_type.get("SEQ", [])
    seq_po = classes_by_type["SEQ_PO"][0]
    ntl_io = classes_by_type["NTL_IO"][0]

    bonds: list[BondDef] = []
    # BA / BC / BD: sequential 5.50% bonds.
    for spec in seq_specs:
        bonds.append(BondDef(
            name=spec["name"],
            kind=TrancheKind.CASH_PAY,
            coupon_type=CouponType.FIXED,
            coupon=spec["coupon_pct"],
            notional=spec["size"],
        ))
    # DO: zero-coupon principal-only.
    bonds.append(BondDef(
        name=seq_po["name"],
        kind=TrancheKind.CASH_PAY,
        coupon_type=CouponType.ZERO,
        coupon=None,
        notional=seq_po["size"],
    ))
    # DI: notional interest-only that strips DO's interest. `tracks_bonds`
    # syncs DI.balance to DO.balance post-waterfall each period; DI's
    # opt_interest is then computed at next period start as
    # DI.balance[i-1] * coupon / 1200, which equals DO.balance[i-1] *
    # coupon / 1200 -- the IO accrues only on the unpaid DO balance.
    bonds.append(BondDef(
        name=ntl_io["name"],
        kind=TrancheKind.CASH_PAY,
        coupon_type=CouponType.FIXED,
        coupon=ntl_io["coupon_pct"],
        notional=ntl_io["size"],
        relations=[
            TrancheRelation(
                relation_type=TrancheRelationType.NOTIONAL_TRACKS,
                targets=[seq_po["name"]],
            )
        ],
    ))
    bonds.append(BondDef(
        name="R",
        kind=TrancheKind.RESIDUAL,
        is_bond=False,
        is_pseudo=True,
    ))

    rules: list[RuleNode] = []
    order = 0

    def add(rule_id, rule_type, sources, targets, cap_mode=None):
        nonlocal order
        rules.append(RuleNode(
            rule_id=rule_id,
            rule_type=rule_type,
            order=order,
            from_sources=sources,
            to_targets=targets,
            cap_mode=cap_mode,
        ))
        order += 1

    interest_targets = [s["name"] for s in seq_specs] + [ntl_io["name"]]
    principal_targets = [s["name"] for s in seq_specs] + [seq_po["name"]]

    # 1. Pay interest on each cash-paying bond from ACT_INT.
    for name in interest_targets:
        add(f"r_int_{name}", RuleType.PAY_INTEREST, ["ACT_INT"], [name])

    # 2. Sequential principal cascade BA -> BC -> BD -> DO from ACT_PRIN.
    for name in principal_targets:
        add(f"r_prin_{name}", RuleType.PAY_PRINCIPAL, ["ACT_PRIN"], [name])

    # 3. Cleanup cascade: every bond gets a `cap_mode=NONE` rule so any
    # leftover principal cash drains to whoever still has balance.
    for name in principal_targets:
        add(
            f"r_prin_{name}_uncapped",
            RuleType.PAY_PRINCIPAL,
            ["ACT_PRIN"],
            [name],
            cap_mode=CapMode.NONE,
        )

    # 4. Residual sweeps both streams.
    add("r_resid_int", RuleType.PAY_RESIDUAL, ["ACT_INT"], ["R"])
    add("r_resid_prin", RuleType.PAY_RESIDUAL, ["ACT_PRIN"], ["R"])

    return DealDefinition(
        deal_name="FNR 2006-018 Group 2",
        bonds=bonds,
        waterfall_rules=rules,
    )


# ---------------------------------------------------------------------------
# Combined two-group deal definition (full FNR 2006-018 trust)
# ---------------------------------------------------------------------------


def build_fnr_2006_018_combined_deal(
    n_periods_group_1: int = 360,
    n_periods_group_2: int = 240,
) -> DealDefinition:
    """Construct the FNR 2006-018 trust as a single multi-group deal.

    The Fannie Mae REMIC Trust 2006-018 is one prospectus with two
    cash-segregated collateral groups: Group 1 (PAC + Z + Support
    classes; 30-yr collateral) and Group 2 (sequential pay; 20-yr
    collateral). Cash from Group 1 collateral pays only Group 1
    bonds; cash from Group 2 collateral pays only Group 2 bonds. The
    residual is shared.

    The combined deal definition declares two collateral groups and
    tags every bond and every cashflow-touching waterfall rule with
    its `group_id`. The runtime then routes each rule's bare
    `ACT_INT` / `ACT_PRIN` / `CASH` tokens through that group's
    cash arrays so the two groups stay financially independent
    inside one IR.

    Parameters
    ----------
    n_periods_group_1 :
        Cashflow horizon for Group 1 bonds (default 360, matches the
        30-yr aggregate term).
    n_periods_group_2 :
        Cashflow horizon for Group 2 bonds (default 240, matches the
        20-yr term).
    """
    g1 = build_fnr_2006_018_group_1_deal(n_periods=n_periods_group_1)
    g2 = build_fnr_2006_018_group_2_deal(n_periods=n_periods_group_2)

    # Helper: tag every non-pseudo bond with its group_id; carry the
    # rest of the bond definition through unchanged.
    def _tag_bond(bond: BondDef, group_id: str) -> BondDef:
        if bond.is_pseudo:
            # The shared residual class lives outside any single group
            # so it can absorb leftover cash from both. Pseudo bonds
            # leave group_id null per the schema rule.
            return bond
        return bond.model_copy(update={"group_id": group_id})

    # Helper: tag every rule (except residual sweeps, which we replace
    # below with per-group sweeps).
    def _tag_rule(rule: RuleNode, group_id: str, order_offset: int) -> RuleNode:
        return rule.model_copy(
            update={
                "rule_id": f"{group_id}__{rule.rule_id}",
                "group_id": group_id,
                "order": rule.order + order_offset,
            },
        )

    # Bonds: tag each non-pseudo bond with its group; deduplicate the
    # residual class (both sub-deals declare "R", we keep one shared).
    g1_bonds_tagged = [_tag_bond(b, "GROUP_1") for b in g1.bonds]
    g2_bonds_tagged = [
        _tag_bond(b, "GROUP_2") for b in g2.bonds if b.name != "R"
    ]
    bonds: list[BondDef] = g1_bonds_tagged + g2_bonds_tagged

    # Rules: tag each rule with its group; offset Group 2's rule
    # `order` so the combined waterfall fires Group 1 first then
    # Group 2 (the actual prospectus runs them in parallel each
    # period; sequencing them here is mathematically equivalent
    # because the runtime fully advances state through Group 1's
    # rules before it touches Group 2's per-group cash arrays).
    rules: list[RuleNode] = []
    g1_max_order = max((r.order for r in g1.waterfall_rules), default=-1)
    rules.extend(_tag_rule(r, "GROUP_1", 0) for r in g1.waterfall_rules)
    rules.extend(
        _tag_rule(r, "GROUP_2", g1_max_order + 1) for r in g2.waterfall_rules
    )

    return DealDefinition(
        deal_name="FNR 2006-018 (Group 1 + Group 2)",
        description=(
            "Fannie Mae REMIC Trust 2006-018, full deal: Group 1 "
            "(PAC + Z + Support, 30-yr) + Group 2 (Sequential, 20-yr). "
            "Each group's collateral is segregated; bonds and rules "
            "are tagged with `group_id` so cashflows do not cross."
        ),
        bonds=bonds,
        waterfall_rules=rules,
        collateral_groups=[
            CollateralGroupDef(
                group_id="GROUP_1",
                label="Group 1 (PAC + Z + Support)",
                description=(
                    "30-year aggregate at 5.94% gross / 5.50% net "
                    "pass-through. Two sub-replines blended for "
                    "$132.65MM UPB. Pays PA-PD, EI, EO, TA-TB, ZA, "
                    "WA-WG, PO."
                ),
            ),
            CollateralGroupDef(
                group_id="GROUP_2",
                label="Group 2 (Sequential)",
                description=(
                    "20-year repline at 5.94% gross / 5.50% net "
                    "pass-through. $128.625MM UPB. Pays BA, BC, BD, "
                    "DO sequentially with DI as a notional IO."
                ),
            ),
        ],
    )
