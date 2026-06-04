"""Parse ``docs/architecture/prospectus_inventory.md`` into typed records.

Provides the canonical programmatic interface to the prospectus inventory
— a structured markdown table that is the single source of truth for every
prospectus referenced in the BMA Standard Formulas corpus.

Public API
----------
- ``load_inventory(path=None)`` → list[ProspectusEntry]
- ``get_entries_by_tier(tier, entries=None)`` → list[ProspectusEntry]
- ``get_entry_by_fixture_dir(name, entries=None)`` → ProspectusEntry | None
- ``MalformedInventoryError`` — raised on parse failures
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_INVENTORY_PATH = (
    _REPO_ROOT / "docs" / "architecture" / "prospectus_inventory.md"
)

Tier = Literal["structural", "quantitative_golden", "research_only"]

_VALID_TIERS: frozenset[str] = frozenset(
    {"structural", "quantitative_golden", "research_only"}
)

_BEGIN_MARKER = "<!-- BEGIN INVENTORY TABLE"
_END_MARKER = "<!-- END INVENTORY TABLE -->"


class MalformedInventoryError(Exception):
    """Raised when the inventory file cannot be parsed."""


_KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class ProspectusEntry(BaseModel):
    """A single row from the prospectus inventory table."""

    prospectus_id: str
    display_name: str
    issuer: str
    asset_class: str
    tier: Tier
    fixture_dir: str | None
    source_docs: list[str]

    @field_validator("prospectus_id", mode="before")
    @classmethod
    def _validate_kebab_case(cls, v: str) -> str:
        if not _KEBAB_RE.match(v):
            raise ValueError(
                f"prospectus_id must be kebab-case matching "
                f"^[a-z0-9]+(-[a-z0-9]+)*$, got {v!r}"
            )
        return v

    @field_validator("tier", mode="before")
    @classmethod
    def _validate_tier(cls, v: str) -> str:
        if v not in _VALID_TIERS:
            raise ValueError(
                f"Invalid tier {v!r}; expected one of {sorted(_VALID_TIERS)}"
            )
        return v

    @field_validator("fixture_dir", mode="before")
    @classmethod
    def _normalize_null(cls, v: str | None) -> str | None:
        if v is None or v.strip().lower() == "null":
            return None
        return v.strip()

    @field_validator("source_docs", mode="before")
    @classmethod
    def _split_source_docs(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, list):
            return v
        return [s.strip() for s in v.split(";") if s.strip()]


def _parse_table(text: str) -> list[ProspectusEntry]:
    """Parse the inventory markdown table between BEGIN/END markers."""
    begin = text.find(_BEGIN_MARKER)
    end = text.find(_END_MARKER)
    if begin == -1 or end == -1:
        raise MalformedInventoryError(
            "Inventory file missing BEGIN/END INVENTORY TABLE markers."
        )

    section = text[begin:end]
    lines = section.splitlines()

    header_idx: int | None = None
    for i, line in enumerate(lines):
        if line.startswith("|") and "prospectus_id" in line:
            header_idx = i
            break

    if header_idx is None:
        raise MalformedInventoryError(
            "No header row with 'prospectus_id' found in inventory table."
        )

    header_cells = [c.strip() for c in lines[header_idx].split("|")]
    header_cells = [c for c in header_cells if c]
    expected = [
        "prospectus_id",
        "display_name",
        "issuer",
        "asset_class",
        "tier",
        "fixture_dir",
        "source_docs",
    ]
    if header_cells != expected:
        raise MalformedInventoryError(
            f"Unexpected header columns: {header_cells}; expected {expected}"
        )

    entries: list[ProspectusEntry] = []
    seen_ids: set[str] = set()
    data_start = header_idx + 2  # skip header + separator

    for line_no, line in enumerate(lines[data_start:], start=data_start + 1):
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        cells = [c for c in cells if c != ""]
        if not cells:
            continue
        if re.match(r"^[-|: ]+$", line):
            continue

        if len(cells) != 7:
            raise MalformedInventoryError(
                f"Row has {len(cells)} cells (expected 7) at line ~{line_no}: "
                f"{line[:100]!r}"
            )

        try:
            entry = ProspectusEntry(
                prospectus_id=cells[0],
                display_name=cells[1],
                issuer=cells[2],
                asset_class=cells[3],
                tier=cells[4],
                fixture_dir=cells[5],
                source_docs=cells[6],
            )
        except Exception as exc:
            raise MalformedInventoryError(
                f"Failed to parse inventory row at line ~{line_no}: {exc}"
            ) from exc

        if entry.prospectus_id in seen_ids:
            raise MalformedInventoryError(
                f"Duplicate prospectus_id at line ~{line_no}: "
                f"{entry.prospectus_id!r}"
            )
        seen_ids.add(entry.prospectus_id)
        entries.append(entry)

    if not entries:
        raise MalformedInventoryError("No data rows found in inventory table.")

    return entries


def load_inventory(
    path: Path | None = None,
) -> list[ProspectusEntry]:
    """Load and parse the prospectus inventory.

    Parameters
    ----------
    path : Path, optional
        Override the default inventory path
        (``docs/architecture/prospectus_inventory.md``).

    Returns
    -------
    list[ProspectusEntry]

    Raises
    ------
    MalformedInventoryError
        If the file is missing, malformed, or contains invalid rows.
    FileNotFoundError
        If the inventory file does not exist.
    """
    target = path or _DEFAULT_INVENTORY_PATH
    if not target.exists():
        raise FileNotFoundError(f"Inventory file not found: {target}")
    text = target.read_text(encoding="utf-8")
    return _parse_table(text)


def get_entries_by_tier(
    tier: Tier,
    entries: list[ProspectusEntry] | None = None,
) -> list[ProspectusEntry]:
    """Return inventory entries matching the given tier.

    Parameters
    ----------
    tier : Tier
        One of ``"structural"``, ``"quantitative_golden"``, ``"research_only"``.
    entries : list[ProspectusEntry], optional
        Pre-loaded entries; calls ``load_inventory()`` if not provided.
    """
    if entries is None:
        entries = load_inventory()
    return [e for e in entries if e.tier == tier]


def get_entry_by_fixture_dir(
    name: str,
    entries: list[ProspectusEntry] | None = None,
) -> ProspectusEntry | None:
    """Return the inventory entry whose ``fixture_dir`` matches *name*.

    Returns ``None`` if no match is found.

    Parameters
    ----------
    name : str
        Fixture directory name (e.g. ``"fnr_2006_018"``).
    entries : list[ProspectusEntry], optional
        Pre-loaded entries; calls ``load_inventory()`` if not provided.
    """
    if entries is None:
        entries = load_inventory()
    for e in entries:
        if e.fixture_dir == name:
            return e
    return None
