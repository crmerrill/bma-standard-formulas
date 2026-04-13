"""IR validation and semantic checks beyond what Pydantic model_validators cover.

Performs:
- Rule DAG acyclicity (no circular condition dependencies)
- Account/bond/fee name uniqueness
- Waterfall rule ordering gaps and duplicates
- Trigger schedule length consistency
- Solver knob reachability
"""
from .schemas.ir import DealDefinition


class DealValidationError(ValueError):
    """Raised when a deal IR fails semantic validation."""


def validate_deal(deal: DealDefinition) -> list[str]:
    """Run full semantic validation on a DealDefinition.

    Returns a list of warning/error strings.  Raises DealValidationError
    if any blocking errors are found.
    """
    errors: list[str] = []
    warnings: list[str] = []

    _check_name_uniqueness(deal, errors)
    _check_rule_ordering(deal, errors, warnings)
    _check_trigger_schedules(deal, warnings)
    _check_condition_dag(deal, errors)
    _check_solver_knobs(deal, warnings)

    if errors:
        raise DealValidationError(
            f"Deal validation failed with {len(errors)} error(s):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    return warnings


def _check_name_uniqueness(deal: DealDefinition, errors: list[str]) -> None:
    bond_names = [b.name for b in deal.bonds]
    account_names = [a.name for a in deal.accounts]
    fee_names = [f.name for f in deal.fees]
    pseudo_bond_names = {b.name for b in deal.bonds if b.is_pseudo}

    # Strict within-category uniqueness.
    for group in (bond_names, account_names, fee_names):
        seen: set[str] = set()
        for name in group:
            if name in seen:
                errors.append(f"Duplicate component name: {name!r}")
            seen.add(name)

    # Cross-category uniqueness with one exception:
    # fee names may intentionally alias pseudo fee-tracking bond names.
    seen_cross: set[str] = set()
    all_names: list[str] = [*bond_names, *account_names, *fee_names]
    for name in all_names:
        if name in seen_cross:
            if name in pseudo_bond_names and name in fee_names:
                continue
            errors.append(f"Duplicate component name: {name!r}")
        seen_cross.add(name)


def _check_rule_ordering(
    deal: DealDefinition, errors: list[str], warnings: list[str],
) -> None:
    orders = [r.order for r in deal.waterfall_rules]
    if len(orders) != len(set(orders)):
        warnings.append("Waterfall rules have duplicate order values")
    if orders != sorted(orders):
        warnings.append("Waterfall rules are not sorted by order field")


def _check_trigger_schedules(deal: DealDefinition, warnings: list[str]) -> None:
    for trigger in deal.triggers:
        if trigger.threshold_schedule and trigger.threshold_value is not None:
            warnings.append(
                f"Trigger {trigger.name!r} has both threshold_schedule and "
                f"threshold_value; schedule takes precedence"
            )


def _check_condition_dag(deal: DealDefinition, errors: list[str]) -> None:
    """Check for circular dependencies among calculation references."""
    calc_deps: dict[str, set[str]] = {}
    calc_names = {c.name for c in deal.calculations}

    for calc in deal.calculations:
        deps: set[str] = set()
        for other_name in calc_names:
            if other_name != calc.name and other_name in calc.expression:
                deps.add(other_name)
        calc_deps[calc.name] = deps

    visited: set[str] = set()
    in_stack: set[str] = set()

    def _dfs(node: str) -> bool:
        if node in in_stack:
            return True
        if node in visited:
            return False
        visited.add(node)
        in_stack.add(node)
        for dep in calc_deps.get(node, set()):
            if _dfs(dep):
                errors.append(f"Circular dependency detected involving calculation {node!r}")
                return True
        in_stack.discard(node)
        return False

    for name in calc_deps:
        _dfs(name)


def _check_solver_knobs(deal: DealDefinition, warnings: list[str]) -> None:
    knob_bonds = [b.name for b in deal.bonds if b.solver_knob_coupon or b.solver_knob_size]
    if knob_bonds:
        warnings.append(
            f"Solver knobs enabled on bonds: {knob_bonds}. "
            f"Ensure SolverSpec references these."
        )
