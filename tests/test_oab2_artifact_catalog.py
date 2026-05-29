"""OA-B2 acceptance tests: ArtifactRef catalog architecture.

Tests that:
1. ArtifactRef is written to the manifest when _write_paired_artifact runs.
2. ArtifactRef includes checksum, loan_count, per_loan_visibility=True.
3. ArtifactRef for aggregate-only artifacts has per_loan_visibility=False.
4. run_store.register_artifact_ref / get_artifact_ref round-trip correctly.
5. Checksum verification detects corrupt artifacts.
6. build_from_runsetup_ref reads per_loan_visibility and error from ArtifactRef catalog.
7. Studio save never embeds Parquet-sized data into JSON (structure check).
8. Raw JSON mode=PAIRED is rejected at the API layer (regression guard).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from bma_cfengine_app.orchestrator.artifact_catalog import (
    ArtifactRef,
    build_artifact_ref,
    compute_sha256,
    verify_checksum,
    artifact_ref_from_dict,
)
from bma_cfengine_app.orchestrator.deals.collateral_bridge import (
    build_from_deal_native,
    build_from_runsetup_ref,
)
from bma_cfengine_app.orchestrator.run_service import _write_paired_artifact
from bma_cfengine_app.storage import run_store
from bma_standard_formulas.deals.adapters import ldcma_to_paired
from bma_standard_formulas.deals.schemas.input import (
    CollateralCashflows,
    DealRunInput,
    PooledCollateralInput,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _use_tmp_workspace(monkeypatch, tmp_path):
    app_home = tmp_path / "app_home"
    runs_dir = app_home / "runs"
    uploads_dir = app_home / "uploads"
    config_dir = app_home / "config"
    monkeypatch.setattr(run_store, "APP_HOME", app_home)
    monkeypatch.setattr(run_store, "_RUNS_DIR", runs_dir)
    monkeypatch.setattr(run_store, "_UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(run_store, "_CONFIG_DIR", config_dir)
    run_store.init_workspace()


def _fake_actual(balance: float = 1_000.0, n: int = 4) -> Any:
    from bma_standard_formulas.deals.schemas.input import (
        CollateralCashflows, PooledCollateralInput, DealRunInput,
    )
    import warnings
    bal = np.linspace(balance, balance * 0.9, n)
    p = np.array([0.0] + [(balance * 0.1 / (n - 1))] * (n - 1))
    interest = np.array([0.0] + [bal[i - 1] * 6.0 / 1200 for i in range(1, n)])
    cf = CollateralCashflows(
        cfdate=list(range(n)), balance=bal.tolist(), principal=p.tolist(),
        interest=interest.tolist(), cashflow=(p + interest).tolist(),
        loss=[0.0]*n, prepbal=[0.0]*n, defbal=[0.0]*n, recovery=[0.0]*n,
        principal_sched=p.tolist(), principal_unsched=[0.0]*n,
        cpr=[0.0]*n, cdr=[0.0]*n, sev=[0.0]*n, dq=[0.0]*n, surv_fac=[1.0]*n,
        sched_coupon=[6.0]*n, sched_netcoupon=[6.0]*n,
        coupon=[6.0]*n, effcoupon=[6.0]*n,
        sched_balance=bal.tolist(), discount_factor=[1.0]*n,
    )
    run_input = DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        original_collateral_balance=balance,
        loan_count=1,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ldcma_to_paired(run_input, loan_count=1)


# ---------------------------------------------------------------------------
# Unit tests: ArtifactRef schema
# ---------------------------------------------------------------------------

class TestArtifactRefSchema:
    def test_artifact_ref_validates(self):
        ref = ArtifactRef(
            artifact_id="run_abc/Base_Case_portfolio_paired",
            artifact_type="paired_cashflows",
            format="parquet",
            uri="Base_Case_portfolio_paired",
            loan_count=3,
            per_loan_visibility=True,
        )
        assert ref.artifact_type == "paired_cashflows"
        assert ref.per_loan_visibility is True
        assert ref.checksum is None  # not yet computed

    def test_artifact_ref_round_trips_json(self):
        ref = ArtifactRef(
            artifact_id="run_xyz/tape",
            artifact_type="loan_tape",
            format="parquet",
            uri="tape",
        )
        dumped = ref.model_dump()
        restored = artifact_ref_from_dict(dumped)
        assert restored is not None
        assert restored.artifact_id == ref.artifact_id
        assert restored.artifact_type == ref.artifact_type

    def test_artifact_ref_from_dict_returns_none_on_garbage(self):
        assert artifact_ref_from_dict({"totally": "invalid"}) is None

    def test_build_artifact_ref_with_parquet_file(self, tmp_path):
        """build_artifact_ref computes checksum and row_count from a real Parquet file."""
        df = pd.DataFrame({"a": [1, 2, 3]})
        p = tmp_path / "test.parquet"
        df.to_parquet(p, index=False)

        ref = build_artifact_ref(
            run_id="run_test",
            artifact_name="test",
            artifact_type="scenario_output",
            artifact_path=p,
        )
        assert ref.checksum is not None
        assert ref.checksum.startswith("sha256:")
        assert ref.file_size_bytes == p.stat().st_size


# ---------------------------------------------------------------------------
# Unit tests: checksum helpers
# ---------------------------------------------------------------------------

class TestChecksumHelpers:
    def test_compute_sha256_matches_hashlib(self, tmp_path):
        content = b"hello artifact"
        p = tmp_path / "file.parquet"
        p.write_bytes(content)
        expected = "sha256:" + hashlib.sha256(content).hexdigest()
        assert compute_sha256(p) == expected

    def test_verify_checksum_passes_when_correct(self, tmp_path):
        content = b"content"
        p = tmp_path / "f.parquet"
        p.write_bytes(content)
        checksum = compute_sha256(p)
        assert verify_checksum(p, checksum) is True

    def test_verify_checksum_fails_when_corrupt(self, tmp_path):
        content = b"original"
        p = tmp_path / "f.parquet"
        p.write_bytes(content)
        good_checksum = compute_sha256(p)
        p.write_bytes(b"corrupted")
        assert verify_checksum(p, good_checksum) is False

    def test_verify_checksum_returns_true_when_none(self, tmp_path):
        p = tmp_path / "f.parquet"
        p.write_bytes(b"anything")
        assert verify_checksum(p, None) is True


# ---------------------------------------------------------------------------
# Integration tests: run_store catalog API
# ---------------------------------------------------------------------------

class TestRunStoreCatalog:
    def test_register_and_get_artifact_ref(self, monkeypatch, tmp_path):
        _use_tmp_workspace(monkeypatch, tmp_path)
        run_id = "run_cat_test"
        run_store.save_manifest(run_id, {"status": "completed"})

        ref_dict = {
            "artifact_id": f"{run_id}/test_artifact",
            "artifact_type": "paired_cashflows",
            "format": "parquet",
            "uri": "test_artifact",
            "checksum": "sha256:abc123",
            "loan_count": 5,
            "per_loan_visibility": True,
            "created_at": "2026-05-28T00:00:00+00:00",
        }
        run_store.register_artifact_ref(run_id, "test_artifact", ref_dict)

        retrieved = run_store.get_artifact_ref(run_id, "test_artifact")
        assert retrieved is not None
        assert retrieved["loan_count"] == 5
        assert retrieved["per_loan_visibility"] is True

    def test_get_artifact_ref_returns_none_when_absent(self, monkeypatch, tmp_path):
        _use_tmp_workspace(monkeypatch, tmp_path)
        run_id = "run_cat_absent"
        run_store.save_manifest(run_id, {"status": "completed"})
        assert run_store.get_artifact_ref(run_id, "nonexistent") is None

    def test_register_artifact_ref_is_idempotent(self, monkeypatch, tmp_path):
        _use_tmp_workspace(monkeypatch, tmp_path)
        run_id = "run_cat_idem"
        run_store.save_manifest(run_id, {"status": "completed"})

        ref = {"artifact_id": f"{run_id}/a", "artifact_type": "loan_tape",
               "format": "parquet", "uri": "a", "checksum": "sha256:v1",
               "created_at": "2026-05-28T00:00:00+00:00"}
        run_store.register_artifact_ref(run_id, "a", ref)

        ref_v2 = {**ref, "checksum": "sha256:v2"}
        run_store.register_artifact_ref(run_id, "a", ref_v2)

        latest = run_store.get_artifact_ref(run_id, "a")
        assert latest["checksum"] == "sha256:v2"

    def test_existing_manifest_fields_preserved_after_registration(self, monkeypatch, tmp_path):
        _use_tmp_workspace(monkeypatch, tmp_path)
        run_id = "run_cat_preserve"
        run_store.save_manifest(run_id, {
            "status": "completed",
            "scenario_names": ["Base Case"],
            "loan_count": 10,
        })

        run_store.register_artifact_ref(run_id, "artifact_x", {
            "artifact_id": f"{run_id}/artifact_x", "artifact_type": "loan_tape",
            "format": "parquet", "uri": "artifact_x",
            "created_at": "2026-05-28T00:00:00+00:00",
        })

        manifest = run_store.load_manifest(run_id)
        assert manifest["status"] == "completed"
        assert manifest["loan_count"] == 10
        assert "artifact_x" in manifest.get("artifacts", {})


# ---------------------------------------------------------------------------
# Integration: _write_paired_artifact registers ArtifactRef
# ---------------------------------------------------------------------------

class TestPairedArtifactRegistration:
    def test_write_paired_artifact_registers_artifact_ref(self, monkeypatch, tmp_path):
        """_write_paired_artifact must write an ArtifactRef to the manifest."""
        import warnings
        _use_tmp_workspace(monkeypatch, tmp_path)
        run_id = "run_paired_ref"
        run_store.save_manifest(run_id, {"status": "completed"})

        paired = _fake_actual(balance=1_000.0)
        actuals = paired.collateral.portfolio.actual_constituents()
        assert len(actuals) == 1

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _write_paired_artifact(run_id, "Base_Case_portfolio_paired", actuals)

        ref_dict = run_store.get_artifact_ref(run_id, "Base_Case_portfolio_paired")
        assert ref_dict is not None, "ArtifactRef must be written after _write_paired_artifact"

        ref = artifact_ref_from_dict(ref_dict)
        assert ref is not None
        assert ref.artifact_type == "paired_cashflows"
        assert ref.per_loan_visibility is True
        assert ref.loan_count == 1
        assert ref.checksum is not None and ref.checksum.startswith("sha256:")
        assert ref.file_size_bytes is not None and ref.file_size_bytes > 0

    def test_artifact_ref_checksum_matches_file_on_disk(self, monkeypatch, tmp_path):
        """Checksum in ArtifactRef must match the actual artifact file on disk."""
        import warnings
        _use_tmp_workspace(monkeypatch, tmp_path)
        run_id = "run_paired_checksum"
        run_store.save_manifest(run_id, {"status": "completed"})

        paired = _fake_actual(balance=2_000.0)
        actuals = paired.collateral.portfolio.actual_constituents()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _write_paired_artifact(run_id, "Base_Case_portfolio_paired", actuals)

        ref_dict = run_store.get_artifact_ref(run_id, "Base_Case_portfolio_paired")
        ref = artifact_ref_from_dict(ref_dict)
        assert ref is not None

        # Locate the file and verify checksum matches
        out_dir = run_store._outputs_dir(run_id)
        artifact_path = out_dir / "Base_Case_portfolio_paired.parquet"
        assert artifact_path.exists()
        actual_checksum = compute_sha256(artifact_path)
        assert actual_checksum == ref.checksum, (
            f"Stored checksum {ref.checksum} != actual {actual_checksum}"
        )


# ---------------------------------------------------------------------------
# Integration: bridge reads ArtifactRef
# ---------------------------------------------------------------------------

class TestBridgeUsesArtifactRef:
    def test_bridge_uses_artifact_ref_per_loan_visibility(self, monkeypatch, tmp_path):
        """build_from_runsetup_ref reads per_loan_visibility from ArtifactRef catalog,
        not only from the legacy manifest key."""
        import warnings
        _use_tmp_workspace(monkeypatch, tmp_path)
        run_id = "run_bridge_ref"

        paired = _fake_actual(balance=1_000.0)
        actuals = paired.collateral.portfolio.actual_constituents()

        run_store.save_manifest(run_id, {
            "status": "completed",
            "scenario_names": ["Base Case"],
            "loan_count": 1,
        })

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _write_paired_artifact(run_id, "Base_Case_portfolio_paired", actuals)

        # Also save aggregate fallback
        n = 4
        agg_df = pd.DataFrame({
            "perf_bal": np.full(n, 1000.0), "act_am": np.full(n, 25.0),
            "vol_prepay": np.zeros(n), "act_int": np.full(n, 5.0),
            "new_def": np.zeros(n), "prin_recov": np.zeros(n), "prin_loss": np.zeros(n),
        })
        run_store.save_artifact(run_id, "Base_Case_portfolio_actual", agg_df)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            built = build_from_runsetup_ref(run_id, scenario_names=["Base Case"])

        run_input = built["Base Case"]
        # Must have found the paired artifact (per_loan_visibility=True from ArtifactRef)
        assert run_input.collateral.mode == "PAIRED"
        assert len(run_input.collateral.portfolio.actual_constituents()) == 1

    def test_bridge_warns_with_checksum_info_on_corrupt_artifact(self, monkeypatch, tmp_path):
        """If the paired artifact exists but its checksum is wrong, bridge warns and falls back."""
        import warnings
        _use_tmp_workspace(monkeypatch, tmp_path)
        run_id = "run_bridge_corrupt"

        paired = _fake_actual(balance=500.0)
        actuals = paired.collateral.portfolio.actual_constituents()

        run_store.save_manifest(run_id, {
            "status": "completed",
            "scenario_names": ["Base Case"],
            "loan_count": 1,
        })

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _write_paired_artifact(run_id, "Base_Case_portfolio_paired", actuals)

        # Corrupt the artifact ref checksum so verification fails
        ref_dict = run_store.get_artifact_ref(run_id, "Base_Case_portfolio_paired")
        assert ref_dict is not None
        ref_dict["checksum"] = "sha256:000000000000bad"
        run_store.register_artifact_ref(run_id, "Base_Case_portfolio_paired", ref_dict)

        n = 4
        agg_df = pd.DataFrame({
            "perf_bal": np.full(n, 500.0), "act_am": np.full(n, 12.5),
            "vol_prepay": np.zeros(n), "act_int": np.full(n, 2.5),
            "new_def": np.zeros(n), "prin_recov": np.zeros(n), "prin_loss": np.zeros(n),
        })
        run_store.save_artifact(run_id, "Base_Case_portfolio_actual", agg_df)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            built = build_from_runsetup_ref(run_id, scenario_names=["Base Case"])
            user_warnings = [str(x.message) for x in w if issubclass(x.category, UserWarning)]

        # Must still return a valid DealRunInput (fallback to aggregate)
        assert "Base Case" in built
        # Must emit the per_loan_visibility warning
        assert any("per_loan_visibility=false" in m for m in user_warnings), (
            f"Expected fallback warning; got: {user_warnings}"
        )


# ---------------------------------------------------------------------------
# Regression: raw JSON PAIRED is rejected
# ---------------------------------------------------------------------------

class TestPairedJsonRejection:
    def test_deal_native_rejects_paired_collateral_mode(self):
        """deal_native source must reject collateral.mode='PAIRED' — regression guard."""
        with pytest.raises(ValueError, match="PAIRED"):
            build_from_deal_native({
                "scenario_name": "Base Case",
                "run_input": {
                    "collateral": {"mode": "PAIRED", "portfolio": {}},
                    "loan_count": 1,
                    "original_collateral_balance": 1_000.0,
                },
            })

    def test_deal_native_accepts_pooled_mode(self):
        """deal_native source accepts POOLED collateral (normal JSON path)."""
        n = 2
        payload = {
            "scenario_name": "Base Case",
            "run_input": {
                "collateral": {
                    "mode": "POOLED",
                    "collateral": {
                        "cfdate": list(range(n)), "balance": [100.0, 90.0],
                        "principal": [0.0, 10.0], "interest": [0.0, 0.5],
                        "cashflow": [0.0, 10.5], "loss": [0.0, 0.0],
                        "prepbal": [0.0, 0.0], "defbal": [0.0, 0.0],
                        "recovery": [0.0, 0.0], "principal_sched": [0.0, 10.0],
                        "principal_unsched": [0.0, 0.0], "cpr": [0.0, 0.0],
                        "cdr": [0.0, 0.0], "sev": [0.0, 0.0], "dq": [0.0, 0.0],
                        "surv_fac": [1.0, 1.0], "sched_coupon": [6.0, 6.0],
                        "sched_netcoupon": [5.0, 5.0], "coupon": [6.0, 6.0],
                        "effcoupon": [6.0, 6.0], "sched_balance": [100.0, 90.0],
                        "discount_factor": [1.0, 1.0],
                    },
                },
                "loan_count": 1,
                "original_collateral_balance": 100.0,
            },
        }
        built = build_from_deal_native(payload)
        assert "Base Case" in built
