"""Legacy studio_v{N}.json migration (sdpm-4).

Extracts Blockly layout XML → sidecar layout_overrides, maps block.data
notes → IR description fields, and surfaces AI provenance for commit
message embedding.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from ..ir import DealDefinition
from ..studio_sidecar import StudioSidecar


def migrate_studio_payload(
    studio_version_payload: dict[str, Any],
    deal_definition: DealDefinition,
) -> tuple[StudioSidecar, DealDefinition, dict[str, Any] | None]:
    """Migrate legacy studio_v{N}.json to (sidecar, ir_with_descriptions, ai_provenance | None).

    Returns:
    - StudioSidecar with layout_overrides extracted from Blockly XML.
    - DealDefinition with `description` fields populated from block.data notes.
    - AI provenance dict (to be embedded in commit message body), or None if absent.
    """
    ir_data = studio_version_payload.get("ir", {})
    blockly_xml = ir_data.get("blockly_xml", "")
    block_data: dict[str, Any] = ir_data.get("block_data", {})

    layout_overrides = _extract_layout_from_xml(blockly_xml)
    sidecar = StudioSidecar(layout_overrides=layout_overrides)

    deal_definition = _apply_block_notes(deal_definition, block_data)

    ai_provenance_list = studio_version_payload.get("ai_provenance")
    provenance: dict[str, Any] | None = None
    if ai_provenance_list:
        provenance = {"ai_provenance": ai_provenance_list}

    return sidecar, deal_definition, provenance


def _extract_layout_from_xml(blockly_xml: str) -> dict[str, dict[str, Any]]:
    """Parse Blockly workspace XML and extract per-block (x, y) positions."""
    if not blockly_xml or not blockly_xml.strip():
        return {}

    layout: dict[str, dict[str, Any]] = {}
    try:
        root = ET.fromstring(blockly_xml)
    except ET.ParseError:
        return {}

    ns = {"blockly": "https://developers.google.com/blockly/xml"}
    blocks = root.findall("blockly:block", ns) or root.findall("block")

    for block in blocks:
        block_id = block.get("id")
        if not block_id:
            continue
        x_str = block.get("x")
        y_str = block.get("y")
        if x_str is None or y_str is None:
            continue
        try:
            x = float(x_str)
            y = float(y_str)
        except (ValueError, TypeError):
            continue
        entry: dict[str, Any] = {"x": x, "y": y}
        collapsed = block.get("collapsed")
        if collapsed is not None:
            entry["collapsed"] = collapsed.lower() == "true"
        layout[block_id] = entry

    return layout


def _apply_block_notes(
    deal: DealDefinition,
    block_data: dict[str, Any],
) -> DealDefinition:
    """Inject description from block.data payloads into matching IR entities."""
    if not block_data:
        return deal

    notes_map: dict[str, str] = {}
    for entity_id, data in block_data.items():
        if isinstance(data, dict) and "description" in data:
            desc = data["description"]
            if isinstance(desc, str) and desc.strip():
                notes_map[entity_id] = desc

    if not notes_map:
        return deal

    dump = deal.model_dump(mode="json")

    for calc in dump.get("calculations", []):
        if calc.get("name") in notes_map:
            calc["description"] = notes_map[calc["name"]]

    for trigger in dump.get("triggers", []):
        if trigger.get("name") in notes_map:
            trigger["description"] = notes_map[trigger["name"]]

    for rule in dump.get("waterfall_rules", []):
        if rule.get("rule_id") in notes_map:
            rule["description"] = notes_map[rule["rule_id"]]

    for group in dump.get("collateral_groups", []):
        if group.get("group_id") in notes_map:
            group["description"] = notes_map[group["group_id"]]

    return DealDefinition.model_validate(dump)
