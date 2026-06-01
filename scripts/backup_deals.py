#!/usr/bin/env python3
"""scripts/backup_deals.py — operator CLI for git-bundle backups.

Per ticket irvc-5b-backup-restore.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

# Allow `python scripts/backup_deals.py` from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bma_cfengine_app.orchestrator.deals import deal_store  # noqa: E402
from bma_cfengine_app.orchestrator.deals.deal_store import deal_dir  # noqa: E402


def _backup_one_deal(deal_id: str, out_dir: Path) -> Path:
    """Create a self-contained git bundle for one deal."""
    src = deal_dir(deal_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = out_dir / f"deal_{deal_id}.bundle"
    subprocess.run(
        ["git", "bundle", "create", str(bundle_path), "--all"],
        cwd=str(src),
        check=True,
        capture_output=True,
        text=True,
    )
    return bundle_path


def _backup_tenant(tenant_id: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    tar_path = out_dir / f"tenant_{tenant_id}.tar"
    deals = [
        p
        for p in deal_store._DEALS_DIR.iterdir()
        if p.is_dir() and (p / ".git").exists()
    ]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        bundle_paths: list[Path] = []
        for deal_d in deals:
            deal_id = deal_d.name
            bundle_path = _backup_one_deal(deal_id, tmp_path)
            bundle_paths.append(bundle_path)

        with tarfile.open(tar_path, "w") as tar:
            for bp in bundle_paths:
                tar.add(bp, arcname=bp.name)

    return tar_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backup deals to git bundle files.")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--deal", help="single deal id")
    g.add_argument("--tenant", help="tenant id (Phase 1: all deals)")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.deal:
        path = _backup_one_deal(args.deal, args.out)
    else:
        path = _backup_tenant(args.tenant, args.out)
    print(f"Created {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
