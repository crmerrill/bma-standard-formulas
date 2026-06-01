from __future__ import annotations

import inspect
import json
import logging
from pathlib import Path

import pytest

from bma_cfengine_app.orchestrator.deals import deal_store, operational
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


def test_git_count_objects_telemetry_aggregates_p95_and_alerts_on_threshold(
    redirected_deals_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    deal_ids = [
        "deal_telemetry_01",
        "deal_telemetry_02",
        "deal_telemetry_03",
        "deal_telemetry_04",
        "deal_telemetry_05",
        "deal_telemetry_06",
    ]
    for i, deal_id in enumerate(deal_ids, start=1):
        for rev in range(i):
            deal_store.save_deal(
                deal_id,
                _build_minimal_deal(
                    deal_name=f"telemetry-{deal_id}-rev-{rev}",
                    coupon=4.0 + i + (rev / 10.0),
                ),
            )

    # Keep the setup cheap by reducing threshold so ordinary repos trigger alerts.
    monkeypatch.setattr(
        operational,
        "GIT_SIZE_ALERT_THRESHOLD_BYTES",
        1024,
        raising=False,
    )
    monkeypatch.setattr(
        operational,
        "DEFAULT_GIT_SIZE_ALERT_THRESHOLD_BYTES",
        1024,
        raising=False,
    )
    monkeypatch.setattr(
        operational,
        "GIT_SIZE_ALERT_THRESHOLD_MB",
        0.001,
        raising=False,
    )
    monkeypatch.setattr(
        operational,
        "DEFAULT_GIT_SIZE_ALERT_THRESHOLD_MB",
        0.001,
        raising=False,
    )

    caplog.set_level(logging.WARNING)

    measure = operational.measure_git_directory_size
    signature = inspect.signature(measure)
    if "threshold_bytes" in signature.parameters:
        result = measure(threshold_bytes=1024)
    elif "threshold_mb" in signature.parameters:
        result = measure(threshold_mb=0.001)
    else:
        result = measure()

    serialized_result = json.dumps(result, default=str)
    serialized_lower = serialized_result.lower()
    assert "p95" in serialized_lower
    for deal_id in deal_ids:
        assert deal_id in serialized_result

    warning_records = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert warning_records, "Expected WARNING+ telemetry logs when threshold is intentionally tiny"

    matched_alert = False
    for record in warning_records:
        joined = (
            record.getMessage()
            + " "
            + json.dumps(record.__dict__, default=str)
        ).lower()
        if "p95" in joined and ("threshold" in joined or "alert" in joined):
            matched_alert = True
            break
    assert matched_alert, "Expected structured telemetry alert mentioning p95/threshold"
