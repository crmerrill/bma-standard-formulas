#!/usr/bin/env python3
"""scripts/restore_deal.py — operator CLI for deal restore.

Per ticket irvc-5b-backup-restore.  Locates the latest bundle for a deal
and delegates to the irvc-5a restore_deal core function.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python scripts/restore_deal.py` from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _find_latest_bundle(backups_dir: Path, deal_id: str) -> Path | None:
    """Locate the latest bundle for a specific deal.

    Strict naming contract: only matches `deal_{deal_id}.bundle` and
    `deal_{deal_id}_*.bundle` (the `_*` form reserves space for a future
    timestamp suffix). Substring matching is intentionally NOT used —
    `deal_abc.bundle` must not be a candidate when the user asks for
    deal `bc`. R1 m1 (irvc-5b) closure.
    """
    candidates = set(backups_dir.glob(f"deal_{deal_id}.bundle"))
    candidates |= set(backups_dir.glob(f"deal_{deal_id}_*.bundle"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Restore a deal from its latest backup bundle."
    )
    parser.add_argument("--deal", required=True)
    parser.add_argument("--backups", required=True, type=Path)
    args = parser.parse_args(argv)

    bundle_path = _find_latest_bundle(args.backups, args.deal)
    if bundle_path is None:
        print(
            f"No bundle found for deal {args.deal!r} in {args.backups}",
            file=sys.stderr,
        )
        return 1

    from bma_cfengine_app.orchestrator.deals.operational import restore_deal  # noqa: E402

    restore_deal(args.deal, bundle_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
