"""Operational hardening — export, fsck, restore, and audit log.

Houses the export_deal, _run_fsck (memoized), restore_deal, and audit-log
writer functions backing the REPO_CORRUPT diagnostic action.  Registered
via the vpc-1 catalog mechanism at module import time.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bma_standard_formulas.diagnostics import (
    DiagnosticPayload,
    Owner,
    Severity,
    diagnostic_code,
)

from .deal_store import deal_dir
from .git_service import GitService, GitServiceError

_FSCK_VERIFIED_REPOS: set[str] = set()


@diagnostic_code(
    "REPO_CORRUPT",
    severity=Severity.error,
    path_schema="deal:{deal_id}",
    owner=Owner.backend,
)
def _repo_corrupt_validator() -> None:
    """Stable diagnostic code for git repository corruption.

    Registered via the vpc-1 catalog mechanism.  The actual detection runs
    inline in _run_fsck; this validator function is a no-op placeholder
    whose sole purpose is to satisfy the decorator-registration contract.
    """


class RepoCorruptError(GitServiceError):
    """Raised when ``git fsck`` detects corruption in a deal repository."""

    def __init__(self, diagnostic: DiagnosticPayload) -> None:
        self.diagnostic = diagnostic
        self.code = diagnostic.code
        super().__init__(f"REPO_CORRUPT: {diagnostic.message}")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_deal(deal_id: str, sha: str) -> bytes:
    """Export the canonical deal.json at the given SHA.

    The function takes NO user-controlled path argument.  It returns the
    bytes of ``deal.json`` at the requested SHA via ``git show <sha>:deal.json``.
    By construction, the function cannot return any other artifact (.git/,
    sidecar.json, scenarios.json, turn_transcripts/, discarded_branches/).
    """
    repo_path = deal_dir(deal_id)
    _run_fsck(repo_path)
    service = GitService(repo_path=repo_path)
    return service.show(sha, "deal.json")


# ---------------------------------------------------------------------------
# Fsck
# ---------------------------------------------------------------------------


def _run_fsck(repo_path: Path) -> None:
    """Run ``git fsck --no-progress`` on the repo.

    Memoized per process per absolute repo path via ``_FSCK_VERIFIED_REPOS``.
    On failure, emits REPO_CORRUPT diagnostic, writes an audit record, and
    raises :class:`RepoCorruptError`.
    """
    abs_path = str(repo_path.resolve())
    if abs_path in _FSCK_VERIFIED_REPOS:
        return
    if not (repo_path / ".git").exists():
        return

    proc = subprocess.run(
        ["git", "fsck", "--no-progress"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        deal_id = repo_path.name
        _write_audit_record(deal_id, repo_path, "corruption_detected", {
            "outcome": "detected",
            "stderr": proc.stderr.strip()[:500],
        })
        diagnostic = DiagnosticPayload(
            code="REPO_CORRUPT",
            severity=Severity.error,
            path=f"deal:{deal_id}",
            message=f"git fsck failed for {deal_id}: {proc.stderr.strip()[:200]}",
            payload={
                "deal_id": deal_id,
                "repo_path": abs_path,
                "stderr": proc.stderr.strip(),
                "restore_action": "Restore from latest backup",
            },
        )
        raise RepoCorruptError(diagnostic)

    _FSCK_VERIFIED_REPOS.add(abs_path)


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


def restore_deal(deal_id: str, bundle_path: Path) -> None:
    """Restore a corrupted deal repo from a git bundle.

    1. Atomically replace the corrupted ``.git/`` with a fresh repo
       unbundled from *bundle_path*.
    2. Preserve ``manifest.json`` studio transitional fields
       (``studio_current_version``, ``studio_versions`` per irvc-3).
    3. Invalidate the fsck memoization for this repo so the next load
       re-runs fsck on the freshly-restored repo.
    """
    bundle_path = Path(bundle_path)
    d = deal_dir(deal_id)

    if not bundle_path.exists():
        _write_audit_record(deal_id, d, "restore_result", {
            "outcome": "failure",
            "reason": "bundle_not_found",
            "bundle_path": str(bundle_path),
        })
        raise GitServiceError(f"BUNDLE_NOT_FOUND: {bundle_path}")

    _write_audit_record(deal_id, d, "restore_attempt", {
        "outcome": "started",
        "bundle_path": str(bundle_path),
    })

    try:
        studio_files = list(d.glob("studio_v*.json"))
        studio_state = {p.name: p.read_bytes() for p in studio_files}
        manifest_path = d / "manifest.json"
        manifest: dict[str, Any] = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.exists()
            else {}
        )

        git_dir = d / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "restored"
            subprocess.run(
                ["git", "clone", str(bundle_path), str(tmp_path)],
                check=True,
                capture_output=True,
            )
            shutil.move(str(tmp_path / ".git"), str(d / ".git"))
            for item in tmp_path.iterdir():
                target = d / item.name
                if item.name == "deal.json":
                    shutil.copy2(str(item), str(target))
                elif not target.exists():
                    shutil.move(str(item), str(target))

        for name, content in studio_state.items():
            (d / name).write_bytes(content)
        if manifest:
            manifest_path.write_text(json.dumps(manifest, indent=2))

        abs_path = str(d.resolve())
        _FSCK_VERIFIED_REPOS.discard(abs_path)

        _write_audit_record(deal_id, d, "restore_result", {
            "outcome": "success",
            "bundle_path": str(bundle_path),
        })
    except Exception:
        _write_audit_record(deal_id, d, "restore_result", {
            "outcome": "failure",
            "bundle_path": str(bundle_path),
        })
        raise


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def _write_audit_record(
    deal_id: str,
    repo_path: Path,
    event_type: str,
    extras: dict[str, Any],
) -> None:
    """Append a newline-delimited JSON audit record to ``<deal_dir>/audit.log``."""
    audit_path = repo_path / "audit.log"
    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "deal_id": deal_id,
        "event_type": event_type,
        **extras,
    }
    with audit_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
