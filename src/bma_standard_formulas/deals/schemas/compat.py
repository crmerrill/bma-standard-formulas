"""Schema version compatibility matrix."""
from .common import SCHEMA_VERSION
from .validation import SchemaCompatibility

COMPATIBILITY_MATRIX: list[SchemaCompatibility] = [
    SchemaCompatibility(
        ir_schema_version="1.0.0",
        runtime_version="1.0.0",
        artifact_schema_version="1.0.0",
        compatible=True,
        notes="Initial release",
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
