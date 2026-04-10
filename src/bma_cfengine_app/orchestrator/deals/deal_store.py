"""Deal definition persistence — versioned JSON storage alongside run artifacts.

Follows the same filesystem layout pattern as run_store.py but for deal
definitions (IR documents). Each deal gets a directory with versioned
JSON snapshots and a manifest tracking the version history.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bma_standard_formulas.deals.schemas.ir import DealDefinition

from ...storage.run_store import APP_HOME

_DEALS_DIR = APP_HOME / "deals"


def init_deals_workspace() -> Path:
    _DEALS_DIR.mkdir(parents=True, exist_ok=True)
    return _DEALS_DIR


def new_deal_id() -> str:
    return f"deal_{uuid.uuid4().hex[:12]}"


def deal_dir(deal_id: str) -> Path:
    p = _DEALS_DIR / deal_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _compute_checksum(deal_json: str) -> str:
    return hashlib.sha256(deal_json.encode()).hexdigest()[:16]


def save_deal(
    deal_id: str,
    deal: DealDefinition,
    version: int | None = None,
) -> dict[str, Any]:
    """Save a deal definition as a versioned JSON snapshot.

    Returns manifest metadata for the saved version.
    """
    d = deal_dir(deal_id)
    manifest_path = d / "manifest.json"

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        current_version = manifest.get("current_version", 0)
    else:
        manifest = {
            "deal_id": deal_id,
            "deal_name": deal.deal_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "current_version": 0,
            "versions": [],
        }
        current_version = 0

    new_version = version if version is not None else current_version + 1
    deal_json = deal.model_dump_json(indent=2)
    checksum = _compute_checksum(deal_json)

    version_file = d / f"v{new_version}.json"
    version_file.write_text(deal_json)

    version_entry = {
        "version": new_version,
        "schema_version": deal.schema_version,
        "checksum": checksum,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    manifest["current_version"] = new_version
    manifest["deal_name"] = deal.deal_name
    manifest["versions"].append(version_entry)
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

    return version_entry


def load_deal(deal_id: str, version: int | None = None) -> DealDefinition:
    """Load a deal definition by ID and optional version.

    If version is None, loads the latest version.
    """
    d = deal_dir(deal_id)
    manifest_path = d / "manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(f"No deal found with ID {deal_id}")

    manifest = json.loads(manifest_path.read_text())
    target_version = version or manifest.get("current_version", 1)

    version_file = d / f"v{target_version}.json"
    if not version_file.exists():
        raise FileNotFoundError(
            f"Version {target_version} not found for deal {deal_id}"
        )

    return DealDefinition.model_validate_json(version_file.read_text())


def load_deal_manifest(deal_id: str) -> dict[str, Any]:
    d = deal_dir(deal_id)
    manifest_path = d / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No deal found with ID {deal_id}")
    return json.loads(manifest_path.read_text())


def list_deals() -> list[dict[str, Any]]:
    """List all saved deals with summary metadata."""
    init_deals_workspace()
    results: list[dict[str, Any]] = []
    for d in _DEALS_DIR.iterdir():
        if not d.is_dir() or not d.name.startswith("deal_"):
            continue
        manifest_path = d / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            m = json.loads(manifest_path.read_text())
            results.append({
                "deal_id": d.name,
                "deal_name": m.get("deal_name", ""),
                "current_version": m.get("current_version", 0),
                "created_at": m.get("created_at", ""),
                "updated_at": m.get("updated_at", ""),
            })
        except Exception:
            pass
    results.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
    return results


# ---------------------------------------------------------------------------
# Structuring Studio — Blockly IR snapshots (no DealDefinition validation)
# ---------------------------------------------------------------------------


def save_studio_ir(
    deal_id: str | None,
    deal_name: str,
    ir: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Append a versioned studio JSON snapshot. Safe alongside canonical save_deal."""
    init_deals_workspace()
    did = deal_id or new_deal_id()
    d = deal_dir(did)
    manifest_path = d / "manifest.json"
    now = datetime.now(timezone.utc).isoformat()

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = {"deal_id": did, "deal_name": deal_name, "created_at": now}

    manifest["deal_id"] = did
    manifest["deal_name"] = deal_name
    manifest["updated_at"] = now

    cur = int(manifest.get("studio_current_version", 0) or 0)
    new_ver = cur + 1
    manifest["studio_current_version"] = new_ver
    manifest.setdefault("studio_versions", []).append(
        {"version": new_ver, "created_at": now}
    )

    payload = {
        "deal_id": did,
        "deal_name": deal_name,
        "schema_version": str(ir.get("schema_version", "studio")),
        "saved_at": now,
        "ir": ir,
    }
    (d / f"studio_v{new_ver}.json").write_text(
        json.dumps(payload, indent=2, default=str)
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

    meta = {
        "deal_id": did,
        "deal_name": deal_name,
        "version": new_ver,
        "created_at": now,
    }
    return did, meta


def load_studio_snapshot(deal_id: str, version: int | None = None) -> dict[str, Any]:
    d = deal_dir(deal_id)
    manifest_path = d / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No deal {deal_id!r}")
    manifest = json.loads(manifest_path.read_text())
    ver = version if version is not None else int(
        manifest.get("studio_current_version", 0) or 0
    )
    if ver < 1:
        raise FileNotFoundError(f"No Structuring Studio snapshots for {deal_id!r}")
    path = d / f"studio_v{ver}.json"
    if not path.exists():
        raise FileNotFoundError(f"studio_v{ver}.json not found for {deal_id!r}")
    return json.loads(path.read_text())


def list_studio_deals() -> list[dict[str, Any]]:
    init_deals_workspace()
    out: list[dict[str, Any]] = []
    if not _DEALS_DIR.exists():
        return out
    for sub in sorted(_DEALS_DIR.iterdir(), key=lambda p: p.name):
        if not sub.is_dir() or not sub.name.startswith("deal_"):
            continue
        mp = sub / "manifest.json"
        if not mp.exists():
            continue
        try:
            m = json.loads(mp.read_text())
        except Exception:
            continue
        ver = int(m.get("studio_current_version", 0) or 0)
        if ver < 1:
            continue
        out.append(
            {
                "deal_id": m.get("deal_id", sub.name),
                "deal_name": m.get("deal_name", ""),
                "current_version": ver,
                "updated_at": m.get("updated_at", m.get("created_at", "")),
            }
        )
    out.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
    return out


def list_solver_presets(deal_id: str) -> list[dict[str, Any]]:
    d = deal_dir(deal_id)
    manifest_path = d / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No deal {deal_id!r}")
    manifest = json.loads(manifest_path.read_text())
    presets = manifest.get("solver_presets_library", [])
    if not isinstance(presets, list):
        return []
    return presets


def save_solver_preset(
    deal_id: str,
    preset_name: str,
    solver_spec: dict[str, Any],
    notes: str | None = None,
) -> dict[str, Any]:
    d = deal_dir(deal_id)
    manifest_path = d / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No deal {deal_id!r}")
    manifest = json.loads(manifest_path.read_text())
    now = datetime.now(timezone.utc).isoformat()
    presets = manifest.get("solver_presets_library", [])
    if not isinstance(presets, list):
        presets = []

    existing_idx = None
    for i, preset in enumerate(presets):
        if isinstance(preset, dict) and preset.get("preset_name") == preset_name:
            existing_idx = i
            break
    payload = {
        "preset_name": preset_name,
        "solver_spec": solver_spec,
        "notes": notes or "",
        "updated_at": now,
    }
    if existing_idx is None:
        payload["created_at"] = now
        presets.append(payload)
    else:
        payload["created_at"] = presets[existing_idx].get("created_at", now)
        presets[existing_idx] = payload

    manifest["solver_presets_library"] = presets
    manifest["updated_at"] = now
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    return payload
