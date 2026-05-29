from __future__ import annotations

import json
import multiprocessing
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest


def _run_git(repo_path: Path, *args: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout.strip()


def _seed_repo_with_initial_commit(repo_path: Path) -> str:
    _run_git(repo_path, "init", "-b", "main")
    (repo_path / "deal.json").write_text(json.dumps({"deal_name": "seed"}), encoding="utf-8")
    _run_git(repo_path, "add", "deal.json")
    commit_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Seed User",
        "GIT_AUTHOR_EMAIL": "seed@example.com",
        "GIT_COMMITTER_NAME": "Seed User",
        "GIT_COMMITTER_EMAIL": "seed@example.com",
    }
    _run_git(repo_path, "commit", "-m", "seed commit", env=commit_env)
    return _run_git(repo_path, "rev-parse", "HEAD")


def _payload(name: str) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "deal_name": name,
        "bonds": [],
        "accounts": [],
        "fees": [],
        "waterfall_rules": [],
    }


def _lock_holder_worker(repo_path: str, parent_sha: str, conn: multiprocessing.connection.Connection) -> None:
    try:
        from bma_cfengine_app.orchestrator.deals.git_service import GitService

        service = GitService(repo_path=Path(repo_path))
        with service._write_lock():
            lock_path = Path(repo_path) / ".git" / "bma_write.lock"
            sha = service.commit_deal(
                deal_payload=_payload("holder-commit"),
                author="Lock Holder <holder@test.local>",
                message="hold lock during commit",
                parent_sha=parent_sha,
            )
            conn.send({"ok": True, "sha": sha, "lock_exists": lock_path.exists()})
            time.sleep(6.0)
    except Exception as exc:  # pragma: no cover - asserted from parent process
        conn.send({"ok": False, "error": repr(exc)})
    finally:
        conn.close()


def _commit_worker(repo_path: str, parent_sha: str, conn: multiprocessing.connection.Connection) -> None:
    try:
        from bma_cfengine_app.orchestrator.deals.git_service import GitService

        service = GitService(repo_path=Path(repo_path))
        sha = service.commit_deal(
            deal_payload=_payload("contender-commit"),
            author="Lock Contender <contender@test.local>",
            message="contend for lock",
            parent_sha=parent_sha,
        )
        conn.send({"ok": True, "sha": sha})
    except Exception as exc:  # pragma: no cover - asserted from parent process
        conn.send({"ok": False, "error": repr(exc)})
    finally:
        conn.close()


def test_cross_process_concurrent_writes_timeout(tmp_path: Path) -> None:
    """AC 4: concurrent cross-process writes time out with LOCK_TIMEOUT using .git/bma_write.lock."""
    from bma_cfengine_app.orchestrator.deals.git_service import GitService

    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    seed_sha = _seed_repo_with_initial_commit(repo_path)
    GitService(repo_path=repo_path)  # Ensure constructor works before spawning workers.

    ctx = multiprocessing.get_context("spawn")

    holder_parent, holder_child = ctx.Pipe()
    holder = ctx.Process(
        target=_lock_holder_worker,
        args=(str(repo_path), seed_sha, holder_child),
    )
    holder.start()

    assert holder_parent.poll(20), "holder worker did not report lock acquisition"
    holder_result = holder_parent.recv()
    assert holder_result["ok"], holder_result
    assert holder_result["lock_exists"] is True
    holder_sha = holder_result["sha"]
    assert re.fullmatch(r"[0-9a-f]{40}", holder_sha)

    lock_path = repo_path / ".git" / "bma_write.lock"
    assert lock_path.exists()

    contender_parent, contender_child = ctx.Pipe()
    contender = ctx.Process(
        target=_commit_worker,
        args=(str(repo_path), holder_sha, contender_child),
    )
    contender.start()

    assert contender_parent.poll(20), "contender worker did not return in time"
    contender_result = contender_parent.recv()
    assert contender_result["ok"] is False
    assert "LOCK_TIMEOUT" in contender_result["error"]

    contender.join(timeout=20)
    holder.join(timeout=20)
    assert contender.exitcode == 0
    assert holder.exitcode == 0


def test_same_process_reentrant_acquire_and_release(tmp_path: Path) -> None:
    """AC 4: same-process nested lock acquires are reentrant and fully release on outer exit."""
    from bma_cfengine_app.orchestrator.deals.git_service import GitService

    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    seed_sha = _seed_repo_with_initial_commit(repo_path)
    service = GitService(repo_path=repo_path)

    started = time.monotonic()
    with service._write_lock():
        with service._write_lock():
            assert (repo_path / ".git" / "bma_write.lock").exists()
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, f"Nested same-process lock acquire took too long: {elapsed:.3f}s"

    ctx = multiprocessing.get_context("spawn")
    child_parent, child_conn = ctx.Pipe()
    child = ctx.Process(
        target=_commit_worker,
        args=(str(repo_path), seed_sha, child_conn),
    )
    child.start()
    assert child_parent.poll(20), "post-release writer process did not return in time"
    child_result = child_parent.recv()
    child.join(timeout=20)

    assert child.exitcode == 0
    assert child_result["ok"], child_result
    assert re.fullmatch(r"[0-9a-f]{40}", child_result["sha"])
