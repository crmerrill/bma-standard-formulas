"""Canonical deal-definition IR schemas (the source of truth for deal structure)."""
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .common import (
    SCHEMA_VERSION,
    AccountCategory,
    AccrualPeriod,
    CapMode,
    CouponType,
    DayCount,
    Dollars,
    FeeBasisType,
    FeeFrequency,
    MinimumBasis,
    PaymentStyle,
    Rate,
    RuleType,
    ScheduleType,
    PrepayModelType,
    StructureRelation,
    TrancheType,
    TriggerMetricType,
    TrancheBehavior,
    PayMode,
)


# ---------------------------------------------------------------------------
# Bond / Tranche definition
# ---------------------------------------------------------------------------


class CollateralGroupDef(BaseModel):
    """A single collateral group within a multi-pool deal.

    Multi-group deals (e.g., Fannie Mae REMIC structures with separate
    REMIC trust groups) carry multiple collateral pools whose cashflows
    are *segregated*: Group 1 collateral pays only Group-1-tagged bonds
    via Group-1-tagged waterfall rules. Each group has its own
    ``GROUP_<id>_CASH`` / ``GROUP_<id>_ACT_INT`` / ``GROUP_<id>_ACT_PRIN``
    source tokens and a parallel ``GROUP_<id>_LOSS`` stream. Bonds and
    rules tagged with a ``group_id`` are scoped to that group.

    Single-pool deals leave ``DealDefinition.collateral_groups`` empty;
    the bare ``CASH`` / ``ACT_INT`` / ``ACT_PRIN`` tokens then refer
    to the single pool unchanged.
    """

    group_id: str = Field(
        min_length=1,
        description="Stable identifier, e.g. 'GROUP_1'. Used as the prefix "
                    "in source tokens like 'GROUP_1_CASH'.",
    )
    label: str = ""
    description: str = ""


class BondDef(BaseModel):
    """Immutable definition of a single tranche in the deal structure."""

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_size_fields(cls, value: Any) -> Any:
        # Hard cut (Phase 2b): do not accept legacy sizing field names.
        if isinstance(value, dict):
            legacy = [
                k for k in ("size_dollars", "size_pct", "schedule_speed_target")
                if k in value
            ]
            if legacy:
                raise ValueError(
                    "BondDef legacy fields are no longer supported; use "
                    "notional/notional_pct_of_collateral and TAC low/high speed band."
                )
        return value

    name: str = Field(min_length=1)
    tranche_type: TrancheType = TrancheType.SEQUENTIAL
    is_bond: bool = True
    is_pseudo: bool = False
    group_id: str | None = Field(
        default=None,
        description="Collateral group this bond is paid from. Required when "
                    "``DealDefinition.collateral_groups`` is non-empty. "
                    "Single-pool deals leave this null.",
    )

    coupon_type: CouponType = CouponType.FIXED
    coupon: Rate | None = None
    margin: Rate | None = None
    index_name: str | None = None
    cap: Rate | None = None
    floor: Rate | None = None
    inverse_multiplier: float | None = None

    notional: Dollars | None = None
    notional_pct_of_collateral: float | None = Field(default=None, ge=0.0, le=100.0)

    maturity_date: date | None = None
    day_count: DayCount = DayCount.THIRTY_360
    accrual_period: AccrualPeriod = AccrualPeriod.MONTHLY

    seniority: int | None = None

    pay_mode: PayMode = PayMode.CASH_PAY
    tranche_behavior: TrancheBehavior = TrancheBehavior.SEQUENTIAL

    # PAC/TAC schedule parameters
    schedule_type: ScheduleType | None = None
    schedule_model_type: PrepayModelType | None = None
    schedule_priority_tier: int | None = None
    schedule_depends_on: str | None = None
    schedule_speed_low: float | None = None
    schedule_speed_high: float | None = None
    schedule_custom_vector: str | None = None
    pac_lower_psa: float | None = None
    pac_upper_psa: float | None = None
    tac_pricing_psa: float | None = None
    schedule_contract: list[dict[str, float | int]] = Field(default_factory=list)
    schedule_derivation: dict[str, Any] | None = Field(
        default=None,
        description="Provenance when schedule_contract was machine-derived (Phase 1i PSA overlay).",
    )
    schedule_tolerance_bps: float | None = None
    support_tranches: list[str] = Field(default_factory=list)
    supported_by_tranches: list[str] = Field(default_factory=list)

    # Z-bond / accrual parameters
    accrual_start_period: int | None = None
    accrual_end_period: int | None = None
    z_accrual_enabled: bool = False
    z_release_trigger: str | None = None

    # Parent-child relationships (floater/inverse, IO/PO)
    parent_tranche: str | None = None
    relation_type: StructureRelation | None = None
    notional_ratio: float | None = None

    # Tracking bonds (pseudo bonds that mirror other bonds)
    tracks_bonds: dict[str, list[str]] | None = None

    # Solver knob flags
    solver_knob_coupon: bool = False
    solver_knob_size: bool = False


