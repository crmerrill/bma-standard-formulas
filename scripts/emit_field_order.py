"""Emit a field-order manifest for the DealDefinition Pydantic model graph.

Introspects DealDefinition and every nested BaseModel reachable via
model_fields annotations, then writes the declaration-order field list
for each model to a JSON file.

Usage:
    python scripts/emit_field_order.py           # write mode
    python scripts/emit_field_order.py --check   # drift guard (CI)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel

from bma_standard_formulas.deals.schemas.ir import DealDefinition

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = (
    REPO_ROOT
    / "src"
    / "bma_standard_formulas"
    / "deals"
    / "schemas"
    / "field_order.json"
)


def _extract_basemodel_types(annotation: Any) -> list[type[BaseModel]]:
    """Extract all BaseModel subclasses from a type annotation."""
    results: list[type[BaseModel]] = []

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        results.append(annotation)
        return results

    origin = get_origin(annotation)
    if origin is Union:
        for arg in get_args(annotation):
            results.extend(_extract_basemodel_types(arg))
    elif origin in (list, set, frozenset, tuple):
        for arg in get_args(annotation):
            results.extend(_extract_basemodel_types(arg))
    elif origin is dict:
        for arg in get_args(annotation):
            results.extend(_extract_basemodel_types(arg))
    else:
        for arg in get_args(annotation):
            results.extend(_extract_basemodel_types(arg))

    return results


def walk_model_graph(root: type[BaseModel]) -> dict[str, list[str]]:
    """Walk the model graph starting from root, collecting field orders."""
    result: dict[str, list[str]] = {}
    queue: list[type[BaseModel]] = [root]
    visited: set[str] = set()

    while queue:
        model = queue.pop(0)
        name = model.__name__
        if name in visited:
            continue
        visited.add(name)

        result[name] = list(model.model_fields.keys())

        for field_info in model.model_fields.values():
            nested = _extract_basemodel_types(field_info.annotation)
            for nested_model in nested:
                if nested_model.__name__ not in visited:
                    queue.append(nested_model)

    return result


def generate_field_order_json() -> str:
    """Generate the field order manifest as a JSON string."""
    manifest = walk_model_graph(DealDefinition)
    return json.dumps(manifest, indent=2) + "\n"


def main() -> int:
    check_mode = "--check" in sys.argv

    generated = generate_field_order_json()

    if check_mode:
        if not OUTPUT_PATH.exists():
            print(
                f"ERROR: field_order.json does not exist at {OUTPUT_PATH}",
                file=sys.stderr,
            )
            return 1

        on_disk = OUTPUT_PATH.read_text(encoding="utf-8")
        if on_disk == generated:
            print("OK: field_order.json is up to date.")
            return 0
        else:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tmp:
                tmp.write(generated)
                tmp_path = tmp.name
            print(
                f"ERROR: field order drift detected. "
                f"Committed file does not match generated output.\n"
                f"Regenerate with: python scripts/emit_field_order.py\n"
                f"Generated (temp): {tmp_path}",
                file=sys.stderr,
            )
            return 1
    else:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(generated, encoding="utf-8")
        print(f"Wrote {OUTPUT_PATH}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
