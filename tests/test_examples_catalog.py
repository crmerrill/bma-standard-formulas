"""Catalog-level tests for BMA example coverage metadata."""

from __future__ import annotations

from bma_standard_formulas.formulas.examples import (
    BMA_EXAMPLES,
    get_included_bma_reference_ids,
)


def test_included_reference_ids_are_unique() -> None:
    """Coverage metadata should not contain duplicate BMA reference IDs."""
    refs = get_included_bma_reference_ids()
    assert len(refs) == len(set(refs))


def test_declared_bma_references_are_present_in_examples() -> None:
    """Each declared BMA SF reference should appear in at least one example entry."""
    refs = get_included_bma_reference_ids()
    text_bank = " | ".join(f"{example.id} {example.description}" for example in BMA_EXAMPLES.values())
    for ref in refs:
        assert ref in text_bank, f"Declared reference {ref} not found in BMA_EXAMPLES catalog"

