"""Canonical deal-definition IR schemas (the source of truth for deal structure)."""
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .common import (
    SCHEMA_VERSION,
    AccountType,
    AccrualPeriod,
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


class BondDef(BaseModel):
    """Immutable definition of a single tranche in the deal structure."""
    name: str = Field(min_length=1)
    tranche_type: TrancheType = TrancheType.SEQUENTIAL
    is_bond: bool = True
    is_pseudo: bool = False

    coupon_type: CouponType = CouponType.FIXED
    coupon: Rate | None = None
    margin: Rate | None = None
    index_name: str | None = None
    cap: Rate | None = None
    floor: Rate | None = None
    inverse_multiplier: float | None = None

    size_dollars: Dollars | None = None
    size_pct: float | None = Field(default=None, ge=0.0, le=100.0)

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
    schedule_speed_target: float | None = None
    schedule_custom_vector: str | None = None
    pac_lower_psa: float | None = None
    pac_upper_psa: float | None = None
    tac_pricing_psa: float | None = None
    schedule_contract: list[dict[str, float | int]] = Field(default_factory=list)
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
    name: str = Field(min_length=1)
    account_type: AccountType = AccountType.RESERVE
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

    from_sources: list[str] = Field(min_length=1)
    to_targets: list[str] = Field(min_length=1)
    reserve_account: str | None = None

    payment_style: PaymentStyle = PaymentStyle.SEQUENTIAL
    max_amount_expr: str | None = None
    max_amount_fixed: Dollars | None = None

    condition_trigger: str | None = None
    condition_invert: bool = False
    condition_expr: str | None = None
    allow_negative_source: bool = False

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

    # Deal-level solver knobs
    deal_knobs: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_references(self) -> "DealDefinition":
        bond_names = {b.name for b in self.bonds}
        account_names = {a.name for a in self.accounts}
        fee_names = {f.name for f in self.fees}
        trigger_names = {t.name for t in self.triggers}
        calc_names = {c.name for c in self.calculations}
        source_formula_names: set[str] = set()
        raw_source_formulas = self.deal_knobs.get("source_formulas")
        if isinstance(raw_source_formulas, dict):
            source_formula_names = {str(k) for k in raw_source_formulas.keys()}
        all_targets = bond_names | account_names | fee_names | {"CASH"}
        valid_sources = all_targets | {"COLLATERAL", "LOSS"} | source_formula_names

        errors: list[str] = []
        for rule in self.waterfall_rules:
            for src in rule.from_sources:
                if src not in valid_sources:
                    errors.append(
                        f"Rule {rule.rule_id!r}: from_source {src!r} not found "
                        f"in bonds/accounts/fees/source_formulas"
                    )
            for tgt in rule.to_targets:
                if tgt not in all_targets:
                    errors.append(
                        f"Rule {rule.rule_id!r}: to_target {tgt!r} not found "
                        f"in bonds/accounts/fees"
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
                        if bond.schedule_speed_target is None:
                            errors.append(
                                f"Bond {bond.name!r}: TAC schedule requires target speed value."
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
