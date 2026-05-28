from bma_standard_formulas.deals.schemas.common import TrancheRelationType
from bma_standard_formulas.deals.schemas.ir import BondDef, TrancheRelation
from bma_standard_formulas.deals.schemas.migrations import migrate_deal_payload


def test_all_relation_types_validate_on_bonddef():
    relation_types = [
        TrancheRelationType.SUPPORTED_BY,
        TrancheRelationType.ACCRETES_TO,
        TrancheRelationType.NOTIONAL_TRACKS,
        TrancheRelationType.BALANCE_TRACKS,
        TrancheRelationType.COUPON_INVERSE_OF,
        TrancheRelationType.COUPON_LEVERAGE_OF,
        TrancheRelationType.MACR_EXCHANGE,
    ]
    bond = BondDef(
        name="X",
        relations=[
            TrancheRelation(
                relation_type=relation_type,
                targets=["A"],
                leverage=2.0 if relation_type == TrancheRelationType.COUPON_LEVERAGE_OF else None,
            )
            for relation_type in relation_types
        ],
    )
    assert len(bond.relations) == len(relation_types)


def test_migration_collapses_legacy_relationship_fields_to_relations():
    payload = {
        "deal_name": "LegacyRelations",
        "bonds": [
            {
                "name": "PAC",
                "kind": "PAC",
                "support_tranches": ["S1", "S2"],
            },
            {
                "name": "Z",
                "kind": "Z",
                "supported_by_tranches": ["A"],
                "tracks_bonds": {"balance": ["PO"]},
                "parent_tranche": "FLT",
                "relation_type": "floater_inverse",
                "notional_ratio": 1.5,
            },
        ],
        "waterfall_rules": [],
    }
    migrated = migrate_deal_payload(payload)
    pac = migrated["bonds"][0]
    z = migrated["bonds"][1]

    assert "support_tranches" not in pac
    assert pac["relations"] == [
        {"relation_type": "SUPPORTED_BY", "targets": ["S1", "S2"]},
    ]

    assert "supported_by_tranches" not in z
    assert "tracks_bonds" not in z
    assert "parent_tranche" not in z
    assert "relation_type" not in z
    assert "notional_ratio" not in z
    rel_types = {rel["relation_type"] for rel in z["relations"]}
    assert rel_types == {"ACCRETES_TO", "NOTIONAL_TRACKS", "COUPON_INVERSE_OF"}
