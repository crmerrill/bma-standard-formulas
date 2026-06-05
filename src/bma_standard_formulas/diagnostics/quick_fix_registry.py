"""QuickFix registry — maps action_id strings to typed QuickFix descriptors (ve-5 fix-pass).

A QuickFix descriptor carries enough metadata for Phase 2's Problems Panel to
determine at runtime whether a given quick-fix is:

- ``"dispatch"``: a fully-typed ``DealAction`` that the store can dispatch
  automatically (e.g. a rename that can be safely applied without user input).
- ``"manual"``: a human-directed instruction the user must resolve themselves
  (e.g. renaming one of two duplicate bonds, where the correct choice is
  ambiguous).

Adding a new quick-fix:
1. Define a ``DispatchQuickFix`` or ``ManualQuickFix`` instance below.
2. Insert it into ``_REGISTRY`` keyed by ``action_id``.
3. Add a test to ``tests/diagnostics/test_quick_fix_registry.py``.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class DispatchQuickFix(BaseModel):
    """A quick-fix that maps 1:1 to a dispatchable ``DealAction`` in the TS store."""

    kind: Literal["dispatch"] = "dispatch"
    action_type: str
    description: str


class ManualQuickFix(BaseModel):
    """A quick-fix that requires the user to resolve manually.

    The Problems Panel renders ``description`` as a hint and marks the
    quick-fix as non-dispatchable.
    """

    kind: Literal["manual"] = "manual"
    description: str


QuickFixDescriptor = Annotated[
    Union[DispatchQuickFix, ManualQuickFix],
    Field(discriminator="kind"),
]


class UnknownQuickFixError(KeyError):
    """Raised when ``get_quick_fix`` is called with an unregistered ``action_id``."""

    def __init__(self, action_id: str) -> None:
        super().__init__(action_id)
        self.action_id = action_id

    def __str__(self) -> str:
        return f"No QuickFix registered for action_id={self.action_id!r}"


_REGISTRY: dict[str, DispatchQuickFix | ManualQuickFix] = {
    "manual_resolve_duplicate_bond_name": ManualQuickFix(
        kind="manual",
        description=(
            "Two or more bonds share the same name. "
            "Rename one of the duplicates to make all bond names unique."
        ),
    ),
    "canonicalize_consolidate_rule_run": DispatchQuickFix(
        kind="dispatch",
        action_type="canonicalizeConsolidateRuleRun",
        description="Consolidate fragmented rules into a single multi-target rule.",
    ),
}


def get_quick_fix(action_id: str) -> DispatchQuickFix | ManualQuickFix:
    """Return the ``QuickFixDescriptor`` registered for *action_id*.

    Raises:
        UnknownQuickFixError: if *action_id* has no registered descriptor.
    """
    try:
        return _REGISTRY[action_id]
    except KeyError:
        raise UnknownQuickFixError(action_id) from None
