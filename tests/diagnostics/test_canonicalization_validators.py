"""rcf-2-fragmentation-detector: failing tests (T1).

Tests in this module intentionally stay RED until the implementation module and
catalog row are added in the follow-up implementation dispatch.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
from pathlib import Path

from bma_standard_formulas.diagnostics import iter_diagnostics
from bma_standard_formulas.diagnostics.canonicalization_validators import (
    detect_rule_fragmentation,
)


def _rule(**overrides) -> dict:
    """Return a minimal rule payload with all consolidatability keys pinned."""
    base: dict = {
        "rule_id": "r1",
        "rule_type": "PAY_INTEREST",
        "order": 0,
        "from_sources": ["CASH"],
        "to_targets": ["CLASS_A"],
        "payment_style": "SEQUENTIAL",
        "cap_mode": None,
        "condition_trigger": None,
        "condition_invert": False,
        "condition_expr": None,
        "group_id": None,
        "coverage_mode": "NORMAL",
        "allow_negative_source": False,
        "max_amount_fixed": None,
        "max_amount_expr": None,
        "target_weights": None,
    }
    base.update(overrides)
    return base


def _run_validator_by_code(code: str, deal: dict) -> list:
    descriptor = next((d for d in iter_diagnostics() if d.code == code), None)
    assert descriptor is not None, f"{code} is not registered in the diagnostics registry"

    module_name, func_name = descriptor.validator_qualname.rsplit(".", 1)
    module = importlib.import_module(module_name)
    fn = getattr(module, func_name, None)
    assert callable(fn), f"Validator callable for {code} is not importable"
    return fn(deal)


def test_fragmentation_detector_emits_diagnostic_for_consecutive_run() -> None:
    """AC 1, 3: a 3-rule consolidatable run emits one pinned diagnostic payload."""
    deal = {
        "waterfall_rules": [
            _rule(rule_id="r1", order=0, to_targets=["CLASS_A"]),
            _rule(rule_id="r2", order=1, to_targets=["CLASS_B"]),
            _rule(rule_id="r3", order=2, to_targets=["CLASS_C"]),
        ]
    }

    results = detect_rule_fragmentation(deal)
    assert len(results) == 1

    diagnostic = results[0]
    assert diagnostic.code == "RULE_FRAGMENTATION_CONSOLIDATABLE"
    assert diagnostic.severity.value == "warning"
    assert diagnostic.path == "deal.waterfall_rules[0..2]"

    payload = diagnostic.payload
    assert payload["start_index"] == 0
    assert payload["end_index"] == 2
    assert payload["rule_ids"] == ["r1", "r2", "r3"]
    assert payload["source"] == "CASH"
    assert payload["target_count"] == 3

    assert diagnostic.fix is not None
    assert diagnostic.fix.action_id == "canonicalize_consolidate_rule_run"
    assert diagnostic.fix.params == {"start_index": 0, "end_index": 2}


def test_fragmentation_detector_ignores_non_consolidatable_rules() -> None:
    """AC 1: rules that are not consolidatable emit no fragmentation diagnostic."""
    deal = {
        "waterfall_rules": [
            _rule(
                rule_id="r1",
                order=0,
                to_targets=["CLASS_A"],
                payment_style="SEQUENTIAL",
            ),
            _rule(
                rule_id="r2",
                order=1,
                to_targets=["CLASS_B"],
                payment_style="PRO_RATA",
            ),
        ]
    }

    results = detect_rule_fragmentation(deal)
    assert results == []


def test_fragmentation_detector_payload_matches_pinned_schema() -> None:
    """AC 3: payload fields and concrete range path follow the pinned schema."""
    deal = {
        "waterfall_rules": [
            _rule(rule_id="r1", order=0, to_targets=["CLASS_A"]),
            _rule(rule_id="r2", order=1, to_targets=["CLASS_B"]),
        ]
    }

    results = detect_rule_fragmentation(deal)
    assert len(results) == 1

    diagnostic = results[0]
    assert re.fullmatch(r"deal\.waterfall_rules\[\d+\.\.\d+\]", diagnostic.path)

    payload = diagnostic.payload
    assert isinstance(payload["start_index"], int)
    assert isinstance(payload["end_index"], int)
    assert isinstance(payload["rule_ids"], list)
    assert all(isinstance(rule_id, str) for rule_id in payload["rule_ids"])
    assert isinstance(payload["source"], str)
    assert isinstance(payload["target_count"], int)

    assert diagnostic.fix is not None
    assert diagnostic.fix.action_id == "canonicalize_consolidate_rule_run"
    assert isinstance(diagnostic.fix.params["start_index"], int)
    assert isinstance(diagnostic.fix.params["end_index"], int)


def test_catalog_row_present_for_rule_fragmentation_consolidatable() -> None:
    """AC 2: catalog row exists and matches pinned metadata for this diagnostic."""
    parser_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "parse_diagnostic_catalog.py"
    )
    spec = importlib.util.spec_from_file_location("parse_diagnostic_catalog", parser_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    catalog_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "architecture"
        / "diagnostic_catalog.md"
    )
    records = module.parse_diagnostic_catalog(catalog_path)
    row = next(
        (record for record in records if record["code"] == "RULE_FRAGMENTATION_CONSOLIDATABLE"),
        None,
    )

    assert row is not None, "RULE_FRAGMENTATION_CONSOLIDATABLE missing from diagnostic catalog"
    assert row["code"] == "RULE_FRAGMENTATION_CONSOLIDATABLE"
    assert row["severity"] == "warning"
    assert row["path_schema"] == "deal.waterfall_rules[start_index..end_index]"
    assert (
        row["message"]
        == "Rules {start_index} through {end_index} can be consolidated into one multi-target rule."
    )
    assert row["owner"] == "both"
    assert row["quick_fix"] == "canonicalize_consolidate_rule_run"
    assert row["validator_file_line"].split(":", 1)[0] == "canonicalization_validators.py"


def test_interleaved_detector_emits_info_diagnostic() -> None:
    """AC 1, 3, 4: interleaved factorable groups emit one info diagnostic with no autofix."""
    deal = {
        "waterfall_rules": [
            _rule(rule_id="x0", order=0, from_sources=["RESERVE"], to_targets=["CLASS_Z"]),
            _rule(rule_id="a", order=1, from_sources=["CASH"], to_targets=["CLASS_A"]),
            _rule(
                rule_id="m",
                order=2,
                from_sources=["CASH"],
                to_targets=["CLASS_M"],
                payment_style="PRO_RATA",
            ),
            _rule(rule_id="b", order=3, from_sources=["CASH"], to_targets=["CLASS_B"]),
            _rule(rule_id="x4", order=4, from_sources=["RESERVE"], to_targets=["CLASS_Q"]),
            _rule(rule_id="c", order=5, from_sources=["CASH"], to_targets=["CLASS_C"]),
        ]
    }

    diagnostics = _run_validator_by_code("INTERLEAVED_RULES_FACTORABLE", deal)
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic.code == "INTERLEAVED_RULES_FACTORABLE"
    assert diagnostic.severity.value == "info"
    assert diagnostic.path == "deal.waterfall_rules[1,3,5]"
    assert diagnostic.fix is None


def test_interleaved_detector_fix_is_null_never_autofix() -> None:
    """AC 4: Python emits fix=None; null-vs-omitted is JSON-equivalent for no-fix semantics."""
    deal = {
        "waterfall_rules": [
            _rule(rule_id="a", order=0, from_sources=["CASH"], to_targets=["CLASS_A"]),
            _rule(
                rule_id="m",
                order=1,
                from_sources=["CASH"],
                to_targets=["CLASS_M"],
                payment_style="PRO_RATA",
            ),
            _rule(rule_id="b", order=2, from_sources=["CASH"], to_targets=["CLASS_B"]),
        ]
    }

    diagnostics = _run_validator_by_code("INTERLEAVED_RULES_FACTORABLE", deal)
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic.fix is None

    serialized = json.loads(diagnostic.model_dump_json())
    assert "fix" in serialized and serialized["fix"] is None

    normalized_no_fix = {k: v for k, v in serialized.items() if v is not None}
    assert "fix" not in normalized_no_fix


def test_interleaved_detector_path_uses_comma_separated_indices() -> None:
    """AC 3: emitted path uses sorted comma-separated indices without spaces."""
    deal = {
        "waterfall_rules": [
            _rule(rule_id="x0", order=0, from_sources=["RESERVE"], to_targets=["CLASS_0"]),
            _rule(rule_id="x1", order=1, from_sources=["RESERVE"], to_targets=["CLASS_1"]),
            _rule(rule_id="x2", order=2, from_sources=["RESERVE"], to_targets=["CLASS_2"]),
            _rule(rule_id="x3", order=3, from_sources=["RESERVE"], to_targets=["CLASS_3"]),
            _rule(rule_id="a", order=4, from_sources=["CASH"], to_targets=["CLASS_A"]),
            _rule(
                rule_id="m",
                order=5,
                from_sources=["CASH"],
                to_targets=["CLASS_M"],
                payment_style="PRO_RATA",
            ),
            _rule(rule_id="x6", order=6, from_sources=["RESERVE"], to_targets=["CLASS_6"]),
            _rule(rule_id="b", order=7, from_sources=["CASH"], to_targets=["CLASS_B"]),
            _rule(rule_id="x8", order=8, from_sources=["RESERVE"], to_targets=["CLASS_8"]),
            _rule(rule_id="c", order=9, from_sources=["CASH"], to_targets=["CLASS_C"]),
        ]
    }

    diagnostics = _run_validator_by_code("INTERLEAVED_RULES_FACTORABLE", deal)
    assert len(diagnostics) == 1
    assert diagnostics[0].path == "deal.waterfall_rules[4,7,9]"


def test_interleaved_detector_groups_transitively_with_internal_mutator() -> None:
    """AC 1: one mutator inside [min,max] makes the full transitive group diagnosable."""
    deal = {
        "waterfall_rules": [
            _rule(rule_id="x0", order=0, from_sources=["RESERVE"], to_targets=["CLASS_0"]),
            _rule(rule_id="a", order=1, from_sources=["CASH"], to_targets=["CLASS_A"]),
            _rule(
                rule_id="m",
                order=2,
                from_sources=["CASH"],
                to_targets=["CLASS_M"],
                payment_style="PRO_RATA",
            ),
            _rule(rule_id="b", order=3, from_sources=["CASH"], to_targets=["CLASS_B"]),
            _rule(rule_id="c", order=4, from_sources=["CASH"], to_targets=["CLASS_C"]),
        ]
    }

    diagnostics = _run_validator_by_code("INTERLEAVED_RULES_FACTORABLE", deal)
    assert len(diagnostics) == 1
    assert diagnostics[0].path == "deal.waterfall_rules[1,3,4]"


def test_interleaved_detector_ignores_rules_without_mutator() -> None:
    """AC 1: shared-key rules without an intervening mutator should not emit interleaved info."""
    contiguous = {
        "waterfall_rules": [
            _rule(rule_id="a", order=0, from_sources=["CASH"], to_targets=["CLASS_A"]),
            _rule(rule_id="b", order=1, from_sources=["CASH"], to_targets=["CLASS_B"]),
        ]
    }
    separated_non_mutating = {
        "waterfall_rules": [
            _rule(rule_id="a", order=0, from_sources=["CASH"], to_targets=["CLASS_A"]),
            _rule(
                rule_id="x",
                order=1,
                from_sources=["RESERVE"],
                to_targets=["CLASS_X"],
                payment_style="PRO_RATA",
            ),
            _rule(rule_id="b", order=2, from_sources=["CASH"], to_targets=["CLASS_B"]),
        ]
    }

    contiguous_results = _run_validator_by_code("INTERLEAVED_RULES_FACTORABLE", contiguous)
    separated_results = _run_validator_by_code(
        "INTERLEAVED_RULES_FACTORABLE", separated_non_mutating
    )
    assert contiguous_results == []
    assert separated_results == []


def test_catalog_row_present_for_interleaved_rules_factorable() -> None:
    """AC 2: catalog row exists and matches pinned metadata for interleaved info diagnostic."""
    parser_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "parse_diagnostic_catalog.py"
    )
    spec = importlib.util.spec_from_file_location("parse_diagnostic_catalog", parser_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    catalog_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "architecture"
        / "diagnostic_catalog.md"
    )
    records = module.parse_diagnostic_catalog(catalog_path)
    row = next(
        (record for record in records if record["code"] == "INTERLEAVED_RULES_FACTORABLE"),
        None,
    )

    assert row is not None, "INTERLEAVED_RULES_FACTORABLE missing from diagnostic catalog"
    assert row["code"] == "INTERLEAVED_RULES_FACTORABLE"
    assert row["severity"] == "info"
    assert row["path_schema"] == "deal.waterfall_rules[{indices}]"
    assert (
        row["message"]
        == "Rules at {indices} share (rule_type, source, payment_style) but are interleaved with a source mutation; manual review recommended."
    )
    assert row["owner"] == "both"
    assert row["quick_fix"] == "Manual review only; no automatic fix is offered."
    assert row["validator_file_line"].split(":", 1)[0] == "canonicalization_validators.py"
