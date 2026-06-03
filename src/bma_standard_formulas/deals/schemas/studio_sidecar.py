"""Studio sidecar schema (sdpm-1).

View-local sidecar persisted alongside deal.json in the deal git repo.
Never exported. Holds graph layout overrides + per-deal UI preferences only.

Per Phase 0 B5:
- AI provenance lives in commit metadata.
- Per-entity notes live on IR description fields.
- Scenarios live in scenarios.json.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class StudioSidecar(BaseModel):
    """Minimal view-local sidecar schema."""

    schema_version: str = "1.0.0"
    layout_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    ui_preferences: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @field_validator("layout_overrides")
    @classmethod
    def _require_x_and_y(
        cls, v: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        for key, entry in v.items():
            if "x" not in entry:
                raise ValueError(f"layout entry '{key}' missing required field 'x'")
            if "y" not in entry:
                raise ValueError(f"layout entry '{key}' missing required field 'y'")
        return v
