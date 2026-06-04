"""Failing tests for scripts/parse_prospectus_inventory.py.

R1 Medium: duplicate prospectus_id → MalformedInventoryError
R1 Low:    non-kebab-case prospectus_id → MalformedInventoryError
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from scripts.parse_prospectus_inventory import MalformedInventoryError, load_inventory

_HEADER = textwrap.dedent(
    """\
    <!-- BEGIN INVENTORY TABLE — machine-parsed by scripts/parse_prospectus_inventory.py -->

    | prospectus_id | display_name | issuer | asset_class | tier | fixture_dir | source_docs |
    |---|---|---|---|---|---|---|
    """
)
_FOOTER = "\n<!-- END INVENTORY TABLE -->\n"


def _make_inventory(rows: str, tmp_path: Path) -> Path:
    content = _HEADER + rows + _FOOTER
    p = tmp_path / "prospectus_inventory.md"
    p.write_text(content)
    return p


def test_duplicate_prospectus_id_raises_malformed_inventory_error(
    tmp_path: Path,
) -> None:
    """Two rows sharing the same prospectus_id must raise MalformedInventoryError
    with the duplicate ID present in the exception message."""
    rows = (
        "| id-one | Deal One | Issuer A | Agency MBS | structural | null | docs/x.md |\n"
        "| id-one | Deal Two | Issuer B | Agency MBS | structural | null | docs/x.md |\n"
    )
    path = _make_inventory(rows, tmp_path)
    with pytest.raises(MalformedInventoryError, match="id-one"):
        load_inventory(path)


def test_non_kebab_case_prospectus_id_raises(tmp_path: Path) -> None:
    """A prospectus_id that is not kebab-case (e.g. snake_case 'FNR_2006_018')
    must raise MalformedInventoryError mentioning the kebab-case requirement."""
    rows = (
        "| FNR_2006_018 | FNR 2006-018 | Fannie Mae | Agency MBS"
        " | quantitative_golden | null | docs/x.md |\n"
    )
    path = _make_inventory(rows, tmp_path)
    with pytest.raises(MalformedInventoryError, match="kebab"):
        load_inventory(path)
