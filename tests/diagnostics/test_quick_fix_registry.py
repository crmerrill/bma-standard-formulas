"""Tests for the QuickFix registry (ve-5 fix-pass).

Validates that:
- Known manual action IDs resolve to a ManualQuickFix with kind == "manual".
- Unknown action IDs raise UnknownQuickFixError.
"""

from __future__ import annotations

import pytest

from bma_standard_formulas.diagnostics.quick_fix_registry import (
    ManualQuickFix,
    UnknownQuickFixError,
    get_quick_fix,
)


def test_get_quick_fix_for_known_manual_action() -> None:
    """manual_resolve_duplicate_bond_name resolves to a ManualQuickFix."""
    descriptor = get_quick_fix("manual_resolve_duplicate_bond_name")
    assert isinstance(descriptor, ManualQuickFix)
    assert descriptor.kind == "manual"
    assert isinstance(descriptor.description, str)
    assert len(descriptor.description) > 0


def test_get_quick_fix_for_unknown_id_raises() -> None:
    """An unregistered action_id raises UnknownQuickFixError."""
    with pytest.raises(UnknownQuickFixError):
        get_quick_fix("nonexistent_action_id_xyz")