# ---------------------------------------------------------------------------
# Account definition
# ---------------------------------------------------------------------------


class AccountDef(BaseModel):
    """Reserve, prefunding, revolving, or payment account."""

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_account_type(cls, value: Any) -> Any:
        # Hard cut (Phase 2a): do not silently migrate legacy field names.
        if isinstance(value, dict) and "account_type" in value:
            raise ValueError(
                "AccountDef.account_type is no longer supported; use account_category."
            )
        return value

    name: str = Field(min_length=1)
    account_category: AccountCategory = AccountCategory.RESERVE
    starting_amount: Dollars = 0.0
    starting_pct: float | None = None
    starting_basis: MinimumBasis = MinimumBasis.FIXED_DOLLAR
    minimum_amount: Dollars = 0.0
    minimum_pct: float | None = None
    minimum_basis: MinimumBasis = MinimumBasis.FIXED_DOLLAR


# ---------------------------------------------------------------------------
# Fee definition
# ---------------------------------------------------------------------------


class FeeDef(BaseModel):
    """A periodic fee paid from the waterfall."""
    name: str = Field(min_length=1)
    basis_type: FeeBasisType = FeeBasisType.FIXED_DOLLAR
    amount: Dollars = 0.0
    amount_expr: str | None = None
    rate: Rate | None = None
    rate_expr: str | None = None
    minimum: Dollars = 0.0
    frequency: FeeFrequency = FeeFrequency.MONTHLY
    cumulative: bool = False


# ---------------------------------------------------------------------------
# Calculation node (formula expressions for triggers / conditions)
# ---------------------------------------------------------------------------


class CalculationNode(BaseModel):
    """A named calculation that can be referenced in triggers and conditions."""
    name: str = Field(min_length=1)
    expression: str = Field(min_length=1)
    description: str = ""


# ---------------------------------------------------------------------------
# Trigger definition
# ---------------------------------------------------------------------------


class TriggerNode(BaseModel):
    """Defines a trigger that can change waterfall behavior."""
    name: str = Field(min_length=1)
    metric_type: TriggerMetricType = TriggerMetricType.CUSTOM
    description: str = ""

    # Static threshold schedule (period -> threshold value)
    threshold_schedule: list[float] | None = None
    threshold_value: float | None = None

    # Reference to a CalculationNode for dynamic thresholds
    calculation_ref: str | None = None
    comparison_ref: str | None = None

    # Cure logic
    cure_periods: int | None = None


# ---------------------------------------------------------------------------
# Waterfall rule (single payment instruction in priority of payments)
# ---------------------------------------------------------------------------


class RuleNode(BaseModel):
    """A single payment rule in the priority-of-payments waterfall."""
    rule_id: str = Field(min_length=1)
    rule_type: RuleType
    order: int = Field(ge=0)
    group_id: str | None = Field(
        default=None,
        description="Collateral group this rule operates on. When set, the "
                    "bare 'CASH'/'ACT_INT'/'ACT_PRIN' tokens in "
                    "from_sources/to_targets are scoped to this group's "
                    "cash streams; equivalent to writing "
                    "'GROUP_<id>_CASH' explicitly. Single-pool deals leave "
                    "this null.",
    )

    from_sources: list[str] = Field(min_length=1)
    to_targets: list[str] = Field(min_length=1)
    reserve_account: str | None = None

    payment_style: PaymentStyle = PaymentStyle.SEQUENTIAL
    max_amount_expr: str | None = None
    max_amount_fixed: Dollars | None = None

    # Per-target weights for `RuleType.SPLIT_CASH`. One entry per
    # `to_targets`, summing to <= 1.0 (the residual stays in `from_sources`).
    # Combined with `from_sources` of length 1 this models a 1->N split; with
    # `to_targets` of length 1 it models a weighted N->1 merge.
    target_weights: list[float] | None = None

    condition_trigger: str | None = None
    condition_invert: bool = False
    condition_expr: str | None = None
    allow_negative_source: bool = False

    # `cap_mode` controls how the rule interprets the target bond's
    # `schedule_contract`. See `CapMode` for the full enum semantics. Maps to
    # prospectus phrasing: PLANNED ("to Planned Balance"), SCHEDULED
    # ("to Scheduled Balance"), TARGETED ("to Targeted Balance"), or NONE
    # ("without regard to ... balance" -> cleanup rule). When omitted, the
    # runtime defaults to PLANNED if the targeted bond carries a schedule and
    # NONE otherwise. Backward compatibility: the legacy `ignore_schedule_cap`
    # field is honored on load -- a True value resolves to NONE during the
    # migration step.
    cap_mode: CapMode | None = None
    ignore_schedule_cap: bool = False  # legacy; superseded by `cap_mode`.

    description: str = ""


