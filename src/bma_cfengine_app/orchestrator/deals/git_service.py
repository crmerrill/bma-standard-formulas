"""Core git service — pygit2 (fast path) with CLI subprocess fallback.

Wraps commit, branch, log, show, diff, and merge_base operations behind a
unified interface. Backend selection is automatic: pygit2 if importable,
otherwise shells out to the system git binary.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator

try:
    import pygit2
except ImportError:
    pygit2 = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_NAMESPACES = ("ai/turn-", "solver/run-", "what-if/")


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

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


# ---------------------------------------------------------------------------
# GitService
# ---------------------------------------------------------------------------

class GitService:
    def __init__(
        self,
        repo_path: Path,
        *,
        lock_timeout_s: float = 5.0,
    ) -> None:
        self._repo_path = Path(repo_path)
        self._lock_timeout_s = lock_timeout_s
        self._lock_fd: int | None = None
        self._local = threading.local()

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
            acquired = False
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except (OSError, BlockingIOError):
                    if time.monotonic() >= deadline:
                        os.close(fd)
                        raise LockTimeoutError(lock_path, self._lock_timeout_s)
                    time.sleep(0.05)
            self._lock_fd = fd

        self._local.lock_depth = counter + 1
        try:
            yield
        finally:
            self._local.lock_depth -= 1
            if self._local.lock_depth == 0:
                fd = self._lock_fd
                if fd is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
                    self._lock_fd = None

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

    def _git_cli(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=self._repo_path,
                check=True,
                capture_output=True,
                text=True,
                env=env,
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
    ) -> str:
        with self._write_lock():
            if self._use_pygit2:
                return self._commit_deal_pygit2(deal_payload, author=author, message=message, parent_sha=parent_sha)
            return self._commit_deal_cli(deal_payload, author=author, message=message, parent_sha=parent_sha)

    def _commit_deal_pygit2(
        self,
        deal_payload: dict[str, Any] | bytes,
        *,
        author: str,
        message: str,
        parent_sha: str | None,
    ) -> str:
        data = deal_payload if isinstance(deal_payload, bytes) else json.dumps(deal_payload, indent=2).encode("utf-8")

        repo = pygit2.Repository(str(self._repo_path / ".git"))

        blob_id = repo.create_blob(data)
        tb = repo.TreeBuilder(repo.revparse_single(parent_sha).tree if parent_sha else None)
        tb.insert("deal.json", blob_id, pygit2.GIT_FILEMODE_BLOB)
        tree_id = tb.write()

        author_name, author_email = _parse_author(author)
        sig = pygit2.Signature(author_name, author_email)
        parents = [pygit2.Oid(hex=parent_sha)] if parent_sha else []

        commit_oid = repo.create_commit(
            "refs/heads/main",
            sig,
            sig,
            message,
            tree_id,
            parents,
        )
        return str(commit_oid)

    def _commit_deal_cli(
        self,
        deal_payload: dict[str, Any] | bytes,
        *,
        author: str,
        message: str,
        parent_sha: str | None,
    ) -> str:
        data = deal_payload if isinstance(deal_payload, bytes) else json.dumps(deal_payload, indent=2).encode("utf-8")
        deal_path = self._repo_path / "deal.json"
        deal_path.write_bytes(data)

        self._git_cli("add", "deal.json")

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

        self._git_cli("commit", "-m", message, "--allow-empty", env=env)
        result = self._git_cli("rev-parse", "HEAD")
        return result.stdout.strip()

    # -------------------------------------------------------------------
    # branch_create / branch_delete / branch_list
    # -------------------------------------------------------------------

    def branch_create(self, name: str, *, from_sha: str) -> None:
        self._validate_branch_name(name)
        with self._write_lock():
            if self._use_pygit2:
                repo = pygit2.Repository(str(self._repo_path / ".git"))
                repo.create_branch(name, repo.revparse_single(from_sha), False)
            else:
                self._git_cli("branch", name, from_sha)

    def branch_delete(self, name: str) -> None:
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
                entries.append(CommitMeta(
                    sha=str(commit.id),
                    author=f"{commit.author.name} <{commit.author.email}>",
                    message=commit.message.strip(),
                    parent_sha=parent,
                ))
                count += 1
                if commit.parent_ids:
                    commit = repo[commit.parent_ids[0]]
                else:
                    break
            return entries
        else:
            proc = self._git_cli(
                "log", branch,
                f"--max-count={limit}",
                "--format=%H%n%an <%ae>%n%s%n%P%n---",
            )
            entries = []
            raw_entries = proc.stdout.strip().split("---\n")
            for entry in raw_entries:
                entry = entry.strip()
                if not entry:
                    continue
                lines = entry.split("\n")
                if len(lines) < 3:
                    continue
                sha = lines[0].strip()
                author_line = lines[1].strip()
                msg = lines[2].strip()
                parent = lines[3].strip() if len(lines) > 3 and lines[3].strip() else None
                if parent and " " in parent:
                    parent = parent.split()[0]
                entries.append(CommitMeta(
                    sha=sha,
                    author=author_line,
                    message=msg,
                    parent_sha=parent,
                ))
            return entries

    # -------------------------------------------------------------------
    # show
    # -------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_author(author: str) -> tuple[str, str]:
    match = re.match(r"^(.+?)\s*<(.+?)>$", author)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return author, "unknown@unknown"
