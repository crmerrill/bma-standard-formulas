"""Contract tests for the Studio sidecar schema (sdpm-1)."""

from __future__ import annotations

from typing import Any, get_args, get_origin

import pydantic
import pytest


def test_studio_sidecar_model_validates_exact_fields() -> None:
    """AC 1, 2: schema is lean and enforces typed layout payloads."""
    from bma_standard_formulas.deals.schemas.studio_sidecar import StudioSidecar

    fields = StudioSidecar.model_fields
    assert set(fields) == {"schema_version", "layout_overrides", "ui_preferences"}

    assert fields["schema_version"].annotation is str
    assert fields["schema_version"].default == "1.0.0"

    layout_annotation = fields["layout_overrides"].annotation
    assert get_origin(layout_annotation) is dict
    assert get_args(layout_annotation)[0] is str
    assert get_origin(get_args(layout_annotation)[1]) is dict
    assert get_args(get_args(layout_annotation)[1]) == (str, Any)

    ui_preferences_annotation = fields["ui_preferences"].annotation
    assert get_origin(ui_preferences_annotation) is dict
    assert get_args(ui_preferences_annotation) == (str, Any)

    sidecar = StudioSidecar(
        layout_overrides={
            "bond:A1": {"x": 110.25, "y": 42.5},
            "bond:B1": {"x": -12.0, "y": 8.75, "collapsed": True},
            "account:RESERVE": {"x": 0.0, "y": 0.0, "collapsed": None},
        },
        ui_preferences={
            "left_panel_width": 360,
            "show_grid": True,
            "zoom": 0.85,
            "selected_tab": "waterfall",
        },
    )
    assert sidecar.layout_overrides["bond:A1"]["x"] == 110.25
    assert sidecar.layout_overrides["bond:B1"]["collapsed"] is True
    assert sidecar.layout_overrides["account:RESERVE"]["collapsed"] is None

    with pytest.raises(pydantic.ValidationError):
        StudioSidecar(
            layout_overrides={"bond:A1": {"y": 10.0}},
            ui_preferences={},
        )

    with pytest.raises(pydantic.ValidationError):
        StudioSidecar(
            layout_overrides={"bond:A1": {"x": 10.0}},
            ui_preferences={},
        )

    payload_with_extras = {
        "schema_version": "1.0.0",
        "layout_overrides": {"bond:A1": {"x": 1.0, "y": 2.0}},
        "ui_preferences": {},
        "ai_provenance": {"source": "llm"},
        "notes": {"bond:A1": "manual note"},
        "tags": ["reviewed"],
        "scratchwork": {"draft": True},
    }
    try:
        parsed = StudioSidecar.model_validate(payload_with_extras)
    except pydantic.ValidationError:
        pass
    else:
        parsed_dump = parsed.model_dump()
        assert "ai_provenance" not in parsed_dump
        assert "notes" not in parsed_dump
        assert "tags" not in parsed_dump
        assert "scratchwork" not in parsed_dump


def test_studio_sidecar_roundtrip_serialization() -> None:
    """AC 3: JSON serialization/deserialization is lossless for allowed fields."""
    from bma_standard_formulas.deals.schemas.studio_sidecar import StudioSidecar

    original = StudioSidecar(
        schema_version="1.0.0",
        layout_overrides={
            "bond:A1": {"x": 125.0, "y": 95.5, "collapsed": False},
            "bond:M1": {"x": 265.25, "y": 210.75},
            "trigger:LOSS_TEST": {"x": 480.0, "y": 320.0, "collapsed": None},
        },
        ui_preferences={
            "canvas_zoom": 0.9,
            "canvas_pan": {"x": -145.5, "y": 88.0},
            "active_sidebar": "inspector",
            "show_diagnostics": True,
            "theme": "dark",
        },
    )

    json_payload = original.model_dump_json(indent=2)
    restored = StudioSidecar.model_validate_json(json_payload)

    assert restored == original
    assert restored.model_dump() == original.model_dump()


def test_studio_sidecar_rejects_invalid_layout_field_types() -> None:
    """AC 1 (R1 fix-pass): inner layout entries require numeric x/y and bool|None collapsed."""
    import pytest
    from pydantic import ValidationError
    from bma_standard_formulas.deals.schemas.studio_sidecar import StudioSidecar

    # Invalid x type (string)
    with pytest.raises(ValidationError) as exc:
        StudioSidecar(layout_overrides={"bond:A1": {"x": "left", "y": 100.0}})
    assert "x" in str(exc.value)

    # Invalid y type (list)
    with pytest.raises(ValidationError) as exc:
        StudioSidecar(layout_overrides={"bond:A1": {"x": 100.0, "y": [1, 2]}})
    assert "y" in str(exc.value)

    # Invalid collapsed type (string)
    with pytest.raises(ValidationError) as exc:
        StudioSidecar(
            layout_overrides={"bond:A1": {"x": 100.0, "y": 200.0, "collapsed": "yes"}}
        )
    assert "collapsed" in str(exc.value)

    # bool x is rejected (bool is technically int subtype in Python; excluded explicitly)
    with pytest.raises(ValidationError) as exc:
        StudioSidecar(layout_overrides={"bond:A1": {"x": True, "y": 100.0}})
    assert "x" in str(exc.value)

    # Valid baseline still works
    StudioSidecar(
        layout_overrides={
            "bond:A1": {"x": 100, "y": 200.5, "collapsed": True},
            "bond:M1": {"x": 50.0, "y": 75.0, "collapsed": None},
            "bond:R1": {"x": 0.0, "y": 0.0},
        }
    )
