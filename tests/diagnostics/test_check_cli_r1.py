"""vpc-4 R1 fix-pass — four new failing tests, one per R1 finding.

These tests are designed to FAIL on HEAD before the fix-pass lands and to PASS
after the four targeted changes are applied to check.py and ci.yml.

Finding 1 (AC 5) — test_shallow_clone_produces_clear_warning
    Simulates a shallow CI checkout (.git/shallow marker).  The checker must
    emit a distinct "shallow clone" error rather than silently returning [].

Finding 2 (AC 6) — test_ci_yml_has_dedicated_diagnostic_check_job
    Parses .github/workflows/ci.yml and asserts a top-level `diagnostic-check`
    job exists (separate from the `test` matrix job).

Finding 3 (AC 1) — test_default_ts_discovery_is_recursive_and_excludes_spec_files
    Inspects the check module source to verify TS discovery uses rglob (recursive)
    and excludes both .test.ts and .spec.ts files.

Finding 4 (AC 4) — test_catalog_vs_python_severity_mismatch_detected
    Creates a catalog entry whose severity disagrees with the Python @diagnostic_code
    decorator.  The checker must fail with a catalog/Python mismatch error.
"""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_ci_guard.py; not imported to avoid coupling)
# ---------------------------------------------------------------------------

_CATALOG_HEADER = textwrap.dedent("""\
    # Diagnostic Catalog

    ## Catalog Table

    | code | severity | path schema | message template | owner | quick fix | owning validator file:line |
    | --- | --- | --- | --- | --- | --- | --- |
""")


def _write_catalog(path: Path, rows: list[dict]) -> Path:
    # Build content by appending rows directly to the header (which already ends
    # with \n) rather than using "\n".join([header, row…]).  The join approach
    # inserts an extra blank line between the separator and the first data row,
    # which causes the catalog parser to stop before reading any entries.
    content = _CATALOG_HEADER  # ends with \n after the separator row
    for row in rows:
        content += (
            f"| {row['code']} | {row['severity']} | {row['path_schema']} "
            f"| {row.get('message', 'msg template')} | {row['owner']} "
            f"| {row.get('quick_fix', 'fix it')} | stub.py:1 |\n"
        )
    path.write_text(content)
    return path


