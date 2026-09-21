"""
The job engine: takes a batch of uploaded files, persists placeholder rows
immediately (so the UI can show "queued" for every file right away), then
processes them with bounded concurrency so one 40-card batch doesn't open 40
simultaneous VLM connections. One bad file fails its own row only — it never
sinks the batch.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from app.config import Settings
from app.db import Database
from app.image_pipeline import (
    ImageTooLargeError,
    UnsupportedImageError,
    preprocess_image,
    validate_upload,
)
from app.models import JobStatus
from app.postprocess import postprocess_lead
from app.vlm.client import VLMClient, VLMError

logger = logging.getLogger("app.jobs")


class UploadFile:
    """Minimal duck-typed shape so this module doesn't import FastAPI's UploadFile,
    keeping it importable (and testable) without a running app."""

    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self.data = data


async def create_job_with_files(
    db: Database,
    settings: Settings,
    files: list[UploadFile],
    *,
    vlm_client: VLMClient | None = None,
    run_in_background: bool = True,
) -> str:
    """
    `vlm_client` is injectable so tests can drive the whole job lifecycle
    against a scripted fake instead of a real network call. `run_in_background`
    defaults to True for the API (upload returns immediately, a background
    task processes the batch); tests pass False to await completion
    deterministically instead of polling.
    """
    job_id = str(uuid.uuid4())
    await db.create_job(job_id, total_files=len(files), retention_minutes=settings.retention_minutes)

    lead_ids: list[tuple[str, UploadFile]] = []
    for f in files:
        lead_id = str(uuid.uuid4())
        await db.create_lead_placeholder(lead_id, job_id, f.filename)
        lead_ids.append((lead_id, f))

    coro = _run_job(db, settings, job_id, lead_ids, vlm_client=vlm_client)
    if run_in_background:
        asyncio.create_task(coro)
    else:
        await coro
    return job_id


async def _run_job(
    db: Database,
    settings: Settings,
    job_id: str,
    lead_ids: list[tuple[str, "UploadFile"]],
    *,
    vlm_client: VLMClient | None = None,
) -> None:
    await db.set_job_status(job_id, JobStatus.PROCESSING)
    client = vlm_client or VLMClient(settings)
    semaphore = asyncio.Semaphore(settings.processing_concurrency)

    async def process_one(lead_id: str, upload: UploadFile) -> None:
        async with semaphore:
            await _process_single_card(db, settings, client, lead_id, upload)

    await asyncio.gather(*(process_one(lid, f) for lid, f in lead_ids))
    await db.set_job_status(job_id, JobStatus.DONE)


async def _process_single_card(
    db: Database, settings: Settings, client: VLMClient, lead_id: str, upload: UploadFile
) -> None:
    job_id_for_progress = None
    try:
        await db.mark_lead_processing(lead_id)
        lead_row = await db.get_lead(lead_id)
        job_id_for_progress = lead_row.job_id if lead_row else None

        mime = validate_upload(
            upload.data,
            max_bytes=int(settings.max_file_mb * 1_000_000),
            allowed_mime_types=settings.allowed_mime_types,
        )
        processed = preprocess_image(
            upload.data,
            long_edge_px=settings.image_long_edge_px,
            thumbnail_px=settings.thumbnail_px,
        )

        image_path = settings.uploads_dir / f"{lead_id}.jpg"
        thumb_path = settings.thumbnails_dir / f"{lead_id}.jpg"
        image_path.write_bytes(processed.jpeg_bytes)
        thumb_path.write_bytes(processed.thumbnail_bytes)
        # Recorded now, before the VLM call — so a failed extraction still
        # leaves the retention sweeper able to find and delete these files,
        # and the UI can still show the card's thumbnail for a failed row.
        await db.set_lead_image_paths(lead_id, str(image_path), str(thumb_path))

        result = await client.extract(processed.jpeg_bytes, mime_type="image/jpeg")
        cleaned = postprocess_lead(result.lead)

        await db.save_lead_result(
            lead_id,
            cleaned,
            image_path=str(image_path),
            thumbnail_path=str(thumb_path),
            vlm_backend_used=result.backend_used,
        )
        if job_id_for_progress:
            await db.increment_job_progress(job_id_for_progress, failed=False)

    except (UnsupportedImageError, ImageTooLargeError) as exc:
        await db.mark_lead_failed(lead_id, f"Invalid image: {exc}")
        if job_id_for_progress:
            await db.increment_job_progress(job_id_for_progress, failed=True)
    except VLMError as exc:
        logger.error("VLM extraction failed for lead %s: %s", lead_id, exc)
        await db.mark_lead_failed(lead_id, "Extraction failed on all available VLM backends")
        if job_id_for_progress:
            await db.increment_job_progress(job_id_for_progress, failed=True)
    except Exception as exc:  # noqa: BLE001 — a single card must never crash the batch
        logger.exception("Unexpected error processing lead %s", lead_id)
        await db.mark_lead_failed(lead_id, "Unexpected processing error")
        if job_id_for_progress:
            await db.increment_job_progress(job_id_for_progress, failed=True)


async def sweep_expired_jobs(db: Database) -> int:
    """Deletes expired jobs (cascades to leads) and their image files on disk.
    Business-card images are PII; we do not keep them past the retention window."""
    paths = await db.list_expired_lead_image_paths()
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not delete expired file: %s", p)

    expired_job_ids = await db.list_expired_jobs()
    for job_id in expired_job_ids:
        await db.delete_job(job_id)

    return len(expired_job_ids)


async def retention_sweeper_loop(db: Database, interval_seconds: int = 300) -> None:
    """Background task: periodically deletes expired jobs/leads/files."""
    while True:
        try:
            deleted = await sweep_expired_jobs(db)
            if deleted:
                logger.info("Retention sweep: deleted %d expired job(s)", deleted)
        except Exception:  # noqa: BLE001
            logger.exception("Retention sweep failed")
        await asyncio.sleep(interval_seconds)
