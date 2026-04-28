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
    for bond in migrated.get("bonds", []) or []:
        if isinstance(bond, dict):
            bond.setdefault("pay_mode", "CASH_PAY")
            bond.setdefault("tranche_behavior", "SEQUENTIAL")
            bond.setdefault("schedule_model_type", None)
            bond.setdefault("schedule_priority_tier", None)
            bond.setdefault("schedule_depends_on", None)
            bond.setdefault("schedule_speed_low", None)
            bond.setdefault("schedule_speed_high", None)
            bond.setdefault("schedule_speed_target", None)
            bond.setdefault("schedule_custom_vector", None)
            bond.setdefault("schedule_contract", [])
            bond.setdefault("schedule_tolerance_bps", None)
            bond.setdefault("support_tranches", [])
            bond.setdefault("supported_by_tranches", [])
            bond.setdefault("z_accrual_enabled", False)
            bond.setdefault("z_release_trigger", None)
    # cap_mode generalization: if the legacy `ignore_schedule_cap=True` flag
    # is set and no explicit cap_mode is provided, infer the cleanup
    # interpretation. If neither is set, leave cap_mode as None so the
    # runtime can pick the default based on whether the target bond carries
    # a schedule. Walk the migrated copy so the result is consistent.
    for rule in migrated.get("waterfall_rules", []) or []:
        if not isinstance(rule, dict):
            continue
        rule.setdefault("ignore_schedule_cap", False)
        if "cap_mode" not in rule:
            rule["cap_mode"] = "NONE" if rule.get("ignore_schedule_cap") else None
    return migrated
