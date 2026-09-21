"""HTTP surface for job/lead lifecycle: upload, poll, edit, export, delete."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.config import Settings, get_settings
from app.db import Database, get_db
from app.export import build_leads_workbook
from app.jobs import UploadFile as InternalUploadFile
from app.jobs import create_job_with_files
from app.models import Job, JobSummary, Lead, LeadUpdate
from app.rate_limit import InMemoryRateLimiter, client_ip

logger = logging.getLogger("app.routers.jobs")
router = APIRouter(prefix="/api", tags=["jobs"])

_upload_limiter = InMemoryRateLimiter(max_requests=get_settings().rate_limit_per_minute, window_seconds=60)


@router.post("/jobs", response_model=JobSummary, status_code=201)
async def upload_job(
    request: Request,
    settings: Settings = Depends(get_settings),
    db: Database = Depends(get_db),
) -> JobSummary:
    _upload_limiter.check(client_ip(request))
    form = await request.form()
    uploads = form.getlist("files")
    files: list[UploadFile] = [u for u in uploads if hasattr(u, "filename")]

    if not files:
        raise HTTPException(400, "No files uploaded. Attach one or more images under 'files'.")
    if len(files) > settings.max_files_per_job:
        raise HTTPException(
            400,
            f"Too many files: {len(files)} uploaded, max is {settings.max_files_per_job} per batch.",
        )

    internal_files = []
    for f in files:
        data = await f.read()
        internal_files.append(InternalUploadFile(filename=f.filename or "unnamed", data=data))

    job_id = await create_job_with_files(db, settings, internal_files)
    job = await db.get_job(job_id)
    assert job is not None
    return JobSummary(**job.model_dump(exclude={"leads"}))


@router.get("/jobs/{job_id}", response_model=Job)
async def get_job(job_id: str, db: Database = Depends(get_db)) -> Job:
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found (it may have expired and been cleaned up).")
    return job


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str, db: Database = Depends(get_db)) -> Response:
    """Lets a user proactively clear their batch. Image files are removed
    first — the DB delete cascades to the lead rows the retention sweeper
    would otherwise use to find them, so cleanup can't be deferred to it."""
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    for path in await db.list_job_image_paths(job_id):
        Path(path).unlink(missing_ok=True)
    await db.delete_job(job_id)
    return Response(status_code=204)


@router.patch("/leads/{lead_id}", response_model=Lead)
async def update_lead(lead_id: str, update: LeadUpdate, db: Database = Depends(get_db)) -> Lead:
    existing = await db.get_lead(lead_id)
    if existing is None:
        raise HTTPException(404, "Lead not found.")
    await db.update_lead_fields(lead_id, update)
    updated = await db.get_lead(lead_id)
    assert updated is not None
    return updated


@router.delete("/leads/{lead_id}", status_code=204)
async def delete_lead(lead_id: str, db: Database = Depends(get_db)) -> Response:
    existing = await db.get_lead(lead_id)
    if existing is None:
        raise HTTPException(404, "Lead not found.")
    cur = await db.conn.execute(
        "SELECT image_path, thumbnail_path FROM leads WHERE id = ?", (lead_id,)
    )
    row = await cur.fetchone()
    if row:
        for path in (row["image_path"], row["thumbnail_path"]):
            if path:
                Path(path).unlink(missing_ok=True)
    await db.delete_lead(lead_id)
    return Response(status_code=204)


@router.get("/leads/{lead_id}/thumbnail")
async def get_thumbnail(lead_id: str, db: Database = Depends(get_db)) -> Response:
    lead = await db.get_lead(lead_id)
    if lead is None:
        raise HTTPException(404, "Lead not found.")
    cur = await db.conn.execute("SELECT thumbnail_path FROM leads WHERE id = ?", (lead_id,))
    row = await cur.fetchone()
    if row is None or not row["thumbnail_path"]:
        raise HTTPException(404, "Thumbnail not available.")
    try:
        with open(row["thumbnail_path"], "rb") as fh:
            return Response(content=fh.read(), media_type="image/jpeg")
    except FileNotFoundError:
        raise HTTPException(404, "Thumbnail file no longer exists (likely expired).")


@router.get("/jobs/{job_id}/export.xlsx")
async def export_job(job_id: str, db: Database = Depends(get_db)) -> StreamingResponse:
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    if not any(l.status == "done" for l in job.leads):
        raise HTTPException(400, "No completed leads to export yet.")

    workbook_bytes = build_leads_workbook(job.leads)
    filename = f"leads_{job_id[:8]}.xlsx"
    return StreamingResponse(
        iter([workbook_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
