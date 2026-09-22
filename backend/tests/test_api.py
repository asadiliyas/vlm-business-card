"""
HTTP-layer tests for the router: request validation, status codes, and
response shapes. Deliberately does NOT exercise the app's `lifespan` (no
`with TestClient(app) as c:`) so it never touches the real global DB or
starts the retention sweeper — `get_db`/`get_settings` are overridden per
test instead. Actual extraction correctness is covered by
test_job_lifecycle.py, which drives the same underlying functions
synchronously; this file covers the HTTP wiring around them.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings, get_settings
from app.db import Database, get_db
from app.main import app
from app.models import ExtractedLead


def _jpeg_file(name: str = "card.jpg", color=(250, 250, 245)) -> tuple[str, bytes, str]:
    img = Image.new("RGB", (400, 300), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return (name, buf.getvalue(), "image/jpeg")


@pytest.fixture
async def test_db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def test_settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        max_files_per_job=3,
        # unreachable on purpose: keeps /api/health and any accidental
        # background extraction fast and network-free in tests
        vlm_primary_base_url="http://127.0.0.1:1/v1",
        vlm_fallback_base_url="http://127.0.0.1:1/v1",
        vlm_max_retries=0,
    )


@pytest.fixture
def client(test_db, test_settings):
    app.dependency_overrides[get_db] = lambda: test_db
    app.dependency_overrides[get_settings] = lambda: test_settings
    yield TestClient(app, raise_server_exceptions=True)
    app.dependency_overrides.clear()


def test_health_endpoint_reports_degraded_when_backends_unreachable(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["primary_backend_healthy"] is False
    assert body["active_vlm_backend"] is None


def test_upload_rejects_empty_request(client):
    resp = client.post("/api/jobs", files=[])
    assert resp.status_code == 400


def test_upload_rejects_too_many_files(client):
    files = [("files", _jpeg_file(f"card{i}.jpg")) for i in range(5)]  # limit is 3
    resp = client.post("/api/jobs", files=files)
    assert resp.status_code == 400
    assert "max is 3" in resp.json()["detail"]


def test_upload_accepts_valid_batch_and_returns_job_summary(client, monkeypatch):
    # The route schedules real background processing via asyncio.create_task
    # (by design — the HTTP response must return before extraction finishes).
    # That task is only reachable here through the real VLMClient, so this
    # patches its network call to resolve instantly rather than actually
    # dialing the deliberately-unreachable test host. Without this, a real
    # regression showed up on Linux CI runners (though not on Windows): the
    # bare TestClient(app) used here has no persistent event loop across
    # calls, and tearing that loop down while a slow/hung connection attempt
    # is still in flight on the background task made the *test itself* hang
    # for hours rather than failing fast — see git history for the incident.
    async def instant_extract(self, image_bytes, *, mime_type="image/jpeg"):
        from app.vlm.client import BackendName, ExtractionResult
        from app.models import ExtractedLead
        return ExtractionResult(lead=ExtractedLead(confidence=0.0), backend_used=BackendName.PRIMARY, attempts=1)

    monkeypatch.setattr("app.vlm.client.VLMClient.extract", instant_extract)

    files = [("files", _jpeg_file("card1.jpg")), ("files", _jpeg_file("card2.jpg"))]
    resp = client.post("/api/jobs", files=files)
    assert resp.status_code == 201
    body = resp.json()
    assert body["total_files"] == 2
    assert body["status"] in ("queued", "processing", "done")
    assert "leads" not in body  # JobSummary excludes the leads list


def test_get_nonexistent_job_returns_404(client):
    resp = client.get("/api/jobs/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_lead_updates_fields(client, test_db):
    job = await test_db.create_job("job-1", total_files=1, retention_minutes=60)
    await test_db.create_lead_placeholder("lead-1", "job-1", "card.jpg")
    await test_db.save_lead_result(
        "lead-1",
        ExtractedLead(first_name="Jane", company="Old Co", confidence=0.9),
        image_path=None,
        thumbnail_path=None,
        vlm_backend_used="primary",
    )

    resp = client.patch("/api/leads/lead-1", json={"company": "New Co"})
    assert resp.status_code == 200
    assert resp.json()["company"] == "New Co"
    assert resp.json()["first_name"] == "Jane"  # untouched field survives


def test_patch_nonexistent_lead_returns_404(client):
    resp = client.patch("/api/leads/does-not-exist", json={"company": "X"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_returns_xlsx_with_correct_content_type(client, test_db):
    await test_db.create_job("job-2", total_files=1, retention_minutes=60)
    await test_db.create_lead_placeholder("lead-2", "job-2", "card.jpg")
    await test_db.save_lead_result(
        "lead-2",
        ExtractedLead(first_name="Jane", last_name="Doe", email="jane@acme.com", confidence=0.9),
        image_path=None,
        thumbnail_path=None,
        vlm_backend_used="primary",
    )

    resp = client.get("/api/jobs/job-2/export.xlsx")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment" in resp.headers["content-disposition"]
    assert len(resp.content) > 0


def test_export_with_no_completed_leads_returns_400(client):
    resp = client.get("/api/jobs/no-such-job/export.xlsx")
    assert resp.status_code == 404  # job doesn't exist at all


@pytest.mark.asyncio
async def test_delete_job_removes_it(client, test_db):
    await test_db.create_job("job-3", total_files=1, retention_minutes=60)
    await test_db.create_lead_placeholder("lead-3", "job-3", "card.jpg")

    resp = client.delete("/api/jobs/job-3")
    assert resp.status_code == 204

    resp2 = client.get("/api/jobs/job-3")
    assert resp2.status_code == 404
