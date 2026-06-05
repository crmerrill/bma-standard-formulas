"""Test helpers for rcf-5 round-trip canonicalization tests.

Provides apply_consolidation_quickfix — a Python equivalent of the TS
canonicalizeConsolidateRuleRun reducer's slice-and-replace logic.
"""

from __future__ import annotations

from bma_standard_formulas.deals.schemas.ir import DealDefinition, RuleNode
from bma_standard_formulas.diagnostics.canonicalization_helpers import is_consolidatable


def apply_consolidation_quickfix(
    deal: DealDefinition, start_index: int, end_index: int
) -> DealDefinition:
    """Apply the canonicalize consolidate rule run quick-fix to a deal.

    Mirrors the TS canonicalizeConsolidateRuleRun reducer's slice-and-replace
    logic, used by rcf-5's round-trip tests to construct post-fix deals for
    cashflow equivalence comparison.

    - Sorts waterfall_rules by ``order`` (matches TS reducer behavior).
    - Replaces rules[start_index..end_index] (inclusive) with one consolidated
      rule whose ``to_targets`` is the concatenation of per-rule targets in
      authored order, all other fields from rules[start_index] (rule_id
      preserved).
    - Returns a new DealDefinition (does not mutate input).

    Raises ValueError if range is invalid or rules are not consolidatable.
    """
    rules = sorted(deal.waterfall_rules, key=lambda r: r.order)

    if not (0 <= start_index < end_index <= len(rules) - 1):
        raise ValueError(
            f"Invalid range [{start_index}..{end_index}] for {len(rules)} rules"
        )

    for i in range(start_index, end_index):
        if not is_consolidatable(rules[i], rules[i + 1], []):
            raise ValueError(
                f"Rules at indices {i} and {i + 1} are not consolidatable"
            )

    consolidated_targets: list[str] = []
    for i in range(start_index, end_index + 1):
        consolidated_targets.extend(rules[i].to_targets)

    consolidated = rules[start_index].model_copy(
        update={"to_targets": consolidated_targets}
    )

    new_rules = [
        *rules[:start_index],
        consolidated,
        *rules[end_index + 1 :],
    ]

    return deal.model_copy(update={"waterfall_rules": new_rules})
