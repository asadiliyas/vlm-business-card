"""
FastAPI application entrypoint. Serves the API under /api and the built
React frontend as static files at /, so the whole app is one origin and one
container in production (no CORS needed there — cors_origins only matters
for local dev where the Vite dev server runs on a different port).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import init_db
from app.jobs import retention_sweeper_loop
from app.routers import health, jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app.main")

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    db = await init_db(settings)
    sweeper_task = asyncio.create_task(retention_sweeper_loop(db))
    logger.info("Started with primary VLM backend=%s model=%s", settings.vlm_primary_base_url, settings.vlm_primary_model)
    yield
    sweeper_task.cancel()
    await db.close()


app = FastAPI(
    title="VLM Business Card Lead Extractor",
    version=health.APP_VERSION,
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak a stack trace to the client — log it server-side and return
    # a clean, generic error instead.
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(health.router)
app.include_router(jobs.router)

if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
else:
    @app.get("/")
    async def root_placeholder() -> dict:
        return {
            "message": "Backend is running. Frontend build not found at "
                       f"{FRONTEND_DIST} — run `npm run build` in frontend/ first.",
            "api_docs": "/docs",
        }
