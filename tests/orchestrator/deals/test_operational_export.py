from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

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


def test_export_deal_strictly_isolates_deal_json_and_blocks_forbidden_artifacts(
    redirected_deals_dir: Path,
) -> None:
    # Import inside the test so this remains a concrete TDD failure signal
    # while operational.py does not yet exist.
    from bma_cfengine_app.orchestrator.deals.operational import export_deal

    deal_id = "deal_export_guardrails"
    deal_store.save_deal(
        deal_id,
        _build_minimal_deal(deal_name="export-guardrails", coupon=5.0),
    )

    repository_dir = deal_store.deal_dir(deal_id)
    assert (repository_dir / ".git" / "HEAD").exists(), "Expected git repo fixture"

    (repository_dir / "sidecar.json").write_text(
        '{"layout_overrides": {}}',
        encoding="utf-8",
    )
    (repository_dir / "scenarios.json").write_text('{"scenarios": []}', encoding="utf-8")

    turn_transcripts_dir = repository_dir / "turn_transcripts"
    turn_transcripts_dir.mkdir(parents=True, exist_ok=True)
    (turn_transcripts_dir / "turn_abc.json").write_text(
        '{"turn_id": "turn_abc"}',
        encoding="utf-8",
    )

    discarded_branch_dir = repository_dir / "discarded_branches" / "branch_def"
    discarded_branch_dir.mkdir(parents=True, exist_ok=True)
    (discarded_branch_dir / "some.txt").write_text("discarded", encoding="utf-8")

    service = GitService(repo_path=repository_dir)
    head = service.log(branch="main", limit=1)
    assert head, "Expected at least one commit to export"
    sha = head[0].sha

    exported_bytes = export_deal(deal_id, sha)
    assert isinstance(exported_bytes, (bytes, bytearray))

    exported_payload = json.loads(bytes(exported_bytes).decode("utf-8"))
    expected_payload = json.loads(service.show(sha, "deal.json").decode("utf-8"))
    assert exported_payload == expected_payload

    signature = inspect.signature(export_deal)
    assert list(signature.parameters.keys()) == ["deal_id", "sha"]

    with pytest.raises(TypeError):
        export_deal(deal_id, sha, "deal.json")  # type: ignore[call-arg]

    forbidden_artifacts = [
        repository_dir / ".git" / "HEAD",
        repository_dir / "sidecar.json",
        repository_dir / "scenarios.json",
        repository_dir / "turn_transcripts" / "turn_abc.json",
        repository_dir / "discarded_branches" / "branch_def" / "some.txt",
    ]
    for artifact_path in forbidden_artifacts:
        assert artifact_path.exists(), f"Fixture artifact unexpectedly missing: {artifact_path}"
