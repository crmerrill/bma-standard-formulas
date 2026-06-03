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
    def _validate_layout_entries(
        cls, v: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Per-entity layout entries require x: float, y: float; optional collapsed: bool | None."""
        for key, entry in v.items():
            # Required: x, y must be present and numeric (int/float; bool excluded since bool is a subtype of int in Python).
            for field in ("x", "y"):
                if field not in entry:
                    raise ValueError(
                        f"layout entry '{key}' missing required field '{field}'"
                    )
                value = entry[field]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(
                        f"layout entry '{key}' field '{field}' must be a number; got {type(value).__name__}"
                    )
            # Optional: collapsed must be bool or None when present.
            if "collapsed" in entry:
                collapsed = entry["collapsed"]
                if collapsed is not None and not isinstance(collapsed, bool):
                    raise ValueError(
                        f"layout entry '{key}' field 'collapsed' must be bool or None; got {type(collapsed).__name__}"
                    )
        return v
