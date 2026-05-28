"""Comprehensive tests for DealDefinition schema migration (RG1).

Covers:
- Schema version is 2.0.0 and SCHEMA_COMPATIBILITY documents all hard cuts
- migrate_deal_payload() handles every removed/renamed field class
- Every legacy RuleType migrates to a valid current rule
- Legacy tranche type/behavior maps correctly via the canonical map
- Consolidated _LEGACY_TRANCHE_KIND_MAP is used by both the migrations module
  and the API normalizer (single source of truth)
- API _normalize_legacy_studio_ir normalizes removed rule types
- Idempotency: running migration twice produces identical output
"""
from __future__ import annotations

import pytest

from bma_standard_formulas.deals.schemas.common import (
    SCHEMA_VERSION,
    SCHEMA_COMPATIBILITY,
)
from bma_standard_formulas.deals.schemas.ir import DealDefinition
from bma_standard_formulas.deals.schemas.migrations import (
    LEGACY_RULE_TYPE_MAP,
    LEGACY_TRANCHE_KIND_MAP,
    migrate_deal_payload,
)
# Keep private alias import for backwards-compat test
_LEGACY_TRANCHE_KIND_MAP = LEGACY_TRANCHE_KIND_MAP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_deal(**overrides) -> dict:
    base: dict = {
        "deal_name": "MigrationTest",
        "bonds": [],
        "waterfall_rules": [],
    }
    base.update(overrides)
    return base


def _bond(name: str = "A", **kw) -> dict:
    b: dict = {"name": name, "kind": "CASH_PAY", "notional": 100.0}
    b.update(kw)
    return b


def _rule(rule_id: str = "r1", rule_type: str = "PAY_RESIDUAL", **kw) -> dict:
    r: dict = {
        "rule_id": rule_id,
        "rule_type": rule_type,
        "order": 0,
        "from_sources": ["CASH"],
        "to_targets": ["A"],
    }
    r.update(kw)
    return r


# ---------------------------------------------------------------------------
# Schema version + compatibility metadata
# ---------------------------------------------------------------------------


def test_schema_version_is_2_0_0():
    assert SCHEMA_VERSION == "2.0.0"


def test_schema_compatibility_documents_all_hard_cuts():
    """Every category of breaking change must have an entry."""
    required_keys = {
        "account_type_removed",
        "size_dollars_removed",
        "size_pct_removed",
        "schedule_speed_target_removed",
        "tranche_type_removed",
        "relation_fields_removed",
        "pay_to_reserve_renamed",
        "reserve_recourse_rules_removed",
        "token_rename",
    }
    missing = required_keys - set(SCHEMA_COMPATIBILITY.keys())
    assert not missing, f"SCHEMA_COMPATIBILITY is missing entries for: {missing}"


def test_schema_compatibility_values_are_nonempty_strings():
    for key, val in SCHEMA_COMPATIBILITY.items():
        assert isinstance(val, str) and val.strip(), (
            f"SCHEMA_COMPATIBILITY['{key}'] must be a non-empty string"
        )


# ---------------------------------------------------------------------------
# RuleType migrations
# ---------------------------------------------------------------------------

_RULE_TYPE_CASES = [
    # (legacy_rule_type, expected_new_type, expected_coverage_mode)
    # PAY_FROM_RESERVE is excluded here — it raises ValueError (see dedicated test below).
    ("PAY_TO_RESERVE",             "PAY_TO_ACCOUNT", "NORMAL"),
    ("PAY_FROM_RESERVE_INTEREST",  "PAY_INTEREST",   "INTEREST_SHORTFALL"),
    ("PAY_FROM_RESERVE_PRINCIPAL", "PAY_PRINCIPAL",  "PRINCIPAL_ACCELERATION"),
    ("PAY_RECOURSE_INTEREST",      "PAY_INTEREST",   "INTEREST_SHORTFALL"),
    ("PAY_RECOURSE_PRINCIPAL",     "PAY_PRINCIPAL",  "PRINCIPAL_ACCELERATION"),
]


