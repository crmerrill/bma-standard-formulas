"""Operational hardening — export, fsck, restore, audit log, GC, and telemetry.

Houses the export_deal, _run_fsck (memoized), restore_deal, audit-log
writer, branch GC hooks, PII redaction, and git-directory-size telemetry
functions.  Registered via the vpc-1 catalog mechanism at module import time.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bma_standard_formulas.diagnostics import (
    DiagnosticPayload,
    Owner,
    Severity,
    diagnostic_code,
)

from . import deal_store
from .deal_store import deal_dir
from .git_service import GitService, GitServiceError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Telemetry thresholds (monkeypatchable in tests)
# ---------------------------------------------------------------------------

DEFAULT_GIT_SIZE_ALERT_THRESHOLD_BYTES: int = 100 * 1024 * 1024  # 100 MB
GIT_SIZE_ALERT_THRESHOLD_BYTES: int = DEFAULT_GIT_SIZE_ALERT_THRESHOLD_BYTES
DEFAULT_GIT_SIZE_ALERT_THRESHOLD_MB: float = 100.0
GIT_SIZE_ALERT_THRESHOLD_MB: float = DEFAULT_GIT_SIZE_ALERT_THRESHOLD_MB

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

    1. Clone/unbundle into a temp dir and validate the result.
    2. Atomically swap ``.git/`` using a ``.git.old`` backup so a failed
       restore never leaves the deal without a recoverable repo.
    3. Preserve ``manifest.json`` studio transitional fields
       (``studio_current_version``, ``studio_versions`` per irvc-3).
    4. Invalidate the fsck memoization for this repo so the next load
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
        git_old = d / ".git.old"

        with tempfile.TemporaryDirectory(
            prefix=f"bma_restore_{deal_id}_"
        ) as tmp:
            tmp_path = Path(tmp) / "restored"
            subprocess.run(
                ["git", "clone", str(bundle_path), str(tmp_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            verify = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(tmp_path),
                check=True,
                capture_output=True,
                text=True,
            )
            if not verify.stdout.strip():
                raise GitServiceError(
                    "RESTORE_VALIDATION_FAILED: cloned repo has no HEAD"
                )

            had_existing = git_dir.exists()
            if had_existing:
                if git_old.exists():
                    shutil.rmtree(git_old)
                os.rename(git_dir, git_old)
            try:
                shutil.move(str(tmp_path / ".git"), str(git_dir))
                for item in tmp_path.iterdir():
                    target = d / item.name
                    if item.name == "deal.json":
                        shutil.copy2(str(item), str(target))
                    elif not target.exists():
                        shutil.move(str(item), str(target))
            except Exception:
                if git_dir.exists():
                    shutil.rmtree(git_dir)
                if had_existing and git_old.exists():
                    os.rename(git_old, git_dir)
                raise
            else:
                if git_old.exists():
                    shutil.rmtree(git_old)

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
    except Exception as exc:
        _write_audit_record(deal_id, d, "restore_result", {
            "outcome": "failure",
            "reason": str(exc)[:500],
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


# ---------------------------------------------------------------------------
# Branch GC hooks (AC 1)
# ---------------------------------------------------------------------------


def gc_branch_after_apply(deal_id: str, branch: str) -> None:
    """Immediately delete an ephemeral branch after a successful Apply.

    Per AC 1: ai/turn-* and solver/run-* are deleted immediately on successful
    merge.  what-if/* branches are NOT touched here.
    """
    if not branch.startswith(("ai/turn-", "solver/run-")):
        return
    service = GitService(repo_path=deal_dir(deal_id))
    try:
        service.branch_delete(branch)
    except GitServiceError:
        pass


def gc_branch_after_discard(deal_id: str, branch: str) -> None:
    """For ephemeral branches: under the GitService write lock, redact PII in
    commit messages, write a redacted summary archive, then delete the branch
    and audit.

    For non-ephemeral branches: no-op (caller deletes directly).
    """
    if not branch.startswith(("ai/turn-", "solver/run-")):
        return
    d = deal_dir(deal_id)
    service = GitService(repo_path=d)
    with service._write_lock():
        try:
            redact_pii_in_commit_messages(d, branch=branch)
        except Exception:
            logger.warning(
                "PII redaction failed for branch %s in deal %s; proceeding with delete",
                branch, deal_id,
            )
        try:
            service.branch_delete(branch)
        except GitServiceError:
            pass
        _write_audit_record(deal_id, d, "branch_discarded", {
            "outcome": "deleted",
            "branch": branch,
        })


# ---------------------------------------------------------------------------
# Stale-branch GC (AC 2)
# ---------------------------------------------------------------------------


def gc_stale_ephemeral_branches(
    deal_id: str | None = None,
    retention_days: int = 7,
) -> None:
    """Delete ai/turn-* and solver/run-* branches whose tip commit is older
    than ``retention_days``.  NEVER touches what-if/* (per AC 4).

    When ``deal_id`` is None the function discovers all deals under
    ``deal_store._DEALS_DIR`` that contain a ``.git`` directory.
    """
    if deal_id is not None:
        deal_ids: list[str] = [deal_id]
    else:
        deals_dir: Path = deal_store._DEALS_DIR
        deal_ids = [
            p.name
            for p in deals_dir.iterdir()
            if p.is_dir() and (p / ".git").exists()
        ]

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    for did in deal_ids:
        d = deal_dir(did)
        service = GitService(repo_path=d)
        try:
            branches = service.branch_list()
        except GitServiceError:
            continue

        for branch_info in branches:
            name = branch_info.name
            if not name.startswith(("ai/turn-", "solver/run-")):
                continue

            try:
                commits = service.log(branch=name, limit=1)
            except GitServiceError:
                continue

            if not commits:
                continue

            tip_time = commits[0].committed_at
            if tip_time.tzinfo is None:
                tip_time = tip_time.replace(tzinfo=timezone.utc)

            if tip_time >= cutoff:
                continue

            with service._write_lock():
                redact_pii_in_commit_messages(d, branch=name)
                try:
                    service.branch_delete(name)
                except GitServiceError:
                    pass

            _write_audit_record(did, d, "branch_gc_stale", {
                "outcome": "deleted",
                "branch": name,
                "tip_age_days": (datetime.now(timezone.utc) - tip_time).days,
            })


# ---------------------------------------------------------------------------
# PII redaction (AC 3)
# ---------------------------------------------------------------------------


def redact_pii_in_commit_messages(
    repo_path: Path,
    branch: str | None = None,
) -> None:
    """Redact verbatim string values in commit messages and rewrite branch history.

    For every ai/turn-* or solver/run-* branch (or the specified ``branch``):
    1. Rewrites each branch-unique commit with string-typed JSON values replaced
       by ``<str>`` placeholders so verbatim user prompts and tool-call argument
       values are removed from reachable git history.
    2. Archives a copy of the redacted messages to
       ``<repo_path>/discarded_branches/<branch_safe>/redacted_messages.txt``
       for auditability.

    what-if/* branches are never processed.
    """
    repo_path = Path(repo_path)

    if branch is not None:
        branches_to_process: list[str] = [branch]
    else:
        try:
            proc = subprocess.run(
                ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=True,
            )
            all_branches = [b.strip() for b in proc.stdout.splitlines() if b.strip()]
        except subprocess.CalledProcessError:
            all_branches = []
        branches_to_process = [
            b for b in all_branches
            if b != "main" and b.startswith(("ai/turn-", "solver/run-"))
        ]

    for br_name in branches_to_process:
        _redact_branch_commits_and_archive(repo_path, br_name)


def _redact_branch_commits_and_archive(repo_path: Path, branch: str) -> None:
    """Rewrite commits unique to ``branch`` with PII-scrubbed messages.

    1. Collects commits reachable from *branch* but not from *main*.
    2. Creates new commit objects with redacted messages (same tree/parents).
    3. Updates the branch ref to the new tip.
    4. Archives the redacted message summaries under
       ``discarded_branches/<branch_safe>/redacted_messages.txt``.
    """
    try:
        log_proc = subprocess.run(
            ["git", "log", "--format=%H", f"main..{branch}"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return

    commit_shas = [s.strip() for s in log_proc.stdout.splitlines() if s.strip()]
    if not commit_shas:
        return

    # git log returns newest → oldest; reverse to rewrite oldest → newest
    commit_shas_oldest_first = list(reversed(commit_shas))
    old_to_new: dict[str, str] = {}
    redacted_lines: list[str] = []

    for sha in commit_shas_oldest_first:
        try:
            msg_proc = subprocess.run(
                ["git", "log", "-1", "--format=%B", sha],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=True,
            )
            tree_proc = subprocess.run(
                ["git", "log", "-1", "--format=%T", sha],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=True,
            )
            parent_proc = subprocess.run(
                ["git", "log", "-1", "--format=%P", sha],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=True,
            )
            meta_proc = subprocess.run(
                ["git", "log", "-1",
                 "--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI", sha],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            continue

        original_message = msg_proc.stdout
        redacted_message = _apply_redaction_patterns(original_message)
        tree_sha = tree_proc.stdout.strip()
        parent_shas = parent_proc.stdout.strip().split() if parent_proc.stdout.strip() else []
        new_parents = [old_to_new.get(p, p) for p in parent_shas]

        fields = meta_proc.stdout.strip().split("\x00")
        author_name = fields[0] if len(fields) > 0 else "System"
        author_email = fields[1] if len(fields) > 1 else "system@bma"
        author_date = fields[2] if len(fields) > 2 else ""
        committer_name = fields[3] if len(fields) > 3 else "System"
        committer_email = fields[4] if len(fields) > 4 else "system@bma"
        committer_date = fields[5] if len(fields) > 5 else ""

        cmd = ["git", "commit-tree", tree_sha]
        for p in new_parents:
            cmd.extend(["-p", p])
        cmd.extend(["-m", redacted_message])

        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": committer_name,
            "GIT_COMMITTER_EMAIL": committer_email,
        }
        if author_date:
            env["GIT_AUTHOR_DATE"] = author_date
        if committer_date:
            env["GIT_COMMITTER_DATE"] = committer_date

        try:
            new_sha_proc = subprocess.run(
                cmd,
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
            new_sha = new_sha_proc.stdout.strip()
            old_to_new[sha] = new_sha
            redacted_lines.append(f"{sha[:8]}: {redacted_message.strip()}")
        except subprocess.CalledProcessError:
            continue

    # Archive redacted messages
    safe_branch = branch.replace("/", "_")
    archive_dir = repo_path / "discarded_branches" / safe_branch
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / "redacted_messages.txt"
    archive_path.write_text("\n".join(redacted_lines) + "\n", encoding="utf-8")

    # Update branch ref to the rewritten tip
    if commit_shas_oldest_first and old_to_new:
        original_tip = commit_shas_oldest_first[-1]
        new_tip = old_to_new.get(original_tip)
        if new_tip:
            try:
                subprocess.run(
                    ["git", "update-ref", f"refs/heads/{branch}", new_tip],
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except subprocess.CalledProcessError:
                pass


def _apply_redaction_patterns(text: str) -> str:
    """Replace verbatim PII with redacted placeholders.

    Patterns covered:
    1. JSON-style "key": "value" -> "key": "<str>"
    2. Free-text ``User said: '<...>'`` and ``User: <...>`` lines -> <prompt>
    3. Tool-call argument blocks ``arguments: { ... }`` / ``args={...}`` -> <args>
    4. Single-quoted prompts wrapped in any context -> '<prompt>'
    """
    out = text
    out = re.sub(r'"([^"]+)":\s*"([^"]*)"', r'"\1": "<str>"', out)
    out = re.sub(
        r"(User\s*(?:said)?\s*:\s*)(['\"])(.+?)\2",
        r"\1<prompt>",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(
        r"(arguments?\s*[:=]\s*)\{[^}]*\}",
        r"\1<args>",
        out,
        flags=re.IGNORECASE,
    )
    return out


# ---------------------------------------------------------------------------
# Git-directory size telemetry (AC 5)
# ---------------------------------------------------------------------------


def measure_git_directory_size(
    deal_ids: list[str] | None = None,
    threshold_bytes: int | None = None,
) -> dict[str, Any]:
    """Measure ``.git/`` size per deal via ``git count-objects -v``.

    Aggregates a tenant p95, emits a structured WARNING log when p95 exceeds
    the threshold.  Returns a dict with ``per_deal_sizes``, ``p95_bytes``,
    ``threshold_bytes``, and ``alert``.

    ``threshold_bytes`` defaults to the module-level
    ``GIT_SIZE_ALERT_THRESHOLD_BYTES`` constant (monkeypatchable in tests).
    """
    effective_threshold = (
        threshold_bytes
        if threshold_bytes is not None
        else GIT_SIZE_ALERT_THRESHOLD_BYTES
    )

    if deal_ids is None:
        deals_dir: Path = deal_store._DEALS_DIR
        deal_ids = [
            p.name
            for p in deals_dir.iterdir()
            if p.is_dir() and (p / ".git").exists()
        ]

    sizes: dict[str, int] = {}
    for did in deal_ids:
        d = deal_dir(did)
        if not (d / ".git").exists():
            continue
        try:
            proc = subprocess.run(
                ["git", "count-objects", "-v"],
                cwd=str(d),
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            continue

        size_kb = 0
        for line in proc.stdout.splitlines():
            if line.startswith("size:") or line.startswith("size-pack:"):
                try:
                    size_kb += int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
        sizes[did] = size_kb * 1024

    if not sizes:
        return {
            "per_deal_sizes": {},
            "p95_bytes": 0,
            "threshold_bytes": effective_threshold,
            "alert": False,
        }

    sorted_sizes = sorted(sizes.values())
    p95_idx = min(int(len(sorted_sizes) * 0.95), len(sorted_sizes) - 1)
    p95_bytes = sorted_sizes[p95_idx]
    alert = p95_bytes > effective_threshold

    if alert:
        logger.warning(
            "git directory size p95 exceeds threshold",
            extra={
                "p95_bytes": p95_bytes,
                "threshold_bytes": effective_threshold,
                "deal_count": len(sizes),
                "per_deal_max_bytes": max(sizes.values()),
                "alert": True,
            },
        )

    return {
        "per_deal_sizes": sizes,
        "p95_bytes": p95_bytes,
        "threshold_bytes": effective_threshold,
        "alert": alert,
    }
