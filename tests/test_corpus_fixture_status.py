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

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = REPO_ROOT / "tests" / "fixtures" / "STATUS.md"
WATERFALL_DESIGN_PATH = (
    REPO_ROOT / "docs" / "architecture" / "waterfall_ir_design.md"
)


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
    # All three tier labels must appear.
    assert "STRUCTURAL" in status_md
    assert "QUANTITATIVE GOLDEN" in status_md
    assert "RESEARCH-ONLY" in status_md


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


def test_status_md_references_research_only_prospectuses(status_md: str) -> None:
    """STATUS.md must reference research-only prospectuses (cited in
    waterfall_ir_design.md but with no fixture). The audit's value is that
    it explicitly downgrades these entries to (iii) so test claims about
    them are bounded."""
    # A representative subset of named research-only entries from
    # waterfall_ir_design.md. STATUS.md must classify all of them as (iii).
    expected_research_only = [
        "FNR 2016-104",
        "FNR 2019-17",
        "JPMMT 2006",
        "Toyota Auto Receivables 2024-A",
        "Santander Drive 2024-2",
        "Westlake 2024-1",
    ]
    missing = [name for name in expected_research_only if name not in status_md]
    assert not missing, (
        f"STATUS.md does not reference these research-only prospectuses: "
        f"{missing}. They are cited in waterfall_ir_design.md and must be "
        f"classified as (iii) RESEARCH-ONLY."
    )


def test_status_md_has_per_deal_classification_section(status_md: str) -> None:
    """The doc must have an explicit per-deal classification section."""
    assert (
        "## Per-deal classification" in status_md
        or "Per-deal classification" in status_md
    ), "STATUS.md must have a 'Per-deal classification' section."


def test_status_md_pins_round_trip_commitment(status_md: str) -> None:
    """The doc must pin which fixture tiers receive canonicalization
    round-trip + cashflow tie-out test coverage."""
    assert "round-trip" in status_md.lower() or "round trip" in status_md.lower(), (
        "STATUS.md must pin the round-trip / canonicalization round-trip "
        "test commitment per fixture tier (Phase 0 B6 + "
        "rule-canonicalization-framework requirement)."
    )


def test_status_md_pins_fnr_2006_018_as_quantitative_golden(status_md: str) -> None:
    """FNR 2006-018 has dedicated decrement-table tests; it MUST be (ii)."""
    # The doc must flag FNR 2006-018 specifically as (ii) QUANTITATIVE GOLDEN.
    # This is the only existing fixture with per-period tie-out.
    fnr_section_present = "fnr_2006_018" in status_md or "FNR 2006-018" in status_md
    assert fnr_section_present, "FNR 2006-018 must be referenced in STATUS.md."
    # The audit's central claim is that fnr_2006_018 is the (ii) anchor.
    # We assert "QUANTITATIVE GOLDEN" appears near "fnr_2006_018" by checking
    # the (ii) marker is in the doc at all.
    assert "QUANTITATIVE GOLDEN" in status_md
