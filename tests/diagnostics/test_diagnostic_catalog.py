"""Catalog parity test for IR_VALIDATION_ERROR — ve-3 R1 fix-pass.

Asserts that IR_VALIDATION_ERROR is present in docs/architecture/diagnostic_catalog.md
with expected metadata: severity=error, owner=backend, non-empty path_schema,
and a non-empty message template.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "docs" / "architecture" / "diagnostic_catalog.md"
SCRIPT_PATH = REPO_ROOT / "scripts" / "parse_diagnostic_catalog.py"


def _import_parser():
    """Dynamically import parse_diagnostic_catalog from scripts/."""
    assert SCRIPT_PATH.exists(), f"Parser script not found: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("parse_diagnostic_catalog", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_ir_validation_error_is_cataloged() -> None:
    """ve-3 R1: IR_VALIDATION_ERROR must be present in the diagnostic catalog.

    stream_validation() in validation_service.py emits IR_VALIDATION_ERROR
    as a first-class diagnostic when DealDefinition.model_validate raises a
    Pydantic ValidationError. Per the R1 review finding, this code must be
    cataloged like all other diagnostic surface.
    """
    mod = _import_parser()
    records = mod.parse_diagnostic_catalog(CATALOG_PATH)
    by_code = {r["code"]: r for r in records}

    assert "IR_VALIDATION_ERROR" in by_code, (
        "IR_VALIDATION_ERROR is emitted by stream_validation() in "
        "src/bma_cfengine_app/orchestrator/deals/validation_service.py "
        "but is not listed in docs/architecture/diagnostic_catalog.md. "
        "Add a catalog row for this code."
    )

    rec = by_code["IR_VALIDATION_ERROR"]

    assert rec["severity"] == "error", (
        f"Expected severity='error' for IR_VALIDATION_ERROR, got '{rec['severity']}'"
    )
    assert rec["owner"] == "backend", (
        f"Expected owner='backend' for IR_VALIDATION_ERROR, got '{rec['owner']}'"
    )
    assert rec["path_schema"], (
        "path_schema for IR_VALIDATION_ERROR must be non-empty"
    )
    assert rec["message"], (
        "message template for IR_VALIDATION_ERROR must be non-empty"
    )


def test_stale_quickfix_is_cataloged() -> None:
    """rcf-3: STALE_QUICKFIX must be present with pinned metadata."""
    mod = _import_parser()
    records = mod.parse_diagnostic_catalog(CATALOG_PATH)
    by_code = {r["code"]: r for r in records}

    assert "STALE_QUICKFIX" in by_code, (
        "STALE_QUICKFIX must be listed in docs/architecture/diagnostic_catalog.md "
        "because canonicalizeConsolidateRuleRun invalid-range handling emits this warning."
    )

    rec = by_code["STALE_QUICKFIX"]
    assert rec["severity"] == "warning"
    assert rec["owner"] == "both"
    assert rec["path_schema"] == "deal.waterfall_rules"
