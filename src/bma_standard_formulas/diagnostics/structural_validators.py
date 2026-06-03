"""Structural validators for deal payloads — owner='both' (Python + TS parity).

These validators run on the raw deal dict (not on the fully-validated Pydantic
model) so they can be exercised identically by both the Python parity test
runner and the TypeScript worker-side registry.

Adding a validator here requires:
  1. A matching ``registerDiagnosticValidator`` call in
     ``src/bma_cfengine_app/ui/src/features/validation/structuralValidators.ts``.
  2. A new row in ``docs/architecture/diagnostic_catalog.md``.
  3. Updating ``python -m bma_standard_formulas.diagnostics.check`` to exit 0.
"""

from __future__ import annotations

from typing import Any

from bma_standard_formulas.diagnostics import (
    DiagnosticPayload,
    Owner,
    Severity,
    diagnostic_code,
)


@diagnostic_code(
    "BOND_NAME_EMPTY",
    severity=Severity.error,
    path_schema="deal.bonds[*].name",
    owner=Owner.both,
)
def validate_bond_name_empty(deal: dict[str, Any]) -> list[DiagnosticPayload]:
    """Emit BOND_NAME_EMPTY for every bond whose name is absent or blank."""
    results: list[DiagnosticPayload] = []
    for i, bond in enumerate(deal.get("bonds", [])):
        name = bond.get("name", "")
        if not isinstance(name, str) or not name.strip():
            results.append(
                DiagnosticPayload(
                    code="BOND_NAME_EMPTY",
                    severity=Severity.error,
                    path=f"deal.bonds[{i}].name",
                    message=f"Bond at index {i} has an empty or missing name.",
                    payload={"index": i},
                )
            )
    return results


@diagnostic_code(
    "BOND_NAME_DUPLICATE",
    severity=Severity.error,
    path_schema="deal.bonds[*].name",
    owner=Owner.both,
)
def validate_bond_name_duplicate(deal: dict[str, Any]) -> list[DiagnosticPayload]:
    """Emit BOND_NAME_DUPLICATE for bonds whose name duplicates an earlier bond."""
    results: list[DiagnosticPayload] = []
    seen: dict[str, int] = {}
    for i, bond in enumerate(deal.get("bonds", [])):
        name = bond.get("name", "")
        if not isinstance(name, str) or not name.strip():
            continue
        if name in seen:
            results.append(
                DiagnosticPayload(
                    code="BOND_NAME_DUPLICATE",
                    severity=Severity.error,
                    path=f"deal.bonds[{i}].name",
                    message=f"Bond '{name}' at index {i} duplicates bond at index {seen[name]}.",
                    payload={"index": i, "first_index": seen[name], "name": name},
                )
            )
        else:
            seen[name] = i
    return results


@diagnostic_code(
    "REFERENCE_BROKEN",
    severity=Severity.error,
    path_schema="deal.waterfall_rules[*].from_sources",
    owner=Owner.both,
)
def validate_reference_broken(deal: dict[str, Any]) -> list[DiagnosticPayload]:
    """Emit REFERENCE_BROKEN for rules referencing non-existent bond/account names."""
    results: list[DiagnosticPayload] = []
    bond_names = {b.get("name", "") for b in deal.get("bonds", []) if b.get("name")}
    account_names = {a.get("name", "") for a in deal.get("accounts", []) if a.get("name")}
    fee_names = {f.get("name", "") for f in deal.get("fees", []) if f.get("name")}
    group_ids = {g.get("group_id", "") for g in deal.get("collateral_groups", []) if g.get("group_id")}

    builtin = {"CASH", "ACT_INT", "ACT_PRIN", "LOSS"}
    group_streams: set[str] = set()
    for gid in group_ids:
        for suffix in ("CASH", "ACT_INT", "ACT_PRIN", "LOSS"):
            group_streams.add(f"GROUP_{gid}_{suffix}")

    valid_names = bond_names | account_names | fee_names | builtin | group_streams

    for i, rule in enumerate(deal.get("waterfall_rules", [])):
        from_sources = rule.get("from_sources", [])
        to_targets = rule.get("to_targets", [])
        has_broken_source = False
        for src in from_sources:
            if src.startswith("GROUP_"):
                continue
            if src not in valid_names:
                has_broken_source = True
                break
        if has_broken_source:
            results.append(
                DiagnosticPayload(
                    code="REFERENCE_BROKEN",
                    severity=Severity.error,
                    path=f"deal.waterfall_rules[{i}].from_sources",
                    message=f"Rule '{rule.get('rule_id', '')}' references non-existent source(s).",
                    payload={"rule_index": i, "rule_id": rule.get("rule_id", "")},
                )
            )
        has_broken_target = False
        for tgt in to_targets:
            if tgt.startswith("GROUP_"):
                continue
            if tgt not in valid_names:
                has_broken_target = True
                break
        if has_broken_target:
            results.append(
                DiagnosticPayload(
                    code="REFERENCE_BROKEN",
                    severity=Severity.error,
                    path=f"deal.waterfall_rules[{i}].to_targets",
                    message=f"Rule '{rule.get('rule_id', '')}' references non-existent target(s).",
                    payload={"rule_index": i, "rule_id": rule.get("rule_id", "")},
                )
            )
    return results


