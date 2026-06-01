from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from bma_cfengine_app.orchestrator.deals import deal_store, operational
from bma_cfengine_app.orchestrator.deals.git_service import GitService
from bma_standard_formulas.deals.schemas.common import RuleType
from bma_standard_formulas.deals.schemas.ir import (
    AccountDef,
    BondDef,
    DealDefinition,
    FeeDef,
    RuleNode,
)


@pytest.fixture
def redirected_deals_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    monkeypatch.setattr(deal_store, "_DEALS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(deal_store, "_POOLS_DIR", tmp_path / "pools", raising=False)
    deal_store.init_deals_workspace()
    return tmp_path


def _build_minimal_deal(*, deal_name: str, coupon: float) -> DealDefinition:
    return DealDefinition(
        deal_name=deal_name,
        bonds=[BondDef(name="A1", coupon=coupon, notional=1_000_000.0)],
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


def _run_git(args: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout.strip()


def _all_branch_names(repo_path: Path) -> set[str]:
    raw = _run_git(
        ["for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        cwd=repo_path,
    )
    return {line.strip() for line in raw.splitlines() if line.strip()}


def _commit_on_branch(
    repo_path: Path,
    *,
    branch_name: str,
    updated_deal_name: str,
    commit_message: str,
    commit_time: datetime,
) -> None:
    _run_git(["checkout", branch_name], cwd=repo_path)
    try:
        deal_json_path = repo_path / "deal.json"
        payload = json.loads(deal_json_path.read_text(encoding="utf-8"))
        payload["deal_name"] = updated_deal_name
        deal_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        commit_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Tester",
            "GIT_AUTHOR_EMAIL": "tester@example.com",
            "GIT_COMMITTER_NAME": "Tester",
            "GIT_COMMITTER_EMAIL": "tester@example.com",
            "GIT_AUTHOR_DATE": commit_time.isoformat(),
            "GIT_COMMITTER_DATE": commit_time.isoformat(),
        }
        _run_git(["add", "deal.json"], cwd=repo_path, env=commit_env)
        _run_git(["commit", "-m", commit_message], cwd=repo_path, env=commit_env)
    finally:
        _run_git(["checkout", "main"], cwd=repo_path)


def _read_discarded_branches_text(repo_path: Path) -> str:
    discarded_dir = repo_path / "discarded_branches"
    if not discarded_dir.exists():
        return ""
    chunks: list[str] = []
    for path in sorted(discarded_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return "\n".join(chunks)


def test_non_applied_ephemeral_branches_gcd_after_7d_with_pii_redaction(
    redirected_deals_dir: Path,
) -> None:
    deal_id = "deal_gc_stale_ephemeral"
    deal_store.save_deal(deal_id, _build_minimal_deal(deal_name="gc-seed", coupon=5.0))
    repo_path = deal_store.deal_dir(deal_id)
    service = GitService(repo_path=repo_path)
    head_sha = service.log("main", limit=1)[0].sha

    branch_name = "ai/turn-baz"
    service.branch_create(branch_name, from_sha=head_sha)
    pii_prompt = "Please add a 5% reserve account funded from waterfall residual cash"
    stale_commit_message = (
        "User said: 'Please add a 5% reserve account funded from waterfall residual cash'\n"
        "tool_call model=gpt-5 tool_name=update_waterfall "
        "args={\"user_prompt\": \"" + pii_prompt + "\", \"reserve_pct\": \"5%\"}"
    )
    _commit_on_branch(
        repo_path,
        branch_name=branch_name,
        updated_deal_name="stale-ephemeral-change",
        commit_message=stale_commit_message,
        commit_time=datetime.now(timezone.utc) - timedelta(days=8),
    )

    operational.gc_stale_ephemeral_branches()

    assert branch_name not in _all_branch_names(repo_path)

    all_log_messages = _run_git(["log", "--all", "--format=%B"], cwd=repo_path)
    assert pii_prompt not in all_log_messages

    combined_redacted_surface = (
        all_log_messages + "\n" + _read_discarded_branches_text(repo_path)
    ).lower()
    assert (
        "arg_shape" in combined_redacted_surface
        or ("model" in combined_redacted_surface and "tool_name" in combined_redacted_surface)
    ), "Expected a redacted summary form (model/tool_name/arg_shape) to survive GC"


def test_pii_redaction_replaces_verbatim_args_with_arg_shape_summary(
    redirected_deals_dir: Path,
) -> None:
    deal_id = "deal_gc_redaction_shape"
    deal_store.save_deal(deal_id, _build_minimal_deal(deal_name="redaction-seed", coupon=6.0))
    repo_path = deal_store.deal_dir(deal_id)
    service = GitService(repo_path=repo_path)
    head_sha = service.log("main", limit=1)[0].sha

    branch_name = "ai/turn-redact"
    service.branch_create(branch_name, from_sha=head_sha)
    sensitive_deal_name = "ABC123-PrivateConfidentialDeal"
    sensitive_phone = "+1-555-123-4567"
    _commit_on_branch(
        repo_path,
        branch_name=branch_name,
        updated_deal_name="redaction-branch-change",
        commit_message=(
            "tool_call model=gpt-5 tool_name=save_draft "
            "args={\"deal_name\": \"" + sensitive_deal_name + "\", "
            "\"user_phone\": \"" + sensitive_phone + "\"}"
        ),
        commit_time=datetime.now(timezone.utc),
    )

    operational.redact_pii_in_commit_messages(repo_path)

    all_log_messages = _run_git(["log", "--all", "--format=%B"], cwd=repo_path)
    assert sensitive_deal_name not in all_log_messages
    assert sensitive_phone not in all_log_messages
    assert (
        "arg_shape" in all_log_messages.lower()
        or ("deal_name" in all_log_messages and "user_phone" in all_log_messages)
    ), "Expected redaction output to preserve argument shape metadata"


@pytest.mark.parametrize(
    "text,should_not_contain",
    [
        pytest.param(
            '"user_prompt": "Please add a 5% reserve account"',
            "Please add a 5% reserve account",
            id="json_string_value",
        ),
        pytest.param(
            "User said: 'Please add a 5% reserve account funded from waterfall residual cash'",
            "Please add a 5% reserve account funded from waterfall residual cash",
            id="user_said_single_quote",
        ),
        pytest.param(
            'User: "structure my deal with 3 tranches"',
            "structure my deal with 3 tranches",
            id="user_colon_double_quote",
        ),
        pytest.param(
            'args={"user_prompt": "sensitive data", "reserve_pct": "5%"}',
            "sensitive data",
            id="args_block",
        ),
        pytest.param(
            'arguments: {"deal_name": "ABC123-Private", "phone": "+1-555-0000"}',
            "ABC123-Private",
            id="arguments_block",
        ),
    ],
)
def test_apply_redaction_patterns_scrubs_pii(text: str, should_not_contain: str) -> None:
    """C3 (R1 fix): _apply_redaction_patterns covers JSON values, free-text
    prompts, and tool-call argument blocks."""
    result = operational._apply_redaction_patterns(text)
    assert should_not_contain not in result


def test_what_if_branches_never_auto_gcd(
    redirected_deals_dir: Path,
) -> None:
    deal_id = "deal_gc_what_if_preserved"
    deal_store.save_deal(deal_id, _build_minimal_deal(deal_name="what-if-seed", coupon=7.0))
    repo_path = deal_store.deal_dir(deal_id)
    service = GitService(repo_path=repo_path)
    head_sha = service.log("main", limit=1)[0].sha

    branch_name = "what-if/scenario-c"
    service.branch_create(branch_name, from_sha=head_sha)
    _commit_on_branch(
        repo_path,
        branch_name=branch_name,
        updated_deal_name="what-if-old-change",
        commit_message="what-if scenario branch edit",
        commit_time=datetime.now(timezone.utc) - timedelta(days=30),
    )

    operational.gc_stale_ephemeral_branches()

    assert branch_name in _all_branch_names(repo_path)
