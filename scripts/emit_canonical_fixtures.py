"""Emit canonical JSON artifacts for all test fixtures.

For each fixture directory under tests/fixtures/:
  - If deal_definition.py exists: instantiate the DealDefinition,
    emit deal.json (model_dump_json) AND deal.canonical.json
    (post-migration model_dump_json).
  - If deal.json already exists (no builder): keep deal.json as-is,
    emit deal.canonical.json (post-migration form).

Usage:
    python scripts/emit_canonical_fixtures.py           # write mode
    python scripts/emit_canonical_fixtures.py --check   # drift guard (CI)
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from bma_standard_formulas.deals.schemas.ir import DealDefinition
from bma_standard_formulas.deals.schemas.migrations import migrate_deal_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_ROOT = REPO_ROOT / "tests" / "fixtures"


def _load_deal_from_builder(builder_path: Path) -> DealDefinition:
    """Dynamically load a deal_definition.py and return its DealDefinition."""
    fixture_dir = builder_path.parent
    fixtures_root = fixture_dir.parent

    # Ensure the fixtures root is on sys.path so the fixture package
    # (which may use relative imports, e.g. fnr_2006_018) resolves.
    root_str = str(fixtures_root)
    added_to_path = False
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
        added_to_path = True

    try:
        package_name = fixture_dir.name
        # Import the package first (loads __init__.py), then the module.
        importlib.import_module(package_name)
        module = importlib.import_module(f"{package_name}.deal_definition")
    finally:
        if added_to_path:
            sys.path.remove(root_str)

    deal = getattr(module, "deal_definition", None)
    if not isinstance(deal, DealDefinition):
        raise RuntimeError(
            f"{builder_path} must export 'deal_definition' as a DealDefinition instance"
        )
    return deal


def _canonical_bytes(deal_json_bytes: bytes) -> bytes:
    raw = json.loads(deal_json_bytes.decode("utf-8"))
    migrated = migrate_deal_payload(raw)
    revalidated = DealDefinition.model_validate(migrated)
    return revalidated.model_dump_json(indent=2).encode("utf-8")


def emit_canonical_fixtures(
    fixtures_root: Path = FIXTURES_ROOT,
    check: bool = False,
) -> None:
    """Emit deal.json and deal.canonical.json for every fixture directory."""
    errors: list[str] = []

    for fixture_dir in sorted(fixtures_root.iterdir()):
        if not fixture_dir.is_dir():
            continue

        builder_path = fixture_dir / "deal_definition.py"
        deal_json_path = fixture_dir / "deal.json"
        canonical_path = fixture_dir / "deal.canonical.json"

        has_builder = builder_path.exists()
        has_deal_json = deal_json_path.exists()

        if not has_builder and not has_deal_json:
            continue

        if has_builder:
            deal = _load_deal_from_builder(builder_path)
            deal_json_bytes = deal.model_dump_json(indent=2).encode("utf-8")
        else:
            deal_json_bytes = deal_json_path.read_bytes()

        canonical_bytes = _canonical_bytes(deal_json_bytes)

        if check:
            if has_builder:
                if deal_json_path.exists():
                    if deal_json_path.read_bytes() != deal_json_bytes:
                        errors.append(f"{fixture_dir.name}/deal.json: drift detected")
                else:
                    errors.append(f"{fixture_dir.name}/deal.json: missing")
            if canonical_path.exists():
                if canonical_path.read_bytes() != canonical_bytes:
                    errors.append(f"{fixture_dir.name}/deal.canonical.json: drift detected")
            else:
                errors.append(f"{fixture_dir.name}/deal.canonical.json: missing")
        else:
            if has_builder:
                deal_json_path.write_bytes(deal_json_bytes)
            canonical_path.write_bytes(canonical_bytes)

    if check and errors:
        msg = "Canonical fixture drift detected:\n" + "\n".join(f"  - {e}" for e in errors)
        print(msg, file=sys.stderr)
        raise RuntimeError(msg)


def assert_fixture_count_parity(fixtures_root: Path = FIXTURES_ROOT) -> None:
    """Assert every deal.json has a matching deal.canonical.json."""
    deal_dirs = {p.parent.name for p in fixtures_root.glob("*/deal.json")}
    canonical_dirs = {p.parent.name for p in fixtures_root.glob("*/deal.canonical.json")}
    missing = deal_dirs - canonical_dirs
    if missing:
        raise AssertionError(
            f"Fixtures with deal.json but missing deal.canonical.json: {sorted(missing)}"
        )


def main() -> int:
    check = "--check" in sys.argv
    try:
        emit_canonical_fixtures(check=check)
        if check:
            print("OK: canonical fixtures are up to date.")
        else:
            print("Canonical fixtures emitted successfully.")
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
