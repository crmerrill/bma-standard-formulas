"""Tests for ve-3-sse-streaming-backend: GET /deals/{deal_id}/validate/stream.

These tests must FAIL on current HEAD (endpoint not yet implemented) and
PASS after the implementation lands.
"""

from __future__ import annotations

import json
import re
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from bma_cfengine_app.api.main import app
from bma_cfengine_app.orchestrator.deals import deal_store
from bma_cfengine_app.orchestrator.deals.git_service import GitService
from bma_standard_formulas.deals.schemas.common import RuleType
from bma_standard_formulas.deals.schemas.ir import (
    AccountDef,
    BondDef,
    DealDefinition,
    FeeDef,
    RuleNode,
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)
    deal_store.init_deals_workspace()
    return TestClient(app)


@pytest.fixture
def deal_id(client: TestClient) -> str:
    """Fixture that creates a seed deal and returns its ID."""
    identifier = "deal_validation_sse"
    deal_store.save_deal(identifier, _build_valid_deal("seed-deal"))
    return identifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_valid_deal(name: str) -> DealDefinition:
    return DealDefinition(
        deal_name=name,
        bonds=[BondDef(name="A1", coupon=5.0, notional=1_000_000.0)],
        accounts=[AccountDef(name="Reserve", starting_amount=100.0)],
        fees=[FeeDef(name="Servicing", amount=10.0)],
        waterfall_rules=[
            RuleNode(
                rule_id="pay-principal-a1",
                rule_type=RuleType.PAY_PRINCIPAL,
                order=0,
                from_sources=["CASH"],
                to_targets=["A1"],
            )
        ],
    )


def _service_for(deal_id: str) -> GitService:
    return GitService(repo_path=deal_store.deal_dir(deal_id))


def _main_head_sha(deal_id: str) -> str:
    commits = _service_for(deal_id).log(branch="main", limit=1)
    assert commits, "Expected at least one commit on main"
    return commits[0].sha


def _commit_raw_dict(deal_id: str, raw_dict: dict[str, Any]) -> str:
    """Commit a raw deal dict bypassing DealDefinition validation. Returns SHA."""
    service = _service_for(deal_id)
    head_commits = service.log(branch="main", limit=1)
    parent_sha = head_commits[0].sha if head_commits else None
    return service.commit_deal(
        json.dumps(raw_dict, indent=2).encode("utf-8"),
        author="test <test@bma.test>",
        message="raw test commit",
        parent_sha=parent_sha,
    )


def _extract_sse_data(line: str | bytes) -> dict[str, Any] | None:
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    if not line.startswith("data:"):
        return None
    payload = line[len("data:"):].strip()
    if not payload:
        return None
    return json.loads(payload)


def _collect_validation_events(
    client: TestClient,
    deal_id: str,
    sha: str,
) -> list[dict[str, Any]]:
    """Stream the validation endpoint and return all parsed events."""
    events: list[dict[str, Any]] = []
    with client.stream(
        "GET",
        f"/api/deals/{deal_id}/validate/stream",
        params={"sha": sha},
        timeout=10.0,
    ) as response:
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}"
        )
        assert "text/event-stream" in response.headers.get("content-type", "")
        for line in response.iter_lines():
            parsed = _extract_sse_data(line)
            if parsed is not None:
                events.append(parsed)
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_validate_stream_yields_payloads_and_closes(
    client: TestClient,
    deal_id: str,
) -> None:
    """AC 1, 3, 4: stream emits diagnostic events + exactly one terminal, then closes.

    Uses a deal with BOND_NAME_DUPLICATE to guarantee at least one diagnostic.
    """
    raw = {
        "deal_name": "dupe-bond-test",
        "bonds": [
            {"name": "A1", "coupon": 5.0, "notional": 1_000_000.0},
            {"name": "A1", "coupon": 4.0, "notional": 500_000.0},  # duplicate
        ],
        "accounts": [],
        "fees": [],
        "waterfall_rules": [
            {
                "rule_id": "pay-a1",
                "rule_type": "PAY_PRINCIPAL",
                "order": 0,
                "from_sources": ["CASH"],
                "to_targets": ["A1"],
            }
        ],
    }
    sha = _commit_raw_dict(deal_id, raw)

    events = _collect_validation_events(client, deal_id, sha)

    # AC 3: at least one diagnostic event with expected payload
    diagnostic_events = [e for e in events if e.get("event_type") == "diagnostic"]
    assert diagnostic_events, "Expected at least one diagnostic event"
    codes = {e["payload"]["code"] for e in diagnostic_events if e.get("payload")}
    assert "BOND_NAME_DUPLICATE" in codes, (
        f"Expected BOND_NAME_DUPLICATE in codes, got: {codes}"
    )

    # AC 4: exactly ONE terminal event
    terminal_types = {"validation_complete", "validation_failed"}
    terminal_events = [e for e in events if e.get("event_type") in terminal_types]
    assert len(terminal_events) == 1, (
        f"Expected exactly 1 terminal event, got {len(terminal_events)}: {terminal_events}"
    )

    # AC 4: stream closes after terminal (no events after terminal)
    terminal_idx = next(
        i for i, e in enumerate(events) if e.get("event_type") in terminal_types
    )
    assert terminal_idx == len(events) - 1, (
        "Events found after terminal: "
        + str(events[terminal_idx + 1:])
    )


