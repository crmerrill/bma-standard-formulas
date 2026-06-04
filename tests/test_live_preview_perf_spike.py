"""Meta-tests for the live-preview-perf-spike deliverables (Phase 1 ticket).

The deliverables are:
1. A regression-testable performance benchmark at
   `tests/performance/live_preview/test_live_preview_budget.py`.
2. A measured-budget STATUS document at
   `docs/architecture/tickets/phase1/live-preview-perf-spike.STATUS.md`
   that captures the spike's findings and decision-gate outcome (per
   Phase 0 fold-back M13).

These meta-tests assert the structural shape of both deliverables. They
fail until the perf benchmark module + STATUS document are authored.

Per the plan's targets, the perf benchmark MUST measure (i) p50/p95
latency for one debounced base-case run and (ii) at minimum the largest
existing real-world fixture. The STATUS document MUST record the
measured numbers + the M13 decision-gate outcome (always-on viable, OR
amend Vision narrative with downscale path).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PERF_MODULE_PATH = (
    REPO_ROOT
    / "tests"
    / "performance"
    / "live_preview"
    / "test_live_preview_budget.py"
)
STATUS_PATH = (
    REPO_ROOT
    / "docs"
    / "architecture"
    / "tickets"
    / "phase1"
    / "live-preview-perf-spike.STATUS.md"
)


# ---------------------------------------------------------------------------
# (1) Perf benchmark module
# ---------------------------------------------------------------------------


def test_perf_module_exists() -> None:
    """The regression-testable perf benchmark must exist."""
    assert PERF_MODULE_PATH.exists(), (
        f"Missing deliverable: {PERF_MODULE_PATH.relative_to(REPO_ROOT)}\n"
        f"The live-preview-perf-spike ticket requires a regression-testable "
        f"performance benchmark."
    )


def test_perf_module_is_importable() -> None:
    """The benchmark module must be valid Python that imports cleanly."""
    spec = importlib.util.spec_from_file_location(
        "perf_benchmark", PERF_MODULE_PATH
    )
    assert spec is not None, "Could not load the perf benchmark module spec."
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Attempt to load; any ImportError or syntax error fails the test.
    spec.loader.exec_module(module)


def test_perf_module_has_budget_targets() -> None:
    """The benchmark module must declare explicit p50 / p95 budget targets."""
    text = PERF_MODULE_PATH.read_text(encoding="utf-8")
    # Both target constants must appear; values must match the plan
    # (p50 < 250 ms, p95 < 600 ms).
    assert "TARGET_P50_MS" in text or "250" in text, (
        "Perf benchmark must declare a p50 target constant (TARGET_P50_MS = 250)."
    )
    assert "TARGET_P95_MS" in text or "600" in text, (
        "Perf benchmark must declare a p95 target constant (TARGET_P95_MS = 600)."
    )


def test_perf_module_runs_at_least_one_real_fixture() -> None:
    """The benchmark must measure at least one real-world fixture.
    The plan names FNR 2006-018 as the largest existing real RMBS fixture."""
    text = PERF_MODULE_PATH.read_text(encoding="utf-8")
    assert "fnr_2006_018" in text or "FNR 2006-018" in text, (
        "Perf benchmark must run at least one real-world fixture; FNR 2006-018 "
        "is the largest existing real-world RMBS fixture."
    )


def test_perf_module_marked_slow() -> None:
    """The benchmark must be marked `slow` so it doesn't run by default in
    `pytest tests/`. CI runs the slow suite separately."""
    text = PERF_MODULE_PATH.read_text(encoding="utf-8")
    assert "@pytest.mark.slow" in text, (
        "Perf benchmark tests must be marked @pytest.mark.slow so they don't "
        "run by default."
    )


# ---------------------------------------------------------------------------
# (2) STATUS document
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def status_md() -> str:
    if not STATUS_PATH.exists():
        pytest.fail(f"Missing deliverable: {STATUS_PATH.relative_to(REPO_ROOT)}")
    return STATUS_PATH.read_text(encoding="utf-8")


def test_status_md_exists() -> None:
    """The spike's measurement + decision-gate document must exist."""
    assert STATUS_PATH.exists(), (
        f"Missing deliverable: {STATUS_PATH.relative_to(REPO_ROOT)}"
    )