@pytest.mark.parametrize("legacy,expected_type,expected_mode", _RULE_TYPE_CASES)
def test_legacy_rule_type_migrates_to_new_form(legacy, expected_type, expected_mode):
    payload = _minimal_deal(
        bonds=[_bond("A"), _bond("R", kind="RESIDUAL", is_bond=False, is_pseudo=True)],
        waterfall_rules=[_rule(rule_type=legacy)],
    )
    migrated = migrate_deal_payload(payload)
    rule = migrated["waterfall_rules"][0]
    assert rule["rule_type"] == expected_type, (
        f"{legacy} should migrate to {expected_type}, got {rule['rule_type']}"
    )
    assert rule["coverage_mode"] == expected_mode, (
        f"{legacy} should produce coverage_mode={expected_mode}, got {rule['coverage_mode']}"
    )


def test_existing_coverage_mode_is_not_overwritten_on_migration():
    """If a rule already has an explicit coverage_mode, migration must not overwrite it."""
    payload = _minimal_deal(
        bonds=[_bond()],
        waterfall_rules=[
            _rule(
                rule_type="PAY_FROM_RESERVE_INTEREST",
                coverage_mode="NORMAL",  # explicit override
            )
        ],
    )
    migrated = migrate_deal_payload(payload)
    assert migrated["waterfall_rules"][0]["coverage_mode"] == "NORMAL"


def test_current_rule_types_are_unchanged_by_migration():
    """Modern rule types must pass through the migrator without modification."""
    for current_type in (
        "PAY_INTEREST", "PAY_PRINCIPAL", "PAY_WRITEDOWN",
        "PAY_FEE", "PAY_TO_ACCOUNT", "PAY_RESIDUAL", "SPLIT_CASH",
    ):
        payload = _minimal_deal(
            bonds=[_bond()],
            waterfall_rules=[_rule(rule_type=current_type)],
        )
        migrated = migrate_deal_payload(payload)
        assert migrated["waterfall_rules"][0]["rule_type"] == current_type


def test_legacy_rule_type_map_covers_all_unambiguous_removed_types():
    """LEGACY_RULE_TYPE_MAP must cover all unambiguously-migratable removed types.
    PAY_FROM_RESERVE is excluded because it has ambiguous semantics and raises
    ValueError — it is handled separately via _AMBIGUOUS_RULE_TYPES."""
    from bma_standard_formulas.deals.schemas.migrations import _AMBIGUOUS_RULE_TYPES
    unambiguous_removed = {
        "PAY_TO_RESERVE",
        "PAY_FROM_RESERVE_INTEREST",
        "PAY_FROM_RESERVE_PRINCIPAL",
        "PAY_RECOURSE_INTEREST",
        "PAY_RECOURSE_PRINCIPAL",
    }
    missing = unambiguous_removed - set(LEGACY_RULE_TYPE_MAP.keys())
    assert not missing, f"LEGACY_RULE_TYPE_MAP missing entries for: {missing}"
    # Ambiguous types must NOT silently migrate.
    assert "PAY_FROM_RESERVE" in _AMBIGUOUS_RULE_TYPES
    assert "PAY_FROM_RESERVE" not in LEGACY_RULE_TYPE_MAP


# ---------------------------------------------------------------------------
# Account field migration
# ---------------------------------------------------------------------------


def test_account_type_renamed_to_account_category():
    payload = _minimal_deal(
        accounts=[{"name": "RESERVE", "account_type": "RESERVE", "initial_balance": 0.0}],
    )
    migrated = migrate_deal_payload(payload)
    acct = migrated["accounts"][0]
    assert "account_type" not in acct
    assert acct["account_category"] == "RESERVE"


def test_account_category_already_present_is_not_duplicated():
    payload = _minimal_deal(
        accounts=[{
            "name": "RESERVE",
            "account_category": "SPREAD_ACCOUNT",
            "account_type": "RESERVE",  # legacy field present alongside new
            "initial_balance": 0.0,
        }],
    )
    migrated = migrate_deal_payload(payload)
    acct = migrated["accounts"][0]
    assert "account_type" not in acct
    # account_category already set; must not be overwritten by the old value
    assert acct["account_category"] == "SPREAD_ACCOUNT"


