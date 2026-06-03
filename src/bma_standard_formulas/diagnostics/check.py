"""Diagnostic catalog CI guard — vpc-4.

CLI tool that verifies three-way synchronization between:

  1. Python ``@diagnostic_code`` decorator registrations (AST scan of source dirs).
  2. TypeScript ``registerDiagnosticValidator`` call sites (regex scan of TS files).
  3. The ``diagnostic_catalog.md`` markdown source-of-truth (parsed via the
     existing ``scripts/parse_diagnostic_catalog`` parser).

Usage::

    python -m bma_standard_formulas.diagnostics.check
    python -m bma_standard_formulas.diagnostics.check \\
        --catalog docs/architecture/diagnostic_catalog.md \\
        --src-dir src/ \\
        --ts-file src/bma_cfengine_app/ui/src/features/validation/diagnosticRegistry.ts

Exit code: 0 on full parity, 1 on any divergence.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Repo-relative default paths
# ---------------------------------------------------------------------------

# check.py lives at: src/bma_standard_formulas/diagnostics/check.py
# parents[0] = diagnostics/  parents[1] = bma_standard_formulas/
# parents[2] = src/           parents[3] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]

_DEFAULT_CATALOG = _REPO_ROOT / "docs" / "architecture" / "diagnostic_catalog.md"
_DEFAULT_SRC_DIRS: list[Path] = [_REPO_ROOT / "src"]
_DEFAULT_TS_FILES: list[Path] = [
    _REPO_ROOT
    / "src"
    / "bma_cfengine_app"
    / "ui"
    / "src"
    / "features"
    / "validation"
    / "diagnosticRegistry.ts"
]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class PyDiagnostic(NamedTuple):
    code: str
    severity: str
    path_schema: str
    owner: str
    file: str


class TsDiagnostic(NamedTuple):
    code: str
    severity: str
    path_schema: str
    owner: str
    file: str


# ---------------------------------------------------------------------------
# Python extraction — AST-based
# ---------------------------------------------------------------------------


def _ast_str(node: ast.expr | None) -> str | None:
    """Return the string value of a Constant node, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _ast_attr_or_str(node: ast.expr | None) -> str | None:
    """Return the attribute name from ``Enum.member`` or a string constant."""
    if isinstance(node, ast.Attribute):
        return node.attr  # e.g. Severity.error → "error"
    return _ast_str(node)


def collect_python_diagnostics(src_dirs: list[Path]) -> dict[str, PyDiagnostic]:
    """Walk Python source directories and extract all ``@diagnostic_code`` metadata via AST.

    Only files that explicitly call ``diagnostic_code(...)`` as a decorator are
    considered; the registry infrastructure files themselves are ignored because
    they define the function, not call it.
    """
    results: dict[str, PyDiagnostic] = {}
    for src_dir in src_dirs:
        if not src_dir.exists():
            continue
        for py_file in src_dir.rglob("*.py"):
            try:
                source = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "diagnostic_code" not in source:
                continue  # fast skip
            try:
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for dec in node.decorator_list:
                    if not isinstance(dec, ast.Call):
                        continue
                    func = dec.func
                    is_diag_call = (
                        isinstance(func, ast.Name) and func.id == "diagnostic_code"
                    ) or (
                        isinstance(func, ast.Attribute) and func.attr == "diagnostic_code"
                    )
                    if not is_diag_call:
                        continue
                    code = _ast_str(dec.args[0]) if dec.args else None
                    if not code:
                        continue
                    kwargs = {kw.arg: kw.value for kw in dec.keywords}
                    results[code] = PyDiagnostic(
                        code=code,
                        severity=_ast_attr_or_str(kwargs.get("severity")) or "",
                        path_schema=_ast_str(kwargs.get("path_schema")) or "",
                        owner=_ast_attr_or_str(kwargs.get("owner")) or "",
                        file=str(py_file),
                    )
    return results


# ---------------------------------------------------------------------------
# TypeScript extraction — regex-based
# ---------------------------------------------------------------------------

# Matches the opening brace of a registerDiagnosticValidator({ … }) call.
# The body is captured non-greedily up to the first closing brace — which is
# intentionally NOT the function-definition line (``export function …``).
_TS_CALL_RE = re.compile(
    r"registerDiagnosticValidator\s*\(\s*\{(?P<body>[^}]+)\}",
    re.DOTALL,
)
_TS_CODE_RE = re.compile(r"""code\s*:\s*["'](?P<v>[A-Z_][A-Z0-9_]*)["']""")
_TS_SEV_RE = re.compile(r"""severity\s*:\s*["'](?P<v>\w+)["']""")
_TS_PATH_RE = re.compile(r"""pathSchema\s*:\s*["'](?P<v>[^"']*)["']""")
_TS_OWNER_RE = re.compile(r"""owner\s*:\s*["'](?P<v>\w+)["']""")