def test_status_md_records_measured_p50_and_p95(status_md: str) -> None:
    """The STATUS doc must record the measured p50 and p95 latencies for at
    least the FNR 2006-018 fixture, with concrete numeric values."""
    assert "p50" in status_md.lower(), "STATUS.md must record p50 latency."
    assert "p95" in status_md.lower(), "STATUS.md must record p95 latency."
    # Look for an `ms` unit somewhere — measurement should report milliseconds.
    assert "ms" in status_md.lower(), "STATUS.md must report latencies in ms."


def test_status_md_records_decision_gate_outcome(status_md: str) -> None:
    """Per Phase 0 fold-back M13, the STATUS doc must record whether
    always-on preview is viable (or specify the downscale path)."""
    text_lower = status_md.lower()
    # The doc must address the M13 decision gate explicitly.
    has_decision = (
        "always-on" in text_lower
        or "decision gate" in text_lower
        or "m13" in text_lower
        or "viable" in text_lower
    )
    assert has_decision, (
        "STATUS.md must record the M13 decision-gate outcome — whether "
        "always-on preview is viable at fixture scale, or what the "
        "downscale path is."
    )


def test_status_md_pins_targets(status_md: str) -> None:
    """The STATUS doc must pin the plan's targets explicitly."""
    assert "250" in status_md, (
        "STATUS.md must reference the 250 ms p50 target from the plan."
    )
    assert "600" in status_md, (
        "STATUS.md must reference the 600 ms p95 target from the plan."
    )


def test_status_md_addresses_cancellation_and_degraded_mode(
    status_md: str,
) -> None:
    """Per the plan, the STATUS doc must address cancellation behavior and
    degraded-mode UI contract."""
    text_lower = status_md.lower()
    assert "cancel" in text_lower, (
        "STATUS.md must address cancellation behavior (the spike's contract)."
    )
    assert "degraded" in text_lower or "stale" in text_lower or "paused" in text_lower, (
        "STATUS.md must address degraded-mode UI behavior (the spike's contract)."
    )


def test_status_md_has_follow_on_tickets_section(status_md: str) -> None:
    """R1 finding #3: STATUS.md must have a dedicated 'Follow-on tickets'
    section heading (## or ###) so the unmeasured fixture-scale gaps are
    tracked for Phase 1 closure or Phase 2 spillover.

    Incidental 'follow-on' mentions in prose do NOT satisfy this requirement;
    the section must appear as a Markdown heading.
    """
    import re

    has_section = bool(
        re.search(r"^#{1,4}\s+follow-on tickets", status_md, re.IGNORECASE | re.MULTILINE)
    )
    assert has_section, (
        "STATUS.md must contain a dedicated '## Follow-on tickets' section heading "
        "per R1 finding #3. Add a section that lists the three unmeasured fixture "
        "gaps (200-rule auto ABS, multi-group RMBS, CC master trust) so they are "
        "tracked for Phase 1 closure or Phase 2 spillover."
    )


def test_status_md_follow_on_items_named(status_md: str) -> None:
    """R1 finding #3: The Follow-on tickets section must enumerate all three
    unmeasured fixture-scale gaps explicitly:
      - 200-rule synthetic auto ABS
      - multi-group RMBS combined deal
      - CC master trust with PFA/IFA
    """
    import re

    # Extract just the text after the follow-on section heading.
    match = re.search(
        r"^#{1,4}\s+follow-on tickets.*",
        status_md,
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    section_text = match.group(0).lower() if match else ""

    assert "200-rule" in section_text or "200 rule" in section_text, (
        "Follow-on tickets section must name the 200-rule auto ABS fixture gap."
    )
    assert "multi-group rmbs" in section_text or (
        "multi-group" in section_text and "rmbs" in section_text
    ), (
        "Follow-on tickets section must name the multi-group RMBS combined deal gap."
    )
    assert "cc master trust" in section_text or "master trust" in section_text, (
        "Follow-on tickets section must name the CC master trust with PFA/IFA gap."
    )
