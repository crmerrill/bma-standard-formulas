"""Three-way typed-field merge for DealDefinition with MERGE_CONFLICT diagnostic."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from bma_standard_formulas.deals.schemas.ir import DealDefinition
from bma_standard_formulas.diagnostics import (
    DiagnosticPayload,
    Owner,
    Severity,
    diagnostic_code,
)


@diagnostic_code(
    "MERGE_CONFLICT",
    severity=Severity.error,
    path_schema="deal.{entity_kind}[{entity_id}].{field_path}",
    owner=Owner.backend,
)
def _merge_conflict_validator() -> None:
    """Stable diagnostic code for typed-field merge conflicts.

    Registered via the vpc-1 catalog mechanism. The actual conflict detection
    runs inline in merge_deal_definitions; this validator function is a no-op
    placeholder whose sole purpose is to satisfy the decorator-registration
    contract.
    """


_ENTITY_COLLECTIONS: dict[str, tuple[str, str]] = {
    "bonds": ("bond", "name"),
    "accounts": ("account", "name"),
    "fees": ("fee", "name"),
    "triggers": ("trigger", "name"),
    "calculations": ("calculation", "name"),
    "waterfall_rules": ("rule", "rule_id"),
    "collateral_groups": ("collateral_group", "group_id"),
}

_CONFLICT = object()


def merge_deal_definitions(
    ancestor: DealDefinition,
    ours: DealDefinition,
    theirs: DealDefinition,
) -> DealDefinition | DiagnosticPayload:
    """Three-way typed-field merge.

    Returns the merged DealDefinition on success, or a DiagnosticPayload
    with code='MERGE_CONFLICT' on the FIRST detected conflict.
    """
    merged_data: dict[str, Any] = {}
    collection_names = set(_ENTITY_COLLECTIONS)

    for field_name in DealDefinition.model_fields:
        if field_name in collection_names:
            continue
        a_val = getattr(ancestor, field_name)
        o_val = getattr(ours, field_name)
        t_val = getattr(theirs, field_name)
        merged = _three_way_value(a_val, o_val, t_val)
        if merged is _CONFLICT:
            # Top-level metadata fields use last-writer-wins-on-target (prefer
            # ours / the merge target) as a deliberate v1 choice.  AC 5 pins
            # MERGE_CONFLICT payloads to the seven entity collections; a future
            # ticket may introduce a separate DEAL_METADATA_CONFLICT diagnostic
            # if structured top-level conflict reporting becomes a requirement.
            merged = o_val
        merged_data[field_name] = merged

    for coll_name, (entity_kind, key_field) in _ENTITY_COLLECTIONS.items():
        result = _merge_collection(
            getattr(ancestor, coll_name),
            getattr(ours, coll_name),
            getattr(theirs, coll_name),
            entity_kind=entity_kind,
            key_field=key_field,
        )
        if isinstance(result, DiagnosticPayload):
            return result
        merged_data[coll_name] = result

    return DealDefinition.model_validate(merged_data)


def _three_way_value(ancestor: Any, ours: Any, theirs: Any) -> Any:
    """Return merged value or the _CONFLICT sentinel."""
    if ours == ancestor:
        return theirs
    if theirs == ancestor:
        return ours
    if ours == theirs:
        return ours
    return _CONFLICT


def _merge_collection(
    ancestor_list: list[Any],
    ours_list: list[Any],
    theirs_list: list[Any],
    *,
    entity_kind: str,
    key_field: str,
) -> list[Any] | DiagnosticPayload:
    ancestor_map = {getattr(e, key_field): e for e in ancestor_list}
    ours_map = {getattr(e, key_field): e for e in ours_list}
    theirs_map = {getattr(e, key_field): e for e in theirs_list}

    all_keys = set(ancestor_map) | set(ours_map) | set(theirs_map)
    merged_map: dict[str, Any] = {}

    for key in all_keys:
        a, o, t = ancestor_map.get(key), ours_map.get(key), theirs_map.get(key)

        if a is not None and o is not None and t is not None:
            entity_result = _merge_entity(
                a, o, t, entity_kind=entity_kind, entity_id=str(key),
            )
            if isinstance(entity_result, DiagnosticPayload):
                return entity_result
            merged_map[key] = entity_result

        elif a is None and o is not None and t is not None:
            if o == t:
                merged_map[key] = o
            else:
                for fn in type(o).model_fields:
                    if getattr(o, fn) != getattr(t, fn):
                        return _build_conflict(
                            entity_kind, str(key), fn,
                            None, getattr(o, fn), getattr(t, fn),
                        )

        elif o is not None and t is None:
            if a is not None:
                if o != a:
                    for fn in type(a).model_fields:
                        a_v, o_v = getattr(a, fn), getattr(o, fn)
                        if a_v != o_v:
                            return _build_conflict(
                                entity_kind, str(key), fn, a_v, o_v, None,
                            )
            else:
                merged_map[key] = o

        elif o is None and t is not None:
            if a is not None:
                if t != a:
                    for fn in type(a).model_fields:
                        a_v, t_v = getattr(a, fn), getattr(t, fn)
                        if a_v != t_v:
                            return _build_conflict(
                                entity_kind, str(key), fn, a_v, None, t_v,
                            )
            else:
                merged_map[key] = t

    seen: set[str] = set()
    result_list: list[Any] = []
    for entity in ours_list:
        k = getattr(entity, key_field)
        if k in merged_map and k not in seen:
            result_list.append(merged_map[k])
            seen.add(k)
    for entity in theirs_list:
        k = getattr(entity, key_field)
        if k in merged_map and k not in seen:
            result_list.append(merged_map[k])
            seen.add(k)

    return result_list


def _merge_entity(
    ancestor: BaseModel,
    ours: BaseModel,
    theirs: BaseModel,
    *,
    entity_kind: str,
    entity_id: str,
) -> BaseModel | DiagnosticPayload:
    updates: dict[str, Any] = {}
    for field_name in type(ancestor).model_fields:
        a_val = getattr(ancestor, field_name)
        o_val = getattr(ours, field_name)
        t_val = getattr(theirs, field_name)
        merged = _three_way_value(a_val, o_val, t_val)
        if merged is _CONFLICT:
            return _build_conflict(
                entity_kind, entity_id, field_name, a_val, o_val, t_val,
            )
        updates[field_name] = merged
    return ancestor.model_copy(update=updates)


def _build_conflict(
    entity_kind: str,
    entity_id: str,
    field_path: str,
    ancestor_value: Any,
    ours_value: Any,
    theirs_value: Any,
) -> DiagnosticPayload:
    return DiagnosticPayload(
        code="MERGE_CONFLICT",
        severity=Severity.error,
        path=f"deal.{entity_kind}[{entity_id}].{field_path}",
        message=f"Conflicting changes to {entity_kind} '{entity_id}' field '{field_path}'",
        payload={
            "entity_kind": entity_kind,
            "entity_id": entity_id,
            "field_path": field_path,
            "ours_value": ours_value,
            "theirs_value": theirs_value,
            "ancestor_value": ancestor_value,
        },
    )