# ---------------------------------------------------------------------------
# Bond sizing field migrations
# ---------------------------------------------------------------------------


def test_size_dollars_renamed_to_notional():
    payload = _minimal_deal(
        bonds=[{"name": "A", "kind": "CASH_PAY", "size_dollars": 250.0}],
    )
    migrated = migrate_deal_payload(payload)
    bond = migrated["bonds"][0]
    assert "size_dollars" not in bond
    assert bond["notional"] == 250.0


def test_size_pct_renamed_to_notional_pct_of_collateral():
    payload = _minimal_deal(
        bonds=[{"name": "A", "kind": "CASH_PAY", "size_pct": 95.65}],
    )
    migrated = migrate_deal_payload(payload)
    bond = migrated["bonds"][0]
    assert "size_pct" not in bond
    assert bond["notional_pct_of_collateral"] == 95.65


def test_notional_already_present_takes_precedence_over_size_dollars():
    payload = _minimal_deal(
        bonds=[{"name": "A", "kind": "CASH_PAY", "notional": 100.0, "size_dollars": 999.0}],
    )
    migrated = migrate_deal_payload(payload)
    bond = migrated["bonds"][0]
    assert "size_dollars" not in bond
    assert bond["notional"] == 100.0


def test_schedule_speed_target_removed():
    payload = _minimal_deal(
        bonds=[{"name": "A", "kind": "TAC", "schedule_speed_target": 165.0}],
    )
    migrated = migrate_deal_payload(payload)
    assert "schedule_speed_target" not in migrated["bonds"][0]


# ---------------------------------------------------------------------------
# Tranche kind map — single source of truth
# ---------------------------------------------------------------------------


def test_legacy_tranche_kind_map_is_canonical():
    """The API router must reference the same map object as migrations module."""
    from bma_cfengine_app.api.routers.deals import _LEGACY_TRANCHE_KIND_MAP as api_map
    # Must point to the same underlying dict (identity check, not just equality).
    assert api_map is LEGACY_TRANCHE_KIND_MAP, (
        "API _LEGACY_TRANCHE_KIND_MAP must reference migrations.LEGACY_TRANCHE_KIND_MAP, "
        "not a copy"
    )


_KIND_CASES = [
    ("SEQUENTIAL",         "CASH_PAY"),
    ("SUPPORT",            "CASH_PAY"),
    ("ACCRETION_DIRECTED", "CASH_PAY"),
    ("FLOATER",            "CASH_PAY"),
    ("INVERSE_FLOATER",    "CASH_PAY"),
    ("PAC_II",             "PAC"),
    ("Z_BOND",             "Z"),
]


@pytest.mark.parametrize("legacy_kind,expected", _KIND_CASES)
def test_legacy_tranche_kind_migrates_correctly(legacy_kind, expected):
    payload = _minimal_deal(
        bonds=[{"name": "A", "kind": legacy_kind}],
    )
    migrated = migrate_deal_payload(payload)
    assert migrated["bonds"][0]["kind"] == expected


def test_tranche_type_field_is_removed_by_migration():
    payload = _minimal_deal(
        bonds=[{"name": "A", "tranche_type": "SEQUENTIAL"}],
    )
    migrated = migrate_deal_payload(payload)
    bond = migrated["bonds"][0]
    assert "tranche_type" not in bond
    assert bond["kind"] == "CASH_PAY"


def test_tranche_behavior_field_is_removed_by_migration():
    payload = _minimal_deal(
        bonds=[{"name": "Z", "tranche_behavior": "Z", "tranche_type": "Z_BOND"}],
    )
    migrated = migrate_deal_payload(payload)
    bond = migrated["bonds"][0]
    assert "tranche_type" not in bond
    assert "tranche_behavior" not in bond
    assert bond["kind"] == "Z"


# ---------------------------------------------------------------------------
# Relation field migration
# ---------------------------------------------------------------------------


