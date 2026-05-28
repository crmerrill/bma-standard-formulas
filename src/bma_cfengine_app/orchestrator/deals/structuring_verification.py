"""Structuring verification gate for execution compatibility checks."""
from __future__ import annotations

from typing import Any

from bma_standard_formulas.deals.schema import DealValidationError, validate_deal
from bma_standard_formulas.deals.schemas.common import (
    CapMode,
    PayMode,
    RuleType,
    TrancheKind,
    TrancheRelationType,
)
from bma_standard_formulas.deals.schemas.ir import DealDefinition


def verify_structure(
    deal: DealDefinition,
    *,
    scenario_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    suggestions: list[str] = []

    try:
        warnings.extend(validate_deal(deal))
    except DealValidationError as exc:
        message = str(exc)
        for line in message.splitlines():
            if line.strip().startswith("-"):
                errors.append(line.replace("-", "", 1).strip())
        if not errors:
            errors.append(message)

    bond_by_name = {bond.name: bond for bond in deal.bonds}

    def _relation_targets(bond, relation_type: TrancheRelationType) -> list[str]:
        out: list[str] = []
        for relation in getattr(bond, "relations", []) or []:
            if getattr(relation, "relation_type", None) != relation_type:
                continue
            out.extend([str(t) for t in getattr(relation, "targets", []) or [] if str(t or "").strip()])
        return out

    behavior_bonds = [
        bond
        for bond in deal.bonds
        if bond.kind != TrancheKind.CASH_PAY or bond.pay_mode == PayMode.PIK
    ]
    if behavior_bonds:
        suggestions.append(
            "Run sensitivity scenarios for contraction/extension and inspect PAC/TAC/Z diagnostics before execution sign-off."
        )

    for bond in behavior_bonds:
        if bond.kind in {TrancheKind.PAC, TrancheKind.TAC}:
            if not bond.schedule_contract and bond.schedule_model_type is None:
                errors.append(
                    f"{bond.name}: {bond.kind.value} requires a prepayment model or schedule points."
                )
                suggestions.append(
                    f"Set schedule model/speeds on the {bond.kind.value} block for {bond.name}."
                )
            if not _relation_targets(bond, TrancheRelationType.SUPPORTED_BY):
                errors.append(
                    f"{bond.name}: {bond.kind.value} requires support tranche linkage."
                )
                suggestions.append(
                    f"Populate support tranche list on the {bond.kind.value} payment block."
                )
            if bond.schedule_model_type is not None and not bond.schedule_contract:
                suggestions.append(
                    f"{bond.name}: model-driven schedule selected; confirm PAC/TAC priority and excess-principal routing in waterfall order."
                )
            if bond.schedule_priority_tier is None:
                warnings.append(
                    f"{bond.name}: schedule priority tier not set; PAC/TAC precedence should be explicit."
                )
            if bond.schedule_depends_on:
                suggestions.append(
                    f"{bond.name}: depends_on={bond.schedule_depends_on}. Verify referenced schedule tier is paid earlier in waterfall."
                )
        if bond.kind == TrancheKind.Z:
            if not bond.z_accrual_enabled:
                errors.append(f"{bond.name}: Z behavior requires accrual enabled.")
            if bond.pay_mode != PayMode.PIK:
                warnings.append(f"{bond.name}: Z behavior is usually paired with pay_mode=PIK.")
            if not _relation_targets(bond, TrancheRelationType.ACCRETES_TO):
                warnings.append(
                    f"{bond.name}: Z bond has no explicit support linkage; verify support stack semantics."
                )
                suggestions.append(
                    f"Link one or more support tranches to {bond.name} using support fields."
                )

        for support_name in _relation_targets(bond, TrancheRelationType.SUPPORTED_BY):
            support_bond = bond_by_name.get(support_name)
            if not support_bond:
                continue
            if support_bond.kind == TrancheKind.Z:
                errors.append(
                    f"{bond.name}: support tranche {support_name} cannot be Z behavior."
                )

    # Schema-only relation types: these are accepted by the IR schema and stored in
    # the deal definition, but the runtime does NOT act on them — they are declarative
    # annotations only. Emit an explicit WARNING for every such relation so that deal
    # authors do not assume the relation changes cashflow behaviour.
    _SCHEMA_ONLY_RELATION_TYPES = {
        TrancheRelationType.COUPON_INVERSE_OF,
        TrancheRelationType.COUPON_LEVERAGE_OF,
        TrancheRelationType.MACR_EXCHANGE,
    }
    _SCHEMA_ONLY_DESCRIPTIONS = {
        TrancheRelationType.COUPON_INVERSE_OF: (
            "COUPON_INVERSE_OF is declarative only and does not affect cashflows. "
            "To model an inverse-floater coupon, set BondDef.coupon to a "
            "list[RateScheduleEntry] or compute it from a CalculationNode expression "
            "and reference the result via deal_knobs."
        ),
        TrancheRelationType.COUPON_LEVERAGE_OF: (
            "COUPON_LEVERAGE_OF is declarative only and does not affect cashflows. "
            "To model a leveraged coupon, set BondDef.coupon to the computed "
            "leveraged rate as a float or list[RateScheduleEntry]. "
            "Alternatively, use a CalculationNode expression in deal_knobs."
        ),
        TrancheRelationType.MACR_EXCHANGE: (
            "MACR_EXCHANGE is declarative only and does not affect cashflows. "
            "MACR exchange mechanics must be modelled explicitly in the waterfall "
            "using PAY_PRINCIPAL or SPLIT_CASH rules if required."
        ),
    }
    # Emit one warning per (bond, relation_type) pair, including the targets, to
    # avoid duplicate messages when a bond has multiple relations of the same type.
    _seen_schema_only: set[tuple[str, str]] = set()
    for bond in deal.bonds:
        targets_by_type: dict[str, list[str]] = {}
        for relation in getattr(bond, "relations", []) or []:
            rel_type = getattr(relation, "relation_type", None)
            if rel_type not in _SCHEMA_ONLY_RELATION_TYPES:
                continue
            targets_by_type.setdefault(rel_type.value, []).extend(
                getattr(relation, "targets", []) or []
            )
        for rel_type_str, tgts in targets_by_type.items():
            key = (bond.name, rel_type_str)
            if key in _seen_schema_only:
                continue
            _seen_schema_only.add(key)
            rel_type_enum = next(
                r for r in _SCHEMA_ONLY_RELATION_TYPES if r.value == rel_type_str
            )
            desc = _SCHEMA_ONLY_DESCRIPTIONS.get(rel_type_enum, f"{rel_type_str} is declarative only.")
            target_note = f" Targets: {', '.join(tgts)}." if tgts else ""
            warnings.append(f"{bond.name}: {desc}{target_note}")

    if scenario_context and scenario_context.get("mode") == "solve" and behavior_bonds:
        suggestions.append(
            "For solve runs, include PAC/TAC schedule deviation and support-burn constraints in the objective stack."
        )

    # Cleanup-rule placement and coverage diagnostics. The standard CMO
    # waterfall has cleanup rules (`cap_mode = NONE`) at the END of the
    # priority of payments -- after support classes are paid -- so that pool
    # cash routes to PAC bonds beyond their planned balances only when
    # supports are exhausted. Placing cleanup rules before supports causes
    # premature PAC paydown; missing cleanup rules let pool excess get stuck.
    explicit_support_names = {
        n
        for bond in deal.bonds
        for n in _relation_targets(bond, TrancheRelationType.SUPPORTED_BY)
    }
    sup_class_names = (
        explicit_support_names
        | {
            bond.name for bond in deal.bonds
            if bond.kind in {TrancheKind.PO, TrancheKind.PSEUDO}
        }
    )
    pac_classes_with_schedule = {
        bond.name for bond in deal.bonds
        if bond.kind in {TrancheKind.PAC, TrancheKind.TAC}
        and bond.schedule_contract
    }
    cleanup_targets: set[str] = set()
    seen_support_rule = False
    for rule in sorted(deal.waterfall_rules, key=lambda r: r.order):
        if rule.rule_type != RuleType.PAY_PRINCIPAL:
            continue
        rule_cap_mode = getattr(rule, "cap_mode", None)
        cap_value = (
            rule_cap_mode.value if hasattr(rule_cap_mode, "value")
            else (str(rule_cap_mode) if rule_cap_mode is not None else None)
        )
        is_cleanup = cap_value == CapMode.NONE.value or getattr(rule, "ignore_schedule_cap", False)
        targets_support = bool(set(rule.to_targets) & sup_class_names)
        if is_cleanup:
            cleanup_targets.update(rule.to_targets)
            if not seen_support_rule and sup_class_names:
                warnings.append(
                    f"Rule {rule.rule_id!r} is a cleanup rule (`cap_mode=NONE`) "
                    f"but appears before any support-class principal rule. "
                    f"Move it after support distribution to match the standard "
                    f"CMO priority of payments."
                )
        if targets_support and not is_cleanup:
            seen_support_rule = True

    pac_without_cleanup = sorted(pac_classes_with_schedule - cleanup_targets)
    for bond_name in pac_without_cleanup:
        warnings.append(
            f"{bond_name}: PAC/TAC bond has a schedule but no cleanup rule "
            f"(`cap_mode=NONE`) targets it. Pool excess delivered after "
            f"supports are exhausted may not flow back to {bond_name}, leaving "
            f"residual balance unpaid at horizon."
        )
        suggestions.append(
            f"Add a cleanup rule with `cap_mode=NONE` targeting {bond_name} at "
            f"the end of the waterfall, after support classes."
        )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "suggestions": suggestions,
    }