# ---------------------------------------------------------------------------
# Top-level deal definition
# ---------------------------------------------------------------------------


class DealDefinition(BaseModel):
    """Complete, self-contained, immutable deal structure definition (the IR)."""
    schema_version: str = SCHEMA_VERSION
    deal_name: str = Field(min_length=1)
    description: str = ""

    origination_date: date | None = None
    settlement_date: date | None = None

    bonds: list[BondDef] = Field(min_length=1)
    accounts: list[AccountDef] = Field(default_factory=list)
    fees: list[FeeDef] = Field(default_factory=list)
    triggers: list[TriggerNode] = Field(default_factory=list)
    calculations: list[CalculationNode] = Field(default_factory=list)
    waterfall_rules: list[RuleNode] = Field(min_length=1)
    collateral_groups: list[CollateralGroupDef] = Field(
        default_factory=list,
        description="Collateral groups for multi-pool deals. Empty list "
                    "(default) means the deal has a single, unnamed pool "
                    "and the bare 'CASH'/'ACT_INT'/'ACT_PRIN' tokens "
                    "refer to it. When non-empty, every BondDef and "
                    "RuleNode that touches collateral cash MUST be tagged "
                    "with a `group_id` matching one of these entries.",
    )

    # Deal-level solver knobs
    deal_knobs: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_references(self) -> "DealDefinition":
        bond_names = {b.name for b in self.bonds}
        account_names = {a.name for a in self.accounts}
        fee_names = {f.name for f in self.fees}
        trigger_names = {t.name for t in self.triggers}
        calc_names = {c.name for c in self.calculations}
        group_ids = {g.group_id for g in self.collateral_groups}
        source_formula_names: set[str] = set()
        raw_source_formulas = self.deal_knobs.get("source_formulas")
        if isinstance(raw_source_formulas, dict):
            source_formula_names = {str(k) for k in raw_source_formulas.keys()}

        # Per-group cashflow stream tokens. For each declared collateral
        # group, the runtime exposes four well-known sources/targets:
        #   GROUP_<id>_CASH      - combined gross collateral cashflow
        #                          (= act_prin + act_int)
        #   GROUP_<id>_ACT_INT   - pool interest only (BMA act_int)
        #   GROUP_<id>_ACT_PRIN  - pool principal only (act_am + vol_prepay)
        #   GROUP_<id>_LOSS      - loss stream for writedowns (BMA prin_loss)
        # Validator accepts any of these as a from_source or to_target.
        BUILTIN_STREAMS = {"CASH", "ACT_INT", "ACT_PRIN", "LOSS"}
        group_stream_names: set[str] = set()
        for gid in group_ids:
            for suffix in BUILTIN_STREAMS:
                group_stream_names.add(f"GROUP_{gid}_{suffix}")
        # Virtual streams declared via SPLIT_CASH targets become valid
        # sources/targets for any subsequent rule. The validator walks the
        # waterfall in declared `order` and accumulates declared streams as
        # it goes, so a SPLIT_CASH at position N can supply downstream rules
        # at positions > N.
        split_streams: set[str] = set()
        for rule in sorted(self.waterfall_rules, key=lambda r: r.order):
            if rule.rule_type == RuleType.SPLIT_CASH:
                for tgt in rule.to_targets:
                    if (
                        tgt not in bond_names
                        and tgt not in account_names
                        and tgt not in fee_names
                        and tgt not in BUILTIN_STREAMS
                        and tgt not in source_formula_names
                    ):
                        split_streams.add(tgt)

        all_targets = bond_names | account_names | fee_names | {"CASH"}
        # Built-in source keys (BMA-native naming):
        #   CASH     = combined gross collateral cashflow (act_prin + act_int)
        #   ACT_INT  = pool interest stream only (BMA act_int)
        #   ACT_PRIN = pool principal stream only (act_am + vol_prepay)
        #   LOSS     = pool loss stream for writedowns (BMA prin_loss)
        # ACT_INT / ACT_PRIN let MBS structures express the standard
        # "interest waterfall + principal waterfall" split without
        # conflating bond cash interest with the principal cascade.
        # Streams declared by SPLIT_CASH `to_targets` are added to both the
        # source and target sets so downstream rules can route cash through
        # them.
        valid_sources = (
            all_targets
            | BUILTIN_STREAMS
            | group_stream_names
            | source_formula_names
            | split_streams
        )
        valid_targets = (
            all_targets
            | split_streams
            | BUILTIN_STREAMS
            | group_stream_names
        )

        errors: list[str] = []
        for rule in self.waterfall_rules:
            for src in rule.from_sources:
                if src not in valid_sources:
                    errors.append(
                        f"Rule {rule.rule_id!r}: from_source {src!r} not found "
                        f"in bonds/accounts/fees/source_formulas/split_streams"
                    )
            for tgt in rule.to_targets:
                if tgt not in valid_targets:
                    errors.append(
                        f"Rule {rule.rule_id!r}: to_target {tgt!r} not found "
                        f"in bonds/accounts/fees/split_streams"
                    )
            if rule.rule_type == RuleType.SPLIT_CASH:
                if rule.target_weights is None:
                    errors.append(
                        f"Rule {rule.rule_id!r}: SPLIT_CASH requires "
                        f"`target_weights`"
                    )
                elif len(rule.target_weights) != len(rule.to_targets):
                    errors.append(
                        f"Rule {rule.rule_id!r}: SPLIT_CASH target_weights "
                        f"length {len(rule.target_weights)} != to_targets "
                        f"length {len(rule.to_targets)}"
                    )
                elif any(w < 0.0 for w in rule.target_weights):
                    errors.append(
                        f"Rule {rule.rule_id!r}: SPLIT_CASH target_weights "
                        f"must all be non-negative"
                    )
                elif sum(rule.target_weights) > 1.0 + 1e-9:
                    errors.append(
                        f"Rule {rule.rule_id!r}: SPLIT_CASH target_weights "
                        f"sum {sum(rule.target_weights):.6f} exceeds 1.0; "
                        f"residual must stay in source streams"
                    )
            if rule.condition_trigger and rule.condition_trigger not in trigger_names:
                errors.append(
                    f"Rule {rule.rule_id!r}: condition_trigger "
                    f"{rule.condition_trigger!r} not found in triggers"
                )

        for trigger in self.triggers:
            if trigger.calculation_ref and trigger.calculation_ref not in calc_names:
                errors.append(
                    f"Trigger {trigger.name!r}: calculation_ref "
                    f"{trigger.calculation_ref!r} not found in calculations"
                )

        # Multi-group consistency: when collateral_groups is set, every
        # bond and rule that touches collateral cash must declare which
        # group it belongs to. Pseudo bonds (fee-pay sinks) are
        # collateral-agnostic and may leave group_id null.
        if group_ids:
            for bond in self.bonds:
                if bond.is_pseudo:
                    continue
                if bond.group_id is None:
                    errors.append(
                        f"Bond {bond.name!r}: deal has collateral_groups "
                        f"declared, so each non-pseudo bond must specify "
                        f"group_id (one of: {sorted(group_ids)})"
                    )
                elif bond.group_id not in group_ids:
                    errors.append(
                        f"Bond {bond.name!r}: group_id {bond.group_id!r} "
                        f"is not among declared collateral_groups "
                        f"{sorted(group_ids)}"
                    )
            for rule in self.waterfall_rules:
                if rule.group_id is not None and rule.group_id not in group_ids:
                    errors.append(
                        f"Rule {rule.rule_id!r}: group_id "
                        f"{rule.group_id!r} is not among declared "
                        f"collateral_groups {sorted(group_ids)}"
                    )
        else:
            # Single-pool deal: group_id should not be set on bonds or rules.
            for bond in self.bonds:
                if bond.group_id is not None:
                    errors.append(
                        f"Bond {bond.name!r}: group_id "
                        f"{bond.group_id!r} is set but deal has no "
                        f"collateral_groups declared"
                    )
            for rule in self.waterfall_rules:
                if rule.group_id is not None:
                    errors.append(
                        f"Rule {rule.rule_id!r}: group_id "
                        f"{rule.group_id!r} is set but deal has no "
                        f"collateral_groups declared"
                    )

        for bond in self.bonds:
            if bond.tracks_bonds:
                for attr, names in bond.tracks_bonds.items():
                    for n in names:
                        if n not in bond_names:
                            errors.append(
                                f"Bond {bond.name!r}: tracks_bonds references "
                                f"unknown bond {n!r}"
                            )
            if bond.tranche_behavior in {TrancheBehavior.PAC, TrancheBehavior.TAC}:
                has_legacy_schedule = bool(bond.schedule_contract)
                has_model = bond.schedule_model_type is not None
                if not has_legacy_schedule and not has_model:
                    errors.append(
                        f"Bond {bond.name!r}: tranche_behavior {bond.tranche_behavior.value} "
                        "requires schedule model or schedule_contract points"
                    )
                if has_model and bond.schedule_model_type == PrepayModelType.CUSTOM_VECTOR:
                    if not (bond.schedule_custom_vector or "").strip():
                        errors.append(
                            f"Bond {bond.name!r}: CUSTOM_VECTOR schedule requires schedule_custom_vector."
                        )
                if has_model and bond.tranche_behavior == TrancheBehavior.PAC:
                    if bond.schedule_model_type != PrepayModelType.CUSTOM_VECTOR:
                        if bond.schedule_speed_low is None or bond.schedule_speed_high is None:
                            errors.append(
                                f"Bond {bond.name!r}: PAC schedule requires low/high speed values."
                            )
                if has_model and bond.tranche_behavior == TrancheBehavior.TAC:
                    if bond.schedule_model_type != PrepayModelType.CUSTOM_VECTOR:
                        if bond.schedule_speed_low is None or bond.schedule_speed_high is None:
                            errors.append(
                                f"Bond {bond.name!r}: TAC schedule requires low/high speed values."
                            )
                        elif abs(float(bond.schedule_speed_low) - float(bond.schedule_speed_high)) > 1e-9:
                            errors.append(
                                f"Bond {bond.name!r}: TAC schedule requires a degenerate band "
                                "(schedule_speed_low == schedule_speed_high)."
                            )
                if not bond.support_tranches and not bond.supported_by_tranches:
                    errors.append(
                        f"Bond {bond.name!r}: tranche_behavior {bond.tranche_behavior.value} "
                        "requires explicit support tranche linkage"
                    )
            if bond.tranche_behavior == TrancheBehavior.Z:
                if not bond.z_accrual_enabled:
                    errors.append(
                        f"Bond {bond.name!r}: tranche_behavior Z requires z_accrual_enabled=true"
                    )
                if bond.pay_mode != PayMode.PIK:
                    errors.append(
                        f"Bond {bond.name!r}: tranche_behavior Z requires pay_mode=PIK"
                    )
                if (
                    bond.accrual_start_period is not None
                    and bond.accrual_end_period is not None
                    and bond.accrual_end_period < bond.accrual_start_period
                ):
                    errors.append(
                        f"Bond {bond.name!r}: accrual_end_period must be >= accrual_start_period"
                    )
                if bond.z_release_trigger and bond.z_release_trigger not in trigger_names:
                    errors.append(
                        f"Bond {bond.name!r}: z_release_trigger {bond.z_release_trigger!r} "
                        f"not found in triggers"
                    )
            for support in bond.support_tranches:
                if support not in bond_names:
                    errors.append(
                        f"Bond {bond.name!r}: support_tranches references unknown bond {support!r}"
                    )
            for supporter in bond.supported_by_tranches:
                if supporter not in bond_names:
                    errors.append(
                        f"Bond {bond.name!r}: supported_by_tranches references unknown bond {supporter!r}"
                    )

        support_graph: dict[str, set[str]] = {
            bond.name: set(bond.support_tranches) for bond in self.bonds
        }

        visited: set[str] = set()
        stack: set[str] = set()

        def _dfs(node: str) -> bool:
            if node in stack:
                return True
            if node in visited:
                return False
            visited.add(node)
            stack.add(node)
            for nxt in support_graph.get(node, set()):
                if _dfs(nxt):
                    return True
            stack.remove(node)
            return False

        for name in support_graph:
            if _dfs(name):
                errors.append("Support-tranche graph contains a cycle")
                break

        if errors:
            raise ValueError(
                f"Deal IR validation failed with {len(errors)} error(s):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        return self
