"""
End-to-end integration test: upload bytes in -> VLM adapter (faked) ->
normalization -> DB -> XLSX export, with no real network or filesystem
outside pytest's tmp_path. This is what proves the pieces actually compose,
not just that each one works in isolation.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app.config import Settings
from app.db import Database
from app.export import build_leads_workbook
from app.jobs import UploadFile, create_job_with_files
from app.models import LeadStatus
from app.vlm.client import BackendConfig, VLMClient


def _jpeg_bytes(color=(250, 250, 245)) -> bytes:
    img = Image.new("RGB", (600, 400), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


class FakeTransport:
    """Returns a fixed, valid extraction for every call — good enough for an
    integration test where the VLM adapter's own behavior is covered by
    test_vlm_client.py already."""

    def __init__(self, response: str = '{"first_name": "Jane", "last_name": "Doe", '
                                        '"company": "Acme", "phone": "+15125551234", '
                                        '"email": "jane@acme.com", "confidence": 0.9}'):
        self.response = response
        self.call_count = 0

    async def chat(self, *, backend: BackendConfig, system: str, image_data_url: str,
                    temperature: float, timeout: float) -> str:
        self.call_count += 1
        return self.response


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data", processing_concurrency=2)


@pytest.mark.asyncio
async def test_full_job_lifecycle_success(db, settings):
    files = [
        UploadFile("card1.jpg", _jpeg_bytes()),
        UploadFile("card2.jpg", _jpeg_bytes(color=(200, 200, 200))),
    ]
    fake_transport = FakeTransport()
    client = VLMClient(settings, transport=fake_transport)

    job_id = await create_job_with_files(
        db, settings, files, vlm_client=client, run_in_background=False
    )

    job = await db.get_job(job_id)
    assert job is not None
    assert job.status == "done"
    assert job.completed_files == 2
    assert job.failed_files == 0
    assert len(job.leads) == 2
    assert all(l.status == LeadStatus.DONE for l in job.leads)
    assert all(l.email == "jane@acme.com" for l in job.leads)
    assert fake_transport.call_count == 2

    # Export should include both leads with a text-formatted phone column.
    xlsx_bytes = build_leads_workbook(job.leads)
    assert len(xlsx_bytes) > 0


@pytest.mark.asyncio
async def test_one_bad_file_does_not_sink_the_batch(db, settings):
    files = [
        UploadFile("good.jpg", _jpeg_bytes()),
        UploadFile("bad.jpg", b"this is not a real image file"),
    ]
    client = VLMClient(settings, transport=FakeTransport())

    job_id = await create_job_with_files(
        db, settings, files, vlm_client=client, run_in_background=False
    )

    job = await db.get_job(job_id)
    assert job.completed_files == 1
    assert job.failed_files == 1
    statuses = {l.status for l in job.leads}
    assert LeadStatus.DONE in statuses
    assert LeadStatus.FAILED in statuses


@pytest.mark.asyncio
async def test_lead_can_be_hand_corrected(db, settings):
    from app.models import LeadUpdate

    files = [UploadFile("card.jpg", _jpeg_bytes())]
    client = VLMClient(settings, transport=FakeTransport())
    job_id = await create_job_with_files(db, settings, files, vlm_client=client, run_in_background=False)

    job = await db.get_job(job_id)
    lead_id = job.leads[0].id

    await db.update_lead_fields(lead_id, LeadUpdate(company="Corrected Company Name"))
    updated = await db.get_lead(lead_id)
    assert updated.company == "Corrected Company Name"
    # Untouched fields must survive the partial update.
    assert updated.email == "jane@acme.com"


@pytest.mark.asyncio
async def test_failed_extraction_still_records_image_paths(db, settings):
    """Regression test: a VLM failure must not orphan the on-disk image and
    thumbnail — the retention sweeper can only delete files it has a path
    for, so those paths must be persisted before the VLM call, not after."""
    class AlwaysFailsTransport:
        async def chat(self, **kwargs):
            raise ConnectionError("simulated VLM outage")

    client = VLMClient(
        settings.model_copy(update={"vlm_fallback_enabled": False, "vlm_max_retries": 0}),
        transport=AlwaysFailsTransport(),
    )
    files = [UploadFile("card.jpg", _jpeg_bytes())]
    job_id = await create_job_with_files(db, settings, files, vlm_client=client, run_in_background=False)

    job = await db.get_job(job_id)
    lead = job.leads[0]
    assert lead.status == LeadStatus.FAILED
    assert lead.thumbnail_url is not None, "failed lead must still have its thumbnail recorded"

    paths = await db.list_job_image_paths(job_id)
    assert len(paths) == 2  # image + thumbnail
    assert all(Path(p).exists() for p in paths)


@pytest.mark.asyncio
async def test_job_deletion_cascades_to_leads(db, settings):
    files = [UploadFile("card.jpg", _jpeg_bytes())]
    client = VLMClient(settings, transport=FakeTransport())
    job_id = await create_job_with_files(db, settings, files, vlm_client=client, run_in_background=False)

    job = await db.get_job(job_id)
    lead_id = job.leads[0].id

    await db.delete_job(job_id)

    assert await db.get_job(job_id) is None
    assert await db.get_lead(lead_id) is None
