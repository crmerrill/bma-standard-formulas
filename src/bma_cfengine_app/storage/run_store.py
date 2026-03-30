from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

APP_HOME = Path.home() / "PrismaRisk" / "BMA-CFEngine"

_UPLOADS_DIR = APP_HOME / "uploads"
_RUNS_DIR = APP_HOME / "runs"
_CONFIG_DIR = APP_HOME / "config"

RAW_SUBDIR = "raw"
WORKING_SUBDIR = "working"


def init_workspace() -> Path:
    """Create the user workspace on first run. Safe to call repeatedly."""
    for d in (APP_HOME, _UPLOADS_DIR, _RUNS_DIR, _CONFIG_DIR):
        d.mkdir(parents=True, exist_ok=True)
    return APP_HOME


def workspace_path() -> Path:
    return APP_HOME


def new_upload_id() -> str:
    return f"upl_{uuid.uuid4().hex[:12]}"


def new_mapping_id() -> str:
    return f"map_{uuid.uuid4().hex[:12]}"


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def upload_dir(upload_id: str) -> Path:
    p = _UPLOADS_DIR / upload_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_dir(run_id: str) -> Path:
    p = _RUNS_DIR / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Upload: raw (immutable) + working (editable) copies
# ---------------------------------------------------------------------------


def save_upload(upload_id: str, file_name: str, content: bytes) -> Path:
    """Save the original upload as an immutable raw file."""
    d = upload_dir(upload_id)
    raw_dir = d / RAW_SUBDIR
    raw_dir.mkdir(exist_ok=True)
    dest = raw_dir / file_name
    dest.write_bytes(content)
    return dest


def _raw_file(upload_id: str) -> Path:
    raw_dir = upload_dir(upload_id) / RAW_SUBDIR
    files = list(raw_dir.glob("*")) if raw_dir.exists() else []
    if not files:
        legacy = [f for f in upload_dir(upload_id).iterdir()
                  if f.is_file() and f.suffix in (".csv", ".xlsx", ".xls")]
        if legacy:
            return legacy[0]
        raise FileNotFoundError(f"No raw file for upload {upload_id}")
    return files[0]


def _working_file(upload_id: str) -> Path | None:
    working_dir = upload_dir(upload_id) / WORKING_SUBDIR
    if not working_dir.exists():
        return None
    parquet = working_dir / "tape.parquet"
    if parquet.exists():
        return parquet
    files = list(working_dir.glob("*"))
    return files[0] if files else None


def _read_file(path: Path) -> pd.DataFrame:
    ext = path.suffix.lower()
    if ext == ".parquet":
        return pd.read_parquet(path)
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path)
    return pd.read_csv(path)


def load_upload_df(upload_id: str) -> tuple[pd.DataFrame, str]:
    """Load the working copy (parquet) if it exists, otherwise the raw original."""
    working = _working_file(upload_id)
    if working:
        return _read_file(working), working.name
    raw = _raw_file(upload_id)
    return _read_file(raw), raw.name


def load_raw_df(upload_id: str) -> tuple[pd.DataFrame, str]:
    """Always load the immutable raw original."""
    raw = _raw_file(upload_id)
    return _read_file(raw), raw.name


def save_working_copy(upload_id: str, df: pd.DataFrame) -> Path:
    """Save a modified working copy as parquet. The raw file is never touched.

    Parquet preserves dtypes (int vs float, dates, categoricals) across
    read/write cycles, avoiding the float-upcast problem that CSV causes.
    """
    working_dir = upload_dir(upload_id) / WORKING_SUBDIR
    working_dir.mkdir(exist_ok=True)
    dest = working_dir / "tape.parquet"
    df.to_parquet(dest, index=False)
    return dest


def has_working_copy(upload_id: str) -> bool:
    return _working_file(upload_id) is not None


def revert_to_raw(upload_id: str) -> None:
    """Delete the working copy, reverting to the raw original."""
    working_dir = upload_dir(upload_id) / WORKING_SUBDIR
    if working_dir.exists():
        shutil.rmtree(working_dir)


# ---------------------------------------------------------------------------
# Run manifests and artifacts
# ---------------------------------------------------------------------------

INPUTS_SUBDIR = "inputs"
OUTPUTS_SUBDIR = "outputs"


def _inputs_dir(run_id: str) -> Path:
    d = run_dir(run_id) / INPUTS_SUBDIR
    d.mkdir(exist_ok=True)
    return d


def _outputs_dir(run_id: str) -> Path:
    d = run_dir(run_id) / OUTPUTS_SUBDIR
    d.mkdir(exist_ok=True)
    return d


def save_manifest(run_id: str, manifest: dict[str, Any]) -> Path:
    d = run_dir(run_id)
    p = d / "manifest.json"
    manifest.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    p.write_text(json.dumps(manifest, indent=2, default=str))
    return p


