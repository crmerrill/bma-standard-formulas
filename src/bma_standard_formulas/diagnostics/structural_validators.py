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
