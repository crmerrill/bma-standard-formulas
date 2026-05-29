"""ArtifactRef: typed metadata for every large artifact produced by the orchestrator.

OA-B2 (Round 3, May 2026):
  JSON is for small, declarative, versioned, human-reviewable configuration and
  manifests.  Parquet/Arrow is for large, typed, numerical, tabular, or per-period
  / per-loan artifacts.  This module provides the schema that explicitly links the
  two: each large artifact is described by an ``ArtifactRef`` entry in the run
  manifest, so callers read artifact metadata from the manifest rather than guessing
  paths by naming convention.

Design:
  - ``ArtifactRef`` is a lightweight Pydantic model that lives inside ``manifest.json``
    under the top-level ``"artifacts"`` dict (keyed by artifact_name).
  - ``register_artifact_ref`` atomically adds a ref to the manifest.
  - ``get_artifact_ref`` retrieves and validates a ref from the manifest.
  - Checksums are computed on write so read failures are actionable.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Type vocabulary
# ---------------------------------------------------------------------------

ArtifactType = Literal[
    "paired_cashflows",      # per-loan BMAActualCashflow constituents (Parquet)
    "scenario_output",       # bond cashflows, waterfall trace, etc. (Parquet)
    "loan_tape",             # input tape (Parquet)
    "rates",                 # rate curve table (Parquet or CSV)
    "prospectus_tieout",     # expected prospectus tables (Parquet)
    "deal_snapshot",         # canonical DealDefinition JSON
    "studio_workspace",      # Blockly workspace state JSON (layout only)
    "assumptions",           # run scenario assumptions (JSON)
    "other",
]

ArtifactFormat = Literal["parquet", "json", "csv", "arrow"]


# ---------------------------------------------------------------------------
# ArtifactRef schema
# ---------------------------------------------------------------------------

class ArtifactRef(BaseModel):
    """Immutable metadata record for a single artifact produced during a run.

    Stored in the run manifest under ``manifest["artifacts"][artifact_name]``.
    Allows any consumer to locate, validate, and load the artifact without
    knowledge of the orchestrator's internal naming conventions.
    """

    artifact_id: str = Field(
        description="Stable opaque identifier, usually '<run_id>/<artifact_name>'.",
    )
    artifact_type: ArtifactType
    format: ArtifactFormat = "parquet"

    # Run-relative URI — the name passed to run_store.save_artifact / save_artifact_raw.
    # Consumers resolve the full path via run_store.load_artifact(run_id, uri).
    uri: str = Field(description="run_store artifact name (key into outputs/ directory).")

    # Integrity
    checksum: str | None = Field(
        default=None,
        description="SHA-256 hex digest of the artifact file. "
                    "'sha256:<hex>' format. None when checksum not computed.",
    )
    checksum_algorithm: Literal["sha256", "none"] = "sha256"

    # Size / shape metadata
    row_count: int | None = None
    loan_count: int | None = None
    period_count: int | None = None
    column_count: int | None = None
    file_size_bytes: int | None = None

    # Provenance
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    schema_version: str | None = None

    # Per-loan visibility flag (for paired_cashflows artifacts).
    # True when the artifact contains genuine per-loan constituents.
    # False when it was written as an aggregate-only fallback.
    per_loan_visibility: bool | None = None

    # Free-form semantic annotations (e.g. {"scenario": "Base Case", "group": "GROUP_1"})
    semantic_tags: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Checksum helpers
# ---------------------------------------------------------------------------

def compute_sha256(path: Path) -> str:
    """Compute the SHA-256 checksum of a file; returns 'sha256:<hex>'."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def verify_checksum(path: Path, expected: str | None) -> bool:
    """Return True if the file matches the expected checksum, or if expected is None."""
    if expected is None:
        return True
    if not path.exists():
        return False
    actual = compute_sha256(path)
    return actual == expected


# ---------------------------------------------------------------------------
# Catalog helpers (used by run_store)
# ---------------------------------------------------------------------------

def build_artifact_ref(
    *,
    run_id: str,
    artifact_name: str,
    artifact_type: ArtifactType,
    artifact_path: Path | None = None,
    format: ArtifactFormat = "parquet",
    row_count: int | None = None,
    loan_count: int | None = None,
    period_count: int | None = None,
    per_loan_visibility: bool | None = None,
    schema_version: str | None = None,
    semantic_tags: dict[str, str] | None = None,
) -> ArtifactRef:
    """Construct an ArtifactRef, computing checksum and file size from disk if path given."""
    checksum: str | None = None
    file_size_bytes: int | None = None
    column_count: int | None = None

    if artifact_path is not None and artifact_path.exists():
        checksum = compute_sha256(artifact_path)
        file_size_bytes = artifact_path.stat().st_size
        # Infer row/column count for Parquet artifacts without loading full data.
        if format == "parquet":
            try:
                import pyarrow.parquet as pq  # type: ignore[import]
                meta = pq.read_metadata(artifact_path)
                if row_count is None:
                    row_count = meta.num_rows
                column_count = meta.num_columns
            except Exception:
                pass  # non-critical; skip if PyArrow not available or file unreadable

    return ArtifactRef(
        artifact_id=f"{run_id}/{artifact_name}",
        artifact_type=artifact_type,
        format=format,
        uri=artifact_name,
        checksum=checksum,
        file_size_bytes=file_size_bytes,
        row_count=row_count,
        loan_count=loan_count,
        period_count=period_count,
        column_count=column_count,
        per_loan_visibility=per_loan_visibility,
        schema_version=schema_version,
        semantic_tags=semantic_tags or {},
    )


def artifact_ref_from_dict(data: dict[str, Any]) -> ArtifactRef | None:
    """Parse an ArtifactRef from a manifest dict entry; return None on failure."""
    try:
        return ArtifactRef.model_validate(data)
    except Exception:
        return None
