"""Tests for scripts/parse_diagnostic_catalog.py (vpc-2-catalog-document).

AC coverage:
  - AC 1, 2: parser extracts structured records with required keys from a valid table.
  - AC 3: parser raises a clear error on malformed/missing-column input.
"""

from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "parse_diagnostic_catalog.py"


def _import_parser():
    """Dynamically import parse_diagnostic_catalog from scripts/."""
    assert SCRIPT_PATH.exists(), f"Parser script not found: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("parse_diagnostic_catalog", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


SAMPLE_CATALOG_MD = textwrap.dedent("""\
    # Diagnostic Catalog

    Contract document linking Python `@diagnostic_code` decorators to the TS worker registry.

    ## Catalog Table

    | code | severity | path schema | message template | owner | quick fix | owning validator file:line |
    | --- | --- | --- | --- | --- | --- | --- |
    | MERGE_CONFLICT | error | deal.{entity_kind}[{entity_id}].{field_path} | Merge conflict on {field_path} between base and branch values for {entity_kind} {entity_id} | backend | Resolve conflict manually in Studio before retrying merge. | src/bma_cfengine_app/orchestrator/deals/merge.py:17 |
    | REPO_CORRUPT | error | deal:{deal_id} | Repository corruption detected for deal {deal_id}: {detail} | backend | Run restore_deal to re-clone from the last known-good backup. | src/bma_cfengine_app/orchestrator/deals/operational.py:45 |
""")


def test_parser_extracts_structured_records_from_markdown(tmp_path: Path) -> None:
    """AC 1, 2: parser returns a list of records with all required keys, one per table row."""
    catalog_file = tmp_path / "diagnostic_catalog.md"
    catalog_file.write_text(SAMPLE_CATALOG_MD)

    mod = _import_parser()
    records = mod.parse_diagnostic_catalog(catalog_file)

    assert len(records) == 2

    required_keys = {
        "code",
        "severity",
        "path_schema",
        "message",
        "owner",
        "quick_fix",
        "validator_file_line",
    }
    for record in records:
        assert required_keys == set(record.keys()), (
            f"Record missing expected keys. Got: {set(record.keys())}"
        )

    merge_conflict = next(r for r in records if r["code"] == "MERGE_CONFLICT")
    assert merge_conflict["severity"] == "error"
    assert merge_conflict["path_schema"] == "deal.{entity_kind}[{entity_id}].{field_path}"
    assert "conflict" in merge_conflict["message"].lower()
    assert merge_conflict["owner"] == "backend"
    assert merge_conflict["quick_fix"] != ""
    assert "merge.py" in merge_conflict["validator_file_line"]
    assert "17" in merge_conflict["validator_file_line"]

    repo_corrupt = next(r for r in records if r["code"] == "REPO_CORRUPT")
    assert repo_corrupt["severity"] == "error"
    assert repo_corrupt["path_schema"] == "deal:{deal_id}"
    assert "corrupt" in repo_corrupt["message"].lower()
    assert repo_corrupt["owner"] == "backend"
    assert repo_corrupt["quick_fix"] != ""
    assert "operational.py" in repo_corrupt["validator_file_line"]
    assert "45" in repo_corrupt["validator_file_line"]


def test_parser_fails_on_malformed_markdown_table(tmp_path: Path) -> None:
    """AC 3: parser raises a clear error when columns are missing or headers are wrong."""
    # Missing the 'quick fix' column — 6 headers instead of 7
    malformed_md = textwrap.dedent("""\
        # Diagnostic Catalog

        ## Catalog Table

        | code | severity | path schema | message template | owner | owning validator file:line |
        | --- | --- | --- | --- | --- | --- |
        | MERGE_CONFLICT | error | deal.x | Conflict message | backend | merge.py:17 |
    """)
    catalog_file = tmp_path / "diagnostic_catalog.md"
    catalog_file.write_text(malformed_md)

    mod = _import_parser()
    with pytest.raises(Exception, match=r"(?i)(malformed|invalid|missing|column|header|found)"):
        mod.parse_diagnostic_catalog(catalog_file)
