"""Meta-tests for the corpus-fixture-status deliverable (Phase 1 ticket).

The deliverable is `tests/fixtures/STATUS.md`, a one-page audit that
classifies every prospectus named in `docs/architecture/waterfall_ir_design.md`
and every fixture in `tests/fixtures/` as one of:

  (i) STRUCTURAL fixture — compiles + runs but no quantitative tie-out
  (ii) QUANTITATIVE GOLDEN fixture — (i) plus matches a published source
  (iii) RESEARCH-ONLY corpus entry — cited prose; no executable artifact

These tests assert the structural shape of STATUS.md so a future audit-on-PR
guard can detect drift between the document and the actual fixture set.

The canonical source of truth for every prospectus in the corpus is
`docs/architecture/prospectus_inventory.md`, parsed by
`scripts/parse_prospectus_inventory.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.parse_prospectus_inventory import load_inventory

REPO_ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = REPO_ROOT / "tests" / "fixtures" / "STATUS.md"
WATERFALL_DESIGN_PATH = (
    REPO_ROOT / "docs" / "architecture" / "waterfall_ir_design.md"
)
INVENTORY_PATH = REPO_ROOT / "docs" / "architecture" / "prospectus_inventory.md"

# Complete list of all research-only prospectuses named in
# waterfall_ir_design.md that lack an executable fixture in tests/fixtures/.
# Every entry must appear under the (iii) RESEARCH-ONLY section of STATUS.md.
# Subset checks are insufficient — this list is the full enumeration.
REQUIRED_RESEARCH_ONLY_NAMES: list[str] = [
    # Agency MBS REMIC (non-fixture)
    "FNR 2016-104",
    "FNR 2019-17",
    "FNMA 2024-M2",
    # Agency Synthetic CRT
    "CAS 2024-R05",
    "CAS 2024-R06",
    # Ginnie Mae (non-fixture)
    "Ginnie Mae 2025-009",
    "Ginnie Mae 2024-115",  # Multifamily; missing from original STATUS.md
    # Freddie Mac
    "Freddie Mac REMIC",  # general structure (offering circular); missing from original STATUS.md
    # Non-Agency RMBS
    "JPMMT 2006",
    "Verus 2026-4",
    # Auto ABS
    "Toyota Auto Receivables 2024-A",
    "Toyota Lexus Owner Trust 2024-A",
    "Santander Drive 2024-2",
    "Westlake 2024-1",
    # Credit Card Master Trusts (all 5 issuers)
    "Capital One COMET",
    "Chase Issuance Trust",
    "Citibank Credit Card Issuance Trust",   # missing from original STATUS.md
    "Discover Card Execution Note Trust",    # missing from original STATUS.md
    "American Express Credit Account Master Trust",  # missing from original STATUS.md
]

# The 6 dedicated test files that must be enumerated on (or near) the FNR
# 2006-018 table row in STATUS.md.
FNR_FIXTURE_TEST_FILES: list[str] = [
    "test_fnr_2006_018_decrement_table.py",
    "test_fnr_2006_018_group_2_decrement_table.py",
    "test_fnr_2006_018_yield_tables.py",
    "test_fnr_2006_018_combined.py",
    "test_fnr_2006_018_staged_tieout.py",
    "test_fnr_2006_018_parity.py",
]

_TIER_LABELS = ["(i) STRUCTURAL", "(ii) QUANTITATIVE GOLDEN", "(iii) RESEARCH-ONLY"]


@pytest.fixture(scope="module")
def status_md() -> str:
    """Read the STATUS.md document. Fails if absent."""
    if not STATUS_PATH.exists():
        pytest.fail(
            f"Missing deliverable: {STATUS_PATH.relative_to(REPO_ROOT)}\n"
            f"The corpus-fixture-status ticket requires this file."
        )
    return STATUS_PATH.read_text(encoding="utf-8")


def test_status_md_exists() -> None:
    """The STATUS.md file is the corpus-fixture-status deliverable."""
    assert STATUS_PATH.exists(), (
        f"Missing deliverable: {STATUS_PATH.relative_to(REPO_ROOT)}"
    )


def test_status_md_has_classification_key_section(status_md: str) -> None:
    """The doc must define the (i)/(ii)/(iii) classification tiers."""
    assert "## Classification key" in status_md, (
        "STATUS.md must have a '## Classification key' section explaining "
        "the (i) STRUCTURAL / (ii) QUANTITATIVE GOLDEN / (iii) RESEARCH-ONLY tiers."
    )
    for label in _TIER_LABELS:
        assert label in status_md, (
            f"STATUS.md must define tier '{label}' in the Classification key."
        )


def test_status_md_classifies_every_existing_fixture(status_md: str) -> None:
    """Every directory under tests/fixtures/ with deal_definition.py must
    appear in the classification table."""
    fixtures_dir = REPO_ROOT / "tests" / "fixtures"
    fixture_dirs = [
        d.name
        for d in fixtures_dir.iterdir()
        if d.is_dir() and (d / "deal_definition.py").exists()
    ]
    assert fixture_dirs, "No deal_definition.py fixtures found — sanity check failed."

    missing = [name for name in fixture_dirs if name not in status_md]
    assert not missing, (
        f"STATUS.md does not classify these fixtures: {missing}. "
        f"Every directory under tests/fixtures/ with deal_definition.py "
        f"must be classified."
    )


def test_status_md_per_row_tier_assertion(status_md: str) -> None:
    """Each fixture directory name must appear on a table row containing
    EXACTLY ONE tier label from (i) STRUCTURAL, (ii) QUANTITATIVE GOLDEN,
    (iii) RESEARCH-ONLY.  A row with zero or two labels signals a
    classification error or a malformed table."""
    fixtures_dir = REPO_ROOT / "tests" / "fixtures"
    fixture_dirs = [
        d.name
        for d in fixtures_dir.iterdir()
        if d.is_dir() and (d / "deal_definition.py").exists()
    ]
    errors: list[str] = []
    for name in fixture_dirs:
        # Rows that both mention the fixture directory name AND a tier label.
        tier_rows = [
            line
            for line in status_md.splitlines()
            if name in line and any(label in line for label in _TIER_LABELS)
        ]
        if not tier_rows:
            errors.append(f"'{name}': no table row with a tier label found")
            continue
        for line in tier_rows:
            count = sum(1 for label in _TIER_LABELS if label in line)
            if count != 1:
                errors.append(
                    f"'{name}': row contains {count} tier labels (expected 1): "
                    f"{line[:120]!r}"
                )
    assert not errors, (
        "Per-row tier assertion failures:\n" + "\n".join(f"  {e}" for e in errors)
    )


def test_status_md_references_all_research_only_prospectuses(status_md: str) -> None:
    """STATUS.md must classify EVERY prospectus named in waterfall_ir_design.md
    that has no executable fixture.  The required list is REQUIRED_RESEARCH_ONLY_NAMES;
    checking only a representative subset is insufficient."""
    # Pass 1: all names must appear somewhere in the document.
    missing_from_doc = [
        name for name in REQUIRED_RESEARCH_ONLY_NAMES if name not in status_md
    ]
    assert not missing_from_doc, (
        f"STATUS.md is missing these required research-only prospectuses: "
        f"{missing_from_doc}.  All prospectuses cited in waterfall_ir_design.md "
        f"without an executable fixture must appear under (iii) RESEARCH-ONLY."
    )

    # Pass 2: every entry must appear in the dedicated research-only section,
    # not just somewhere in the document.
    research_section_start = status_md.find("### Research-only corpus entries")
    assert research_section_start != -1, (
        "STATUS.md must have a '### Research-only corpus entries' section."
    )
    research_section = status_md[research_section_start:]
    misplaced = [
        name
        for name in REQUIRED_RESEARCH_ONLY_NAMES
        if name not in research_section
    ]
    assert not misplaced, (
        f"These research-only prospectuses are not in the "
        f"'### Research-only corpus entries' section: {misplaced}."
    )


def test_status_md_has_per_deal_classification_section(status_md: str) -> None:
    """The doc must have an explicit per-deal classification section."""
    assert "## Per-deal classification" in status_md, (
        "STATUS.md must have a '## Per-deal classification' section."
    )


def test_status_md_pins_round_trip_commitment(status_md: str) -> None:
    """The round-trip commitment section must:
    (a) explicitly name every (i) and (ii) fixture as requiring round-trip
        + canonicalization tests, and
    (b) explicitly state that (iii) RESEARCH-ONLY entries receive NO
        automated test coverage.
    """
    assert "round-trip" in status_md.lower(), (
        "STATUS.md must pin the round-trip / canonicalization round-trip "
        "test commitment per fixture tier (Phase 0 B6 + "
        "rule-canonicalization-framework requirement)."
    )
    # (i) and (ii) fixtures must be explicitly named as receiving round-trip.
    assert "every (i) and (ii)" in status_md or "(i) and (ii) fixture" in status_md, (
        "STATUS.md must state that EVERY (i) and (ii) fixture requires "
        "round-trip + canonicalization testing."
    )
    # (iii) must be explicitly excluded from automated test coverage.
    lower = status_md.lower()
    assert "no test coverage" in lower or "no automated test" in lower, (
        "STATUS.md must explicitly state that (iii) RESEARCH-ONLY entries "
        "receive NO automated test coverage."
    )


def test_status_md_pins_fnr_2006_018_as_quantitative_golden(status_md: str) -> None:
    """FNR 2006-018 must be classified as (ii) QUANTITATIVE GOLDEN on its
    table row, and all 6 dedicated quantitative test files must be listed
    on that same row (not merely somewhere in the document)."""
    lines = status_md.splitlines()

    # Find lines containing the FNR fixture name together with the tier label.
    fnr_tier_lines = [
        (i, line)
        for i, line in enumerate(lines)
        if ("fnr_2006_018" in line or "FNR 2006-018" in line)
        and "(ii) QUANTITATIVE GOLDEN" in line
    ]
    assert fnr_tier_lines, (
        "No table row found with both 'FNR 2006-018' / 'fnr_2006_018' "
        "and '(ii) QUANTITATIVE GOLDEN'. FNR 2006-018 must be classified "
        "as (ii) QUANTITATIVE GOLDEN on its classification row."
    )

    # All 6 test files must appear on (or within 2 lines of) the FNR tier row.
    first_tier_idx, _ = fnr_tier_lines[0]
    window_start = max(0, first_tier_idx - 2)
    window_end = min(len(lines), first_tier_idx + 3)
    window_text = "\n".join(lines[window_start:window_end])

    missing_files = [f for f in FNR_FIXTURE_TEST_FILES if f not in window_text]
    assert not missing_files, (
        f"These FNR test files are not listed near the FNR 2006-018 "
        f"classification row in STATUS.md: {missing_files}. All 6 dedicated "
        f"quantitative test files must be enumerated on (or within 2 lines "
        f"of) the FNR tier row."
    )


def test_status_md_research_only_drift_against_waterfall_design(
    status_md: str,
) -> None:
    """Every inventory entry that cites waterfall_ir_design.md as a source
    must appear somewhere in STATUS.md.

    Uses the structured inventory instead of heuristic issuer-family regex
    patterns, eliminating false-negative risk from unknown issuer families.
    """
    inventory = load_inventory()
    waterfall_entries = [
        e
        for e in inventory
        if any("waterfall_ir_design" in sd for sd in e.source_docs)
    ]
    assert waterfall_entries, (
        "No inventory entries cite waterfall_ir_design.md — "
        "the inventory may be incomplete."
    )
    missing = sorted(
        e.display_name
        for e in waterfall_entries
        if e.display_name not in status_md
    )
    assert not missing, (
        f"These inventory entries cite waterfall_ir_design.md but are "
        f"absent from STATUS.md: {missing}. Add them to STATUS.md under the "
        f"correct tier (fixture table for (i)/(ii); Research-only table for (iii))."
    )


def test_each_fixture_directory_appears_in_exactly_one_tier_row(
    status_md: str,
) -> None:
    """Each fixture directory (those containing deal_definition.py) must appear
    on EXACTLY ONE classification row in STATUS.md — a row that contains both
    the directory name and a tier label.

    Zero rows → fixture is not classified at all (already caught by
    test_status_md_classifies_every_existing_fixture, but redundantly enforced
    here for clarity).  Two or more rows → duplicate or conflicting classification.
    """
    fixtures_dir = REPO_ROOT / "tests" / "fixtures"
    fixture_dirs = [
        d.name
        for d in fixtures_dir.iterdir()
        if d.is_dir() and (d / "deal_definition.py").exists()
    ]
    assert fixture_dirs, "No deal_definition.py fixtures found — sanity check failed."

    errors: list[str] = []
    for name in fixture_dirs:
        tier_rows = [
            line
            for line in status_md.splitlines()
            if name in line and any(label in line for label in _TIER_LABELS)
        ]
        if len(tier_rows) != 1:
            errors.append(
                f"'{name}': expected exactly 1 tier-classification row, "
                f"found {len(tier_rows)}: {tier_rows!r}"
            )
    assert not errors, (
        "Fixture-directory tier-row uniqueness failures:\n"
        + "\n".join(f"  {e}" for e in errors)
    )


# ---------------------------------------------------------------------------
# Inventory-driven tests (structured source-of-truth artifact)
# ---------------------------------------------------------------------------

_TIER_TO_STATUS_LABEL = {
    "structural": "(i) STRUCTURAL",
    "quantitative_golden": "(ii) QUANTITATIVE GOLDEN",
    "research_only": "(iii) RESEARCH-ONLY",
}


def _extract_design_doc_sample_rows(path: Path) -> list[str]:
    """Structurally parse the sample-size table in waterfall_ir_design.md.

    Returns the full text of each data row (Asset class + Deal + Key features).
    Callers match display_names against the full row text, which handles
    edge cases like the Freddie Mac row where the name spans the Asset class
    column rather than the Deal column.
    """
    text = path.read_text(encoding="utf-8")
    rows: list[str] = []
    in_table = False
    for line in text.splitlines():
        if "| Asset class |" in line and "| Deal |" in line:
            in_table = True
            continue
        if in_table:
            if line.strip().startswith("|---"):
                continue
            if not line.startswith("|"):
                break
            rows.append(line)
    return rows


def _extract_cell_deal_names(deal_cell: str) -> list[str]:
    """Extract individual deal names from a table Deal-column cell.

    Splits on comma-space and slash separators, then strips trailing
    parentheticals (e.g. '(fixture)', '(HECM)', '(TLOT)').  Returns an
    empty list when the cell itself is entirely parenthetical
    (e.g. Freddie Mac row uses '(offering circular)').
    """
    parts = re.split(r",\s*|\s*/\s*", deal_cell)
    names: list[str] = []
    for part in parts:
        name = re.sub(r"\s*\([^)]*\)", "", part).strip()
        if name and not name.startswith("("):
            names.append(name)
    return names


def test_inventory_covers_all_waterfall_design_references() -> None:
    """Every deal name extracted from the waterfall_ir_design.md sample-size
    table must correspond to at least one inventory entry, AND every inventory
    entry that cites waterfall_ir_design.md must have its display_name present
    somewhere in that document (table or prose).

    Two-direction enforcement:
    1. Forward  — per-cell: split multi-deal cells on comma/slash, strip
       parentheticals, check each extracted name against inventory.
       Catches a new deal name silently added to an existing multi-deal row.
    2. Inverse  — inventory → doc: every inventory entry whose source_docs
       includes waterfall_ir_design.md must have its display_name appear
       somewhere in the file (handles prose-only mentions such as the
       credit-card master trust section).
       Catches deletion of an inventory entry from the design document without
       a corresponding inventory update.
    """
    inventory = load_inventory()
    display_names = {e.display_name for e in inventory}
    waterfall_text = WATERFALL_DESIGN_PATH.read_text(encoding="utf-8")

    rows = _extract_design_doc_sample_rows(WATERFALL_DESIGN_PATH)
    assert rows, (
        "No rows extracted from waterfall_ir_design.md sample-size table — "
        "table format may have changed."
    )

    # --- Forward direction: per-cell deal name extraction ---
    missing: list[str] = []
    for row in rows:
        cells = [c.strip() for c in row.split("|") if c.strip()]
        if len(cells) < 2:
            continue
        deal_cell = cells[1]
        names = _extract_cell_deal_names(deal_cell)
        if not names:
            # Cell is entirely parenthetical (e.g. Freddie Mac offering
            # circular row); fall back to full-row display_name substring
            # check so the row is still validated.
            if not any(dn in row for dn in display_names):
                missing.append(row.strip()[:100])
            continue
        for name in names:
            if not any(name in dn or dn in name for dn in display_names):
                missing.append(name)

    assert not missing, (
        f"These deal names extracted from waterfall_ir_design.md sample-table "
        f"cells have no matching inventory entry: {missing}"
    )

    # --- Inverse direction: every waterfall-citing inventory entry must
    #     appear somewhere in the document text ---
    waterfall_citing = [
        e
        for e in inventory
        if any("waterfall_ir_design" in sd for sd in e.source_docs)
    ]
    absent_from_doc = sorted(
        e.display_name
        for e in waterfall_citing
        if e.display_name not in waterfall_text
    )
    assert not absent_from_doc, (
        f"These inventory entries cite waterfall_ir_design.md but their "
        f"display_name does not appear anywhere in that document: "
        f"{absent_from_doc}"
    )


def test_inventory_covers_all_status_md_research_only_entries(
    status_md: str,
) -> None:
    """Every research-only deal name in STATUS.md must have a matching
    inventory entry with tier=research_only."""
    inventory = load_inventory()
    research_ids = {
        e.display_name for e in inventory if e.tier == "research_only"
    }

    for name in REQUIRED_RESEARCH_ONLY_NAMES:
        assert name in research_ids, (
            f"Research-only prospectus '{name}' (from STATUS.md / "
            f"REQUIRED_RESEARCH_ONLY_NAMES) has no inventory entry with "
            f"tier=research_only."
        )


def test_status_md_classifications_match_inventory(status_md: str) -> None:
    """For each inventory entry with a non-null fixture_dir, STATUS.md must
    classify it under the same tier label."""
    inventory = load_inventory()
    errors: list[str] = []
    for entry in inventory:
        if entry.fixture_dir is None:
            continue
        expected_label = _TIER_TO_STATUS_LABEL.get(entry.tier)
        if expected_label is None:
            errors.append(
                f"'{entry.prospectus_id}': unknown tier '{entry.tier}'"
            )
            continue
        tier_rows = [
            line
            for line in status_md.splitlines()
            if entry.fixture_dir in line
            and any(label in line for label in _TIER_LABELS)
        ]
        if not tier_rows:
            errors.append(
                f"'{entry.prospectus_id}': fixture_dir='{entry.fixture_dir}' "
                f"not found on any tier row in STATUS.md"
            )
            continue
        for row in tier_rows:
            if expected_label not in row:
                errors.append(
                    f"'{entry.prospectus_id}': inventory says "
                    f"tier='{entry.tier}' but STATUS.md row classifies "
                    f"'{entry.fixture_dir}' differently: {row[:120]!r}"
                )
    assert not errors, (
        "Inventory ↔ STATUS.md tier mismatches:\n"
        + "\n".join(f"  {e}" for e in errors)
    )


def test_drift_catches_new_prospectus_in_existing_multi_deal_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drift detection must individually verify each deal name extracted from
    a multi-deal table cell, not just confirm that *any* known display_name
    appears somewhere in the row.

    Currently fails: the existing check passes the CAS row because
    'CAS 2024-R05' is already in inventory, silently missing 'CAS 2999-NEW'.
    """
    fake = (
        "| Asset class | Deal | Key features |\n"
        "|---|---|---|\n"
        "| Agency Synthetic CRT | CAS 2024-R05, CAS 2024-R06, CAS 2999-NEW | row |\n"
    )
    wf = tmp_path / "waterfall_ir_design.md"
    wf.write_text(fake)

    import tests.test_corpus_fixture_status as m

    monkeypatch.setattr(m, "WATERFALL_DESIGN_PATH", wf)

    with pytest.raises(AssertionError, match="CAS 2999-NEW"):
        m.test_inventory_covers_all_waterfall_design_references()


