"""Core git service — pygit2 (fast path) with CLI subprocess fallback.

Wraps commit, branch, log, show, diff, and merge_base operations behind a
unified interface. Backend selection is automatic: pygit2 if importable,
otherwise shells out to the system git binary.
"""
from __future__ import annotations

import contextlib
import fcntl
import functools
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

try:
    import pygit2
except ImportError:
    pygit2 = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_NAMESPACES = ("ai/turn-", "solver/run-", "what-if/")

_INIT_FSCK_CHECKED: set[str] = set()


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class GitServiceError(Exception):
    pass


class LockTimeoutError(GitServiceError):
    def __init__(self, path: Path, timeout: float) -> None:
        super().__init__(
            f"LOCK_TIMEOUT: could not acquire write lock at {path} "
            f"within {timeout:.1f}s"
        )


class InvalidBranchNameError(GitServiceError):
    def __init__(self, name: str) -> None:
        super().__init__(f"INVALID_BRANCH_NAME: {name!r}")


class StaleParentShaError(GitServiceError):
    """Raised when parent_sha does not match the target branch's current tip."""

    def __init__(self, head_sha: str | None) -> None:
        super().__init__(f"STALE_PARENT_SHA: head_sha={head_sha}")
        self.head_sha = head_sha


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BranchInfo:
    name: str
    tip_sha: str

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


@dataclass(frozen=True)
class CommitMeta:
    sha: str
    author: str
    message: str
    parent_sha: str | None
    committed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


# ---------------------------------------------------------------------------
# GitService
# ---------------------------------------------------------------------------

def _wrap_pygit2(func):  # type: ignore[no-untyped-def]
    """Re-raise pygit2/lookup errors as GitServiceError; let GitServiceError subclasses through."""
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except GitServiceError:
            raise
        except Exception as exc:
            if pygit2 is not None and isinstance(exc, pygit2.GitError):
                raise GitServiceError(
                    f"{func.__name__}: {exc}"
                ) from exc
            if isinstance(exc, (KeyError, ValueError)):
                raise GitServiceError(
                    f"{func.__name__}: {exc}"
                ) from exc
            raise
    return wrapper


