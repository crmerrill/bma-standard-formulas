"""rcf-1-equivalence-predicate: unit tests for is_consolidatable.

All four tests must FAIL before the implementation module is created.
"""

from __future__ import annotations

import pytest

from bma_standard_formulas.diagnostics.canonicalization_helpers import (
    is_consolidatable,
)
from bma_standard_formulas.deals.schemas.ir import RuleNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_rule(**overrides) -> RuleNode:
    """Minimal valid RuleNode with all AC-2 predicate fields at fixed defaults."""
    defaults: dict = {
        "rule_id": "r1",
        "rule_type": "PAY",
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
    defaults.update(overrides)
    return RuleNode(**defaults)


# ---------------------------------------------------------------------------
# AC 1, 2 — positive case
# ---------------------------------------------------------------------------


def test_is_consolidatable_positive_cases() -> None:
    """AC 1, 2: two rules with identical predicate fields and no intervening
    rules returns True."""
    rule_a = _base_rule(rule_id="r1", to_targets=["CLASS_A"])
    rule_b = _base_rule(rule_id="r2", to_targets=["CLASS_B"])
    assert is_consolidatable(rule_a, rule_b, []) is True


# ---------------------------------------------------------------------------
# AC 1, 3 — per-target differences
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value_a,value_b",
    [
        ("max_amount_fixed", 1_000.0, 2_000.0),
        ("max_amount_expr", "SCHED_BAL_A", "SCHED_BAL_B"),
        ("target_weights", [1.0], [0.5]),
    ],
    ids=["max_amount_fixed", "max_amount_expr", "target_weights"],
)
def test_is_consolidatable_rejects_per_target_differences(
    field: str, value_a, value_b
) -> None:
    """AC 1, 3: same shared-predicate fields but differing per-target field
    returns False (3 sub-cases)."""
    rule_a = _base_rule(rule_id="r1", to_targets=["CLASS_A"], **{field: value_a})
    rule_b = _base_rule(rule_id="r2", to_targets=["CLASS_B"], **{field: value_b})
    assert is_consolidatable(rule_a, rule_b, []) is False


# ---------------------------------------------------------------------------
# AC 1, 4 case (a) — intervening to_targets mutation
# ---------------------------------------------------------------------------


def test_is_consolidatable_rejects_intervening_to_target_mutation() -> None:
    """AC 1, 4a: intervening rule writes to the shared source → returns False."""
    rule_a = _base_rule(rule_id="r1", from_sources=["CASH"], to_targets=["CLASS_A"])
    rule_b = _base_rule(rule_id="r3", from_sources=["CASH"], to_targets=["CLASS_B"])
    # Intervening rule whose to_targets includes the shared source CASH.
    intervening = _base_rule(
        rule_id="r2",
        from_sources=["ACT_INT"],
        to_targets=["CASH"],  # mutates the shared source
    )
    assert is_consolidatable(rule_a, rule_b, [intervening]) is False


# ---------------------------------------------------------------------------
# AC 1, 4 case (b) — intervening group-alias mutation
# ---------------------------------------------------------------------------


def test_is_consolidatable_rejects_intervening_group_alias_mutation() -> None:
    """AC 1, 4b: intervening rule's from_sources aliases to the shared source
    via group routing (GROUP_1_CASH ≡ CASH when group_id='1') → returns False."""
    # Shared rules operate on bare CASH scoped to group_id="1", so the logical
    # pool is GROUP_1_CASH.
    rule_a = _base_rule(
        rule_id="r1",
        from_sources=["CASH"],
        group_id="1",
        to_targets=["CLASS_A"],
    )
    rule_b = _base_rule(
        rule_id="r3",
        from_sources=["CASH"],
        group_id="1",
        to_targets=["CLASS_B"],
    )
    # Intervening rule explicitly uses the group-qualified form GROUP_1_CASH,
    # which aliases to the same logical pool as the shared source.
    intervening = _base_rule(
        rule_id="r2",
        from_sources=["GROUP_1_CASH"],  # aliases via group routing
        group_id=None,
        to_targets=["CLASS_C"],
    )
    assert is_consolidatable(rule_a, rule_b, [intervening]) is False