def test_drift_catches_prospectus_outside_sample_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drift detection must enforce the inverse direction: every inventory
    entry that cites waterfall_ir_design.md must have its display_name
    present somewhere in that document (table *or* prose).

    Currently fails: the existing check is forward-only (table rows →
    inventory) and does not assert that every inventory entry citing the
    design document actually appears in it.  Credit-card trusts
    (e.g. Capital One COMET) are only mentioned in prose outside the
    sample-size table, so if they were deleted from that prose without
    being removed from the inventory, the existing test would not detect it.
    """
    # Minimal waterfall: only FNR 2006-018 in the table, no credit-card prose.
    fake = (
        "| Asset class | Deal | Key features |\n"
        "|---|---|---|\n"
        "| Agency MBS REMIC | FNR 2006-018 | anchor |\n"
    )
    wf = tmp_path / "waterfall_ir_design.md"
    wf.write_text(fake)

    import tests.test_corpus_fixture_status as m

    monkeypatch.setattr(m, "WATERFALL_DESIGN_PATH", wf)

    with pytest.raises(AssertionError, match="Capital One COMET"):
        m.test_inventory_covers_all_waterfall_design_references()


def test_each_fixture_directory_has_inventory_entry() -> None:
    """Every fixture directory with deal_definition.py must have a
    matching inventory entry (fixture_dir column)."""
    fixtures_dir = REPO_ROOT / "tests" / "fixtures"
    fixture_dirs = sorted(
        d.name
        for d in fixtures_dir.iterdir()
        if d.is_dir() and (d / "deal_definition.py").exists()
    )
    assert fixture_dirs, "No deal_definition.py fixtures found."

    inventory = load_inventory()
    inventory_fixture_dirs = {
        e.fixture_dir for e in inventory if e.fixture_dir is not None
    }

    missing = [d for d in fixture_dirs if d not in inventory_fixture_dirs]
    assert not missing, (
        f"These fixture directories have no inventory entry: {missing}"
    )
