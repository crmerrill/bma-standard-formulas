"""Emit a field-order manifest for the DealDefinition Pydantic model graph.

Introspects DealDefinition and every nested BaseModel reachable via
model_fields annotations, then writes the declaration-order field list
with per-field type metadata for each model to a JSON file.

Usage:
    python scripts/emit_field_order.py           # write mode
    python scripts/emit_field_order.py --check   # drift guard (CI)
"""
from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

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


def _type_string(annotation: Any) -> str:
    """Convert a type annotation into a compact string discriminator.

    Supported output forms: str, int, float, bool, date, <ModelName>,
    list[X], Optional[X], dict[K, V], Union[X, Y, ...], Literal[...], Any.
    """
    if annotation is type(None):
        return "None"

    if isinstance(annotation, type):
        if issubclass(annotation, bool):
            return "bool"
        if issubclass(annotation, int):
            return "int"
        if issubclass(annotation, float):
            return "float"
        if issubclass(annotation, str):
            return "str"
        if issubclass(annotation, BaseModel):
            return annotation.__name__
        return annotation.__name__

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Annotated:
        if args:
            return _type_string(args[0])
        return "Any"

    if origin is Literal:
        return f"Literal[{', '.join(repr(a) for a in args)}]"

    if origin is Union or origin is types.UnionType:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and len(args) == 2:
            return f"Optional[{_type_string(non_none[0])}]"
        return f"Union[{', '.join(_type_string(a) for a in args)}]"

    if origin is list:
        if args:
            return f"list[{_type_string(args[0])}]"
        return "list"

    if origin is dict:
        if args and len(args) == 2:
            return f"dict[{_type_string(args[0])}, {_type_string(args[1])}]"
        return "dict"

    if origin is tuple:
        if args:
            return f"tuple[{', '.join(_type_string(a) for a in args)}]"
        return "tuple"

    if origin is set or origin is frozenset:
        if args:
            return f"set[{_type_string(args[0])}]"
        return "set"

    if args:
        return f"{origin}[{', '.join(_type_string(a) for a in args)}]"

    return str(annotation)


def _resolve_annotation(field_info: FieldInfo) -> str:
    """Resolve a Pydantic FieldInfo's annotation to a type string."""
    ann = field_info.annotation
    if ann is None:
        return "Any"
    return _type_string(ann)


def walk_model_graph(root: type[BaseModel]) -> dict[str, dict[str, Any]]:
    """Walk the model graph starting from root, collecting field orders and types."""
    result: dict[str, dict[str, Any]] = {}
    queue: list[type[BaseModel]] = [root]
    visited: set[str] = set()

    while queue:
        model = queue.pop(0)
        name = model.__name__
        if name in visited:
            continue
        visited.add(name)

        fields_list: list[dict[str, str]] = []
        for field_name, field_info in model.model_fields.items():
            type_str = _resolve_annotation(field_info)
            fields_list.append({"name": field_name, "type": type_str})

        result[name] = {"fields": fields_list}

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
