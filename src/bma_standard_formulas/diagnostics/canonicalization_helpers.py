"""Phase 1 canonicalization equivalence predicate (rcf-1).

Pure functions only — no side effects, no I/O.
"""

from __future__ import annotations

from bma_standard_formulas.deals.schemas.ir import RuleNode

# Builtin stream tokens that may be bare (single-pool) or group-scoped.
# When a RuleNode carries group_id='N', a bare token like 'CASH' in
# from_sources/to_targets is logically equivalent to 'GROUP_N_CASH'.
_BUILTIN_TOKENS: frozenset[str] = frozenset({"CASH", "ACT_INT", "ACT_PRIN", "LOSS"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_logical(token: str, group_id: str | None) -> str:
    """Return the canonical logical-pool identifier for *token*.

    If *group_id* is set and *token* is a bare builtin stream token, the
    logical pool is ``GROUP_<group_id>_<token>`` (underscore-joined, matching
    the IR naming convention established in common.py).  All other tokens are
    returned unchanged.

    Example::

        _resolve_logical("CASH", "1")   # → "GROUP_1_CASH"
        _resolve_logical("CASH", None)  # → "CASH"
        _resolve_logical("CLASS_A", "1")  # → "CLASS_A"  (non-builtin)

    Limitation: dot-notation aliases (e.g. 'GROUP_1.CASH') are NOT resolved
    because the Phase 1 IR schema uses underscore notation exclusively.
    """
    if group_id and token in _BUILTIN_TOKENS:
        return f"GROUP_{group_id}_{token}"
    return token


def _mutates_source(intervening: RuleNode, source: str, source_group_id: str | None) -> bool:
    """Return True iff *intervening* mutates the logical pool identified by
    (*source*, *source_group_id*).

    Mutation is defined by the rcf-1 AC-4 Mi1 contract:
      (a) The intervening rule's ``to_targets`` contains the shared source
          (possibly under its group-resolved form).
      (b) The intervening rule's ``from_sources`` aliases to the shared source
          via group routing — i.e. it reads from the same logical pool, which
          alters the pool balance and makes rule ordering load-bearing.
    """
    logical_shared = _resolve_logical(source, source_group_id)

    for target in intervening.to_targets:
        if _resolve_logical(target, intervening.group_id) == logical_shared:
            return True

    for src in intervening.from_sources:
        if _resolve_logical(src, intervening.group_id) == logical_shared:
            return True

    return False


# ---------------------------------------------------------------------------
# Public predicate
# ---------------------------------------------------------------------------


def is_consolidatable(
    rule_a: RuleNode,
    rule_b: RuleNode,
    all_rules_between: list[RuleNode],
) -> bool:
    """Phase 1 canonicalization equivalence predicate per Phase 0 B6.

    Returns True iff:
    - Both rules share exactly: rule_type, from_sources, payment_style,
      cap_mode, condition_trigger, condition_invert, condition_expr, group_id,
      coverage_mode, allow_negative_source.
    - Both rules have no per-target differences: max_amount_fixed,
      max_amount_expr, and target_weights are all equal (or both absent).
    - No rule in all_rules_between mutates the shared source (as defined by
      the rcf-1 AC-4 Mi1 contract: to_targets contains the source, OR the
      intervening source aliases to the same logical pool via group routing).

    This predicate is PURE — no side effects, no I/O.
    """
    # AC 2: shared predicate fields must be identical.
    if rule_a.rule_type != rule_b.rule_type:
        return False
    if rule_a.from_sources != rule_b.from_sources:
        return False
    if rule_a.payment_style != rule_b.payment_style:
        return False
    if rule_a.cap_mode != rule_b.cap_mode:
        return False
    if rule_a.condition_trigger != rule_b.condition_trigger:
        return False
    if rule_a.condition_invert != rule_b.condition_invert:
        return False
    if rule_a.condition_expr != rule_b.condition_expr:
        return False
    if rule_a.group_id != rule_b.group_id:
        return False
    if rule_a.coverage_mode != rule_b.coverage_mode:
        return False
    if rule_a.allow_negative_source != rule_b.allow_negative_source:
        return False

    # AC 3: per-target fields must be identical (or both absent).
    if rule_a.max_amount_fixed != rule_b.max_amount_fixed:
        return False
    if rule_a.max_amount_expr != rule_b.max_amount_expr:
        return False
    if rule_a.target_weights != rule_b.target_weights:
        return False

    # AC 4: no intervening rule may mutate any shared source.
    if all_rules_between:
        group_id = rule_a.group_id
        for source in rule_a.from_sources:
            for intervening in all_rules_between:
                if _mutates_source(intervening, source, group_id):
                    return False

    return True