def load_manifest(run_id: str) -> dict[str, Any]:
    p = run_dir(run_id) / "manifest.json"
    if not p.exists():
        raise FileNotFoundError(f"No manifest for run {run_id}")
    return json.loads(p.read_text())


# ---------------------------------------------------------------------------
# Run inputs: tape, rates, mappings, assumptions
# ---------------------------------------------------------------------------


def save_run_inputs(
    run_id: str,
    tape_df: pd.DataFrame,
    mappings: list[dict[str, Any]],
    assumptions: dict[str, Any],
    asof_date: str | None,
    rates_df: pd.DataFrame | None = None,
    grouping: dict[str, Any] | None = None,
    run_mode: str = "actual",
    scenarios: list[dict[str, Any]] | None = None,
    dq_mapping: dict[str, Any] | None = None,
) -> None:
    """Persist all run inputs in a structured inputs/ subdirectory."""
    d = _inputs_dir(run_id)

    tape_df.to_parquet(d / "tape.parquet", index=False)
    tape_df.to_csv(d / "tape.csv", index=False)

    if rates_df is not None:
        rates_df.to_csv(d / "rates.csv", index=False)

    mapping_doc = {
        "asof_date": asof_date,
        "mappings": mappings,
    }
    (d / "mappings.json").write_text(json.dumps(mapping_doc, indent=2, default=str))

    assumptions_doc = {
        "run_mode": run_mode,
        "grouping": grouping,
        "base_assumptions": assumptions,
        "scenarios": scenarios,
    }
    (d / "assumptions.json").write_text(json.dumps(assumptions_doc, indent=2, default=str))

    if dq_mapping is not None:
        (d / "dq_mapping.json").write_text(json.dumps(dq_mapping, indent=2, default=str))


def load_run_input(run_id: str, name: str) -> pd.DataFrame:
    """Load a run input (tape or rates) as a DataFrame."""
    d = run_dir(run_id) / INPUTS_SUBDIR
    parquet = d / f"{name}.parquet"
    if parquet.exists():
        return pd.read_parquet(parquet)
    csv = d / f"{name}.csv"
    if csv.exists():
        return pd.read_csv(csv)
    legacy = run_dir(run_id) / f"{name}_snapshot.parquet"
    if legacy.exists():
        return pd.read_parquet(legacy)
    legacy_csv = run_dir(run_id) / f"{name}_snapshot.csv"
    if legacy_csv.exists():
        return pd.read_csv(legacy_csv)
    raise FileNotFoundError(f"Input '{name}' not found for run {run_id}")


def load_run_input_json(run_id: str, name: str) -> dict[str, Any]:
    """Load a JSON input file (mappings.json or assumptions.json)."""
    d = run_dir(run_id) / INPUTS_SUBDIR
    p = d / f"{name}.json"
    if p.exists():
        return json.loads(p.read_text())
    raise FileNotFoundError(f"Input '{name}' not found for run {run_id}")


def has_run_inputs(run_id: str) -> bool:
    d = run_dir(run_id) / INPUTS_SUBDIR
    return d.exists() and any(d.iterdir())


# ---------------------------------------------------------------------------
# Run outputs (artifacts)
# ---------------------------------------------------------------------------


def save_artifact(run_id: str, name: str, df: pd.DataFrame) -> Path:
    d = _outputs_dir(run_id)
    dest = d / f"{name}.parquet"
    df.to_parquet(dest, index=False)
    return dest


def save_artifact_csv(run_id: str, name: str, df: pd.DataFrame) -> Path:
    d = _outputs_dir(run_id)
    dest = d / f"{name}.csv"
    df.to_csv(dest, index=False)
    return dest


def load_artifact(run_id: str, name: str) -> pd.DataFrame:
    for subdir in (OUTPUTS_SUBDIR, "artifacts"):
        d = run_dir(run_id) / subdir
        parquet = d / f"{name}.parquet"
        if parquet.exists():
            return pd.read_parquet(parquet)
        csv = d / f"{name}.csv"
        if csv.exists():
            return pd.read_csv(csv)
    raise FileNotFoundError(f"Artifact '{name}' not found for run {run_id}")


def list_artifacts(run_id: str) -> list[str]:
    seen: set[str] = set()
    for subdir in (OUTPUTS_SUBDIR, "artifacts"):
        d = run_dir(run_id) / subdir
        if d.exists():
            for f in d.iterdir():
                if f.is_file():
                    seen.add(f.stem)
    return sorted(seen)


# ---------------------------------------------------------------------------
# Mappings
# ---------------------------------------------------------------------------


def save_mapping(upload_id: str, mapping_id: str, mapping_data: dict) -> Path:
    d = upload_dir(upload_id)
    p = d / f"{mapping_id}.json"
    p.write_text(json.dumps(mapping_data, indent=2))
    return p


def load_mapping(upload_id: str, mapping_id: str) -> dict:
    d = upload_dir(upload_id)
    p = d / f"{mapping_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"Mapping {mapping_id} not found")
    return json.loads(p.read_text())
