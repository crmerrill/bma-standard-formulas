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


_BUILTIN_STREAMS = frozenset({"CASH", "ACT_INT", "ACT_PRIN", "LOSS"})


def _build_valid_references(deal: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Build the valid source and target sets, mirroring ``DealDefinition._validate_references``.

    Returns (valid_sources, valid_targets).
    """
    bond_names = {b.get("name", "") for b in deal.get("bonds", []) if b.get("name")}
    account_names = {a.get("name", "") for a in deal.get("accounts", []) if a.get("name")}
    fee_names = {f.get("name", "") for f in deal.get("fees", []) if f.get("name")}
    group_ids = {g.get("group_id", "") for g in deal.get("collateral_groups", []) if g.get("group_id")}

    source_formula_names: set[str] = set()
    deal_knobs = deal.get("deal_knobs")
    if isinstance(deal_knobs, dict):
        raw_sf = deal_knobs.get("source_formulas")
        if isinstance(raw_sf, dict):
            source_formula_names = {str(k) for k in raw_sf.keys()}

    group_streams: set[str] = set()
    for gid in group_ids:
        for suffix in ("CASH", "ACT_INT", "ACT_PRIN", "LOSS"):
            group_streams.add(f"GROUP_{gid}_{suffix}")

    entity_names = bond_names | account_names | fee_names

    split_streams: set[str] = set()
    rules_sorted = sorted(deal.get("waterfall_rules", []), key=lambda r: r.get("order", 0))
    for rule in rules_sorted:
        if rule.get("rule_type") == "SPLIT_CASH":
            for tgt in rule.get("to_targets", []):
                if (
                    tgt not in entity_names
                    and tgt not in _BUILTIN_STREAMS
                    and tgt not in source_formula_names
                ):
                    split_streams.add(tgt)

    all_targets = entity_names | {"CASH"}
    valid_sources = (
        all_targets | _BUILTIN_STREAMS | group_streams | source_formula_names | split_streams
    )
    valid_targets = all_targets | split_streams | _BUILTIN_STREAMS | group_streams

    return valid_sources, valid_targets


@diagnostic_code(
    "REFERENCE_BROKEN",
    severity=Severity.error,
    path_schema="deal.waterfall_rules[*].from_sources",
    owner=Owner.both,
)
def validate_reference_broken(deal: dict[str, Any]) -> list[DiagnosticPayload]:
    """Emit REFERENCE_BROKEN for rules referencing non-existent bond/account names."""
    results: list[DiagnosticPayload] = []
    valid_sources, valid_targets = _build_valid_references(deal)

    for i, rule in enumerate(deal.get("waterfall_rules", [])):
        from_sources = rule.get("from_sources", [])
        to_targets = rule.get("to_targets", [])
        has_broken_source = False
        for src in from_sources:
            if src not in valid_sources:
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
            if tgt not in valid_targets:
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


def _extract_group_from_token(token: str) -> str | None:
    """Extract the group id from a ``GROUP_<gid>_<suffix>`` token, or ``None``."""
    for suffix in ("_CASH", "_ACT_INT", "_ACT_PRIN", "_LOSS"):
        if token.startswith("GROUP_") and token.endswith(suffix):
            return token[len("GROUP_"):-len(suffix)]
    return None


@diagnostic_code(
    "MULTI_GROUP_ROUTING_INVALID",
    severity=Severity.error,
    path_schema="deal.waterfall_rules[*].from_sources",
    owner=Owner.both,
)
def validate_multi_group_routing(deal: dict[str, Any]) -> list[DiagnosticPayload]:
    """Emit MULTI_GROUP_ROUTING_INVALID for invalid group routing.

    Checks two conditions:
    1. Group-prefixed tokens in from_sources or to_targets that don't match
       any declared collateral_groups entry.
    2. OA5 cross-group mixing: a rule with group_id must not mix bare
       collateral tokens (CASH/ACT_INT/ACT_PRIN/LOSS) with explicit
       GROUP_<other>_* tokens for a different group.
    """
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
        to_targets = rule.get("to_targets", [])

        has_invalid_source = False
        for src in from_sources:
            if src.startswith("GROUP_") and src not in valid_group_streams:
                has_invalid_source = True
                break
        has_invalid_target = False
        for tgt in to_targets:
            if tgt.startswith("GROUP_") and tgt not in valid_group_streams:
                has_invalid_target = True
                break

        if has_invalid_source or has_invalid_target:
            results.append(
                DiagnosticPayload(
                    code="MULTI_GROUP_ROUTING_INVALID",
                    severity=Severity.error,
                    path=f"deal.waterfall_rules[{i}].from_sources",
                    message=f"Rule '{rule.get('rule_id', '')}' references group-prefixed token not in declared collateral_groups.",
                    payload={"rule_index": i, "rule_id": rule.get("rule_id", "")},
                )
            )
            continue

        rule_group_id = rule.get("group_id")
        if not rule_group_id:
            continue
        all_keys = list(from_sources) + list(to_targets)
        has_bare = any(k in _BUILTIN_STREAMS for k in all_keys)
        if not has_bare:
            continue
        for key in all_keys:
            other_group = _extract_group_from_token(key)
            if other_group is not None and other_group != rule_group_id:
                results.append(
                    DiagnosticPayload(
                        code="MULTI_GROUP_ROUTING_INVALID",
                        severity=Severity.error,
                        path=f"deal.waterfall_rules[{i}].from_sources",
                        message=(
                            f"Rule '{rule.get('rule_id', '')}' mixes bare collateral tokens "
                            f"(scoped to group_id={rule_group_id!r}) with explicit "
                            f"token {key!r} for a different group {other_group!r}."
                        ),
                        payload={"rule_index": i, "rule_id": rule.get("rule_id", "")},
                    )
                )
                break

    return results
