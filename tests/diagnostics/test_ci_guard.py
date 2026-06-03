"""CI guard tests for vpc-4: diagnostic catalog parity check.

These tests exercise the CLI tool ``python -m bma_standard_formulas.diagnostics.check``
against artificially constructed scenarios to verify each parity condition.
All four tests are expected to FAIL on HEAD before ``check.py`` is implemented.

AC coverage:
  - test_ci_guard_fails_on_missing_catalog_entry               → AC 1, 2
  - test_ci_guard_fails_on_missing_ts_implementation_for_both_owner → AC 1, 3
  - test_ci_guard_fails_on_metadata_divergence_between_python_and_ts → AC 1, 4
  - test_ci_guard_diff_check_enforces_same_commit_catalog_updates   → AC 5

AC 6 (pnpm ``diagnostic:check`` script + CI workflow step) is verified by
inspection of ``src/bma_cfengine_app/ui/package.json`` and
``.github/workflows/ci.yml``, not by a Python test — analogous to irvc-1 AC 6.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CATALOG_HEADER = textwrap.dedent("""\
    # Diagnostic Catalog

    ## Catalog Table

    | code | severity | path schema | message template | owner | quick fix | owning validator file:line |
    | --- | --- | --- | --- | --- | --- | --- |
""")


def _write_catalog(path: Path, rows: list[dict]) -> Path:
    """Write a minimal catalog markdown file with the given rows."""
    lines = [_CATALOG_HEADER]
    for row in rows:
        lines.append(
            f"| {row['code']} | {row['severity']} | {row['path_schema']} "
            f"| {row.get('message', 'msg template')} | {row['owner']} "
            f"| {row.get('quick_fix', 'fix it')} | stub.py:1 |"
        )
    path.write_text("\n".join(lines) + "\n")
    return path


def _run_check(
    *,
    catalog_path: Path,
    src_dirs: list[Path] | None = None,
    ts_files: list[Path] | None = None,
    skip_git_check: bool = True,
    git_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke ``python -m bma_standard_formulas.diagnostics.check`` and return the result."""
    cmd: list[str] = [
        sys.executable,
        "-m",
        "bma_standard_formulas.diagnostics.check",
        "--catalog",
        str(catalog_path),
    ]
    for d in (src_dirs or []):
        cmd += ["--src-dir", str(d)]
    for f in (ts_files or []):
        cmd += ["--ts-file", str(f)]
    if skip_git_check:
        cmd.append("--skip-git-check")
    if git_dir is not None:
        cmd += ["--git-dir", str(git_dir)]
    return subprocess.run(cmd, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def py_src(tmp_path: Path):
    """Return a factory that writes a temp Python source file with @diagnostic_code."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    def _write(entries: list[dict]) -> tuple[Path, Path]:
        """Write validators.py with one @diagnostic_code per entry dict.

        Each entry must have: code, severity (e.g. "error"), path_schema, owner (e.g. "backend").
        Returns (src_dir, py_file).
        """
        lines = [
            "from bma_standard_formulas.diagnostics import diagnostic_code, Owner, Severity",
            "",
        ]
        for i, e in enumerate(entries):
            lines += [
                f"@diagnostic_code(",
                f'    "{e["code"]}",',
                f'    severity=Severity.{e["severity"]},',
                f'    path_schema="{e["path_schema"]}",',
                f'    owner=Owner.{e["owner"]},',
                f")",
                f"def _validator_{i}(v):",
                f"    return v",
                "",
            ]
        (src_dir / "validators.py").write_text("\n".join(lines))
        return src_dir, src_dir / "validators.py"

    return _write


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_ci_guard_fails_on_missing_catalog_entry(tmp_path: Path, py_src) -> None:
    """AC 1, 2: A @diagnostic_code not listed in the catalog causes exit code > 0 with a
    clear error message containing the offending code.
    """
    src_dir, _ = py_src([
        {
            "code": "MISSING_FROM_CATALOG",
            "severity": "error",
            "path_schema": "deal.test[*]",
            "owner": "backend",
        }
    ])
    # Empty catalog — no rows.
    catalog = _write_catalog(tmp_path / "catalog.md", [])

    result = _run_check(catalog_path=catalog, src_dirs=[src_dir])

    assert result.returncode != 0, (
        "Expected non-zero exit code when @diagnostic_code is absent from the catalog"
    )
    combined = result.stdout + result.stderr
    assert "MISSING_FROM_CATALOG" in combined, (
        f"Expected error message to name the missing code. Got:\n{combined}"
    )


def test_ci_guard_fails_on_missing_ts_implementation_for_both_owner(
    tmp_path: Path, py_src
) -> None:
    """AC 1, 3: A catalog entry with owner='both' must have a TS registerDiagnosticValidator
    call; absence causes exit code > 0.
    """
    src_dir, _ = py_src([
        {
            "code": "BOTH_OWNER_CODE",
            "severity": "error",
            "path_schema": "deal.bonds[*].coupon",
            "owner": "both",
        }
    ])
    catalog = _write_catalog(
        tmp_path / "catalog.md",
        [
            {
                "code": "BOTH_OWNER_CODE",
                "severity": "error",
                "path_schema": "deal.bonds[*].coupon",
                "owner": "both",
            }
        ],
    )
    # TS file with zero registerDiagnosticValidator calls.
    ts_file = tmp_path / "diagnosticRegistry.ts"
    ts_file.write_text("// empty registry — no validators registered\n")

    result = _run_check(catalog_path=catalog, src_dirs=[src_dir], ts_files=[ts_file])

    assert result.returncode != 0, (
        "Expected non-zero exit code when owner='both' entry lacks a TS implementation"
    )
    combined = result.stdout + result.stderr
    assert "BOTH_OWNER_CODE" in combined, (
        f"Expected error message to name the missing TS code. Got:\n{combined}"
    )


def test_ci_guard_fails_on_metadata_divergence_between_python_and_ts(
    tmp_path: Path, py_src
) -> None:
    """AC 1, 4: Python severity='error' vs TS severity='warning' for the same code causes
    exit code > 0 with a message identifying the diverging code.
    """
    src_dir, _ = py_src([
        {
            "code": "DIV_CODE",
            "severity": "error",
            "path_schema": "deal.bonds[*].coupon",
            "owner": "both",
        }
    ])
    catalog = _write_catalog(
        tmp_path / "catalog.md",
        [
            {
                "code": "DIV_CODE",
                "severity": "error",
                "path_schema": "deal.bonds[*].coupon",
                "owner": "both",
            }
        ],
    )
    # TS registers DIV_CODE with severity='warning' — deliberate divergence.
    ts_file = tmp_path / "diagnosticRegistry.ts"
    ts_file.write_text(
        textwrap.dedent("""\
            registerDiagnosticValidator({
                code: "DIV_CODE",
                severity: "warning",
                pathSchema: "deal.bonds[*].coupon",
                owner: "both",
                fn: () => [],
            });
        """)
    )

    result = _run_check(catalog_path=catalog, src_dirs=[src_dir], ts_files=[ts_file])

    assert result.returncode != 0, (
        "Expected non-zero exit code when Python and TS severity values diverge"
    )
    combined = result.stdout + result.stderr
    assert "DIV_CODE" in combined, (
        f"Expected error message to name the diverging code. Got:\n{combined}"
    )


def test_ci_guard_diff_check_enforces_same_commit_catalog_updates(
    tmp_path: Path,
) -> None:
    """AC 5: Adding a @diagnostic_code without updating the catalog in the same commit
    causes exit code > 0.

    Trade-off: This check uses ``git diff --name-only HEAD~1 HEAD``. On the first
    commit of a new branch (where HEAD~1 does not exist), the check is skipped
    entirely — there is no parent commit to diff against, so enforcement is
    deferred to subsequent commits. This is documented as a deliberate design
    choice (see ticket vpc-4 AC 5).
    """
    git_dir = tmp_path / "git_repo"
    git_dir.mkdir()
    _git = lambda *args: subprocess.run(  # noqa: E731
        ["git", "-C", str(git_dir), *args],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "init", str(git_dir)], check=True, capture_output=True)
    _git("config", "user.email", "test@vpc4.com")
    _git("config", "user.name", "vpc4-test")

    # Initial commit: catalog already contains EXISTING_CODE (simulating a prior merge).
    catalog_file = git_dir / "diagnostic_catalog.md"
    _write_catalog(
        catalog_file,
        [
            {
                "code": "EXISTING_CODE",
                "severity": "error",
                "path_schema": "deal.test[*]",
                "owner": "backend",
            }
        ],
    )
    _git("add", ".")
    _git("commit", "-m", "init: catalog with EXISTING_CODE")

    # Second commit: add a Python validator file that uses EXISTING_CODE but do NOT
    # touch the catalog — simulating a developer who forgets to update the catalog.
    src_dir = git_dir / "src"
    src_dir.mkdir()
    py_file = src_dir / "validators.py"
    py_file.write_text(
        textwrap.dedent("""\
            from bma_standard_formulas.diagnostics import diagnostic_code, Owner, Severity

            @diagnostic_code(
                "EXISTING_CODE",
                severity=Severity.error,
                path_schema="deal.test[*]",
                owner=Owner.backend,
            )
            def _validator(v):
                return v
        """)
    )
    _git("add", ".")
    _git("commit", "-m", "add validator file without catalog update")

    # Run check with git-dir pointing at the temp repo (no --skip-git-check).
    result = _run_check(
        catalog_path=catalog_file,
        src_dirs=[src_dir],
        ts_files=[],
        skip_git_check=False,
        git_dir=git_dir,
    )

    assert result.returncode != 0, (
        "Expected non-zero exit code when @diagnostic_code file added without "
        "catalog update in the same commit"
    )
    combined = result.stdout + result.stderr
    assert "catalog" in combined.lower(), (
        f"Expected error message to mention the catalog update requirement. Got:\n{combined}"
    )
