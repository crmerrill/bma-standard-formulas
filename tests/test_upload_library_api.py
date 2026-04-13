from __future__ import annotations

from fastapi.testclient import TestClient

from bma_cfengine_app.api.main import app


def test_list_uploads_contract(monkeypatch):
    from bma_cfengine_app.api.routers import uploads as uploads_router

    monkeypatch.setattr(
        uploads_router.run_store,
        "list_uploads",
        lambda: [
            {
                "upload_id": "upl_abc",
                "file_name": "tape.csv",
                "display_name": "Prime Jumbo Tape",
                "row_count": 100,
                "column_count": 25,
                "file_size_bytes": 1024,
                "latest_mapping_id": "map_123",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ],
    )
    client = TestClient(app)
    res = client.get("/api/uploads")
    assert res.status_code == 200
    assert res.json()["items"][0]["upload_id"] == "upl_abc"
    assert res.json()["items"][0]["display_name"] == "Prime Jumbo Tape"


def test_list_upload_mappings_contract(monkeypatch):
    from bma_cfengine_app.api.routers import uploads as uploads_router

    monkeypatch.setattr(
        uploads_router.run_store,
        "list_mappings",
        lambda upload_id: [
            {
                "mapping_id": "map_123",
                "asof_date": "2026-01-31",
                "mapped_fields": 24,
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ],
    )
    client = TestClient(app)
    res = client.get("/api/uploads/upl_abc/mappings")
    assert res.status_code == 200
    assert res.json()["upload_id"] == "upl_abc"
    assert res.json()["items"][0]["mapping_id"] == "map_123"


def test_rename_upload_contract(monkeypatch):
    from bma_cfengine_app.api.routers import uploads as uploads_router

    monkeypatch.setattr(
        uploads_router.run_store,
        "set_upload_display_name",
        lambda upload_id, display_name: {"display_name": display_name},
    )
    client = TestClient(app)
    res = client.patch("/api/uploads/upl_abc", json={"display_name": "Q2 Prime Tape"})
    assert res.status_code == 200
    assert res.json()["upload_id"] == "upl_abc"
    assert res.json()["display_name"] == "Q2 Prime Tape"
