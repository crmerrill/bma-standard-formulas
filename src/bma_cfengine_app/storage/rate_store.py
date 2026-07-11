"""Versioned rate packages: immutable, dated, approved before use.

A *rate package* is a named, versioned set of curves with an as-of date.  Runs
reference a specific version, so a run remains reproducible after someone uploads
newer rates.

    rate_packages/
      <package_id>/
        package.json           name, created_at, versions[]
        v1/
          rates.parquet        the cleaned frame
          version.json         asof_date, source_file, layout, approval, repairs

Versions are immutable once written.  Re-ingesting the same package with new data
mints v2; v1 stays exactly as the run that used it saw it.

A version is only usable once ``approve`` has been called on it.  Ingestion runs
DQ (orchestrator.rates_dq), and a version carrying unresolved blocking problems
cannot be approved — that is the gate that stops a silently-mis-scaled curve from
reaching pricing.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .run_store import APP_HOME

_RATE_PACKAGES_DIR = APP_HOME / "rate_packages"

PACKAGE_META_FILE = "package.json"
VERSION_META_FILE = "version.json"
RATES_FILE = "rates.parquet"


class RatePackageError(ValueError):
    """Raised when a rate package or version is missing, or used before approval."""


def init_rate_store() -> Path:
    _RATE_PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
    return _RATE_PACKAGES_DIR


def new_package_id() -> str:
    return uuid.uuid4().hex[:12]


def package_dir(package_id: str) -> Path:
    return _RATE_PACKAGES_DIR / package_id


def version_dir(package_id: str, version: int) -> Path:
    return package_dir(package_id) / f"v{version}"


def _read_json(p: Path) -> dict[str, Any]:
    if not p.exists():
        raise RatePackageError(f"Not found: {p}")
    return json.loads(p.read_text())


def create_package(name: str, package_id: str | None = None) -> str:
    """Create an empty package. Versions are added by ``add_version``."""
    pid = package_id or new_package_id()
    d = package_dir(pid)
    d.mkdir(parents=True, exist_ok=True)
    (d / PACKAGE_META_FILE).write_text(json.dumps({
        "package_id": pid,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "versions": [],
    }, indent=2))
    return pid


def load_package(package_id: str) -> dict[str, Any]:
    return _read_json(package_dir(package_id) / PACKAGE_META_FILE)


def list_packages() -> list[dict[str, Any]]:
    if not _RATE_PACKAGES_DIR.exists():
        return []
    out = []
    for d in sorted(_RATE_PACKAGES_DIR.iterdir()):
        meta = d / PACKAGE_META_FILE
        if meta.exists():
            out.append(json.loads(meta.read_text()))
    return out


def add_version(
    package_id: str,
    df: pd.DataFrame,
    asof_date: date | str,
    source_file: str | None = None,
    repairs_applied: list[str] | None = None,
) -> int:
    """Write a new immutable version of the package. Returns the version number.

    The version starts *unapproved*.  ``build_deck`` refuses to read it until
    ``approve`` succeeds, and approval is refused while the frame still has
    blocking DQ problems.
    """
    from ..orchestrator.rates_dq import diagnose_rates

    pkg = load_package(package_id)
    version = len(pkg["versions"]) + 1

    d = version_dir(package_id, version)
    d.mkdir(parents=True, exist_ok=True)
    df.to_parquet(d / RATES_FILE, index=False)

    diag = diagnose_rates(df)
    blocking = [p for p in diag["problems"] if p["severity"] == "blocking"]

    (d / VERSION_META_FILE).write_text(json.dumps({
        "package_id": package_id,
        "version": version,
        "asof_date": str(asof_date),
        "source_file": source_file,
        "layout": diag.get("layout"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repairs_applied": repairs_applied or [],
        "diagnosis": diag,
        "blocking_count": len(blocking),
        "approved": False,
        "approved_at": None,
    }, indent=2, default=str))

    pkg["versions"].append(version)
    (package_dir(package_id) / PACKAGE_META_FILE).write_text(
        json.dumps(pkg, indent=2, default=str)
    )
    return version


def load_version(package_id: str, version: int) -> dict[str, Any]:
    return _read_json(version_dir(package_id, version) / VERSION_META_FILE)


def approve(package_id: str, version: int, approved_by: str | None = None) -> dict[str, Any]:
    """Mark a version usable. Refuses while blocking problems remain."""
    meta = load_version(package_id, version)
    if meta["blocking_count"]:
        problems = "; ".join(
            f"{p.get('column') or 'file'}: {p['detail']}"
            for p in meta["diagnosis"]["problems"]
            if p["severity"] == "blocking"
        )
        raise RatePackageError(
            f"Cannot approve {package_id} v{version}: "
            f"{meta['blocking_count']} blocking problem(s) unresolved. {problems}"
        )

    meta["approved"] = True
    meta["approved_at"] = datetime.now(timezone.utc).isoformat()
    meta["approved_by"] = approved_by
    (version_dir(package_id, version) / VERSION_META_FILE).write_text(
        json.dumps(meta, indent=2, default=str)
    )
    return meta


def load_rates_df(package_id: str, version: int) -> pd.DataFrame:
    p = version_dir(package_id, version) / RATES_FILE
    if not p.exists():
        raise RatePackageError(f"No rates data for {package_id} v{version}")
    return pd.read_parquet(p)


def latest_approved_version(package_id: str) -> int | None:
    pkg = load_package(package_id)
    for v in reversed(pkg["versions"]):
        if load_version(package_id, v).get("approved"):
            return v
    return None


def build_deck(package_id: str, version: int | None = None):
    """Build a RateDeck from an approved package version.

    Refuses an unapproved version — that is the gate between "someone uploaded a
    file" and "we priced a portfolio with it".
    """
    from bma_standard_formulas.engine.rates import RateDeck

    if version is None:
        version = latest_approved_version(package_id)
        if version is None:
            raise RatePackageError(
                f"Package {package_id} has no approved version. "
                f"Ingest and approve one before pricing with it."
            )

    meta = load_version(package_id, version)
    if not meta.get("approved"):
        raise RatePackageError(
            f"{package_id} v{version} is not approved. It carries "
            f"{meta['blocking_count']} blocking problem(s). Resolve and approve first."
        )

    df = load_rates_df(package_id, version)
    return RateDeck.from_frame(df, name=f"{package_id}@v{version}")