def test_support_tranches_migrated_to_relations():
    payload = _minimal_deal(
        bonds=[
            {"name": "PAC", "kind": "PAC", "support_tranches": ["S1", "S2"]},
            {"name": "S1",  "kind": "CASH_PAY"},
            {"name": "S2",  "kind": "CASH_PAY"},
        ],
    )
    migrated = migrate_deal_payload(payload)
    pac = migrated["bonds"][0]
    assert "support_tranches" not in pac
    rels = pac["relations"]
    assert len(rels) == 1
    assert rels[0]["relation_type"] == "SUPPORTED_BY"
    assert set(rels[0]["targets"]) == {"S1", "S2"}


def test_legacy_relation_fields_all_removed_after_migration():
    legacy_fields = (
        "support_tranches", "supported_by_tranches", "tracks_bonds",
        "parent_tranche", "relation_type", "notional_ratio",
    )
    payload = _minimal_deal(
        bonds=[{
            "name": "Z",
            "kind": "Z",
            "supported_by_tranches": ["A"],
            "parent_tranche": "FLT",
            "relation_type": "floater_inverse",
            "notional_ratio": 1.5,
        }],
    )
    migrated = migrate_deal_payload(payload)
    bond = migrated["bonds"][0]
    for field in legacy_fields:
        assert field not in bond, f"Legacy field '{field}' not removed by migration"


# ---------------------------------------------------------------------------
# API normalizer covers legacy rule types end-to-end
# ---------------------------------------------------------------------------


def test_api_normalizer_rewrites_legacy_rule_types():
    """_normalize_legacy_studio_ir must handle legacy rule types so that
    migrate_deal_payload receives already-normalized rule_type values."""
    from bma_cfengine_app.api.routers.deals import _normalize_legacy_studio_ir

    # Test each unambiguous legacy rule type.
    cases = [
        ("PAY_FROM_RESERVE_INTEREST",  "PAY_INTEREST",  "INTEREST_SHORTFALL"),
        ("PAY_FROM_RESERVE_PRINCIPAL", "PAY_PRINCIPAL", "PRINCIPAL_ACCELERATION"),
        ("PAY_RECOURSE_INTEREST",      "PAY_INTEREST",  "INTEREST_SHORTFALL"),
        ("PAY_RECOURSE_PRINCIPAL",     "PAY_PRINCIPAL", "PRINCIPAL_ACCELERATION"),
        ("PAY_TO_RESERVE",             "PAY_TO_ACCOUNT","NORMAL"),
    ]
    for legacy_type, expected_type, expected_mode in cases:
        raw = {
            "deal_name": "LegacyRuleStudio",
            "bonds": [{"name": "A", "kind": "CASH_PAY"}],
            "waterfall_rules": [
                {"rule_id": "r1", "rule_type": legacy_type,
                 "order": 0, "from_sources": ["SPREAD"], "to_targets": ["A"]},
            ],
        }
        normalized = _normalize_legacy_studio_ir(raw)
        rule = normalized["waterfall_rules"][0]
        assert rule["rule_type"] == expected_type, f"Failed for {legacy_type}"
        assert rule.get("coverage_mode") == expected_mode, f"Wrong mode for {legacy_type}"


