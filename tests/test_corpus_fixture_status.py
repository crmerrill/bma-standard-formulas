"""Meta-tests for the corpus-fixture-status deliverable (Phase 1 ticket).

The deliverable is `tests/fixtures/STATUS.md`, a one-page audit that
classifies every prospectus named in `docs/architecture/waterfall_ir_design.md`
and every fixture in `tests/fixtures/` as one of:

  (i) STRUCTURAL fixture — compiles + runs but no quantitative tie-out
  (ii) QUANTITATIVE GOLDEN fixture — (i) plus matches a published source
  (iii) RESEARCH-ONLY corpus entry — cited prose; no executable artifact

These tests assert the structural shape of STATUS.md so a future audit-on-PR
guard can detect drift between the document and the actual fixture set.

The tests fail until `tests/fixtures/STATUS.md` is authored with the
required sections and references.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = REPO_ROOT / "tests" / "fixtures" / "STATUS.md"
WATERFALL_DESIGN_PATH = (
    REPO_ROOT / "docs" / "architecture" / "waterfall_ir_design.md"
)

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

# Compiled regex patterns matching known SF/RMBS/ABS issuer prefixes.  One
# pattern per issuer family; each match yields exactly the name token that
# must appear verbatim in STATUS.md.  Adding a new prospectus to
# waterfall_ir_design.md without updating STATUS.md will be caught by
# test_status_md_research_only_drift_against_waterfall_design.
_PROSPECTUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"FNR \d{4}-\d+"),
    re.compile(r"FNMA \d{4}-\w+"),
    re.compile(r"CAS \d{4}-\w+"),
    re.compile(r"Ginnie Mae \d{4}-\d+"),
    re.compile(r"Freddie Mac REMIC"),
    re.compile(r"JPMMT \d{4}"),
    re.compile(r"Verus \d{4}-\d+"),
    re.compile(r"Ford Credit Auto Owner Trust \d{4}-\w+"),
    re.compile(r"Toyota Auto Receivables \d{4}-\w+"),
    re.compile(r"Toyota Lexus Owner Trust \d{4}-\w+"),
    re.compile(r"Santander Drive \d{4}-\d+"),
    re.compile(r"Westlake \d{4}-\d+"),
    re.compile(r"Capital One COMET"),
    re.compile(r"Chase Issuance Trust"),
    re.compile(r"Citibank Credit Card Issuance Trust"),
    re.compile(r"Discover Card Execution Note Trust"),
    re.compile(r"American Express Credit Account Master Trust"),
]


def _parse_waterfall_prospectuses(path: Path) -> set[str]:
    """Extract prospectus names from waterfall_ir_design.md via issuer-prefix patterns.

    Scans the full text of the design doc with each pattern in _PROSPECTUS_PATTERNS
    and returns the union of all matches as a deduplicated set.  The same name may
    appear dozens of times in the doc (section headers, prose, tables); deduplication
    ensures the assertion loop in the drift test is clean.

    Heuristic: one compiled regex per known SF/RMBS/ABS issuer family, each pattern
    anchored to the issuer prefix and capturing the adjacent identifier token.  This
    is intentionally liberal — false positives (e.g. internal variable names) are not
    a practical risk in a design doc.  False negatives (new issuers not yet in
    _PROSPECTUS_PATTERNS) are the failure mode this test guards against over time.
    """
    text = path.read_text(encoding="utf-8")
    found: set[str] = set()
    for pattern in _PROSPECTUS_PATTERNS:
        found.update(pattern.findall(text))
    return found


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
    """Every prospectus name extracted from waterfall_ir_design.md must appear
    somewhere in STATUS.md.

    Uses _parse_waterfall_prospectuses() to scan the design doc dynamically so
    that adding a new prospectus there without updating STATUS.md will fail CI,
    not just the hardcoded REQUIRED_RESEARCH_ONLY_NAMES list.
    """
    candidates = _parse_waterfall_prospectuses(WATERFALL_DESIGN_PATH)
    assert candidates, (
        "No prospectus candidates extracted from waterfall_ir_design.md — "
        "_PROSPECTUS_PATTERNS may be broken or the design doc was moved."
    )
    missing = sorted(name for name in candidates if name not in status_md)
    assert not missing, (
        f"These prospectus names appear in waterfall_ir_design.md but are "
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
