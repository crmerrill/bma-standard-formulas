"""Parse the diagnostic catalog markdown table into structured records.

Usage (CLI)::

    python scripts/parse_diagnostic_catalog.py [path/to/catalog.md]

Reads ``docs/architecture/diagnostic_catalog.md`` by default and prints
the parsed records as JSON. Can also be imported directly::

    from scripts.parse_diagnostic_catalog import parse_diagnostic_catalog
    records = parse_diagnostic_catalog(Path("docs/architecture/diagnostic_catalog.md"))
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TypedDict

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG_PATH = REPO_ROOT / "docs" / "architecture" / "diagnostic_catalog.md"

# Exact column headers expected in the markdown table (lowercase, stripped).
EXPECTED_HEADERS: list[str] = [
    "code",
    "severity",
    "path schema",
    "message template",
    "owner",
    "quick fix",
    "owning validator file:line",
]

# Maps header position → record key name.
_HEADER_TO_KEY: dict[str, str] = {
    "code": "code",
    "severity": "severity",
    "path schema": "path_schema",
    "message template": "message",
    "owner": "owner",
    "quick fix": "quick_fix",
    "owning validator file:line": "validator_file_line",
}


class CatalogRecord(TypedDict):
    code: str
    severity: str
    path_schema: str
    message: str
    owner: str
    quick_fix: str
    validator_file_line: str


class MalformedCatalogError(ValueError):
    """Raised when the catalog markdown table is missing or has wrong/missing columns."""


def _split_row(line: str) -> list[str]:
    """Split a markdown table row on ``|`` delimiters, stripping each cell."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_diagnostic_catalog(path: Path | str | None = None) -> list[CatalogRecord]:
    """Parse the diagnostic catalog markdown and return one record per table row.

    Args:
        path: Path to the catalog markdown file. Defaults to
              ``docs/architecture/diagnostic_catalog.md`` relative to repo root.

    Returns:
        List of :class:`CatalogRecord` dicts, one per data row in the catalog table.

    Raises:
        MalformedCatalogError: If no table with the expected header is found, or
            if any data row has the wrong number of columns.
        FileNotFoundError: If the catalog file does not exist.
    """
    catalog_path = Path(path) if path is not None else DEFAULT_CATALOG_PATH
    text = catalog_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Locate the header row by matching normalized cell values.
    header_idx: int | None = None
    for i, line in enumerate(lines):
        if "|" not in line:
            continue
        cells = _split_row(line)
        if [c.lower() for c in cells] == EXPECTED_HEADERS:
            header_idx = i
            break

    if header_idx is None:
        raise MalformedCatalogError(
            f"No valid catalog table header found in {catalog_path}. "
            f"Expected column headers (in order): {EXPECTED_HEADERS!r}"
        )

    # Validate the separator row immediately after the header.
    sep_idx = header_idx + 1
    if sep_idx >= len(lines):
        raise MalformedCatalogError(
            f"Expected a separator row after the header at line {header_idx + 1} "
            f"in {catalog_path}, but the file ended."
        )
    sep_line = lines[sep_idx]
    if not re.match(r"\s*\|[\s\-|]+\|\s*$", sep_line):
        raise MalformedCatalogError(
            f"Expected a separator row (e.g. '| --- | ...' ) at line {sep_idx + 1} "
            f"in {catalog_path}, but got: {sep_line!r}"
        )
    separator_cells = _split_row(sep_line)
    if len(separator_cells) != len(EXPECTED_HEADERS):
        raise MalformedCatalogError(
            f"Separator row at line {sep_idx + 1} has {len(separator_cells)} column(s), "
            f"expected {len(EXPECTED_HEADERS)}: {sep_line!r}"
        )

    records: list[CatalogRecord] = []
    for line_no, line in enumerate(lines[sep_idx + 1 :], start=sep_idx + 2):
        stripped = line.strip()
        if not stripped or not stripped.startswith("|"):
            break
        cells = _split_row(stripped)
        if len(cells) != len(EXPECTED_HEADERS):
            raise MalformedCatalogError(
                f"Data row at line {line_no} has {len(cells)} column(s), "
                f"expected {len(EXPECTED_HEADERS)}: {stripped!r}"
            )
        record: CatalogRecord = {
            "code": cells[0],
            "severity": cells[1],
            "path_schema": cells[2],
            "message": cells[3],
            "owner": cells[4],
            "quick_fix": cells[5],
            "validator_file_line": cells[6],
        }
        records.append(record)

    return records


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CATALOG_PATH
    records = parse_diagnostic_catalog(path)
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