def collect_ts_diagnostics(ts_files: list[Path]) -> dict[str, TsDiagnostic]:
    """Regex-scan TypeScript files for ``registerDiagnosticValidator`` call sites.

    The registry definition file itself uses ``export function registerDiagnosticValidator``
    which does not match the ``registerDiagnosticValidator({`` pattern (no leading ``{``),
    so it is naturally excluded.
    """
    results: dict[str, TsDiagnostic] = {}
    for ts_file in ts_files:
        if not ts_file.exists():
            continue
        try:
            source = ts_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in _TS_CALL_RE.finditer(source):
            body = m.group("body")
            code_m = _TS_CODE_RE.search(body)
            if not code_m:
                continue
            code = code_m.group("v")
            sev_m = _TS_SEV_RE.search(body)
            path_m = _TS_PATH_RE.search(body)
            owner_m = _TS_OWNER_RE.search(body)
            results[code] = TsDiagnostic(
                code=code,
                severity=sev_m.group("v") if sev_m else "",
                path_schema=path_m.group("v") if path_m else "",
                owner=owner_m.group("v") if owner_m else "",
                file=str(ts_file),
            )
    return results


# ---------------------------------------------------------------------------
# Catalog parser — delegate to existing scripts/parse_diagnostic_catalog.py
# ---------------------------------------------------------------------------


