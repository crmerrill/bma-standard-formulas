"""Phase 1 rule canonicalization validators (rcf-2, rcf-4).

rcf-2: Walks ``deal.waterfall_rules`` (sorted by ``order``) and identifies
maximal consecutive runs of length >= 2 where every adjacent pair is
consolidatable via the rcf-1 ``is_consolidatable`` predicate with an empty
intervening set.

rcf-4: Groups rules by ``(rule_type, source, payment_style)`` and flags groups
whose members are interleaved with a source-mutating intervening rule.
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
from bma_standard_formulas.diagnostics.canonicalization_helpers import (
    is_consolidatable,
    mutates_source,
)
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


@diagnostic_code(
    "INTERLEAVED_RULES_FACTORABLE",
    severity=Severity.info,
    path_schema="deal.waterfall_rules[{indices}]",
    owner=Owner.both,
)
def detect_interleaved_rules(deal: dict[str, Any]) -> list[DiagnosticPayload]:
    """Emit INTERLEAVED_RULES_FACTORABLE for groups interleaved with a source mutation.

    Algorithm — group-and-transitivity:
    1. Walk waterfall_rules sorted by ``order``. Build a dict mapping
       ``(rule_type, source, payment_style)`` → list of sorted indices.
    2. For each group with len >= 2, compute min/max index and examine every
       rule whose index falls strictly between them that is NOT a group member.
    3. If ANY such intervening rule satisfies ``mutates_source(rule, shared_source)``,
       emit ONE info diagnostic covering all group indices.
    """
    raw_rules: list[dict[str, Any]] = deal.get("waterfall_rules", [])
    if len(raw_rules) < 2:
        return []

    rules_sorted = sorted(raw_rules, key=lambda r: r.get("order", 0))
    rule_nodes = [RuleNode.model_validate(r) for r in rules_sorted]

    groups: dict[tuple[Any, str, Any], list[int]] = {}
    for idx, rule in enumerate(rule_nodes):
        if not rule.from_sources:
            continue
        key = (rule.rule_type, rule.from_sources[0], rule.payment_style)
        groups.setdefault(key, []).append(idx)

    results: list[DiagnosticPayload] = []
    for (rt, src, ps), indices in groups.items():
        if len(indices) < 2:
            continue

        min_idx = min(indices)
        max_idx = max(indices)
        group_member_set = set(indices)
        shared_group_id = rule_nodes[indices[0]].group_id

        has_mutator = any(
            mutates_source(rule_nodes[i], src, shared_group_id)
            for i in range(min_idx + 1, max_idx)
            if i not in group_member_set
        )
        if not has_mutator:
            continue

        sorted_indices = sorted(indices)
        results.append(
            DiagnosticPayload(
                code="INTERLEAVED_RULES_FACTORABLE",
                severity=Severity.info,
                path=f"deal.waterfall_rules[{','.join(map(str, sorted_indices))}]",
                message=(
                    f"Rules at {sorted_indices} share (rule_type, source, payment_style)"
                    " but are interleaved with a source mutation; manual review recommended."
                ),
                payload={
                    "indices": sorted_indices,
                    "rule_type": rt.value if hasattr(rt, "value") else rt,
                    "source": src,
                    "payment_style": ps.value if hasattr(ps, "value") else ps,
                },
                fix=None,
            )
        )

    return results
