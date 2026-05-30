from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from bma_cfengine_app.orchestrator.deals import merge as _merge_module  # noqa: F401
from bma_cfengine_app.orchestrator.deals.git_service import GitService
from bma_standard_formulas.deals.schemas.common import RuleType
from bma_standard_formulas.deals.schemas.ir import AccountDef, BondDef, DealDefinition, FeeDef, RuleNode
from bma_standard_formulas.diagnostics import (
    DiagnosticDescriptor,
    DiagnosticPayload,
    Owner,
    Severity,
    get_diagnostic,
)


def _run_git(repo_path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _init_repo(repo_path: Path) -> None:
    subprocess.run(
        ["git", "init", str(repo_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    _run_git(repo_path, "branch", "-M", "main")


def _deal_payload(
    *,
    coupon: float,
    account_starting_amount: float,
    fee_amount: float,
) -> dict[str, Any]:
    deal = DealDefinition(
        deal_name="typed-field-merge-diagnostics-test",
        bonds=[BondDef(name="A1", coupon=coupon, notional=1_000_000.0)],
        accounts=[AccountDef(name="Reserve", starting_amount=account_starting_amount)],
        fees=[FeeDef(name="Servicing", amount=fee_amount)],
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
    return deal.model_dump(mode="json")


def _extract_conflict_payload(result: Any) -> tuple[str, Severity, dict[str, Any]]:
    if isinstance(result, DiagnosticPayload):
        code = result.code
        severity = result.severity
        payload = result.payload
    elif isinstance(result, dict):
        code = result.get("code")
        severity = result.get("severity")
        payload = result.get("payload")
    else:
        code = getattr(result, "code", None)
        severity = getattr(result, "severity", None)
        payload = getattr(result, "payload", None)

    assert isinstance(code, str), f"Expected code str, got {type(code).__name__}"
    if isinstance(severity, str):
        severity = Severity(severity)
    assert isinstance(severity, Severity), f"Expected Severity, got {type(severity).__name__}"
    assert isinstance(payload, dict), f"Expected payload dict, got {type(payload).__name__}"
    return code, severity, payload


def _set_entity_field(
    payload: dict[str, Any],
    *,
    entity_kind: str,
    value: Any,
) -> tuple[str, str]:
    if entity_kind == "bond":
        payload["bonds"][0]["coupon"] = value
        return "A1", "coupon"
    if entity_kind == "account":
        payload["accounts"][0]["starting_amount"] = value
        return "Reserve", "starting_amount"
    if entity_kind == "fee":
        payload["fees"][0]["amount"] = value
        return "Servicing", "amount"
    raise AssertionError(f"Unsupported test entity kind: {entity_kind}")


def test_merge_conflict_code_is_registered_in_catalog() -> None:
    """AC 4: MERGE_CONFLICT is registered via @diagnostic_code at import time."""
    descriptor = get_diagnostic("MERGE_CONFLICT")

    assert isinstance(descriptor, DiagnosticDescriptor)
    assert descriptor.code == "MERGE_CONFLICT"
    assert descriptor.severity == Severity.error
    assert descriptor.owner == Owner.backend
    assert isinstance(descriptor.path_schema, str)
    assert descriptor.path_schema.strip()
    assert "bma_cfengine_app.orchestrator.deals.merge" in descriptor.validator_qualname


@pytest.mark.parametrize(
    "entity_kind,ancestor_value,ours_value,theirs_value",
    [
        pytest.param("bond", 5.0, 6.0, 7.0, id="bond"),
        pytest.param("account", 100.0, 125.0, 150.0, id="account"),
        pytest.param("fee", 10.0, 11.0, 12.0, id="fee"),
    ],
)
def test_merge_conflict_payload_schema_is_stable(
    tmp_path: Path,
    entity_kind: str,
    ancestor_value: Any,
    ours_value: Any,
    theirs_value: Any,
) -> None:
    """AC 5: conflict payload keeps a closed six-key schema across entity kinds."""
    _init_repo(tmp_path)
    service = GitService(repo_path=tmp_path)
    author = "system:test <test@example.com>"

    base_payload = _deal_payload(
        coupon=5.0,
        account_starting_amount=100.0,
        fee_amount=10.0,
    )
    _entity_id, _field_path = _set_entity_field(
        base_payload,
        entity_kind=entity_kind,
        value=ancestor_value,
    )
    base_sha = service.commit_deal(
        deal_payload=base_payload,
        author=author,
        message="initial",
    )

    service.branch_create("what-if/branch-a", from_sha=base_sha)
    _run_git(tmp_path, "checkout", "what-if/branch-a")
    payload_a = _deal_payload(
        coupon=5.0,
        account_starting_amount=100.0,
        fee_amount=10.0,
    )
    expected_entity_id, expected_field_path = _set_entity_field(
        payload_a,
        entity_kind=entity_kind,
        value=ours_value,
    )
    branch_a_sha = service.commit_deal(
        deal_payload=payload_a,
        author=author,
        message="branch-a edit",
        parent_sha=base_sha,
    )
    _run_git(tmp_path, "branch", "-f", "what-if/branch-a", branch_a_sha)

    _run_git(tmp_path, "checkout", "main")
    service.branch_create("what-if/branch-b", from_sha=base_sha)
    _run_git(tmp_path, "checkout", "what-if/branch-b")
    payload_b = _deal_payload(
        coupon=5.0,
        account_starting_amount=100.0,
        fee_amount=10.0,
    )
    _set_entity_field(
        payload_b,
        entity_kind=entity_kind,
        value=theirs_value,
    )
    branch_b_sha = service.commit_deal(
        deal_payload=payload_b,
        author=author,
        message="branch-b edit",
        parent_sha=base_sha,
    )
    _run_git(tmp_path, "branch", "-f", "what-if/branch-b", branch_b_sha)

    _run_git(tmp_path, "checkout", "main")
    _run_git(tmp_path, "reset", "--hard", branch_a_sha)

    result = service.merge(branch="what-if/branch-b", into="main")
    code, severity, payload = _extract_conflict_payload(result)

    assert code == "MERGE_CONFLICT"
    assert severity == Severity.error
    assert set(payload.keys()) == {
        "entity_kind",
        "entity_id",
        "field_path",
        "ours_value",
        "theirs_value",
        "ancestor_value",
    }
    assert isinstance(payload["entity_kind"], str)
    assert payload["entity_kind"] in {
        "bond",
        "account",
        "fee",
        "trigger",
        "calculation",
        "rule",
        "collateral_group",
    }
    assert payload["entity_kind"] == entity_kind
    assert isinstance(payload["entity_id"], str)
    assert payload["entity_id"] == expected_entity_id
    assert isinstance(payload["field_path"], str)
    assert payload["field_path"] == expected_field_path
    assert payload["ancestor_value"] == ancestor_value
    assert payload["ours_value"] == ours_value
    assert payload["theirs_value"] == theirs_value
