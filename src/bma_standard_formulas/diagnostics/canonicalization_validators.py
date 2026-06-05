"""Phase 1 rule fragmentation detector (rcf-2).

Walks ``deal.waterfall_rules`` (sorted by ``order``) and identifies maximal
consecutive runs of length >= 2 where every adjacent pair is consolidatable
via the rcf-1 ``is_consolidatable`` predicate with an empty intervening set.
"""

from __future__ import annotations

from typing import Any

from bma_standard_formulas.deals.schemas.ir import RuleNode
from bma_standard_formulas.diagnostics import (
    DiagnosticPayload,
    Owner,
    Severity,
    diagnostic_code,
)
from bma_standard_formulas.diagnostics.canonicalization_helpers import is_consolidatable
from bma_standard_formulas.diagnostics.payload import QuickFix


@diagnostic_code(
    "RULE_FRAGMENTATION_CONSOLIDATABLE",
    severity=Severity.warning,
    path_schema="deal.waterfall_rules[start_index..end_index]",
    owner=Owner.both,
)
def detect_rule_fragmentation(deal: dict[str, Any]) -> list[DiagnosticPayload]:
    """Emit RULE_FRAGMENTATION_CONSOLIDATABLE for consolidatable consecutive rule runs."""
    raw_rules: list[dict[str, Any]] = deal.get("waterfall_rules", [])
    if len(raw_rules) < 2:
        return []

    rules_sorted = sorted(raw_rules, key=lambda r: r.get("order", 0))
    rule_nodes = [RuleNode.model_validate(r) for r in rules_sorted]

    results: list[DiagnosticPayload] = []
    i = 0
    while i < len(rule_nodes) - 1:
        if not is_consolidatable(rule_nodes[i], rule_nodes[i + 1], []):
            i += 1
            continue

        start = i
        j = i + 1
        while (
            j < len(rule_nodes) - 1
            and is_consolidatable(rule_nodes[j], rule_nodes[j + 1], [])
        ):
            j += 1

        end = j
        run = rule_nodes[start : end + 1]
        results.append(
            DiagnosticPayload(
                code="RULE_FRAGMENTATION_CONSOLIDATABLE",
                severity=Severity.warning,
                path=f"deal.waterfall_rules[{start}..{end}]",
                message=(
                    f"Rules {start} through {end} can be consolidated into one"
                    " multi-target rule."
                ),
                payload={
                    "start_index": start,
                    "end_index": end,
                    "rule_ids": [r.rule_id for r in run],
                    "source": run[0].from_sources[0],
                    "target_count": sum(len(r.to_targets) for r in run),
                },
                fix=QuickFix(
                    action_id="canonicalize_consolidate_rule_run",
                    params={"start_index": start, "end_index": end},
                ),
            )
        )
        i = end + 1

    return results


@diagnostic_code(
    "STALE_QUICKFIX",
    severity=Severity.warning,
    path_schema="deal.waterfall_rules",
    owner=Owner.both,
)
def _stale_quickfix_sentinel(deal: dict[str, Any]) -> list[DiagnosticPayload]:
    """Sentinel for STALE_QUICKFIX diagnostic.

    Emitted by the ``canonicalizeConsolidateRuleRun`` reducer in TypeScript
    when a QuickFix range is invalid or stale. This Python decorator exists
    only to satisfy the vpc-4 same-commit catalog parity guard. Returns an
    empty list for any input — never produces diagnostics from the worker.
    """
    return []