def test_api_normalizer_then_migrate_produces_valid_deal():
    """Full pipeline: normalize → migrate → validate must succeed for a
    snapshot containing legacy reserve/recourse rule types."""
    from bma_cfengine_app.api.routers.deals import _normalize_legacy_studio_ir

    raw = {
        "deal_name": "LegacyReserveDeal",
        "bonds": [
            {"name": "A",  "kind": "CASH_PAY", "coupon": 5.0, "notional": 100.0},
            {"name": "R",  "kind": "RESIDUAL",  "is_bond": False, "is_pseudo": True},
        ],
        "accounts": [{"name": "SPREAD_ACCT", "account_category": "SPREAD_ACCOUNT"}],
        "waterfall_rules": [
            {"rule_id": "r1", "rule_type": "PAY_FROM_RESERVE_INTEREST",
             "order": 0, "from_sources": ["SPREAD_ACCT"], "to_targets": ["A"]},
            {"rule_id": "r2", "rule_type": "PAY_RESIDUAL",
             "order": 1, "from_sources": ["CASH"], "to_targets": ["R"]},
        ],
    }
    normalized = _normalize_legacy_studio_ir(raw)
    canonical = DealDefinition.model_validate(migrate_deal_payload(normalized))
    assert canonical.deal_name == "LegacyReserveDeal"
    rule = next(r for r in canonical.waterfall_rules if r.rule_id == "r1")
    from bma_standard_formulas.deals.schemas.common import RuleType, CoverageMode
    assert rule.rule_type == RuleType.PAY_INTEREST
    assert rule.coverage_mode == CoverageMode.INTEREST_SHORTFALL


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_migration_is_idempotent():
    """Calling migrate_deal_payload twice must produce the same result."""
    payload = _minimal_deal(
        bonds=[{
            "name": "A",
            "tranche_type": "SEQUENTIAL",
            "size_dollars": 100.0,
            "support_tranches": ["B"],
        }],
        accounts=[{"name": "RSRV", "account_type": "RESERVE", "initial_balance": 0.0}],
        waterfall_rules=[
            _rule(rule_type="PAY_FROM_RESERVE_INTEREST"),
        ],
    )
    once = migrate_deal_payload(payload)
    twice = migrate_deal_payload(once)
    assert once == twice


# ---------------------------------------------------------------------------
# Schema version stamping
# ---------------------------------------------------------------------------


def test_migration_stamps_schema_version():
    """migrate_deal_payload() must set schema_version to the current version."""
    payload = _minimal_deal()
    migrated = migrate_deal_payload(payload)
    assert migrated.get("schema_version") == SCHEMA_VERSION


def test_migration_always_stamps_current_schema_version():
    """After migration, schema_version must always be the current version.
    A persisted 1.0.0 payload becomes 2.0.0 after migration."""
    payload = _minimal_deal()
    payload["schema_version"] = "1.0.0"
    migrated = migrate_deal_payload(payload)
    assert migrated["schema_version"] == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Source / target token rename
# ---------------------------------------------------------------------------


_TOKEN_CASES = [
    ("INT_CASH",          "ACT_INT"),
    ("PRIN_CASH",         "ACT_PRIN"),
    ("COLLATERAL",        "CASH"),
    ("GROUP_1_INT_CASH",  "GROUP_1_ACT_INT"),
    ("GROUP_2_PRIN_CASH", "GROUP_2_ACT_PRIN"),
    ("GROUP_1_COLLATERAL","GROUP_1_CASH"),
]


@pytest.mark.parametrize("legacy_token,expected", _TOKEN_CASES)
def test_legacy_source_token_migrated_in_from_sources(legacy_token, expected):
    payload = _minimal_deal(
        bonds=[_bond()],
        waterfall_rules=[_rule(rule_type="PAY_INTEREST", from_sources=[legacy_token])],
    )
    migrated = migrate_deal_payload(payload)
    assert migrated["waterfall_rules"][0]["from_sources"] == [expected]


@pytest.mark.parametrize("legacy_token,expected", _TOKEN_CASES)
def test_legacy_source_token_migrated_in_to_targets(legacy_token, expected):
    payload = _minimal_deal(
        bonds=[_bond()],
        waterfall_rules=[_rule(rule_type="SPLIT_CASH", to_targets=[legacy_token])],
    )
    migrated = migrate_deal_payload(payload)
    assert migrated["waterfall_rules"][0]["to_targets"] == [expected]


def test_current_source_tokens_are_unchanged():
    for token in ("CASH", "ACT_INT", "ACT_PRIN", "LOSS", "GROUP_1_CASH"):
        payload = _minimal_deal(
            bonds=[_bond()],
            waterfall_rules=[_rule(from_sources=[token])],
        )
        migrated = migrate_deal_payload(payload)
        assert migrated["waterfall_rules"][0]["from_sources"] == [token]


# ---------------------------------------------------------------------------
# Ambiguous PAY_FROM_RESERVE must fail loudly
# ---------------------------------------------------------------------------