def test_validate_stream_includes_deep_checks(
    client: TestClient,
    deal_id: str,
) -> None:
    """AC 2: Pydantic model validators (deeper than worker-side) appear in SSE output.

    Commits a deal with duplicate account names — structural validators miss this,
    but DealDefinition._validate_references raises, producing IR_VALIDATION_ERROR
    diagnostic events. Also asserts carry tie-out is absent.
    """
    # Duplicate account names: structural validators don't check this,
    # but Pydantic's _validate_references does.
    raw = {
        "deal_name": "deep-check-deal",
        "bonds": [{"name": "A1", "coupon": 5.0, "notional": 1_000_000.0}],
        "accounts": [
            {"name": "Reserve", "starting_amount": 100.0},
            {"name": "Reserve", "starting_amount": 200.0},  # duplicate — bypasses save_deal
        ],
        "fees": [],
        "waterfall_rules": [
            {
                "rule_id": "pay-a1",
                "rule_type": "PAY_PRINCIPAL",
                "order": 0,
                "from_sources": ["CASH"],
                "to_targets": ["A1"],
            }
        ],
    }
    sha = _commit_raw_dict(deal_id, raw)

    events = _collect_validation_events(client, deal_id, sha)

    # AC 2: deep Pydantic check produces a diagnostic event
    diagnostic_events = [e for e in events if e.get("event_type") == "diagnostic"]
    assert diagnostic_events, (
        "Expected at least one diagnostic event from deep Pydantic model_validate check"
    )
    codes = {e["payload"]["code"] for e in diagnostic_events if e.get("payload")}
    assert "IR_VALIDATION_ERROR" in codes, (
        f"Expected IR_VALIDATION_ERROR (from Pydantic _validate_references) in codes, got: {codes}"
    )

    # AC 2: carry tie-out must NOT appear (out of scope for static SHA-only validation)
    all_text = json.dumps(events).lower()
    assert "carry" not in all_text, (
        "Carry tie-out diagnostics must not appear in static SSE validation"
    )


def test_validate_stream_emits_complete_terminal_then_closes(
    client: TestClient,
    deal_id: str,
) -> None:
    """R1 pass-1 fold-back: valid deal → 0 diagnostics + exactly 1 validation_complete."""
    sha = _main_head_sha(deal_id)

    events = _collect_validation_events(client, deal_id, sha)

    # No diagnostic events for a valid deal
    diagnostic_events = [e for e in events if e.get("event_type") == "diagnostic"]
    assert diagnostic_events == [], (
        f"Expected 0 diagnostic events for a valid deal, got: {diagnostic_events}"
    )

    # Exactly one terminal, and it must be validation_complete
    terminal_events = [
        e for e in events
        if e.get("event_type") in {"validation_complete", "validation_failed"}
    ]
    assert len(terminal_events) == 1, (
        f"Expected exactly 1 terminal event, got: {terminal_events}"
    )
    assert terminal_events[0]["event_type"] == "validation_complete", (
        f"Expected validation_complete, got: {terminal_events[0]}"
    )


def test_validate_stream_emits_failed_terminal_on_validation_exception(
    client: TestClient,
    deal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R1 pass-1 fold-back: mock validation to raise → validation_failed terminal.

    Before implementation: assert status_code == 200 fails (route not found).
    After implementation: monkeypatch _STRUCTURAL_VALIDATORS to raise RuntimeError;
    stream must emit exactly one validation_failed event with error field populated.
    """
    sha = _main_head_sha(deal_id)

    # Patch the service's validator list to inject a failing validator.
    # If the module doesn't exist yet, ImportError is swallowed here;
    # the subsequent assert on status_code == 200 will fail the test.
    try:
        import bma_cfengine_app.orchestrator.deals.validation_service as _vs  # noqa: PLC0415

        monkeypatch.setattr(
            _vs,
            "_STRUCTURAL_VALIDATORS",
            [Mock(side_effect=RuntimeError("simulated validation failure"))],
        )
    except (ImportError, AttributeError):
        # Module not yet implemented — the endpoint will 404 and the assertion below fails.
        pass

    with client.stream(
        "GET",
        f"/api/deals/{deal_id}/validate/stream",
        params={"sha": sha},
        timeout=10.0,
    ) as response:
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}"
        )
        events: list[dict[str, Any]] = []
        for line in response.iter_lines():
            parsed = _extract_sse_data(line)
            if parsed is not None:
                events.append(parsed)

    terminal_events = [
        e for e in events
        if e.get("event_type") in {"validation_complete", "validation_failed"}
    ]
    assert len(terminal_events) == 1, (
        f"Expected exactly 1 terminal event, got: {terminal_events}"
    )
    terminal = terminal_events[0]
    assert terminal["event_type"] == "validation_failed", (
        f"Expected validation_failed, got: {terminal['event_type']}"
    )
    assert terminal.get("error"), (
        "Expected non-empty 'error' field in validation_failed event"
    )
