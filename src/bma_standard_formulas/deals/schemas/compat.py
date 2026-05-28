"""Schema version compatibility matrix."""
from .common import SCHEMA_VERSION
from .validation import SchemaCompatibility

COMPATIBILITY_MATRIX: list[SchemaCompatibility] = [
    SchemaCompatibility(
        ir_schema_version="1.0.0",
        runtime_version="1.0.0",
        artifact_schema_version="1.0.0",
        compatible=False,
        notes=(
            "1.0.0 payloads require migration to 2.0.0 before use. "
            "Call migrate_deal_payload() from bma_standard_formulas.deals.schemas.migrations "
            "on any persisted 1.x payload before DealDefinition.model_validate()."
        ),
    ),
    SchemaCompatibility(
        ir_schema_version="2.0.0",
        runtime_version="2.0.0",
        artifact_schema_version="2.0.0",
        compatible=True,
        notes=(
            "2.0.0 introduces hard-cut breaking changes from 1.x: "
            "AccountDef.account_type removed; BondDef.size_dollars/size_pct removed; "
            "BondDef.schedule_speed_target removed; TrancheType+TrancheBehavior collapsed "
            "to TrancheKind; 6 relation fields collapsed to BondDef.relations; "
            "PAY_TO_RESERVE and PAY_FROM_RESERVE_* rule types removed; "
            "INT_CASH/PRIN_CASH/COLLATERAL source tokens renamed. "
            "All rewritable 1.x fields are handled by migrate_deal_payload()."
        ),
    ),
]


def check_compatibility(
    ir_version: str,
    runtime_version: str,
    artifact_version: str,
) -> bool:
    """Return True if the given version triple is in the compatibility matrix."""
    for entry in COMPATIBILITY_MATRIX:
        if (
            entry.ir_schema_version == ir_version
            and entry.runtime_version == runtime_version
            and entry.artifact_schema_version == artifact_version
        ):
            return entry.compatible
    return False