def test_pay_from_reserve_raises_value_error():
    """PAY_FROM_RESERVE has ambiguous semantics and must not be silently migrated."""
    payload = _minimal_deal(
        bonds=[_bond()],
        waterfall_rules=[_rule(rule_type="PAY_FROM_RESERVE")],
    )
    with pytest.raises(ValueError, match="PAY_FROM_RESERVE"):
        migrate_deal_payload(payload)


def test_pay_from_reserve_error_message_is_actionable():
    """The error must tell the user which replacement rule types to use."""
    payload = _minimal_deal(
        bonds=[_bond()],
        waterfall_rules=[_rule(rule_id="reserve_r1", rule_type="PAY_FROM_RESERVE")],
    )
    with pytest.raises(ValueError) as exc_info:
        migrate_deal_payload(payload)
    msg = str(exc_info.value)
    assert "reserve_r1" in msg
    assert "PAY_INTEREST" in msg
    assert "PAY_PRINCIPAL" in msg


# ---------------------------------------------------------------------------
# schedule_speed_target preserved into low/high
# ---------------------------------------------------------------------------


def test_schedule_speed_target_copied_into_low_high_when_absent():
    payload = _minimal_deal(
        bonds=[{"name": "A", "kind": "TAC", "schedule_speed_target": 165.0}],
    )
    migrated = migrate_deal_payload(payload)
    bond = migrated["bonds"][0]
    assert "schedule_speed_target" not in bond
    assert bond["schedule_speed_low"] == 165.0
    assert bond["schedule_speed_high"] == 165.0


def test_schedule_speed_target_does_not_overwrite_explicit_low_high():
    payload = _minimal_deal(
        bonds=[{
            "name": "A", "kind": "TAC",
            "schedule_speed_low": 150.0,
            "schedule_speed_high": 150.0,
            "schedule_speed_target": 165.0,
        }],
    )
    migrated = migrate_deal_payload(payload)
    bond = migrated["bonds"][0]
    assert "schedule_speed_target" not in bond
    # Original low/high must be preserved
    assert bond["schedule_speed_low"] == 150.0
    assert bond["schedule_speed_high"] == 150.0


# ---------------------------------------------------------------------------
# coverage_mode: null treated as missing
# ---------------------------------------------------------------------------


def test_coverage_mode_null_defaults_to_normal():
    """A rule with coverage_mode: null (JSON null) must default to NORMAL."""
    payload = _minimal_deal(
        bonds=[_bond()],
        waterfall_rules=[
            {**_rule(), "coverage_mode": None},
        ],
    )
    migrated = migrate_deal_payload(payload)
    assert migrated["waterfall_rules"][0]["coverage_mode"] == "NORMAL"


# ---------------------------------------------------------------------------
# Compat matrix
# ---------------------------------------------------------------------------


def test_compat_matrix_has_2_0_0_entry():
    from bma_standard_formulas.deals.schemas.compat import COMPATIBILITY_MATRIX, check_compatibility
    versions = [e.ir_schema_version for e in COMPATIBILITY_MATRIX]
    assert "2.0.0" in versions, "COMPATIBILITY_MATRIX must contain a 2.0.0 entry"


def test_compat_matrix_marks_1_0_0_incompatible():
    from bma_standard_formulas.deals.schemas.compat import check_compatibility
    assert not check_compatibility("1.0.0", "1.0.0", "1.0.0"), (
        "1.0.0 payloads are not directly compatible with 2.0; they require migration"
    )


def test_compat_matrix_marks_2_0_0_compatible():
    from bma_standard_formulas.deals.schemas.compat import check_compatibility
    assert check_compatibility("2.0.0", "2.0.0", "2.0.0")


# ---------------------------------------------------------------------------
# Public canonical tranche kind map
# ---------------------------------------------------------------------------


def test_legacy_tranche_kind_map_is_public():
    """LEGACY_TRANCHE_KIND_MAP must be importable as a public name."""
    from bma_standard_formulas.deals.schemas.migrations import LEGACY_TRANCHE_KIND_MAP
    assert isinstance(LEGACY_TRANCHE_KIND_MAP, dict)
    assert "SEQUENTIAL" in LEGACY_TRANCHE_KIND_MAP
