"""Structuring verification gate for execution compatibility checks."""
from __future__ import annotations

from typing import Any

from bma_standard_formulas.deals.schema import DealValidationError, validate_deal
from bma_standard_formulas.deals.schemas.common import PayMode, TrancheBehavior
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
    behavior_bonds = [
        bond
        for bond in deal.bonds
        if bond.tranche_behavior != TrancheBehavior.SEQUENTIAL or bond.pay_mode == PayMode.PIK
    ]
    if behavior_bonds:
        suggestions.append(
            "Run sensitivity scenarios for contraction/extension and inspect PAC/TAC/Z diagnostics before execution sign-off."
        )

    for bond in behavior_bonds:
        if bond.tranche_behavior in {TrancheBehavior.PAC, TrancheBehavior.TAC}:
            if not bond.schedule_contract and bond.schedule_model_type is None:
                errors.append(
                    f"{bond.name}: {bond.tranche_behavior.value} requires a prepayment model or schedule points."
                )
                suggestions.append(
                    f"Set schedule model/speeds on the {bond.tranche_behavior.value} block for {bond.name}."
                )
            if not bond.support_tranches and not bond.supported_by_tranches:
                errors.append(
                    f"{bond.name}: {bond.tranche_behavior.value} requires support tranche linkage."
                )
                suggestions.append(
                    f"Populate support tranche list on the {bond.tranche_behavior.value} payment block."
                )
            if bond.schedule_model_type is not None and not bond.schedule_contract:
                suggestions.append(
                    f"{bond.name}: model-driven schedule selected; confirm PAC/TAC priority and excess-principal routing in waterfall order."
                )
        if bond.tranche_behavior == TrancheBehavior.Z:
            if not bond.z_accrual_enabled:
                errors.append(f"{bond.name}: Z behavior requires accrual enabled.")
            if bond.pay_mode != PayMode.PIK:
                warnings.append(f"{bond.name}: Z behavior is usually paired with pay_mode=PIK.")
            if not bond.supported_by_tranches and not bond.support_tranches:
                warnings.append(
                    f"{bond.name}: Z bond has no explicit support linkage; verify support stack semantics."
                )
                suggestions.append(
                    f"Link one or more support tranches to {bond.name} using support fields."
                )

        for support_name in bond.support_tranches:
            support_bond = bond_by_name.get(support_name)
            if not support_bond:
                continue
            if support_bond.tranche_behavior == TrancheBehavior.Z:
                errors.append(
                    f"{bond.name}: support tranche {support_name} cannot be Z behavior."
                )

    if scenario_context and scenario_context.get("mode") == "solve" and behavior_bonds:
        suggestions.append(
            "For solve runs, include PAC/TAC schedule deviation and support-burn constraints in the objective stack."
        )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "suggestions": suggestions,
    }