class GitService:
    def __init__(
        self,
        repo_path: Path,
        *,
        lock_timeout_s: float = 5.0,
        _verified_clean: bool = False,
    ) -> None:
        self._repo_path = Path(repo_path)
        self._lock_timeout_s = lock_timeout_s
        self._local = threading.local()
        if not _verified_clean and (self._repo_path / ".git").exists():
            self._fsck_on_init()

    def _fsck_on_init(self) -> None:
        """Run git fsck if this repo hasn't been verified by any path yet."""
        try:
            from .operational import _FSCK_VERIFIED_REPOS
        except ImportError:
            return
        abs_path = str(self._repo_path.resolve())
        if abs_path in _FSCK_VERIFIED_REPOS or abs_path in _INIT_FSCK_CHECKED:
            return
        proc = subprocess.run(
            ["git", "fsck", "--no-progress"],
            cwd=str(self._repo_path),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            try:
                from .operational import RepoCorruptError, _write_audit_record
                from bma_standard_formulas.diagnostics import (
                    DiagnosticPayload,
                    Severity,
                )
            except ImportError:
                raise GitServiceError(
                    f"git fsck failed: {proc.stderr.strip()[:200]}"
                )
            deal_id = self._repo_path.name
            _write_audit_record(deal_id, self._repo_path, "corruption_detected", {
                "outcome": "detected",
                "stderr": proc.stderr.strip()[:500],
            })
            diagnostic = DiagnosticPayload(
                code="REPO_CORRUPT",
                severity=Severity.error,
                path=f"deal:{deal_id}",
                message=(
                    f"git fsck failed for {deal_id}: "
                    f"{proc.stderr.strip()[:200]}"
                ),
                payload={
                    "deal_id": deal_id,
                    "repo_path": abs_path,
                    "stderr": proc.stderr.strip(),
                    "restore_action": "Restore from latest backup",
                },
            )
            raise RepoCorruptError(diagnostic)
        _INIT_FSCK_CHECKED.add(abs_path)

    @property
    def _use_pygit2(self) -> bool:
        return pygit2 is not None

    # -------------------------------------------------------------------
    # Locking
    # -------------------------------------------------------------------

    @contextlib.contextmanager
    def _write_lock(self) -> Generator[None, None, None]:
        # FUTURE: cross-host-locking — replace with distributed lock when multi-host backend lands
        counter: int = getattr(self._local, "lock_depth", 0)
        lock_path = self._repo_path / ".git" / "bma_write.lock"

        if counter == 0:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
            deadline = time.monotonic() + self._lock_timeout_s
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (OSError, BlockingIOError):
                    if time.monotonic() >= deadline:
                        os.close(fd)
                        raise LockTimeoutError(lock_path, self._lock_timeout_s)
                    time.sleep(0.05)
            self._local.lock_fd = fd

        self._local.lock_depth = counter + 1
        try:
            yield
        finally:
            self._local.lock_depth -= 1
            if self._local.lock_depth == 0:
                fd = getattr(self._local, "lock_fd", None)
                if fd is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
                    self._local.lock_fd = None

    # -------------------------------------------------------------------
    # Branch validation
    # -------------------------------------------------------------------

    def _validate_branch_name(self, name: str) -> None:
        if name == "main":
            return

        if not name or ".." in name or "\\" in name:
            raise InvalidBranchNameError(name)

        matched_ns = False
        for ns in _NAMESPACES:
            if name.startswith(ns):
                slug = name[len(ns):]
                if not slug or not _SLUG_RE.fullmatch(slug):
                    raise InvalidBranchNameError(name)
                matched_ns = True
                break

        if not matched_ns:
            raise InvalidBranchNameError(name)

    # -------------------------------------------------------------------
    # CLI subprocess helper
    # -------------------------------------------------------------------

    def _git_cli(
        self,
        *args: str,
        env: dict[str, str] | None = None,
        input: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=self._repo_path,
                check=True,
                capture_output=True,
                text=True,
                env=env,
                input=input,
            )
        except subprocess.CalledProcessError as exc:
            raise GitServiceError(
                f"git {' '.join(args)} failed (exit {exc.returncode}): "
                f"{exc.stderr.strip()}"
            ) from exc

    # -------------------------------------------------------------------
    # commit_deal
    # -------------------------------------------------------------------

    def commit_deal(
        self,
        deal_payload: dict[str, Any] | bytes,
        *,
        author: str,
        message: str,
        parent_sha: str | None = None,
        commit_target: str = "main",
        sidecar_payload: dict[str, Any] | bytes | None = None,
    ) -> str:
        self._validate_branch_name(commit_target)
        with self._write_lock():
            if self._use_pygit2:
                return self._commit_deal_pygit2(
                    deal_payload,
                    author=author,
                    message=message,
                    parent_sha=parent_sha,
                    commit_target=commit_target,
                    sidecar_payload=sidecar_payload,
                )
            return self._commit_deal_cli(
                deal_payload,
                author=author,
                message=message,
                parent_sha=parent_sha,
                commit_target=commit_target,
                sidecar_payload=sidecar_payload,
            )

    @_wrap_pygit2
    def _commit_deal_pygit2(
        self,
        deal_payload: dict[str, Any] | bytes,
        *,
        author: str,
        message: str,
        parent_sha: str | None,
        commit_target: str,
        sidecar_payload: dict[str, Any] | bytes | None = None,
    ) -> str:
        data = deal_payload if isinstance(deal_payload, bytes) else json.dumps(deal_payload, indent=2).encode("utf-8")
        sidecar_data: bytes | None = None
        if sidecar_payload is not None:
            if isinstance(sidecar_payload, bytes):
                sidecar_data = sidecar_payload
            else:
                from bma_standard_formulas.deals.schemas.studio_sidecar import StudioSidecar
                sidecar_data = StudioSidecar.model_validate(sidecar_payload).model_dump_json(indent=2).encode("utf-8")

        repo = pygit2.Repository(str(self._repo_path / ".git"))

        # Non-main branch: validate parent_sha against the target branch tip and always
        # advance the target ref directly (no is_fast_forward dance, no HEAD manipulation).
        if commit_target != "main":
            target_ref = repo.references.get(f"refs/heads/{commit_target}")
            target_tip = str(target_ref.peel().id) if target_ref is not None else None
            if target_tip != parent_sha:
                raise StaleParentShaError(head_sha=target_tip)

            blob_id = repo.create_blob(data)
            if parent_sha:
                tb = repo.TreeBuilder(repo.revparse_single(parent_sha).tree)
            else:
                tb = repo.TreeBuilder()
            tb.insert("deal.json", blob_id, pygit2.GIT_FILEMODE_BLOB)
            if sidecar_data is not None:
                sidecar_blob_id = repo.create_blob(sidecar_data)
                tb.insert("sidecar.json", sidecar_blob_id, pygit2.GIT_FILEMODE_BLOB)
            tree_id = tb.write()

            author_name, author_email = _parse_author(author)
            sig = pygit2.Signature(author_name, author_email)
            parents = [pygit2.Oid(hex=parent_sha)] if parent_sha else []

            commit_oid = repo.create_commit(
                f"refs/heads/{commit_target}",
                sig,
                sig,
                message,
                tree_id,
                parents,
            )
            return str(commit_oid)

        # Main branch: preserve the original is_fast_forward / set_head / working-tree behavior
        # exactly so that existing irvc-1 tests continue to pass without modification.
        blob_id = repo.create_blob(data)
        if parent_sha:
            tb = repo.TreeBuilder(repo.revparse_single(parent_sha).tree)
        else:
            tb = repo.TreeBuilder()
        tb.insert("deal.json", blob_id, pygit2.GIT_FILEMODE_BLOB)
        if sidecar_data is not None:
            sidecar_blob_id = repo.create_blob(sidecar_data)
            tb.insert("sidecar.json", sidecar_blob_id, pygit2.GIT_FILEMODE_BLOB)
        tree_id = tb.write()

        author_name, author_email = _parse_author(author)
        sig = pygit2.Signature(author_name, author_email)
        parents = [pygit2.Oid(hex=parent_sha)] if parent_sha else []

        main_ref = repo.references.get("refs/heads/main")
        is_fast_forward = (
            main_ref is None
            or not parent_sha
            or str(main_ref.peel().id) == parent_sha
        )

        if is_fast_forward:
            commit_oid = repo.create_commit(
                "refs/heads/main",
                sig,
                sig,
                message,
                tree_id,
                parents,
            )
        else:
            commit_oid = repo.create_commit(
                None,
                sig,
                sig,
                message,
                tree_id,
                parents,
            )

        repo.set_head(commit_oid)

        deal_path = self._repo_path / "deal.json"
        fd, tmp = tempfile.mkstemp(dir=str(self._repo_path), suffix=".tmp")
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, str(deal_path))

        index = repo.index
        index.read()
        index.add("deal.json")
        if sidecar_data is not None:
            sidecar_path = self._repo_path / "sidecar.json"
            fd2, tmp2 = tempfile.mkstemp(dir=str(self._repo_path), suffix=".tmp")
            try:
                os.write(fd2, sidecar_data)
                os.fsync(fd2)
            finally:
                os.close(fd2)
            os.replace(tmp2, str(sidecar_path))
            index.add("sidecar.json")
        index.write()

        return str(commit_oid)

    def _commit_deal_cli(
        self,
        deal_payload: dict[str, Any] | bytes,
        *,
        author: str,
        message: str,
        parent_sha: str | None,
        commit_target: str,
        sidecar_payload: dict[str, Any] | bytes | None = None,
    ) -> str:
        data = deal_payload if isinstance(deal_payload, bytes) else json.dumps(deal_payload, indent=2).encode("utf-8")
        sidecar_data: bytes | None = None
        if sidecar_payload is not None:
            if isinstance(sidecar_payload, bytes):
                sidecar_data = sidecar_payload
            else:
                from bma_standard_formulas.deals.schemas.studio_sidecar import StudioSidecar
                sidecar_data = StudioSidecar.model_validate(sidecar_payload).model_dump_json(indent=2).encode("utf-8")

        # Non-main branch: validate parent_sha against the target branch tip and use
        # low-level plumbing commands (commit-tree + update-ref) to avoid touching HEAD.
        if commit_target != "main":
            try:
                target_tip = self._git_cli(
                    "rev-parse", f"refs/heads/{commit_target}"
                ).stdout.strip()
            except GitServiceError:
                target_tip = None  # unborn branch

            if target_tip != parent_sha:
                raise StaleParentShaError(head_sha=target_tip)

            blob_sha = self._git_cli(
                "hash-object", "-w", "--stdin",
                input=data.decode("utf-8"),
            ).stdout.strip()

            sidecar_blob_sha: str | None = None
            if sidecar_data is not None:
                sidecar_blob_sha = self._git_cli(
                    "hash-object", "-w", "--stdin",
                    input=sidecar_data.decode("utf-8"),
                ).stdout.strip()

            if parent_sha:
                fd, tmp_idx = tempfile.mkstemp(prefix="bma_commit_idx_")
                os.close(fd)
                try:
                    idx_env = {**os.environ, "GIT_INDEX_FILE": tmp_idx}
                    self._git_cli("read-tree", parent_sha, env=idx_env)
                    self._git_cli(
                        "update-index", "--add", "--cacheinfo",
                        f"100644,{blob_sha},deal.json",
                        env=idx_env,
                    )
                    if sidecar_blob_sha is not None:
                        self._git_cli(
                            "update-index", "--add", "--cacheinfo",
                            f"100644,{sidecar_blob_sha},sidecar.json",
                            env=idx_env,
                        )
                    tree_sha = self._git_cli("write-tree", env=idx_env).stdout.strip()
                finally:
                    Path(tmp_idx).unlink(missing_ok=True)
            else:
                mktree_input = f"100644 blob {blob_sha}\tdeal.json\n"
                if sidecar_blob_sha is not None:
                    mktree_input += f"100644 blob {sidecar_blob_sha}\tsidecar.json\n"
                tree_sha = self._git_cli(
                    "mktree",
                    input=mktree_input,
                ).stdout.strip()

            author_name, author_email = _parse_author(author)
            author_env = {
                **os.environ,
                "GIT_AUTHOR_NAME": author_name,
                "GIT_AUTHOR_EMAIL": author_email,
                "GIT_COMMITTER_NAME": author_name,
                "GIT_COMMITTER_EMAIL": author_email,
            }
            commit_args = ["commit-tree", tree_sha, "-m", message]
            if parent_sha:
                commit_args.extend(["-p", parent_sha])
            commit_sha = self._git_cli(*commit_args, env=author_env).stdout.strip()

            if target_tip:
                self._git_cli(
                    "update-ref", f"refs/heads/{commit_target}", commit_sha, target_tip
                )
            else:
                self._git_cli("update-ref", f"refs/heads/{commit_target}", commit_sha)

            return commit_sha

        # Main branch: preserve original behavior exactly so that existing irvc-1 tests
        # continue to pass without modification.
        deal_path = self._repo_path / "deal.json"
        deal_path.write_bytes(data)

        self._git_cli("add", "deal.json")

        if sidecar_data is not None:
            sidecar_path = self._repo_path / "sidecar.json"
            sidecar_path.write_bytes(sidecar_data)
            self._git_cli("add", "sidecar.json")

        author_name, author_email = _parse_author(author)
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
        }

        if parent_sha:
            self._git_cli("reset", "--soft", parent_sha, env=env)
            self._git_cli("add", "deal.json", env=env)
            if sidecar_data is not None:
                self._git_cli("add", "sidecar.json", env=env)

        self._git_cli("commit", "-m", message, "--allow-empty", env=env)
        result = self._git_cli("rev-parse", "HEAD")
        return result.stdout.strip()

    # -------------------------------------------------------------------
    # branch_create / branch_delete / branch_list
    # -------------------------------------------------------------------

    @_wrap_pygit2
    def branch_create(self, name: str, *, from_sha: str) -> None:
        self._validate_branch_name(name)
        with self._write_lock():
            if self._use_pygit2:
                repo = pygit2.Repository(str(self._repo_path / ".git"))
                repo.create_branch(name, repo.revparse_single(from_sha), False)
            else:
                self._git_cli("branch", name, from_sha)

    @_wrap_pygit2
    def branch_delete(self, name: str) -> None:
        if name == "main":
            raise GitServiceError(
                "PROTECTED_BRANCH: refusing to delete the primary branch 'main'"
            )
        self._validate_branch_name(name)
        with self._write_lock():
            if self._use_pygit2:
                repo = pygit2.Repository(str(self._repo_path / ".git"))
                branch = repo.branches.get(name)
                if branch is not None:
                    branch.delete()
                else:
                    raise GitServiceError(f"Branch {name!r} not found")
            else:
                self._git_cli("branch", "-D", name)

    @_wrap_pygit2
    def branch_list(self) -> list[BranchInfo]:
        if self._use_pygit2:
            repo = pygit2.Repository(str(self._repo_path / ".git"))
            result: list[BranchInfo] = []
            for branch_name in repo.branches:
                branch = repo.branches.get(branch_name)
                if branch is not None:
                    tip = branch.peel()
                    result.append(BranchInfo(name=branch_name, tip_sha=str(tip.id)))
            return result
        else:
            proc = self._git_cli("for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads/")
            result = []
            for line in proc.stdout.strip().splitlines():
                if not line.strip():
                    continue
                parts = line.strip().split(" ", 1)
                if len(parts) == 2:
                    result.append(BranchInfo(name=parts[0], tip_sha=parts[1]))
            return result

    # -------------------------------------------------------------------
    # log
    # -------------------------------------------------------------------

    @_wrap_pygit2
    def log(self, branch: str = "main", *, limit: int = 50) -> list[CommitMeta]:
        if self._use_pygit2:
            repo = pygit2.Repository(str(self._repo_path / ".git"))
            ref = repo.branches.get(branch)
            if ref is None:
                return []
            entries: list[CommitMeta] = []
            commit = ref.peel()
            count = 0
            while commit and count < limit:
                parent = str(commit.parent_ids[0]) if commit.parent_ids else None
                committed_at = datetime.fromtimestamp(commit.commit_time, tz=timezone.utc)
                entries.append(CommitMeta(
                    sha=str(commit.id),
                    author=f"{commit.author.name} <{commit.author.email}>",
                    message=commit.message.strip(),
                    parent_sha=parent,
                    committed_at=committed_at,
                ))
                count += 1
                if commit.parent_ids:
                    commit = repo[commit.parent_ids[0]]
                else:
                    break
            return entries
        else:
            try:
                proc = self._git_cli(
                    "log", "-z",
                    f"--max-count={limit}",
                    "--format=%H%x00%an <%ae>%x00%s%x00%P%x00%cI",
                    branch,
                )
            except GitServiceError as exc:
                if "does not have any commits yet" in str(exc) or "unknown revision" in str(exc):
                    return []
                raise
            raw = proc.stdout
            if not raw:
                return []
            # With -z, git uses NUL as the inter-record terminator and we use
            # %x00 as the intra-record field separator.  Splitting the entire
            # output on NUL gives a flat list: [sha, author, subject, parents,
            # date, sha, ...] with a trailing empty string from the final
            # terminator.  NUL bytes are forbidden in git commit messages by
            # git itself, so this delimiter cannot collide.
            fields = raw.split("\x00")
            # Drop trailing empty entry produced by the NUL terminator.
            if fields and fields[-1] == "":
                fields = fields[:-1]
            if not fields:
                return []
            if len(fields) % 5 != 0:
                raise GitServiceError(
                    f"CLI log output has {len(fields)} NUL-delimited fields; "
                    "expected a multiple of 5 (sha, author, subject, parents, date). "
                    "Possible git version incompatibility."
                )
            entries = []
            for i in range(0, len(fields), 5):
                sha = fields[i]
                author_line = fields[i + 1]
                msg = fields[i + 2]
                parents_raw = fields[i + 3]
                date_str = fields[i + 4]
                # First parent = integration target for merge commits.
                parent = parents_raw.split()[0] if parents_raw.strip() else None
                try:
                    committed_at = datetime.fromisoformat(date_str)
                except ValueError:
                    committed_at = datetime.now(timezone.utc)
                entries.append(CommitMeta(
                    sha=sha,
                    author=author_line,
                    message=msg,
                    parent_sha=parent,
                    committed_at=committed_at,
                ))
            return entries

    # -------------------------------------------------------------------
    # show
    # -------------------------------------------------------------------

    @_wrap_pygit2
    def show(self, sha: str, path: str) -> bytes:
        if self._use_pygit2:
            repo = pygit2.Repository(str(self._repo_path / ".git"))
            commit = repo.revparse_single(sha)
            entry = commit.tree[path]
            blob = repo[entry.id]
            return bytes(blob.data)
        else:
            proc = self._git_cli("show", f"{sha}:{path}")
            return proc.stdout.encode("utf-8")

    # -------------------------------------------------------------------
    # diff
    # -------------------------------------------------------------------

    @_wrap_pygit2
    def diff(self, sha_a: str, sha_b: str) -> str:
        if self._use_pygit2:
            repo = pygit2.Repository(str(self._repo_path / ".git"))
            commit_a = repo.revparse_single(sha_a)
            commit_b = repo.revparse_single(sha_b)
            d = repo.diff(commit_a.tree, commit_b.tree)
            return d.patch or ""
        else:
            proc = self._git_cli("diff", sha_a, sha_b)
            return proc.stdout

    # -------------------------------------------------------------------
    # merge_base
    # -------------------------------------------------------------------

    @_wrap_pygit2
    def merge_base(self, branch_a: str, branch_b: str) -> str:
        if self._use_pygit2:
            repo = pygit2.Repository(str(self._repo_path / ".git"))
            oid_a = repo.branches.get(branch_a).peel().id
            oid_b = repo.branches.get(branch_b).peel().id
            base = repo.merge_base(oid_a, oid_b)
            if base is None:
                raise GitServiceError(f"No merge base between {branch_a!r} and {branch_b!r}")
            return str(base)
        else:
            proc = self._git_cli("merge-base", branch_a, branch_b)
            return proc.stdout.strip()

    # -------------------------------------------------------------------
    # merge
    # -------------------------------------------------------------------

    def merge(self, branch: str, *, into: str = "main", squash: bool = False) -> str | Any:
        """Three-way merge of *branch* into *into*.

        Returns the merge-commit SHA (str) on success, or a
        ``DiagnosticPayload`` with ``code='MERGE_CONFLICT'`` on conflict.

        When ``squash=True``, the merge commit on *into* has ONLY *into*'s HEAD
        as parent (single-parent), so the source branch's commits become
        unreachable after the source branch ref is deleted.  Used for ephemeral
        branches (ai/turn-*, solver/run-*) per the Phase 0 C11 "squash on
        Apply" contract.

        When ``squash=False`` (default), the merge commit has two parents
        (the standard git merge primitive).
        """
        self._validate_branch_name(branch)
        self._validate_branch_name(into)
        with self._write_lock():
            if self._use_pygit2:
                return self._merge_pygit2(branch, into=into, squash=squash)
            return self._merge_cli(branch, into=into, squash=squash)

    @_wrap_pygit2
    def _merge_pygit2(self, branch: str, *, into: str, squash: bool) -> str | Any:
        from bma_cfengine_app.orchestrator.deals.merge import merge_deal_definitions
        from bma_standard_formulas.deals.schemas.ir import DealDefinition
        from bma_standard_formulas.diagnostics import DiagnosticPayload

        repo = pygit2.Repository(str(self._repo_path / ".git"))

        ours_ref = repo.branches.get(into)
        theirs_ref = repo.branches.get(branch)
        if ours_ref is None:
            raise GitServiceError(f"Branch {into!r} not found")
        if theirs_ref is None:
            raise GitServiceError(f"Branch {branch!r} not found")

        ours_commit = ours_ref.peel()
        theirs_commit = theirs_ref.peel()

        base_oid = repo.merge_base(ours_commit.id, theirs_commit.id)
        if base_oid is None:
            raise GitServiceError(
                f"No merge base between {into!r} and {branch!r}"
            )
        ancestor_commit = repo[base_oid]

        ancestor_deal = DealDefinition.model_validate_json(
            bytes(repo[ancestor_commit.tree["deal.json"].id].data)
        )
        ours_deal = DealDefinition.model_validate_json(
            bytes(repo[ours_commit.tree["deal.json"].id].data)
        )
        theirs_deal = DealDefinition.model_validate_json(
            bytes(repo[theirs_commit.tree["deal.json"].id].data)
        )

        result = merge_deal_definitions(ancestor_deal, ours_deal, theirs_deal)
        if isinstance(result, DiagnosticPayload):
            return result

        merged_json = json.dumps(
            result.model_dump(mode="json"), indent=2,
        ).encode("utf-8")
        blob_id = repo.create_blob(merged_json)

        tb = repo.TreeBuilder(ours_commit.tree)
        tb.insert("deal.json", blob_id, pygit2.GIT_FILEMODE_BLOB)
        tree_id = tb.write()

        sig = pygit2.Signature("system", "merge@bma")
        parents = [ours_commit.id] if squash else [ours_commit.id, theirs_commit.id]
        message = (
            f"Apply '{branch}' onto '{into}'"
            if squash
            else f"Merge branch '{branch}' into '{into}'"
        )
        commit_oid = repo.create_commit(
            f"refs/heads/{into}",
            sig,
            sig,
            message,
            tree_id,
            parents,
        )

        merge_commit = repo[commit_oid]
        head_is_into = (
            not repo.head_is_detached
            and repo.head.shorthand == into
        )
        if head_is_into:
            repo.checkout_tree(merge_commit.tree)
            repo.state_cleanup()

        return str(commit_oid)

    def _merge_cli(self, branch: str, *, into: str, squash: bool) -> str | Any:
        from bma_cfengine_app.orchestrator.deals.merge import merge_deal_definitions
        from bma_standard_formulas.deals.schemas.ir import DealDefinition
        from bma_standard_formulas.diagnostics import DiagnosticPayload

        base_sha = self._git_cli("merge-base", into, branch).stdout.strip()

        ours_sha = self._git_cli("rev-parse", into).stdout.strip()
        theirs_sha = self._git_cli("rev-parse", branch).stdout.strip()

        ancestor_deal = DealDefinition.model_validate_json(
            self._git_cli("show", f"{base_sha}:deal.json").stdout.encode("utf-8")
        )
        ours_deal = DealDefinition.model_validate_json(
            self._git_cli("show", f"{ours_sha}:deal.json").stdout.encode("utf-8")
        )
        theirs_deal = DealDefinition.model_validate_json(
            self._git_cli("show", f"{theirs_sha}:deal.json").stdout.encode("utf-8")
        )

        result = merge_deal_definitions(ancestor_deal, ours_deal, theirs_deal)
        if isinstance(result, DiagnosticPayload):
            return result

        merged_json = json.dumps(
            result.model_dump(mode="json"), indent=2,
        ).encode("utf-8")

        merged_blob_sha = self._git_cli(
            "hash-object", "-w", "--stdin",
            input=merged_json.decode("utf-8"),
        ).stdout.strip()

        fd, tmp_idx_path = tempfile.mkstemp(prefix="bma_merge_")
        os.close(fd)
        try:
            idx_env = {**os.environ, "GIT_INDEX_FILE": tmp_idx_path}
            self._git_cli("read-tree", ours_sha, env=idx_env)
            self._git_cli(
                "update-index", "--add", "--cacheinfo",
                f"100644,{merged_blob_sha},deal.json",
                env=idx_env,
            )
            tree_sha = self._git_cli("write-tree", env=idx_env).stdout.strip()
        finally:
            Path(tmp_idx_path).unlink(missing_ok=True)

        author_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "system",
            "GIT_AUTHOR_EMAIL": "merge@bma",
            "GIT_COMMITTER_NAME": "system",
            "GIT_COMMITTER_EMAIL": "merge@bma",
        }
        message = (
            f"Apply '{branch}' onto '{into}'"
            if squash
            else f"Merge branch '{branch}' into '{into}'"
        )
        commit_tree_args = ["commit-tree", tree_sha, "-p", ours_sha]
        if not squash:
            commit_tree_args.extend(["-p", theirs_sha])
        commit_tree_args.extend(["-m", message])
        commit_sha = self._git_cli(
            *commit_tree_args,
            env=author_env,
        ).stdout.strip()

        self._git_cli("update-ref", f"refs/heads/{into}", commit_sha, ours_sha)

        try:
            current_branch = self._git_cli(
                "symbolic-ref", "--short", "HEAD",
            ).stdout.strip()
        except GitServiceError:
            current_branch = None
        if current_branch == into:
            self._git_cli("read-tree", "-m", tree_sha)
            self._git_cli("checkout-index", "--all", "--force")

        return commit_sha


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_author(author: str) -> tuple[str, str]:
    match = re.match(r"^(.+?)\s*<(.+?)>$", author)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return author, "unknown@unknown"
