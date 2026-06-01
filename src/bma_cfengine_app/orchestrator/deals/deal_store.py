"""Deal definition persistence — git-backed canonical storage with legacy migration.

Canonical deal persistence uses a GitService-backed git repository in each
deal directory. On first open of a legacy deal (containing v{N}.json files),
an idempotent migration runs: git init + one commit per legacy version with
author "system:migration" in version order + manifest collapse.

Studio IR snapshots (studio_v{N}.json) and solver presets continue to operate
on flat files in the deal directory and are NOT routed through git; that
transition belongs to studio-document-persistence-and-migration.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bma_standard_formulas.deals.schemas.ir import DealDefinition
from bma_standard_formulas.deals.schemas.migrations import migrate_deal_payload

from ...storage.run_store import APP_HOME
from .git_service import GitService

_DEALS_DIR = APP_HOME / "deals"
_POOLS_DIR = APP_HOME / "pools"


def init_deals_workspace() -> Path:
    _DEALS_DIR.mkdir(parents=True, exist_ok=True)
    _POOLS_DIR.mkdir(parents=True, exist_ok=True)
    return _DEALS_DIR


def new_deal_id() -> str:
    return f"deal_{uuid.uuid4().hex[:12]}"


def new_pool_id() -> str:
    return f"pool_{uuid.uuid4().hex[:12]}"


def deal_dir(deal_id: str) -> Path:
    p = _DEALS_DIR / deal_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def pool_dir(pool_id: str) -> Path:
    p = _POOLS_DIR / pool_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _compute_checksum(deal_json: str) -> str:
    return hashlib.sha256(deal_json.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Migration lock (M2 fix: wrap entire first-open migration atomically)
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _migration_lock(deal_dir: Path, timeout_s: float = 30.0):  # type: ignore[return]
    """Per-deal-dir advisory lock that wraps the entire migration (init + commits +
    manifest collapse). Bounded retry; raises TimeoutError if not acquired within timeout.
    """
    deal_dir.mkdir(parents=True, exist_ok=True)
    lock_path = deal_dir / ".bma_migration.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"MIGRATION_LOCK_TIMEOUT: could not acquire migration lock at "
                        f"{lock_path} within {timeout_s}s"
                    )
                time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


# ---------------------------------------------------------------------------
# Legacy migration helpers
# ---------------------------------------------------------------------------


def _has_legacy_snapshots(d: Path) -> bool:
    """Return True if the deal directory contains any v{N}.json files."""
    return any(
        p
        for p in d.iterdir()
        if p.name.startswith("v") and p.name.endswith(".json") and p.stem[1:].isdigit()
    )


def _list_legacy_versions(d: Path) -> list[int]:
    """Return sorted list of legacy version integers found in the deal directory."""
    versions: list[int] = []
    for p in d.iterdir():
        if p.name.startswith("v") and p.name.endswith(".json") and p.stem[1:].isdigit():
            versions.append(int(p.stem[1:]))
    return sorted(versions)


def _git_init_main(d: Path) -> None:
    """Initialize a git repository with 'main' as the default branch."""
    subprocess.run(["git", "init", str(d)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(d), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True,
        capture_output=True,
    )


def _commit_count(deal_id: str) -> int:
    """Return the total number of commits on main in the git-backed deal repo."""
    d = deal_dir(deal_id)
    try:
        result = subprocess.run(
            ["git", "-C", str(d), "rev-list", "--count", "main"],
            check=True,
            capture_output=True,
            text=True,
        )
        return int(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return 0


def _migrate_legacy_to_git(deal_id: str) -> None:
    """Idempotent: migrate legacy v{N}.json files into a linear git history.

    Creates one commit per legacy version in ascending order. Each payload is
    passed through migrate_deal_payload before landing in the commit so the
    canonical history starts at schema-current.

    The entire sequence (git init + commits + manifest collapse) is wrapped in
    a per-deal-dir advisory lock so concurrent first-opens serialize cleanly
    and produce exactly one migration commit chain.
    """
    d = deal_dir(deal_id)
    if (d / ".git").exists():
        return  # fast path: no lock needed

    with _migration_lock(d):
        # Double-check inside the lock (another process may have migrated while
        # we were waiting).
        if (d / ".git").exists():
            return

        legacy_versions = _list_legacy_versions(d)
        if not legacy_versions:
            return

        _git_init_main(d)
        service = GitService(repo_path=d, _verified_clean=True)
        parent_sha: str | None = None

        for v in legacy_versions:
            legacy_path = d / f"v{v}.json"
            legacy_payload = json.loads(legacy_path.read_text(encoding="utf-8"))
            canonical_payload = migrate_deal_payload(legacy_payload)
            canonical_bytes = json.dumps(canonical_payload, indent=2, sort_keys=True).encode("utf-8")
            parent_sha = service.commit_deal(
                canonical_bytes,
                author="system:migration <migration@bma>",
                message=f"Migrate v{v}",
                parent_sha=parent_sha,
            )

        _collapse_manifest_post_migration(deal_id)


def _collapse_manifest_post_migration(deal_id: str) -> None:
    """Rewrite manifest.json to the AC-3 allowed field set after git migration."""
    d = deal_dir(deal_id)
    manifest_path = d / "manifest.json"
    legacy: dict[str, Any] = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )

    service = GitService(repo_path=d)
    commits = service.log(branch="main", limit=1)
    if commits:
        raw = service.show(commits[0].sha, "deal.json")
        final_payload: dict[str, Any] = json.loads(raw)
    else:
        final_payload = {}

    new_manifest: dict[str, Any] = {
        "deal_id": deal_id,
        "deal_name": final_payload.get("deal_name") or legacy.get("deal_name", ""),
        "asset_class": final_payload.get("asset_class") or legacy.get("asset_class"),
        "schema_version_pin": final_payload.get("schema_version") or legacy.get("schema_version_pin"),
        "created_at": legacy.get("created_at") or datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        # FUTURE: studio-document-persistence-and-migration — migrate these transitional fields out
        "studio_current_version": legacy.get("studio_current_version", 0),
        "studio_versions": legacy.get("studio_versions", []),
    }
    manifest_path.write_text(json.dumps(new_manifest, indent=2))


# ---------------------------------------------------------------------------
# Git-backed load helper
# ---------------------------------------------------------------------------


def _resolve_version_to_sha(service: GitService, version: int | None) -> str | None:
    """Map a 1-indexed version number to the corresponding commit SHA.

    Version 1 = oldest commit (the bottom of the linear chain).
    Version N = the Nth commit from the bottom.
    Version None = HEAD (latest commit).

    Returns None if the repo has no commits or the requested version is out
    of range.
    """
    commits = service.log(branch="main", limit=10000)  # newest-first
    if not commits:
        return None
    if version is None:
        return commits[0].sha  # HEAD
    if version < 1 or version > len(commits):
        return None
    # commits is newest-first; version is 1-indexed from oldest.
    # version=1 -> commits[-1] (oldest); version=len -> commits[0] (newest).
    return commits[len(commits) - version].sha


def _load_from_git(deal_id: str, version: int | None = None) -> DealDefinition | None:
    """Load a deal definition from the git-backed repo."""
    d = deal_dir(deal_id)
    service = GitService(repo_path=d)

    sha = _resolve_version_to_sha(service, version)
    if sha is None:
        return None

    raw = service.show(sha, "deal.json")
    payload = json.loads(raw)
    payload = migrate_deal_payload(payload)
    return DealDefinition.model_validate(payload)


def _update_manifest_on_save(deal_id: str, deal: DealDefinition) -> None:
    """Update manifest after a git-backed save; preserves all existing fields."""
    d = deal_dir(deal_id)
    manifest_path = d / "manifest.json"
    if manifest_path.exists():
        manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {
            "deal_id": deal_id,
            "deal_name": deal.deal_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            # FUTURE: studio-document-persistence-and-migration — migrate these transitional fields out
            "studio_current_version": 0,
            "studio_versions": [],
        }
    manifest["deal_name"] = deal.deal_name
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    manifest["schema_version_pin"] = deal.schema_version
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))


# ---------------------------------------------------------------------------
# Public API: save_deal / load_deal
# ---------------------------------------------------------------------------


def _fsck_guard(d: Path) -> None:
    """Run operational._run_fsck at most once per absolute repo path per process."""
    from . import operational

    abs_path = str(d.resolve())
    if abs_path not in operational._FSCK_VERIFIED_REPOS:
        operational._run_fsck(d)
        operational._FSCK_VERIFIED_REPOS.add(abs_path)


def save_deal(
    deal_id: str,
    deal: DealDefinition,
    version: int | None = None,
) -> dict[str, Any]:
    """Persist a deal definition via GitService.

    Returns a dict with the commit SHA and version count.
    """
    d = deal_dir(deal_id)

    if (d / ".git").exists():
        _fsck_guard(d)

    if not (d / ".git").exists() and _has_legacy_snapshots(d):
        _migrate_legacy_to_git(deal_id)

    freshly_created = False
    if not (d / ".git").exists():
        _git_init_main(d)
        freshly_created = True

    service = GitService(repo_path=d, _verified_clean=freshly_created)
    head_commits = service.log(branch="main", limit=1)
    parent_sha: str | None = head_commits[0].sha if head_commits else None

    payload_bytes = deal.model_dump_json(indent=2).encode("utf-8")
    new_sha = service.commit_deal(
        payload_bytes,
        author="system:user <user@bma>",
        message=f"Save deal {deal.deal_name}",
        parent_sha=parent_sha,
    )

    _update_manifest_on_save(deal_id, deal)
    return {"sha": new_sha, "version": _commit_count(deal_id)}


def load_deal(deal_id: str, version: int | None = None) -> DealDefinition | None:
    """Load a deal definition; triggers legacy migration on first open.

    Migration is idempotent: skipped if .git/ already exists.
    Falls back to legacy flat-file behavior for deals without legacy snapshots.
    """
    d = deal_dir(deal_id)

    if not (d / ".git").exists() and _has_legacy_snapshots(d):
        _migrate_legacy_to_git(deal_id)

    if (d / ".git").exists():
        _fsck_guard(d)
        return _load_from_git(deal_id, version=version)

    return _load_legacy(deal_id, version=version)


def _load_legacy(deal_id: str, version: int | None = None) -> DealDefinition | None:
    """Legacy flat-file load path for deals with no git repo and no legacy snapshots."""
    d = deal_dir(deal_id)
    manifest_path = d / "manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(f"No deal found with ID {deal_id}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target_version = version or manifest.get("current_version", 1)

    version_file = d / f"v{target_version}.json"
    if not version_file.exists():
        raise FileNotFoundError(
            f"Version {target_version} not found for deal {deal_id}"
        )

    payload = json.loads(version_file.read_text(encoding="utf-8"))
    return DealDefinition.model_validate(migrate_deal_payload(payload))


def load_deal_manifest(deal_id: str) -> dict[str, Any]:
    d = deal_dir(deal_id)
    manifest_path = d / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No deal found with ID {deal_id}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


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
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
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
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
    if (d / ".git").exists():
        _fsck_guard(d)
    manifest_path = d / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No deal {deal_id!r}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ver = version if version is not None else int(
        manifest.get("studio_current_version", 0) or 0
    )
    if ver < 1:
        raise FileNotFoundError(f"No Structuring Studio snapshots for {deal_id!r}")
    path = d / f"studio_v{ver}.json"
    if not path.exists():
        raise FileNotFoundError(f"studio_v{ver}.json not found for {deal_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


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
            m = json.loads(mp.read_text(encoding="utf-8"))
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
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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


# ---------------------------------------------------------------------------
# Tape/Pool registry — versioned named pool snapshots
# ---------------------------------------------------------------------------


def save_pool_snapshot(
    pool_id: str | None,
    pool_name: str,
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    init_deals_workspace()
    pid = pool_id or new_pool_id()
    d = pool_dir(pid)
    manifest_path = d / "manifest.json"
    now = datetime.now(timezone.utc).isoformat()

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"pool_id": pid, "pool_name": pool_name, "created_at": now}

    manifest["pool_id"] = pid
    manifest["pool_name"] = pool_name
    manifest["updated_at"] = now
    cur = int(manifest.get("current_version", 0) or 0)
    new_ver = cur + 1
    manifest["current_version"] = new_ver
    manifest.setdefault("versions", []).append({"version": new_ver, "created_at": now})

    body = {
        "pool_id": pid,
        "pool_name": pool_name,
        "saved_at": now,
        "version": new_ver,
        "payload": payload,
    }
    (d / f"v{new_ver}.json").write_text(json.dumps(body, indent=2, default=str))
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    return pid, {"pool_id": pid, "pool_name": pool_name, "version": new_ver, "saved_at": now}


def load_pool_snapshot(pool_id: str, version: int | None = None) -> dict[str, Any]:
    d = pool_dir(pool_id)
    manifest_path = d / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No pool {pool_id!r}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ver = version if version is not None else int(manifest.get("current_version", 0) or 0)
    if ver < 1:
        raise FileNotFoundError(f"No versions found for pool {pool_id!r}")
    path = d / f"v{ver}.json"
    if not path.exists():
        raise FileNotFoundError(f"v{ver}.json not found for pool {pool_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_pool_snapshots(search: str | None = None) -> list[dict[str, Any]]:
    init_deals_workspace()
    out: list[dict[str, Any]] = []
    if not _POOLS_DIR.exists():
        return out
    needle = (search or "").strip().lower()
    for sub in sorted(_POOLS_DIR.iterdir(), key=lambda p: p.name):
        if not sub.is_dir() or not sub.name.startswith("pool_"):
            continue
        mp = sub / "manifest.json"
        if not mp.exists():
            continue
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        row = {
            "pool_id": m.get("pool_id", sub.name),
            "pool_name": m.get("pool_name", ""),
            "current_version": int(m.get("current_version", 0) or 0),
            "updated_at": m.get("updated_at", m.get("created_at", "")),
            "created_at": m.get("created_at", ""),
        }
        if needle and needle not in f"{row['pool_name']} {row['pool_id']}".lower():
            continue
        out.append(row)
    out.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
    return out
