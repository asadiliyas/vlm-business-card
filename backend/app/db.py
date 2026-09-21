"""
Thin async SQLite layer. Deliberately not an ORM: two tables, simple queries,
and a schema small enough that plain SQL is more legible than an abstraction
over it would be.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import aiosqlite

from app.config import Settings
from app.models import ExtractedLead, Job, JobStatus, Lead, LeadStatus, LeadUpdate

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    status        TEXT NOT NULL,
    total_files   INTEGER NOT NULL,
    completed_files INTEGER NOT NULL DEFAULT 0,
    failed_files  INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leads (
    id            TEXT PRIMARY KEY,
    job_id        TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source_file   TEXT NOT NULL,
    image_path    TEXT,
    thumbnail_path TEXT,
    first_name    TEXT,
    last_name     TEXT,
    job_title     TEXT,
    company       TEXT,
    location      TEXT,
    phone         TEXT,
    email         TEXT,
    additional_phones TEXT NOT NULL DEFAULT '[]',
    website       TEXT,
    raw_text      TEXT,
    confidence    REAL NOT NULL DEFAULT 0,
    warnings      TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL,
    error         TEXT,
    vlm_backend_used TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_leads_job_id ON leads(job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_expires_at ON jobs(expires_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Owns the single aiosqlite connection used by the whole process."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected — call connect() first")
        return self._conn

    # ---------------------------------------------------------------- jobs

    async def create_job(self, job_id: str, total_files: int, retention_minutes: int) -> Job:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=retention_minutes)
        await self.conn.execute(
            "INSERT INTO jobs (id, status, total_files, completed_files, failed_files, "
            "created_at, updated_at, expires_at) VALUES (?, ?, ?, 0, 0, ?, ?, ?)",
            (job_id, JobStatus.QUEUED, total_files, now.isoformat(), now.isoformat(), expires.isoformat()),
        )
        await self.conn.commit()
        job = await self.get_job(job_id)
        assert job is not None
        return job

    async def set_job_status(self, job_id: str, status: JobStatus) -> None:
        await self.conn.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), job_id),
        )
        await self.conn.commit()

    async def increment_job_progress(self, job_id: str, *, failed: bool) -> None:
        col = "failed_files" if failed else "completed_files"
        await self.conn.execute(
            f"UPDATE jobs SET {col} = {col} + 1, updated_at = ? WHERE id = ?",
            (_now(), job_id),
        )
        await self.conn.commit()

    async def get_job(self, job_id: str) -> Job | None:
        cur = await self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cur.fetchone()
        if row is None:
            return None
        leads = await self.list_leads(job_id)
        return Job(
            id=row["id"],
            status=JobStatus(row["status"]),
            total_files=row["total_files"],
            completed_files=row["completed_files"],
            failed_files=row["failed_files"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            leads=leads,
        )

    async def delete_job(self, job_id: str) -> None:
        await self.conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        await self.conn.commit()

    async def list_expired_jobs(self) -> list[str]:
        cur = await self.conn.execute(
            "SELECT id FROM jobs WHERE expires_at < ?", (_now(),)
        )
        rows = await cur.fetchall()
        return [r["id"] for r in rows]

    # --------------------------------------------------------------- leads

    async def create_lead_placeholder(self, lead_id: str, job_id: str, source_file: str) -> None:
        now = _now()
        await self.conn.execute(
            "INSERT INTO leads (id, job_id, source_file, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (lead_id, job_id, source_file, LeadStatus.QUEUED, now, now),
        )
        await self.conn.commit()

    async def set_lead_image_paths(self, lead_id: str, image_path: str, thumbnail_path: str) -> None:
        """
        Recorded as soon as the files are written to disk — independently of
        whether extraction goes on to succeed or fail. If this weren't
        separate from save_lead_result(), a VLM failure would leave the
        image/thumbnail on disk with no DB row pointing at them, and the
        retention sweeper (which finds files to delete via the DB) would
        never be able to clean them up.
        """
        await self.conn.execute(
            "UPDATE leads SET image_path = ?, thumbnail_path = ?, updated_at = ? WHERE id = ?",
            (image_path, thumbnail_path, _now(), lead_id),
        )
        await self.conn.commit()

    async def mark_lead_processing(self, lead_id: str) -> None:
        await self.conn.execute(
            "UPDATE leads SET status = ?, updated_at = ? WHERE id = ?",
            (LeadStatus.PROCESSING, _now(), lead_id),
        )
        await self.conn.commit()

    async def save_lead_result(
        self,
        lead_id: str,
        extracted: ExtractedLead,
        *,
        image_path: str | None,
        thumbnail_path: str | None,
        vlm_backend_used: str,
    ) -> None:
        await self.conn.execute(
            """
            UPDATE leads SET
                first_name = ?, last_name = ?, job_title = ?, company = ?, location = ?,
                phone = ?, email = ?, additional_phones = ?, website = ?, raw_text = ?,
                confidence = ?, warnings = ?, status = ?, error = NULL,
                image_path = ?, thumbnail_path = ?, vlm_backend_used = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                extracted.first_name, extracted.last_name, extracted.job_title,
                extracted.company, extracted.location, extracted.phone, extracted.email,
                json.dumps(extracted.additional_phones), extracted.website, extracted.raw_text,
                extracted.confidence, json.dumps(extracted.warnings), LeadStatus.DONE,
                image_path, thumbnail_path, vlm_backend_used, _now(), lead_id,
            ),
        )
        await self.conn.commit()

    async def mark_lead_failed(self, lead_id: str, error: str) -> None:
        await self.conn.execute(
            "UPDATE leads SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (LeadStatus.FAILED, error, _now(), lead_id),
        )
        await self.conn.commit()

    async def update_lead_fields(self, lead_id: str, update: LeadUpdate) -> None:
        fields = update.model_dump(exclude_unset=True)
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [_now(), lead_id]
        await self.conn.execute(
            f"UPDATE leads SET {set_clause}, updated_at = ? WHERE id = ?", values
        )
        await self.conn.commit()

    async def delete_lead(self, lead_id: str) -> None:
        await self.conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
        await self.conn.commit()

    async def get_lead(self, lead_id: str) -> Lead | None:
        cur = await self.conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
        row = await cur.fetchone()
        return self._row_to_lead(row) if row else None

    async def list_leads(self, job_id: str) -> list[Lead]:
        cur = await self.conn.execute(
            "SELECT * FROM leads WHERE job_id = ? ORDER BY created_at ASC", (job_id,)
        )
        rows = await cur.fetchall()
        return [self._row_to_lead(r) for r in rows]

    async def list_job_image_paths(self, job_id: str) -> list[str]:
        """All on-disk image/thumbnail paths for a job — used to clean up files
        on explicit user delete, before the cascading DB delete removes the
        rows the retention sweeper would otherwise have used to find them."""
        cur = await self.conn.execute(
            "SELECT image_path, thumbnail_path FROM leads WHERE job_id = ?", (job_id,)
        )
        rows = await cur.fetchall()
        paths: list[str] = []
        for r in rows:
            if r["image_path"]:
                paths.append(r["image_path"])
            if r["thumbnail_path"]:
                paths.append(r["thumbnail_path"])
        return paths

    async def list_expired_lead_image_paths(self) -> list[str]:
        cur = await self.conn.execute(
            """
            SELECT l.image_path, l.thumbnail_path FROM leads l
            JOIN jobs j ON j.id = l.job_id
            WHERE j.expires_at < ? AND l.image_path IS NOT NULL
            """,
            (_now(),),
        )
        rows = await cur.fetchall()
        paths: list[str] = []
        for r in rows:
            if r["image_path"]:
                paths.append(r["image_path"])
            if r["thumbnail_path"]:
                paths.append(r["thumbnail_path"])
        return paths

    @staticmethod
    def _row_to_lead(row: aiosqlite.Row) -> Lead:
        return Lead(
            id=row["id"],
            job_id=row["job_id"],
            source_file=row["source_file"],
            thumbnail_url=f"/api/leads/{row['id']}/thumbnail" if row["thumbnail_path"] else None,
            first_name=row["first_name"],
            last_name=row["last_name"],
            job_title=row["job_title"],
            company=row["company"],
            location=row["location"],
            phone=row["phone"],
            email=row["email"],
            additional_phones=json.loads(row["additional_phones"] or "[]"),
            website=row["website"],
            raw_text=row["raw_text"],
            confidence=row["confidence"] or 0.0,
            warnings=json.loads(row["warnings"] or "[]"),
            status=LeadStatus(row["status"]),
            error=row["error"],
            vlm_backend_used=row["vlm_backend_used"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


_db: Database | None = None


def get_db() -> Database:
    if _db is None:
        raise RuntimeError("Database not initialized")
    return _db


async def init_db(settings: Settings) -> Database:
    global _db
    _db = Database(str(settings.db_path))
    await _db.connect()
    return _db


@asynccontextmanager
async def lifespan_db(settings: Settings) -> AsyncIterator[Database]:
    db = await init_db(settings)
    try:
        yield db
    finally:
        await db.close()
