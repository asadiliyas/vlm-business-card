"""Health/status endpoint — reports which VLM backend is actually reachable
so the fallback chain (Section 0 of the architecture) is observable rather
than silent."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.models import HealthResponse
from app.vlm.client import check_backend_health

router = APIRouter(prefix="/api", tags=["health"])

APP_VERSION = "1.0.0"


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    primary_ok = settings.vlm_primary_enabled and await check_backend_health(
        settings.vlm_primary_base_url
    )
    fallback_ok = settings.vlm_fallback_enabled and await check_backend_health(
        settings.vlm_fallback_base_url
    )

    active = "primary" if primary_ok else ("fallback" if fallback_ok else None)

    return HealthResponse(
        status="ok" if active else "degraded",
        active_vlm_backend=active,
        primary_backend_healthy=primary_ok,
        fallback_backend_healthy=fallback_ok,
        version=APP_VERSION,
    )
