"""Contract tests for diagnostic payload schema types."""

from __future__ import annotations

from typing import Any, get_args, get_origin

import pydantic
import pytest

from bma_standard_formulas.diagnostics import DiagnosticPayload, Owner, Severity


def test_payload_and_enums_conform_to_schema() -> None:
    """AC 1, 2: Enums and payload schema match the contract."""
    assert {s.value for s in Severity} == {"error", "warning", "info"}
    assert {o.value for o in Owner} == {"worker", "backend", "both"}

    assert issubclass(DiagnosticPayload, pydantic.BaseModel)

    fields = DiagnosticPayload.model_fields
    # ve-5 added optional `fix: QuickFix | None`; the original five fields remain.
    assert set(fields) == {"code", "severity", "path", "message", "payload", "fix"}
    assert fields["code"].annotation is str
    assert fields["severity"].annotation is Severity
    assert fields["path"].annotation is str
    assert fields["message"].annotation is str

    payload_annotation = fields["payload"].annotation
    assert get_origin(payload_annotation) is dict
    assert get_args(payload_annotation) == (str, Any)
    assert fields["payload"].default_factory is dict

    payload = DiagnosticPayload(
        code="X",
        severity=Severity.error,
        path="deal.bonds[0].coupon",
        message="bad",
        payload={"k": "v"},
    )
    assert payload.model_dump(mode="json") == {
        "code": "X",
        "severity": "error",
        "path": "deal.bonds[0].coupon",
        "message": "bad",
        "payload": {"k": "v"},
        "fix": None,
    }

    with pytest.raises(pydantic.ValidationError):
        DiagnosticPayload(
            code="X",
            severity="critical",
            path="deal.bonds[0].coupon",
            message="bad",
        )
