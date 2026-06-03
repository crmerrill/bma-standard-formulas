"""Backend SSE validation service — ve-3-sse-streaming-backend.

Streams diagnostic events produced by static backend validation (structural
validators + Pydantic model validators).  Runtime checks (carry tie-out, etc.)
that require DealRunInput / ScenarioOutputBundle are intentionally excluded.
"""

from __future__ import annotations

from typing import Any, Iterator, Literal

from pydantic import BaseModel, ValidationError

from bma_standard_formulas.diagnostics import DiagnosticPayload, Severity
from bma_standard_formulas.diagnostics.structural_validators import (
    validate_bond_name_duplicate,
    validate_bond_name_empty,
    validate_kind_schedule_source,
    validate_multi_group_routing,
    validate_multi_target_weight_sum,
    validate_nla_subordination,
    validate_reference_broken,
)
from bma_standard_formulas.deals.schemas.ir import DealDefinition

# Ordered list of all registered structural validator callables.
# Each function accepts a raw deal dict and returns list[DiagnosticPayload].
# Patched by test_validate_stream_emits_failed_terminal_on_validation_exception.
_STRUCTURAL_VALIDATORS = [
    validate_bond_name_empty,
    validate_bond_name_duplicate,
    validate_reference_broken,
    validate_multi_target_weight_sum,
    validate_kind_schedule_source,
    validate_nla_subordination,
    validate_multi_group_routing,
]


class ValidationStreamEvent(BaseModel):
    event_type: Literal["diagnostic", "validation_complete", "validation_failed"]
    payload: DiagnosticPayload | None = None
    error: str | None = None


def stream_validation(deal_dict: dict[str, Any]) -> Iterator[ValidationStreamEvent]:
    """Yield diagnostic events then a single terminal event.

    Runs:
    1. All registered ``@diagnostic_code`` structural validators (vpc-1 + vpc-5 + ve-2).
    2. ``DealDefinition.model_validate`` — catches model_validators (including
       ``_validate_references``) and field_validators; Pydantic ValidationError
       is converted to ``IR_VALIDATION_ERROR`` diagnostic events rather than
       treated as an unexpected failure.

    Yields a ``validation_complete`` terminal on success or a
    ``validation_failed`` terminal if an unexpected exception propagates.
    Exactly one terminal event is always emitted; the stream closes immediately
    after it.
    """
    try:
        # ── 1. Structural validators (work on the raw dict) ───────────────
        for fn in _STRUCTURAL_VALIDATORS:
            for dx in fn(deal_dict):
                yield ValidationStreamEvent(event_type="diagnostic", payload=dx)

        # ── 2. Pydantic model validators (including _validate_references) ─
        try:
            DealDefinition.model_validate(deal_dict)
        except ValidationError as exc:
            for err in exc.errors():
                loc_parts = err.get("loc", ())
                path = ".".join(str(p) for p in loc_parts) if loc_parts else "$"
                yield ValidationStreamEvent(
                    event_type="diagnostic",
                    payload=DiagnosticPayload(
                        code="IR_VALIDATION_ERROR",
                        severity=Severity.error,
                        path=path,
                        message=err.get("msg", "IR validation error"),
                        payload={"pydantic_type": err.get("type", "")},
                    ),
                )

        # ── Terminal: success ─────────────────────────────────────────────
        yield ValidationStreamEvent(event_type="validation_complete")

    except Exception as exc:  # unexpected failure — not a ValidationError
        yield ValidationStreamEvent(
            event_type="validation_failed",
            error=str(exc),
        )
