"""Schema migration helpers for DealDefinition payload compatibility.

All public helpers are safe to call before Pydantic validation.  They are
additive / idempotent: running a payload through migrate_deal_payload() twice
produces the same result as running it once.

API and studio-load paths MUST call migrate_deal_payload() on every payload
before model_validate() so that 1.x studio snapshots are transparently
upgraded to 2.0 schema shape.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


from ..common import SCHEMA_VERSION

_LEGACY_STRUCTURE_RELATION_MAP = {
    "z_accrual": "ACCRETES_TO",
    "io_po": "BALANCE_TRACKS",
    "floater_inverse": "COUPON_INVERSE_OF",
}

# Canonical 1.x → 2.0 TrancheKind map.  Exported as a public name so that the
# API normalizer imports from a single source of truth.  All consumers of the
# old private name should switch to LEGACY_TRANCHE_KIND_MAP.
LEGACY_TRANCHE_KIND_MAP: dict[str, str] = {
    "CASH_PAY":           "CASH_PAY",
    "SEQUENTIAL":         "CASH_PAY",
    "SUPPORT":            "CASH_PAY",
    "ACCRETION_DIRECTED": "CASH_PAY",
    "FLOATER":            "CASH_PAY",
    "INVERSE_FLOATER":    "CASH_PAY",
    "PAC":                "PAC",
    "PAC_II":             "PAC",
    "TAC":                "TAC",
    "IO":                 "IO",
    "PO":                 "PO",
    "Z_BOND":             "Z",
    "Z":                  "Z",
    "RESIDUAL":           "RESIDUAL",
    "PSEUDO":             "PSEUDO",
}
# Keep the private alias for backwards compat with existing imports.
_LEGACY_TRANCHE_KIND_MAP = LEGACY_TRANCHE_KIND_MAP


def _append_relation(
    bond: dict[str, Any],
    *,
    relation_type: str,
    targets: list[str],
    leverage: float | None = None,
) -> None:
    cleaned_targets = [str(t) for t in targets if str(t or "").strip()]
    if not cleaned_targets:
        return
    relations = bond.setdefault("relations", [])
    if not isinstance(relations, list):
        return
    relation: dict[str, Any] = {
        "relation_type": relation_type,
        "targets": cleaned_targets,
    }
    if leverage is not None:
        relation["leverage"] = float(leverage)
    relations.append(relation)


# Canonical 1.x → 2.0 RuleType rewrites for unambiguous rule types.
# Exported so the API normalizer imports from a single source of truth.
# Each value is (new_rule_type, coverage_mode).
#
# PAY_FROM_RESERVE is intentionally ABSENT: its semantics are ambiguous
# (it could mean current-coupon top-up, shortfall coverage, or principal
# acceleration depending on context) and silently mapping it would change
# cashflow behaviour.  migrate_deal_payload() raises ValueError for that
# type with a message that tells the user which explicit form to use.
LEGACY_RULE_TYPE_MAP: dict[str, tuple[str, str]] = {
    "PAY_TO_RESERVE":             ("PAY_TO_ACCOUNT", "NORMAL"),
    "PAY_FROM_RESERVE_INTEREST":  ("PAY_INTEREST",   "INTEREST_SHORTFALL"),
    "PAY_FROM_RESERVE_PRINCIPAL": ("PAY_PRINCIPAL",  "PRINCIPAL_ACCELERATION"),
    "PAY_RECOURSE_INTEREST":      ("PAY_INTEREST",   "INTEREST_SHORTFALL"),
    "PAY_RECOURSE_PRINCIPAL":     ("PAY_PRINCIPAL",  "PRINCIPAL_ACCELERATION"),
}

# Generic PAY_FROM_RESERVE must be resolved manually; raise a descriptive error.
_AMBIGUOUS_RULE_TYPES = frozenset({"PAY_FROM_RESERVE"})


def migrate_deal_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy deal payloads to current schema shape.

    This migration layer is idempotent and non-destructive:
    - rewrites removed / renamed fields to their current equivalents
    - injects missing optional keys expected by the current runtime
    - safe to call multiple times on the same payload

    Must be called before DealDefinition.model_validate() on any payload that
    may have originated from a 1.x studio snapshot or an older API client.
    """
    migrated = deepcopy(payload)

    # ── Stamp the output with the current schema version ─────────────────────
    # Always overwrite: any payload that has been through migrate_deal_payload
    # is now in 2.0 form regardless of what version was persisted.
    migrated["schema_version"] = SCHEMA_VERSION

    # ── SR7: Migrate deal_knobs.discount_factor → discount_factor_pct ────────
    # Remove the legacy knob unconditionally; typed field is canonical.
    # If both exist, typed field wins. If only legacy exists, copy and clamp.
    knobs = migrated.get("deal_knobs")
    if isinstance(knobs, dict) and "discount_factor" in knobs:
        legacy_val = knobs.pop("discount_factor")
        migrated["deal_knobs"] = knobs
        if "discount_factor_pct" not in migrated or migrated.get("discount_factor_pct") is None:
            if isinstance(legacy_val, (int, float)):
                # Clamp to schema range [0, 100] to match typed field validation.
                migrated["discount_factor_pct"] = max(0.0, min(100.0, float(legacy_val)))

    # ── Account hard-cut fields ──────────────────────────────────────────────
    for acct in migrated.get("accounts", []) or []:
        if isinstance(acct, dict):
            if "account_type" in acct and "account_category" not in acct:
                acct["account_category"] = acct.pop("account_type")
            elif "account_type" in acct:
                acct.pop("account_type")

    for fee in migrated.get("fees", []) or []:
        if isinstance(fee, dict):
            fee.setdefault("amount_expr", None)
            fee.setdefault("rate_expr", None)

    for rule in migrated.get("waterfall_rules", []) or []:
        if isinstance(rule, dict):
            old_type = rule.get("rule_type")
            if isinstance(old_type, str) and old_type in _AMBIGUOUS_RULE_TYPES:
                raise ValueError(
                    f"Rule '{rule.get('rule_id', '?')}' uses removed rule_type "
                    f"'{old_type}', which has ambiguous semantics and cannot be "
                    f"automatically migrated.  Replace it with one of: "
                    f"PAY_INTEREST (with coverage_mode=NORMAL or INTEREST_SHORTFALL), "
                    f"PAY_PRINCIPAL (with coverage_mode=NORMAL or PRINCIPAL_ACCELERATION), "
                    f"or PAY_TO_ACCOUNT."
                )
            if isinstance(old_type, str) and old_type in LEGACY_RULE_TYPE_MAP:
                new_type, default_mode = LEGACY_RULE_TYPE_MAP[old_type]
                rule["rule_type"] = new_type
                # Only set coverage_mode if not already explicitly specified and
                # non-None.  Treat null/None the same as absent.
                existing_mode = rule.get("coverage_mode")
                if existing_mode is None:
                    rule["coverage_mode"] = default_mode
            if "max_amount" in rule and "max_amount_fixed" not in rule:
                rule["max_amount_fixed"] = rule.get("max_amount")
            rule.setdefault("max_amount_expr", None)
            rule.setdefault("condition_expr", None)
            rule.setdefault("allow_negative_source", False)
            # Treat null/None coverage_mode as missing → default to NORMAL.
            if rule.get("coverage_mode") is None:
                rule["coverage_mode"] = "NORMAL"
    for trigger in migrated.get("triggers", []) or []:
        if isinstance(trigger, dict):
            trigger.setdefault("calculation_ref", None)
            trigger.setdefault("comparison_ref", None)
    # ── Source / target token rename (1.x → 2.0) ────────────────────────────
    # INT_CASH → ACT_INT, PRIN_CASH → ACT_PRIN, COLLATERAL → CASH (dropped).
    # Group-prefixed variants (GROUP_1_INT_CASH etc.) are handled by the regex
    # replacement below.  This applies to from_sources and to_targets in rules.
    def _migrate_token(tok: Any) -> Any:
        if not isinstance(tok, str):
            return tok
        # Bare tokens — internal IR renames only. INT_COLLECTION / PRIN_COLLECTION
        # are UI source-dropdown labels that only appear in from_sources (never in
        # to_targets, which always contain bond/account/fee/stream names). Rewriting
        # them here would corrupt any bond or account legitimately named
        # "INT_COLLECTION". The API normalizer's _LEGACY_RULE_SOURCE_MAP handles
        # those labels correctly, restricted to from_sources.
        _bare = {
            "INT_CASH": "ACT_INT",
            "PRIN_CASH": "ACT_PRIN",
            "COLLATERAL": "CASH",
        }
        if tok in _bare:
            return _bare[tok]
        # Group-prefixed tokens: GROUP_<id>_INT_CASH → GROUP_<id>_ACT_INT etc.
        for old_suffix, new_suffix in (
            ("_INT_CASH", "_ACT_INT"),
            ("_PRIN_CASH", "_ACT_PRIN"),
            ("_COLLATERAL", "_CASH"),
        ):
            if tok.endswith(old_suffix):
                return tok[: -len(old_suffix)] + new_suffix
        return tok

    for rule in migrated.get("waterfall_rules", []) or []:
        if not isinstance(rule, dict):
            continue
        if isinstance(rule.get("from_sources"), list):
            rule["from_sources"] = [_migrate_token(s) for s in rule["from_sources"]]
        if isinstance(rule.get("to_targets"), list):
            rule["to_targets"] = [_migrate_token(t) for t in rule["to_targets"]]

    for bond in migrated.get("bonds", []) or []:
        if isinstance(bond, dict):
            # ── Notional / sizing hard-cut renames ──────────────────────────
            if "size_dollars" in bond and "notional" not in bond:
                bond["notional"] = bond.pop("size_dollars")
            elif "size_dollars" in bond:
                bond.pop("size_dollars")
            if "size_pct" in bond and "notional_pct_of_collateral" not in bond:
                bond["notional_pct_of_collateral"] = bond.pop("size_pct")
            elif "size_pct" in bond:
                bond.pop("size_pct")
            # schedule_speed_target was removed; TAC uses a degenerate low==high
            # band.  If the legacy field is present and the new band fields are
            # absent, copy the value so the deal remains valid after migration.
            sst = bond.pop("schedule_speed_target", None)
            if sst is not None:
                bond.setdefault("schedule_speed_low",  sst)
                bond.setdefault("schedule_speed_high", sst)

            kind = bond.get("kind")
            if isinstance(kind, str) and kind in _LEGACY_TRANCHE_KIND_MAP:
                bond["kind"] = _LEGACY_TRANCHE_KIND_MAP[kind]
            elif isinstance(bond.get("tranche_behavior"), str):
                bond["kind"] = _LEGACY_TRANCHE_KIND_MAP.get(str(bond["tranche_behavior"]), "CASH_PAY")
            elif isinstance(bond.get("tranche_type"), str):
                bond["kind"] = _LEGACY_TRANCHE_KIND_MAP.get(str(bond["tranche_type"]), "CASH_PAY")
            bond.pop("tranche_type", None)
            bond.pop("tranche_behavior", None)
            support_targets = bond.get("support_tranches")
            if isinstance(support_targets, list):
                _append_relation(
                    bond,
                    relation_type="SUPPORTED_BY",
                    targets=[str(t) for t in support_targets],
                )
            accretes_to_targets = bond.get("supported_by_tranches")
            if isinstance(accretes_to_targets, list):
                _append_relation(
                    bond,
                    relation_type="ACCRETES_TO",
                    targets=[str(t) for t in accretes_to_targets],
                )
            tracks = bond.get("tracks_bonds")
            if isinstance(tracks, dict):
                tracked = tracks.get("balance")
                if isinstance(tracked, list):
                    track_type = "BALANCE_TRACKS" if str(bond.get("kind") or "") == "PO" else "NOTIONAL_TRACKS"
                    _append_relation(
                        bond,
                        relation_type=track_type,
                        targets=[str(t) for t in tracked],
                    )
            parent = bond.get("parent_tranche")
            legacy_relation = bond.get("relation_type")
            if isinstance(parent, str) and parent.strip() and legacy_relation is not None:
                relation_key = (
                    legacy_relation.get("value")
                    if isinstance(legacy_relation, dict)
                    else str(getattr(legacy_relation, "value", legacy_relation))
                )
                relation_type = _LEGACY_STRUCTURE_RELATION_MAP.get(str(relation_key), str(relation_key).upper())
                leverage = bond.get("notional_ratio")
                _append_relation(
                    bond,
                    relation_type=relation_type,
                    targets=[parent],
                    leverage=float(leverage) if isinstance(leverage, (int, float)) else None,
                )
            for legacy_key in (
                "support_tranches",
                "supported_by_tranches",
                "tracks_bonds",
                "parent_tranche",
                "relation_type",
                "notional_ratio",
            ):
                bond.pop(legacy_key, None)
            bond.setdefault("kind", "CASH_PAY")
            bond.setdefault("pay_mode", "CASH_PAY")
            bond.setdefault("schedule_model_type", None)
            bond.setdefault("schedule_priority_tier", None)
            bond.setdefault("schedule_depends_on", None)
            bond.setdefault("schedule_speed_low", None)
            bond.setdefault("schedule_speed_high", None)
            bond.setdefault("schedule_custom_vector", None)
            bond.setdefault("schedule_contract", [])
            bond.setdefault("schedule_tolerance_bps", None)
            bond.setdefault("relations", [])
            bond.setdefault("z_accrual_enabled", False)
            bond.setdefault("z_release_trigger", None)

            # OA7 migration invariants: ensure migrated bonds satisfy DealDefinition
            # validators without requiring callers to know the new invariant rules.
            migrated_kind = bond.get("kind", "CASH_PAY")
            if migrated_kind == "Z":
                # Z bonds require z_accrual_enabled=True and pay_mode=PIK.
                # Legacy Z bonds that didn't set these explicitly are corrected here
                # so that migrate_deal_payload() output always satisfies the invariant.
                if not bond.get("z_accrual_enabled"):
                    bond["z_accrual_enabled"] = True
                if bond.get("pay_mode") == "CASH_PAY":
                    bond["pay_mode"] = "PIK"
            elif migrated_kind in ("PAC", "TAC"):
                # PAC/TAC require schedule_contract or schedule_model_type.
                # Legacy deals without a schedule get a PSA placeholder so the deal
                # can load and run (the user can re-derive the schedule in the Studio).
                has_contract = bool(bond.get("schedule_contract"))
                has_model = bond.get("schedule_model_type") not in (None, "")
                if not has_contract and not has_model:
                    bond["schedule_model_type"] = "PSA"
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