def _load_catalog_parser():  # type: ignore[return]
    """Import ``parse_diagnostic_catalog`` from the scripts directory.

    The ``scripts/`` directory is not a package, so we load it via importlib
    rather than polluting ``sys.path``.
    """
    try:
        from scripts.parse_diagnostic_catalog import (  # type: ignore[import]
            parse_diagnostic_catalog,
        )

        return parse_diagnostic_catalog
    except ImportError:
        pass

    parser_path = _REPO_ROOT / "scripts" / "parse_diagnostic_catalog.py"
    spec = importlib.util.spec_from_file_location("parse_diagnostic_catalog", parser_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load parse_diagnostic_catalog from {parser_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.parse_diagnostic_catalog


# ---------------------------------------------------------------------------
# AC 5 — same-commit catalog update enforcement
# ---------------------------------------------------------------------------


def _files_containing_py_decorators(src_dirs: list[Path]) -> list[Path]:
    """Return Python files that contain at least one ``@diagnostic_code(`` call."""
    hits: list[Path] = []
    for src_dir in src_dirs:
        if not src_dir.exists():
            continue
        for py_file in src_dir.rglob("*.py"):
            try:
                if "@diagnostic_code(" in py_file.read_text(encoding="utf-8", errors="ignore"):
                    hits.append(py_file)
            except OSError:
                pass
    return hits


def _files_containing_ts_calls(ts_files: list[Path]) -> list[Path]:
    """Return TS files that contain at least one ``registerDiagnosticValidator({`` call."""
    hits: list[Path] = []
    for ts_file in ts_files:
        if not ts_file.exists():
            continue
        try:
            if "registerDiagnosticValidator({" in ts_file.read_text(
                encoding="utf-8", errors="ignore"
            ):
                hits.append(ts_file)
        except OSError:
            pass
    return hits


def check_same_commit_catalog_update(
    git_dir: Path,
    src_dirs: list[Path],
    ts_files: list[Path],
    catalog_path: Path,
) -> list[str]:
    """Return error strings if validator files changed without a catalog update.

    Uses ``git diff --name-only HEAD~1 HEAD``.

    Trade-off — first-commit skip: if HEAD~1 does not exist (the very first
    commit on a new branch), ``git diff`` exits non-zero. In that case this
    check is skipped entirely and an empty list is returned. Subsequent commits
    on the same branch will have a parent and the check re-enables automatically.
    """
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            capture_output=True,
            text=True,
            cwd=git_dir,
            check=True,
        )
    except subprocess.CalledProcessError:
        # No parent commit — first commit on branch; skip this check.
        return []

    changed = set(proc.stdout.strip().splitlines())
    if not changed:
        return []

    # Determine catalog path relative to git_dir so it matches diff output.
    try:
        catalog_rel = str(catalog_path.resolve().relative_to(git_dir.resolve()))
    except ValueError:
        catalog_rel = str(catalog_path)

    catalog_changed = catalog_rel in changed

    # Collect validator files that (a) contain decorator calls AND (b) appear in diff.
    py_decorator_files = _files_containing_py_decorators(src_dirs)
    ts_call_files = _files_containing_ts_calls(ts_files)
    all_validator_files = py_decorator_files + ts_call_files

    changed_validator_files: list[str] = []
    for vf in all_validator_files:
        try:
            vf_rel = str(vf.resolve().relative_to(git_dir.resolve()))
        except ValueError:
            vf_rel = str(vf)
        if vf_rel in changed:
            changed_validator_files.append(vf_rel)

    if changed_validator_files and not catalog_changed:
        return [
            "SAME-COMMIT CHECK: validator file(s) were modified in this commit but "
            f"'{catalog_rel}' was not updated in the same commit. "
            f"Changed validator files: {changed_validator_files}. "
            "Update the catalog alongside every new @diagnostic_code or "
            "registerDiagnosticValidator addition."
        ]
    return []


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run the diagnostic catalog parity check. Returns 0 on success, 1 on failure."""
    parser = argparse.ArgumentParser(
        description=(
            "Verify three-way parity between the Python @diagnostic_code registry, "
            "the TypeScript registerDiagnosticValidator registry, and diagnostic_catalog.md."
        )
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=_DEFAULT_CATALOG,
        metavar="PATH",
        help="Path to diagnostic_catalog.md (default: repo-relative default).",
    )
    parser.add_argument(
        "--src-dir",
        dest="src_dirs",
        type=Path,
        action="append",
        metavar="DIR",
        help="Python source directory to scan (repeatable). Default: src/.",
    )
    parser.add_argument(
        "--ts-file",
        dest="ts_files",
        type=Path,
        action="append",
        metavar="FILE",
        help="TypeScript file to scan for registerDiagnosticValidator calls (repeatable).",
    )
    parser.add_argument(
        "--skip-git-check",
        action="store_true",
        default=False,
        help="Skip the same-commit catalog update enforcement (AC 5).",
    )
    parser.add_argument(
        "--git-dir",
        type=Path,
        default=_REPO_ROOT,
        metavar="DIR",
        help="Repository root for git diff (default: auto-detected repo root).",
    )
    args = parser.parse_args(argv)

    catalog_path: Path = args.catalog
    src_dirs: list[Path] = args.src_dirs if args.src_dirs else _DEFAULT_SRC_DIRS
    ts_files: list[Path] = args.ts_files if args.ts_files else _DEFAULT_TS_FILES
    git_dir: Path = args.git_dir

    # 1. Parse the catalog.
    try:
        parse_catalog = _load_catalog_parser()
        catalog_records = parse_catalog(catalog_path)
    except FileNotFoundError:
        print(f"ERROR: Catalog file not found: {catalog_path}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: Failed to parse catalog '{catalog_path}': {exc}", file=sys.stderr)
        return 1

    catalog: dict[str, dict] = {r["code"]: r for r in catalog_records}

    # 2. Collect Python diagnostics.
    py_diagnostics = collect_python_diagnostics(src_dirs)

    # 3. Collect TypeScript diagnostics.
    ts_diagnostics = collect_ts_diagnostics(ts_files)

    errors: list[str] = []

    # AC 2: Every Python @diagnostic_code must have a catalog entry.
    for code, py_diag in py_diagnostics.items():
        if code not in catalog:
            errors.append(
                f"[AC-2] Python validator '{code}' (in {py_diag.file}) "
                "has no entry in the diagnostic catalog."
            )

    # AC 3: Catalog entries with owner in {worker, both} require a TS implementation.
    for code, record in catalog.items():
        if record["owner"] in ("worker", "both"):
            if code not in ts_diagnostics:
                errors.append(
                    f"[AC-3] Catalog entry '{code}' has owner='{record['owner']}' "
                    "but no matching TypeScript registerDiagnosticValidator call was found."
                )

    # AC 4: Python and TS must agree on severity and path_schema for shared codes.
    for code, ts_diag in ts_diagnostics.items():
        if code not in py_diagnostics:
            continue
        py_diag = py_diagnostics[code]
        if py_diag.severity != ts_diag.severity:
            errors.append(
                f"[AC-4] Metadata divergence for '{code}': "
                f"Python severity='{py_diag.severity}' vs TS severity='{ts_diag.severity}'."
            )
        if py_diag.path_schema != ts_diag.path_schema:
            errors.append(
                f"[AC-4] Metadata divergence for '{code}': "
                f"Python path_schema='{py_diag.path_schema}' "
                f"vs TS path_schema='{ts_diag.path_schema}'."
            )

    # AC 5: Same-commit catalog update check.
    if not args.skip_git_check:
        errors.extend(
            check_same_commit_catalog_update(git_dir, src_dirs, ts_files, catalog_path)
        )

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        print(f"\nDiagnostic catalog check FAILED with {len(errors)} error(s).", file=sys.stderr)
        return 1

    print("Diagnostic catalog parity check PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
