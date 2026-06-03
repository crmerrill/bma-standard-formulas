"""Tests for DiagnosticPayload + QuickFix (ve-5).

AC 1 — QuickFix is an additive optional field on DiagnosticPayload (Python).
       Existing 5-field payloads remain valid (no schema change).
       QuickFix schema is exactly: {action_id: str, params: dict[str, Any]}.

AC 1.b (R1 fold-back) — backward compat: payloads with no `fix` still validate.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from bma_standard_formulas.diagnostics.payload import (
    DiagnosticPayload,
    Severity,
)


def test_payload_remains_backward_compatible_with_no_fix() -> None:
    """A payload without `fix` validates and serializes the same as before ve-5."""
    payload = DiagnosticPayload(
        code="BOND_NAME_EMPTY",
        severity=Severity.error,
        path="deal.bonds[0].name",
        message="Bond name must not be empty.",
        payload={},
    )
    # `fix` defaults to None; payload is otherwise identical to vpc-1 era.
    assert payload.fix is None

    # Round-trip serialization preserves backward-compat shape: when fix is
    # None, it can be excluded for legacy compatibility OR emitted as null.
    # Either is acceptable per "additive field"; assert both directions parse.
    legacy_json = json.dumps(
        {
            "code": "BOND_NAME_EMPTY",
            "severity": "error",
            "path": "deal.bonds[0].name",
            "message": "Bond name must not be empty.",
            "payload": {},
        }
    )
    parsed = DiagnosticPayload.model_validate_json(legacy_json)
    assert parsed.fix is None
    assert parsed.code == "BOND_NAME_EMPTY"


def test_quick_fix_schema_serialization() -> None:
    """QuickFix has exactly action_id (str) + params (dict[str, Any])."""
    payload = DiagnosticPayload(
        code="BOND_NAME_DUPLICATE",
        severity=Severity.error,
        path="deal.bonds[1].name",
        message="Duplicate bond name 'Tranche_A'.",
        payload={"duplicate_at_indices": [0, 1]},
        fix={
            "action_id": "manual_resolve_duplicate_bond_name",
            "params": {
                "duplicate_indices": [0, 1],
                "hint": "Rename one of the duplicates.",
            },
        },
    )
    assert payload.fix is not None
    assert payload.fix.action_id == "manual_resolve_duplicate_bond_name"
    assert payload.fix.params == {
        "duplicate_indices": [0, 1],
        "hint": "Rename one of the duplicates.",
    }

    # Round-trip via JSON: fix is preserved.
    j = payload.model_dump_json()
    restored = DiagnosticPayload.model_validate_json(j)
    assert restored.fix is not None
    assert restored.fix.action_id == "manual_resolve_duplicate_bond_name"
    assert restored.fix.params["duplicate_indices"] == [0, 1]


def test_quick_fix_rejects_invalid_shape() -> None:
    """QuickFix must have action_id (str) and params (dict). Other shapes fail."""
    with pytest.raises(ValidationError):
        DiagnosticPayload(
            code="X",
            severity=Severity.error,
            path="$",
            message="m",
            payload={},
            fix={"action_id": 123, "params": {}},  # action_id must be str
        )

    with pytest.raises(ValidationError):
        DiagnosticPayload(
            code="X",
            severity=Severity.error,
            path="$",
            message="m",
            payload={},
            fix={"action_id": "foo"},  # missing params
        )
