"""
Pydantic schemas shared across the app. `ExtractedLead` is the contract the
VLM's output is forced into — everything downstream (normalization, the API
response, the Excel export) trusts this shape and nothing else.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class LeadStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class ExtractedLead(BaseModel):
    """What we ask the VLM to produce, validated before it ever touches the DB."""

    model_config = ConfigDict(extra="ignore")

    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    company: str | None = None
    location: str | None = None
    phone: str | None = None
    email: str | None = None
    additional_phones: list[str] = Field(default_factory=list)
    website: str | None = None
    raw_text: str | None = None
    confidence: float = 0.5
    warnings: list[str] = Field(default_factory=list)


class Lead(BaseModel):
    """A persisted lead row, as returned by the API."""

    id: str
    job_id: str
    source_file: str
    thumbnail_url: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    company: str | None = None
    location: str | None = None
    phone: str | None = None
    email: str | None = None
    additional_phones: list[str] = Field(default_factory=list)
    website: str | None = None
    raw_text: str | None = None
    confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    status: LeadStatus = LeadStatus.QUEUED
    error: str | None = None
    vlm_backend_used: str | None = None
    created_at: datetime
    updated_at: datetime


class LeadUpdate(BaseModel):
    """Fields a user can hand-correct in the results table."""

    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    company: str | None = None
    location: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None


class Job(BaseModel):
    id: str
    status: JobStatus
    total_files: int
    completed_files: int
    failed_files: int
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    leads: list[Lead] = Field(default_factory=list)


class JobSummary(BaseModel):
    id: str
    status: JobStatus
    total_files: int
    completed_files: int
    failed_files: int
    created_at: datetime
    updated_at: datetime


class HealthResponse(BaseModel):
    status: str
    active_vlm_backend: str | None
    primary_backend_healthy: bool
    fallback_backend_healthy: bool
    version: str