@diagnostic_code(
    "MULTI_TARGET_WEIGHT_SUM_INVALID",
    severity=Severity.error,
    path_schema="deal.waterfall_rules[*].target_weights",
    owner=Owner.both,
)
def validate_multi_target_weight_sum(deal: dict[str, Any]) -> list[DiagnosticPayload]:
    """Emit MULTI_TARGET_WEIGHT_SUM_INVALID when target_weights don't sum to 1.0."""
    results: list[DiagnosticPayload] = []
    epsilon = 1e-9
    for i, rule in enumerate(deal.get("waterfall_rules", [])):
        weights = rule.get("target_weights")
        if weights is None or not isinstance(weights, list):
            continue
        if len(weights) == 0:
            continue
        total = sum(weights)
        if abs(total - 1.0) > epsilon:
            results.append(
                DiagnosticPayload(
                    code="MULTI_TARGET_WEIGHT_SUM_INVALID",
                    severity=Severity.error,
                    path=f"deal.waterfall_rules[{i}].target_weights",
                    message=f"Rule '{rule.get('rule_id', '')}' target_weights sum to {total:.6f}, expected 1.0.",
                    payload={"rule_index": i, "rule_id": rule.get("rule_id", ""), "sum": total},
                )
            )
    return results


_PAC_TAC_KINDS = {"PAC", "TAC"}


@diagnostic_code(
    "KIND_SCHEDULE_SOURCE_INCONSISTENT",
    severity=Severity.error,
    path_schema="deal.bonds[*].kind",
    owner=Owner.both,
)
def validate_kind_schedule_source(deal: dict[str, Any]) -> list[DiagnosticPayload]:
    """Emit KIND_SCHEDULE_SOURCE_INCONSISTENT for PAC/TAC missing schedule or non-PAC/TAC having one."""
    results: list[DiagnosticPayload] = []
    for i, bond in enumerate(deal.get("bonds", [])):
        kind = bond.get("kind", "CASH_PAY")
        has_contract = bool(bond.get("schedule_contract"))
        has_model = bond.get("schedule_model_type") is not None
        if kind in _PAC_TAC_KINDS:
            if not has_contract and not has_model:
                results.append(
                    DiagnosticPayload(
                        code="KIND_SCHEDULE_SOURCE_INCONSISTENT",
                        severity=Severity.error,
                        path=f"deal.bonds[{i}].kind",
                        message=f"Bond '{bond.get('name', '')}' (kind={kind}) requires schedule_contract or schedule_model_type.",
                        payload={"index": i, "kind": kind},
                    )
                )
        else:
            if has_contract or has_model:
                results.append(
                    DiagnosticPayload(
                        code="KIND_SCHEDULE_SOURCE_INCONSISTENT",
                        severity=Severity.error,
                        path=f"deal.bonds[{i}].kind",
                        message=f"Bond '{bond.get('name', '')}' (kind={kind}) must not have schedule_contract or schedule_model_type.",
                        payload={"index": i, "kind": kind},
                    )
                )
    return results


@diagnostic_code(
    "NLA_SUBORDINATION_INCONSISTENT",
    severity=Severity.error,
    path_schema="deal.bonds[*].nla_starting_balance",
    owner=Owner.both,
)
def validate_nla_subordination(deal: dict[str, Any]) -> list[DiagnosticPayload]:
    """Emit NLA_SUBORDINATION_INCONSISTENT when NLA and subordination fields are not jointly set."""
    results: list[DiagnosticPayload] = []
    for i, bond in enumerate(deal.get("bonds", [])):
        has_nla = bond.get("nla_starting_balance") is not None
        has_sub = bond.get("required_subordination_pct") is not None
        if has_nla != has_sub:
            results.append(
                DiagnosticPayload(
                    code="NLA_SUBORDINATION_INCONSISTENT",
                    severity=Severity.error,
                    path=f"deal.bonds[{i}].nla_starting_balance",
                    message=(
                        f"Bond '{bond.get('name', '')}' has "
                        f"{'nla_starting_balance' if has_nla else 'required_subordination_pct'} "
                        f"set but not {'required_subordination_pct' if has_nla else 'nla_starting_balance'}."
                    ),
                    payload={"index": i, "has_nla": has_nla, "has_sub": has_sub},
                )
            )
    return results


@diagnostic_code(
    "MULTI_GROUP_ROUTING_INVALID",
    severity=Severity.error,
    path_schema="deal.waterfall_rules[*].from_sources",
    owner=Owner.both,
)
def validate_multi_group_routing(deal: dict[str, Any]) -> list[DiagnosticPayload]:
    """Emit MULTI_GROUP_ROUTING_INVALID for group-prefixed sources not in collateral_groups."""
    results: list[DiagnosticPayload] = []
    group_ids = {g.get("group_id", "") for g in deal.get("collateral_groups", []) if g.get("group_id")}
    if not group_ids:
        return results

    valid_group_streams: set[str] = set()
    for gid in group_ids:
        for suffix in ("CASH", "ACT_INT", "ACT_PRIN", "LOSS"):
            valid_group_streams.add(f"GROUP_{gid}_{suffix}")

    for i, rule in enumerate(deal.get("waterfall_rules", [])):
        from_sources = rule.get("from_sources", [])
        has_invalid = False
        for src in from_sources:
            if src.startswith("GROUP_") and src not in valid_group_streams:
                has_invalid = True
                break
        if has_invalid:
            results.append(
                DiagnosticPayload(
                    code="MULTI_GROUP_ROUTING_INVALID",
                    severity=Severity.error,
                    path=f"deal.waterfall_rules[{i}].from_sources",
                    message=f"Rule '{rule.get('rule_id', '')}' references group-prefixed source not in declared collateral_groups.",
                    payload={"rule_index": i, "rule_id": rule.get("rule_id", "")},
                )
            )
    return results