def _run_check(
    *,
    catalog_path: Path,
    src_dirs: list[Path] | None = None,
    ts_files: list[Path] | None = None,
    skip_git_check: bool = True,
    git_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
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
# Finding 1 (AC 5) — shallow clone must be detected and reported clearly
# ---------------------------------------------------------------------------


def test_shallow_clone_produces_clear_warning(tmp_path: Path) -> None:
    """AC 5 (R1 finding 1): A shallow git checkout must produce a distinct 'shallow clone'
    error, not a silent pass.

    Currently the checker catches CalledProcessError from ``git diff HEAD~1 HEAD`` and
    returns [] unconditionally — meaning a shallow CI checkout silently bypasses AC 5.

    After the fix the checker must inspect the .git/shallow marker and return an error
    that contains the word 'shallow' when it is present.
    """
    git_dir = tmp_path / "repo"
    git_dir.mkdir()

    _git = lambda *args: subprocess.run(  # noqa: E731
        ["git", "-C", str(git_dir), *args],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "init", str(git_dir)], check=True, capture_output=True)
    _git("config", "user.email", "vpc4-r1@test.com")
    _git("config", "user.name", "vpc4-r1-test")

    # Simulate shallow checkout: plant .git/shallow (GitHub Actions does this
    # when fetch-depth < full history).
    (git_dir / ".git" / "shallow").write_text("0000000000000000000000000000000000000000\n")

    # One commit only — HEAD~1 is therefore unavailable regardless.
    catalog_file = git_dir / "catalog.md"
    _write_catalog(catalog_file, [])
    _git("add", ".")
    _git("commit", "-m", "init: shallow-clone simulation")

    result = _run_check(
        catalog_path=catalog_file,
        src_dirs=[git_dir],
        ts_files=[],
        skip_git_check=False,
        git_dir=git_dir,
    )

    combined = result.stdout + result.stderr
    assert "shallow" in combined.lower(), (
        "Expected the checker to emit a 'shallow clone' warning/error when "
        ".git/shallow exists, but got no mention of 'shallow' in output.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# Finding 2 (AC 6) — ci.yml must have a dedicated diagnostic-check job
# ---------------------------------------------------------------------------


def test_ci_yml_has_dedicated_diagnostic_check_job() -> None:
    """AC 6 (R1 finding 2): .github/workflows/ci.yml must declare a top-level
    ``diagnostic-check`` job that is separate from the ``test`` matrix job.

    Currently the diagnostic parity check is a step inside the ``test`` job;
    it must be extracted to its own dedicated job.
    """
    repo_root = Path(__file__).resolve().parents[2]
    ci_path = repo_root / ".github" / "workflows" / "ci.yml"
    assert ci_path.exists(), f"CI workflow file not found: {ci_path}"

    content = ci_path.read_text(encoding="utf-8")

    # A YAML job key appears as two-space-indented "<name>:" under the "jobs:" block.
    job_pattern = re.compile(r"^  diagnostic-check\s*:", re.MULTILINE)
    assert job_pattern.search(content), (
        "Expected a dedicated 'diagnostic-check:' job in .github/workflows/ci.yml "
        "(two-space indented under 'jobs:'). Currently the diagnostic check runs as "
        "a step inside the 'test' matrix job, which does not satisfy AC 6."
    )


# ---------------------------------------------------------------------------
# Finding 3 (AC 1) — default TS discovery must be recursive and exclude .spec.ts
# ---------------------------------------------------------------------------


def test_default_ts_discovery_is_recursive_and_excludes_spec_files() -> None:
    """AC 1 (R1 finding 3): The default TS file discovery in check.py must use a
    recursive glob (rglob / **) so that validator modules in subdirectories are found
    automatically.  It must also exclude .spec.ts files in addition to .test.ts.

    Currently ``_DEFAULT_TS_FILES`` uses ``glob("*.ts")`` — a shallow, non-recursive
    scan — and only filters out ``.test.ts``.
    """
    import inspect

    import bma_standard_formulas.diagnostics.check as check_mod

    source = inspect.getsource(check_mod)

    is_recursive = 'rglob("*.ts")' in source or '"**/*.ts"' in source
    assert is_recursive, (
        "check.py must use rglob('*.ts') or '**/*.ts' for recursive TS discovery. "
        "Current code uses glob('*.ts') which only scans the top-level directory and "
        "will miss validator modules added in subdirectories."
    )

    excludes_spec = ".spec.ts" in source
    assert excludes_spec, (
        "check.py must exclude '.spec.ts' files from default TS discovery. "
        "Currently only '.test.ts' is excluded."
    )


# ---------------------------------------------------------------------------
# Finding 4 (AC 4) — catalog metadata must be compared against Python metadata
# ---------------------------------------------------------------------------


@pytest.fixture()
def _py_src(tmp_path: Path):
    """Write a Python source file with @diagnostic_code entries."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    def _write(entries: list[dict]) -> tuple[Path, Path]:
        lines = [
            "from bma_standard_formulas.diagnostics import diagnostic_code, Owner, Severity",
            "",
        ]
        for i, e in enumerate(entries):
            lines += [
                "@diagnostic_code(",
                f'    "{e["code"]}",',
                f'    severity=Severity.{e["severity"]},',
                f'    path_schema="{e["path_schema"]}",',
                f'    owner=Owner.{e["owner"]},',
                ")",
                f"def _validator_{i}(v):",
                "    return v",
                "",
            ]
        (src_dir / "validators.py").write_text("\n".join(lines))
        return src_dir, src_dir / "validators.py"

    return _write


def test_catalog_vs_python_severity_mismatch_detected(
    tmp_path: Path, _py_src
) -> None:
    """AC 4 (R1 finding 4): When the catalog row severity disagrees with the Python
    @diagnostic_code decorator severity, the checker must exit non-zero and name the
    offending code.

    Currently the checker only compares Python vs TS — a backend-only diagnostic whose
    catalog row says severity='warning' but whose decorator says severity='error' passes
    silently because there is no TS side to compare against.
    """
    src_dir, _ = _py_src([
        {
            "code": "CAT_PY_SEV_MISMATCH",
            "severity": "error",        # Python decorator: error
            "path_schema": "deal.bonds[*].name",
            "owner": "backend",
        }
    ])
    # Catalog declares severity='warning' — intentional divergence from Python.
    catalog = _write_catalog(
        tmp_path / "catalog.md",
        [
            {
                "code": "CAT_PY_SEV_MISMATCH",
                "severity": "warning",  # Catalog: warning ← mismatch
                "path_schema": "deal.bonds[*].name",
                "owner": "backend",
            }
        ],
    )

    result = _run_check(catalog_path=catalog, src_dirs=[src_dir])

    assert result.returncode != 0, (
        "Expected non-zero exit code when catalog severity differs from Python "
        "@diagnostic_code severity, but check PASSED."
    )
    combined = result.stdout + result.stderr
    assert "CAT_PY_SEV_MISMATCH" in combined, (
        f"Expected error message to name the diverging code. Got:\n{combined}"
    )
    assert "severity" in combined.lower(), (
        f"Expected error message to mention 'severity'. Got:\n{combined}"
    )
