"""rcf-5-negative-tests-and-roundtrip: negative consolidatability cases."""

from __future__ import annotations

from bma_standard_formulas.diagnostics.canonicalization_validators import (
    detect_rule_fragmentation,
)


def _rule(**overrides) -> dict:
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


def _assert_no_consolidatable_diagnostic(deal: dict) -> None:
    diagnostics = detect_rule_fragmentation(deal)
    assert not any(
        d.code == "RULE_FRAGMENTATION_CONSOLIDATABLE" for d in diagnostics
    ), diagnostics


def test_negative_different_payment_style_not_consolidatable() -> None:
    deal = {
        "waterfall_rules": [
            _rule(rule_id="r1", order=0, payment_style="SEQUENTIAL"),
            _rule(rule_id="r2", order=1, payment_style="PRO_RATA", to_targets=["CLASS_B"]),
        ]
    }
    _assert_no_consolidatable_diagnostic(deal)


def test_negative_different_cap_mode_not_consolidatable() -> None:
    deal = {
        "waterfall_rules": [
            _rule(rule_id="r1", order=0, cap_mode=None),
            _rule(rule_id="r2", order=1, cap_mode="NONE", to_targets=["CLASS_B"]),
        ]
    }
    _assert_no_consolidatable_diagnostic(deal)


def test_negative_different_condition_trigger_not_consolidatable() -> None:
    deal = {
        "waterfall_rules": [
            _rule(rule_id="r1", order=0, condition_trigger=None),
            _rule(
                rule_id="r2",
                order=1,
                condition_trigger="TRIGGER_A",
                to_targets=["CLASS_B"],
            ),
        ]
    }
    _assert_no_consolidatable_diagnostic(deal)


def test_negative_different_group_or_coverage_not_consolidatable() -> None:
    variants = [
        ("group_id", "1", "2"),
        ("coverage_mode", "NORMAL", "INTEREST_SHORTFALL"),
        ("allow_negative_source", False, True),
    ]
    for field, left, right in variants:
        deal = {
            "waterfall_rules": [
                _rule(rule_id="r1", order=0, **{field: left}),
                _rule(rule_id="r2", order=1, to_targets=["CLASS_B"], **{field: right}),
            ]
        }
        _assert_no_consolidatable_diagnostic(deal)


def test_negative_intervening_to_target_mutation_not_consolidatable() -> None:
    deal = {
        "waterfall_rules": [
            _rule(rule_id="r1", order=0, from_sources=["CASH"], to_targets=["CLASS_A"]),
            _rule(
                rule_id="r2",
                order=1,
                rule_type="PAY_PRINCIPAL",
                from_sources=["RESERVE"],
                to_targets=["CASH"],
            ),
            _rule(rule_id="r3", order=2, from_sources=["CASH"], to_targets=["CLASS_B"]),
        ]
    }
    _assert_no_consolidatable_diagnostic(deal)


def test_negative_intervening_group_alias_mutation_not_consolidatable() -> None:
    deal = {
        "waterfall_rules": [
            _rule(
                rule_id="r1",
                order=0,
                group_id="1",
                from_sources=["CASH"],
                to_targets=["CLASS_A"],
            ),
            _rule(
                rule_id="r2",
                order=1,
                rule_type="PAY_PRINCIPAL",
                from_sources=["GROUP_1_CASH"],
                to_targets=["CLASS_X"],
            ),
            _rule(
                rule_id="r3",
                order=2,
                group_id="1",
                from_sources=["CASH"],
                to_targets=["CLASS_B"],
            ),
        ]
    }
    _assert_no_consolidatable_diagnostic(deal)


def test_negative_per_target_amount_or_weight_differences_not_consolidatable() -> None:
    variants = [
        ("max_amount_fixed", 1_000.0, 2_000.0),
        ("max_amount_expr", "SCHED_BAL_A", "SCHED_BAL_B"),
        ("target_weights", [1.0], [0.25, 0.75]),
    ]
    for field, left, right in variants:
        deal = {
            "waterfall_rules": [
                _rule(rule_id="r1", order=0, to_targets=["CLASS_A"], **{field: left}),
                _rule(rule_id="r2", order=1, to_targets=["CLASS_B"], **{field: right}),
            ]
        }
        _assert_no_consolidatable_diagnostic(deal)
