"""Schema migration helpers for DealDefinition payload compatibility."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def migrate_deal_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy deal payloads to current schema shape.

    This migration layer is intentionally non-destructive and additive:
    - keeps existing fields untouched
    - injects missing optional keys used by newer runtimes
    """
    migrated = deepcopy(payload)
    for fee in migrated.get("fees", []) or []:
        if isinstance(fee, dict):
            fee.setdefault("amount_expr", None)
            fee.setdefault("rate_expr", None)
    for rule in migrated.get("waterfall_rules", []) or []:
        if isinstance(rule, dict):
            if "max_amount" in rule and "max_amount_fixed" not in rule:
                rule["max_amount_fixed"] = rule.get("max_amount")
            rule.setdefault("max_amount_expr", None)
            rule.setdefault("condition_expr", None)
            rule.setdefault("allow_negative_source", False)
    for trigger in migrated.get("triggers", []) or []:
        if isinstance(trigger, dict):
            trigger.setdefault("calculation_ref", None)
            trigger.setdefault("comparison_ref", None)
    return migrated
